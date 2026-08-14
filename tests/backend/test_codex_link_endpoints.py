"""Tests de los endpoints de vínculo ChatGPT (device-code OAuth) — T04.

Cubren el contrato de global-constraints.md §Link endpoints contra el fake
app-server de T02 (read-only, escenarios `login_completes`/`login_pending`/
`logout_ok`/`account_read_plan`): start/status/cancel/delete, persistencia de
`auth.json` cifrado + planType al completar el login, timeout del vínculo,
cold start honesto (pending → failed tras el grace) y los códigos 400/409/503.

Los tests corren sobre el loop de sesión de pytest-asyncio (igual que
test_codex_app_server.py): el singleton `codex_manager` y sus primitivas
asyncio quedan ligadas a ese loop. El cliente HTTP es httpx ASGITransport con
el lifespan del app ejecutado manualmente sobre el mismo loop (sin
TestClient/portal, que abriría otro loop). El usuario autenticado es un UUID
válido (el gestor rechaza `user-123`).
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# --- Nota de orden de imports: `backend.codex_app_server` lee su configuración
# de env en el import y congela el singleton `codex_manager` con esos valores.
# Este módulo NO importa main ni el gestor a nivel de módulo: main.py carga el
# runtime de Codex de forma perezosa (ver `_load_codex_runtime`), y aquí el
# gestor se importa dentro de fixtures/tests, cuando el env ya está fijado
# (por test_codex_app_server.py en una corrida conjunta, o por `link_env` en
# una corrida aislada). Así el orden de colección no altera la configuración.
_FAKE_BIN = str(Path(__file__).resolve().parent / "fake_codex_app_server.py")

import main as main_module  # noqa: E402
from main import (  # noqa: E402
    CODEX_LINK_COLD_START_ERROR_MESSAGE,
    CODEX_LINK_TIMEOUT_ERROR_MESSAGE,
)
from backend import rate_limit  # noqa: E402
from backend.auth import get_current_user_id  # noqa: E402
from backend.crypto import decrypt_user_api_key, encrypt_user_api_key  # noqa: E402

pytestmark = pytest.mark.asyncio(loop_scope="session")

_UID_COUNTER = [0]


def _uid() -> str:
    """UUID determinista de 36 chars (formato aceptado por el gestor)."""
    _UID_COUNTER[0] += 1
    i = _UID_COUNTER[0]
    return f"{i:08d}-0000-4000-8000-{i:012d}"


def _codex_manager():
    """Singleton del gestor del app-server (import diferido: su configuración
    se congela en el primer import, que debe ver el env ya fijado)."""
    import backend.codex_app_server as codex_app_server

    return codex_app_server.codex_manager


class _FakeConnectionStore:
    """Sustituto en memoria de user_provider_connections (T01, consumido vía
    monkeypatch de backend.supabase_data; misma firma que T01)."""

    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}

    def get(self, user_id: str):
        row = self._rows.get(user_id)
        return dict(row) if row else None

    def upsert(self, user_id, *, status, encrypted_credentials=None,
               login_id=None, plan_type=None, last_error=None):
        row = self._rows.setdefault(user_id, {})
        row.update(
            user_id=user_id,
            provider="codex",
            status=status,
            encrypted_credentials=encrypted_credentials,
            login_id=login_id,
            plan_type=plan_type,
            last_error=last_error,
        )
        row.setdefault("updated_at", "2026-08-14T00:00:00Z")

    def delete(self, user_id: str) -> bool:
        return self._rows.pop(user_id, None) is not None


class _PermissiveRateLimiter(rate_limit.MemoryRateLimiter):
    """El rate limit de los endpoints settings ya existe y no es objeto de
    T04; un limiter permisivo evita 429 espurios con polls repetidos."""

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        return True


@pytest.fixture
def link_env(tmp_path_factory, monkeypatch):
    """Parchea (function-scoped) el store de conexiones, el home root y el
    binario del singleton codex_manager para el test en curso."""
    import backend.codex_app_server as codex_app_server
    import backend.supabase_data as supabase_data

    store = _FakeConnectionStore()
    monkeypatch.setattr(supabase_data, "get_user_provider_connection", store.get)
    monkeypatch.setattr(supabase_data, "upsert_user_provider_connection", store.upsert)
    monkeypatch.setattr(supabase_data, "delete_user_provider_connection", store.delete)
    monkeypatch.setattr(rate_limit, "_limiter", _PermissiveRateLimiter())

    home_root = tmp_path_factory.mktemp("codex-link-home")
    monkeypatch.setattr(codex_app_server.codex_manager, "_home_root", home_root)
    monkeypatch.setattr(codex_app_server.codex_manager, "_bin_path", _FAKE_BIN)
    monkeypatch.setenv("CODEX_HOME_ROOT", str(home_root))
    monkeypatch.setenv("CODEX_BIN_PATH", _FAKE_BIN)
    return store, home_root


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _lifespan_app():
    """Entra en el lifespan del app UNA vez por sesión, sobre el loop de
    sesión. El `finally` del lifespan cierra el default executor del loop;
    hacerlo por test rompería los `asyncio.to_thread` de otros tests
    session-scoped (T02). El teardown de sesión (tras todos los tests)
    ejecuta además el shutdown hook de `codex_manager`."""
    async with main_module.app.router.lifespan_context(main_module.app):
        yield


@pytest_asyncio.fixture(loop_scope="session")
async def auth_client(_lifespan_app, link_env):
    """Cliente HTTP autenticado (get_current_user_id → UUID) sobre el app con
    el lifespan de sesión ya activo."""
    store, home_root = link_env
    user_id = _uid()
    main_module.app.dependency_overrides[get_current_user_id] = lambda: user_id
    try:
        async with AsyncClient(
            transport=ASGITransport(app=main_module.app), base_url="http://test"
        ) as ac:
            yield ac, user_id, store, home_root
    finally:
        main_module.app.dependency_overrides.pop(get_current_user_id, None)


@pytest_asyncio.fixture(loop_scope="session", autouse=True)
async def _reset_codex_state():
    """Deja el manager y el estado del vínculo limpios tras cada test
    (shutdown es idempotente; corre en el loop de sesión, igual que T02)."""
    yield
    await _codex_manager().shutdown()
    main_module._codex_pending_logins.clear()
    main_module._codex_cold_start_seen.clear()
    for task in list(main_module._codex_link_timeout_tasks.values()):
        if not task.done():
            task.cancel()
    main_module._codex_link_timeout_tasks.clear()


async def _poll_status(client, expected: str, *, timeout: float = 4.0) -> dict:
    """Polls `GET /api/settings/codex-link/status` hasta `expected`; devuelve
    el último body (para asertar el fallo) o el body esperado."""
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        r = await client.get("/api/settings/codex-link/status")
        assert r.status_code == 200
        last = r.json()
        if last["codex_status"] == expected:
            return last
        await asyncio.sleep(0.1)
    return last


class TestStart:
    async def test_happy_path_links_and_persists_encrypted_auth(self, auth_client, monkeypatch):
        client, user_id, store, home_root = auth_client
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "login_completes")
        monkeypatch.setenv("FAKE_CODEX_LOGIN_DELAY_SECONDS", "0.2")
        # El app-server real escribe auth.json antes de emitir la notificación;
        # aquí lo dejamos en disco antes de iniciar (el restore del spawn es
        # no-op: la fila aún no es linked).
        auth_content = json.dumps({"tokens": {"access_token": "fake-secret"}})
        home = home_root / user_id
        home.mkdir(parents=True)
        (home / "auth.json").write_text(auth_content, encoding="utf-8")

        r = await client.post("/api/settings/codex-link/start")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["verification_url"] == "https://chatgpt.com/device/verify"
        assert body["user_code"] == "ABCD-EFGH"
        assert body["login_id"] == "fake-login-1"
        assert body["expires_in"] == 600

        row = store.get(user_id)
        assert row["status"] == "pending"
        assert row["login_id"] == "fake-login-1"

        # La notificación account/login/completed persiste linked + planType
        # (account/read es echo en este escenario; cae al planType de la
        # notificación).
        body = await _poll_status(client, "linked")
        assert body["codex_status"] == "linked"
        assert body["codex_plan_type"] == "plus"
        row = store.get(user_id)
        assert row["status"] == "linked"
        assert row["plan_type"] == "plus"
        assert decrypt_user_api_key(row["encrypted_credentials"], user_id) == auth_content

    async def test_start_400_when_linked(self, auth_client):
        client, user_id, store, _ = auth_client
        store.upsert(user_id, status="linked")
        r = await client.post("/api/settings/codex-link/start")
        assert r.status_code == 400
        assert r.json()["detail"] == "Tu cuenta ChatGPT ya está vinculada."

    async def test_start_409_when_pending(self, auth_client):
        client, user_id, store, _ = auth_client
        store.upsert(user_id, status="pending", login_id="fake-login-pending")
        r = await client.post("/api/settings/codex-link/start")
        assert r.status_code == 409

    async def test_start_503_when_spawn_fails(self, auth_client, monkeypatch):
        client, user_id, store, _ = auth_client
        import backend.codex_app_server as codex_app_server

        monkeypatch.setattr(
            codex_app_server.codex_manager, "_bin_path", "/nonexistent/codex-bin"
        )
        r = await client.post("/api/settings/codex-link/start")
        assert r.status_code == 503
        assert "Codex" in r.json()["detail"]
        # Sin reintento silencioso: la fila sigue sin tocar.
        assert store.get(user_id) is None


class TestStatus:
    async def test_status_none_without_link(self, auth_client):
        client, _, _, _ = auth_client
        r = await client.get("/api/settings/codex-link/status")
        assert r.status_code == 200
        assert r.json() == {
            "ok": True,
            "codex_status": "none",
            "codex_plan_type": None,
            "last_error": None,
        }

    async def test_cold_start_pending_stays_pending_within_grace(self, auth_client, monkeypatch):
        client, user_id, store, _ = auth_client
        monkeypatch.setattr(main_module, "CODEX_LINK_TIMEOUT_SECONDS", 5.0)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "login_pending")
        r = await client.post("/api/settings/codex-link/start")
        assert r.status_code == 200
        # Reinicio simulado: proceso evacuado y ningún login en vuelo.
        await _codex_manager().evict(user_id)
        main_module._codex_pending_logins.clear()
        r = await client.get("/api/settings/codex-link/status")
        # Dentro del grace de 60 s sigue pending.
        assert r.status_code == 200
        assert r.json()["codex_status"] == "pending"

    async def test_cold_start_pending_becomes_failed_after_grace(self, auth_client, monkeypatch):
        client, user_id, store, _ = auth_client
        monkeypatch.setattr(main_module, "CODEX_LINK_TIMEOUT_SECONDS", 5.0)
        monkeypatch.setattr(main_module, "_CODEX_COLD_START_GRACE_SECONDS", 0.0)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "login_pending")
        r = await client.post("/api/settings/codex-link/start")
        assert r.status_code == 200
        # Reinicio simulado: proceso evacuado y ningún login en vuelo.
        await _codex_manager().evict(user_id)
        main_module._codex_pending_logins.clear()
        r = await client.get("/api/settings/codex-link/status")
        assert r.status_code == 200
        body = r.json()
        assert body["codex_status"] == "failed"
        assert body["last_error"] == CODEX_LINK_COLD_START_ERROR_MESSAGE
        assert store.get(user_id)["status"] == "failed"
        assert store.get(user_id)["last_error"] == CODEX_LINK_COLD_START_ERROR_MESSAGE

    async def test_link_timeout_marks_failed_and_cancels(self, auth_client, monkeypatch):
        client, user_id, store, _ = auth_client
        monkeypatch.setattr(main_module, "CODEX_LINK_TIMEOUT_SECONDS", 0.3)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "login_pending")
        r = await client.post("/api/settings/codex-link/start")
        assert r.status_code == 200
        body = await _poll_status(client, "failed", timeout=4.0)
        assert body["codex_status"] == "failed"
        assert body["last_error"] == CODEX_LINK_TIMEOUT_ERROR_MESSAGE
        assert store.get(user_id)["status"] == "failed"
        assert store.get(user_id)["last_error"] == CODEX_LINK_TIMEOUT_ERROR_MESSAGE


class TestCancel:
    async def test_cancel_pending_goes_to_none(self, auth_client, monkeypatch):
        client, user_id, store, _ = auth_client
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "login_pending")
        r = await client.post("/api/settings/codex-link/start")
        assert r.status_code == 200
        assert store.get(user_id)["status"] == "pending"

        r = await client.post("/api/settings/codex-link/cancel")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert store.get(user_id)["status"] == "none"

        r = await client.get("/api/settings/codex-link/status")
        assert r.json()["codex_status"] == "none"

    async def test_cancel_idempotent_without_pending(self, auth_client):
        client, user_id, store, _ = auth_client
        r = await client.post("/api/settings/codex-link/cancel")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        # Un vínculo linked no se toca (solo aplica a pendientes).
        store.upsert(user_id, status="linked")
        r = await client.post("/api/settings/codex-link/cancel")
        assert r.status_code == 200
        assert store.get(user_id)["status"] == "linked"


class TestDelete:
    async def test_delete_removes_link_and_is_idempotent(self, auth_client, monkeypatch):
        client, user_id, store, home_root = auth_client
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "logout_ok")
        encrypted = encrypt_user_api_key(
            json.dumps({"tokens": {"access_token": "fake-secret"}}), user_id
        )
        store.upsert(user_id, status="linked", encrypted_credentials=encrypted, plan_type="plus")

        r = await client.delete("/api/settings/codex-link")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert store.get(user_id) is None
        assert not (home_root / user_id).exists()  # CODEX_HOME eliminado

        r = await client.get("/api/settings/codex-link/status")
        assert r.json()["codex_status"] == "none"

        # Idempotente.
        r = await client.delete("/api/settings/codex-link")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    async def test_delete_logout_failure_does_not_block_local_delete(self, auth_client, monkeypatch):
        client, user_id, store, _ = auth_client
        # usage_limit: error object en TODOS los requests → logout falla.
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "usage_limit")
        encrypted = encrypt_user_api_key(
            json.dumps({"tokens": {"access_token": "fake-secret"}}), user_id
        )
        store.upsert(user_id, status="linked", encrypted_credentials=encrypted)

        r = await client.delete("/api/settings/codex-link")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert store.get(user_id) is None


class TestHandler:
    async def test_plan_type_from_account_read_best_effort(self, auth_client, monkeypatch):
        client, user_id, store, home_root = auth_client
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "account_read_plan")
        auth_content = json.dumps({"tokens": {"access_token": "fake-secret"}})
        home = home_root / user_id
        home.mkdir(parents=True)
        (home / "auth.json").write_text(auth_content, encoding="utf-8")
        # Login en vuelo registrado (como tras account/login/start).
        main_module._codex_pending_logins[user_id] = ("fake-login-1", time.monotonic() + 600)

        await main_module._codex_persist_login_completed(
            user_id, {"loginId": "fake-login-1", "planType": "free"}
        )

        row = store.get(user_id)
        assert row["status"] == "linked"
        # account/read devuelve planType "plus": gana sobre el de la notificación.
        assert row["plan_type"] == "plus"
        assert decrypt_user_api_key(row["encrypted_credentials"], user_id) == auth_content
        assert main_module._codex_pending_logins.get(user_id) is None

    async def test_login_completed_handler_registered_once_after_reload(self):
        """RC-01: el registro del handler sobrevive a `importlib.reload(main)`.

        Tras una recarga, el manager conserva el handler del módulo anterior
        (un objeto distinto de la función actual) y el guard global de módulo
        vuelve a False. La idempotencia debe depender de una marca estable del
        handler (no de la identidad ni del booleano): solo puede quedar UN
        handler registrado para `account/login/completed`, de modo que la
        notificación se procesa exactamente una vez.
        """
        manager = _codex_manager()
        handlers = manager._notification_handlers.setdefault(
            "account/login/completed", []
        )
        original_handlers = list(handlers)
        had_guard = hasattr(main_module, "_codex_login_handler_registered")
        original_guard = getattr(main_module, "_codex_login_handler_registered", None)
        try:
            handlers[:] = []
            if had_guard:
                # El código de módulo re-ejecutado por importlib.reload
                # restablece el guard global a False.
                main_module._codex_login_handler_registered = False

            # Estado post-reload: el manager conserva el handler del módulo
            # anterior — objeto distinto de `_codex_handle_login_completed`
            # actual, pero con la marca estable de su registro.
            async def _stale_handler(user_id, params):
                await main_module._codex_handle_login_completed(user_id, params)

            _stale_handler._codex_login_completed_handler_registered = True
            handlers.append(_stale_handler)

            main_module._register_codex_login_completed_handler(manager)

            # Un solo handler registrado (la identidad del objeto ya no
            # coincide, pero la marca estable sí lo detecta).
            assert len(handlers) == 1
        finally:
            if had_guard:
                main_module._codex_login_handler_registered = original_guard
            handlers[:] = original_handlers
