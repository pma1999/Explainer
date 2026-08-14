"""Unit tests for backend/codex_app_server.py (T02).

Cubren el contrato congelado del gestor de procesos `codex app-server --stdio`:
spawn por tenant con CODEX_HOME 0700 y restauración de auth.json, transporte
JSONL (requests por id, notificaciones, errores, timeout), semáforos (5 por
proceso, 3 procesos globales con evicción LRU), evicción por inactividad,
evict/shutdown con snapshot cifrado y user_id inválido rechazado.

El binario real se sustituye por tests/backend/fake_codex_app_server.py vía
CODEX_BIN_PATH (sin red ni credenciales). Los tests corren sobre un único loop
de sesión para que el singleton `codex_manager` (con primitivas asyncio
ligadas al loop) sea seguro de reutilizar entre tests.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

import pytest
import pytest_asyncio

# --- Configuración del entorno ANTES de importar el módulo bajo test: el
# gestor lee sus límites de env en el import. El singleton `codex_manager` de
# los tests usa estos valores; los tests que necesitan otra configuración
# crean instancias propias de CodexAppServerManager.
_FAKE_BIN = str(Path(__file__).resolve().parent / "fake_codex_app_server.py")
_TEST_HOME_ROOT = tempfile.mkdtemp(prefix="codex-app-server-tests-")
os.environ["CODEX_BIN_PATH"] = _FAKE_BIN
os.environ["CODEX_HOME_ROOT"] = _TEST_HOME_ROOT
os.environ["CODEX_SPAWN_WAIT_SECONDS"] = "0.3"
os.environ["CODEX_IDLE_TTL_SECONDS"] = "600"
os.environ["CODEX_REQUEST_TIMEOUT_SECONDS"] = "30"
os.environ["CODEX_MAX_PROCESSES"] = "3"
os.environ["CODEX_PER_PROCESS_MAX_CONCURRENCY"] = "5"
atexit.register(shutil.rmtree, _TEST_HOME_ROOT, True)

from backend.codex_app_server import (  # noqa: E402  (env configurado arriba)
    CODEX_MAX_PROCESSES,
    CODEX_PER_PROCESS_MAX_CONCURRENCY,
    CodexAppServerManager,
    CodexAppServerError,
    CodexRequestError,
    CodexSpawnError,
    CodexTimeoutError,
    codex_manager,
)
from backend.crypto import decrypt_user_api_key, encrypt_user_api_key  # noqa: E402


def _uid(i: int) -> str:
    """UUID determinista de 36 chars (formato aceptado por el gestor)."""
    return f"{i:08d}-0000-4000-8000-{i:012d}"


class _StreamingCollector:
    """Recoge las notificaciones de turno del fake en orden de llegada.

    Un handler por método del ciclo streaming (todos comparten la lista
    `received`): el reader-task del manager las despacha en orden de llegada
    por proceso vía `asyncio.create_task`, así que el orden de la lista es el
    orden de emisión del fake.
    """

    STREAM_METHODS = (
        "turn/started",
        "item/started",
        "item/agentMessage/delta",
        "item/completed",
        "thread/tokenUsage/updated",
        "turn/completed",
        "error",
    )

    def __init__(self, manager: CodexAppServerManager, expected: int):
        self.received: list[tuple[str, dict]] = []
        self._expected = expected
        self.done = asyncio.Event()
        for method in self.STREAM_METHODS:
            manager.add_notification_handler(method, self._make_handler(method))

    def _make_handler(self, method: str):
        async def handler(user_id: str, params: dict) -> None:
            self.received.append((method, params))
            if len(self.received) >= self._expected:
                self.done.set()

        return handler


def _linked_row(user_id: str, auth_json_str: str) -> dict:
    return {
        "user_id": user_id,
        "provider": "codex",
        "status": "linked",
        "encrypted_credentials": encrypt_user_api_key(auth_json_str, user_id),
        "login_id": None,
        "plan_type": "plus",
        "last_error": None,
    }


@pytest.fixture(autouse=True)
def _no_supabase(monkeypatch):
    """Aísla los tests de Supabase: sin fila de conexión y sin persistencia.

    Los tests que ejercitan restauración/snapshot re-parchan las funciones
    concretas con sus propios valores dentro del test.
    """
    import backend.supabase_data as supabase_data

    monkeypatch.setattr(
        supabase_data, "get_user_provider_connection", lambda user_id: None
    )
    monkeypatch.setattr(
        supabase_data, "upsert_user_provider_connection", lambda *args, **kwargs: None
    )


@pytest_asyncio.fixture(loop_scope="session", autouse=True)
async def _reset_manager():
    """Deja el singleton limpio tras cada test (shutdown es idempotente).

    Corre en el loop de sesión (igual que los tests) para que el shutdown
    toque las primitivas asyncio del singleton en su loop ligado.
    """
    yield
    await codex_manager.shutdown()


class TestUserValidation:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_invalid_user_id_rejected(self):
        for bad in ("user-123", "", "..", "not-a-uuid-1234567890-abcdef", "x" * 36, "a" * 35):
            with pytest.raises(CodexAppServerError):
                await codex_manager.acquire(bad)
        # evict con user_id inválido: no-op, sin excepción (idempotente).
        await codex_manager.evict("bad-user-id")
        assert codex_manager.active_count == 0


class TestSpawnAndRestore:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_spawn_creates_home_0700_and_restores_auth_json(self, monkeypatch):
        user_id = _uid(1)
        auth_content = json.dumps({"tokens": {"access_token": "fake-secret"}})
        monkeypatch.setattr(
            "backend.supabase_data.get_user_provider_connection",
            lambda u: _linked_row(u, auth_content),
        )
        server = await codex_manager.acquire(user_id)

        assert codex_manager.active_count == 1
        home = Path(_TEST_HOME_ROOT) / user_id
        assert home.is_dir()
        if os.name != "nt":
            assert stat.S_IMODE(home.stat().st_mode) == 0o700
        # auth.json restaurado desde el blob cifrado (escritura atómica temp+rename).
        assert (home / "auth.json").read_text(encoding="utf-8") == auth_content
        # stderr del subproceso → fichero del home, nunca a los logs de la app.
        stderr_log = home / "app-server.stderr.log"
        assert stderr_log.exists()
        for _ in range(100):
            if b"fake app-server started" in stderr_log.read_bytes():
                break
            await asyncio.sleep(0.05)
        assert b"fake app-server started" in stderr_log.read_bytes()
        assert server.home_dir == home

    @pytest.mark.asyncio(loop_scope="session")
    async def test_no_restore_when_not_linked(self, monkeypatch):
        user_id = _uid(2)
        monkeypatch.setattr(
            "backend.supabase_data.get_user_provider_connection",
            lambda u: {"user_id": u, "status": "pending", "encrypted_credentials": None},
        )
        server = await codex_manager.acquire(user_id)
        assert not (server.home_dir / "auth.json").exists()

    @pytest.mark.asyncio(loop_scope="session")
    async def test_live_process_reused_without_respawn(self):
        user_id = _uid(3)
        s1 = await codex_manager.acquire(user_id)
        s2 = await codex_manager.acquire(user_id)
        assert s1 is s2
        # Adquisiones concurrentes del mismo tenant: una sola creación.
        s3, s4 = await asyncio.gather(
            codex_manager.acquire(user_id), codex_manager.acquire(user_id)
        )
        assert s3 is s1 and s4 is s1
        assert codex_manager.active_count == 1

    @pytest.mark.asyncio(loop_scope="session")
    async def test_stderr_log_truncated_per_spawn(self, monkeypatch):
        user_id = _uid(80)
        server = await codex_manager.acquire(user_id)
        home = Path(_TEST_HOME_ROOT) / user_id
        log = home / "app-server.stderr.log"
        for _ in range(100):
            if b"fake app-server started" in log.read_bytes():
                break
            await asyncio.sleep(0.05)

        # Crash del proceso: el registro se limpia solo y un nuevo acquire
        # re-spawnea reutilizando el home (sin borrarlo).
        server._process.kill()
        await server._process.wait()
        for _ in range(100):
            if not server.is_alive:
                break
            await asyncio.sleep(0.05)
        assert not server.is_alive
        assert codex_manager.active_count == 0

        server2 = await codex_manager.acquire(user_id)
        assert server2 is not server
        assert server2.is_alive
        for _ in range(100):
            content = log.read_bytes()
            if content.count(b"fake app-server started") == 1:
                break
            await asyncio.sleep(0.05)
        # stderr truncado en cada spawn: una sola línea de banner.
        assert content.count(b"fake app-server started") == 1


class TestJsonlTransport:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_request_and_response(self):
        user_id = _uid(4)
        server = await codex_manager.acquire(user_id)
        result = await server.request("echo", {"x": 1})
        assert result == {"ok": True, "method": "echo", "params": {"x": 1}}

    @pytest.mark.asyncio(loop_scope="session")
    async def test_concurrent_requests_resolved_by_id(self):
        user_id = _uid(5)
        server = await codex_manager.acquire(user_id)
        results = await asyncio.gather(
            *(server.request("echo", {"i": i}) for i in range(10))
        )
        for i, result in enumerate(results):
            assert result["params"]["i"] == i  # correlación por id, sin mezclas

    @pytest.mark.asyncio(loop_scope="session")
    async def test_notification_dispatched_to_handlers(self, monkeypatch):
        user_id = _uid(6)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "login_completes")
        received: dict = {}
        done = asyncio.Event()

        async def handler(u, params):
            received["user_id"] = u
            received["params"] = params
            done.set()

        codex_manager.add_notification_handler("account/login/completed", handler)
        server = await codex_manager.acquire(user_id)
        result = await server.request("account/login/start", {"type": "chatgptDeviceCode"})
        assert result["loginId"] == "fake-login-1"
        await asyncio.wait_for(done.wait(), timeout=5)
        assert received["user_id"] == user_id
        assert received["params"]["loginId"] == "fake-login-1"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_error_object_raises_codex_request_error(self, monkeypatch):
        user_id = _uid(7)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "usage_limit")
        server = await codex_manager.acquire(user_id)
        with pytest.raises(CodexRequestError) as exc_info:
            await server.request("account/read", {})
        error = exc_info.value
        assert error.code == "UsageLimitExceeded"
        assert error.message and "limit" in error.message.lower()
        assert error.data is None

    @pytest.mark.asyncio(loop_scope="session")
    async def test_scripted_error_code_from_env(self, monkeypatch):
        user_id = _uid(8)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "scripted_error")
        monkeypatch.setenv("FAKE_CODEX_ERROR_CODE", "BadTurn")
        server = await codex_manager.acquire(user_id)
        with pytest.raises(CodexRequestError) as exc_info:
            await server.request("turn/start", {})
        assert exc_info.value.code == "BadTurn"
        assert exc_info.value.data is None

    @pytest.mark.asyncio(loop_scope="session")
    async def test_request_timeout_raises_codex_timeout_error(self, monkeypatch):
        user_id = _uid(9)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "slow_turn")
        server = await codex_manager.acquire(user_id)
        with pytest.raises(CodexTimeoutError):
            await server.request("turn/start", {}, timeout=0.2)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_invalid_json_line_tolerated(self, monkeypatch):
        user_id = _uid(10)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "invalid_json")
        server = await codex_manager.acquire(user_id)
        result = await server.request("echo", {"i": 1})
        assert result["ok"] is True


class TestStreamingTurn:
    """FR-01 (brief enmendado): el wire-format del fake es STREAMING.

    `turn/start` responde `{turn:{id,status:"inProgress",items:[]}}` sin texto
    ni usage; el resultado llega por notificaciones (`turn/started`,
    `item/started`, `item/agentMessage/delta`, `item/completed` con el texto
    final, opcionalmente `thread/tokenUsage/updated`, `turn/completed`).
    """

    @pytest.mark.asyncio(loop_scope="session")
    async def test_scripted_turn_streams_full_sequence_with_usage(self, monkeypatch, tmp_path):
        user_id = _uid(71)
        turn_file = tmp_path / "turn.txt"
        turn_file.write_text("Hola desde el fake.", encoding="utf-8")
        usage_file = tmp_path / "usage.json"
        usage_file.write_text(
            json.dumps({
                "total": {"inputTokens": 100, "cachedInputTokens": 10,
                          "cacheWriteInputTokens": 5, "outputTokens": 50,
                          "reasoningOutputTokens": 20, "totalTokens": 150},
                "last": {"inputTokens": 90, "cachedInputTokens": 8,
                         "cacheWriteInputTokens": 4, "outputTokens": 45,
                         "reasoningOutputTokens": 18, "totalTokens": 135},
                "modelContextWindow": 200000,
            }),
            encoding="utf-8",
        )
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "scripted_turn")
        monkeypatch.setenv("FAKE_CODEX_TURN_OUTPUT_FILE", str(turn_file))
        monkeypatch.setenv("FAKE_CODEX_TOKEN_USAGE_FILE", str(usage_file))
        server = await codex_manager.acquire(user_id)
        collector = _StreamingCollector(codex_manager, expected=6)

        thread_result = await server.request("thread/start", {})
        thread_id = thread_result["thread"]["id"]
        assert thread_id == "thread_1"

        turn_result = await server.request(
            "turn/start",
            {"threadId": thread_id, "input": {"type": "text", "text": "hola"}},
        )
        # Response inmediata: inProgress, SIN texto ni usage.
        assert turn_result == {"turn": {"id": "turn_1", "status": "inProgress", "items": []}}

        await asyncio.wait_for(collector.done.wait(), timeout=5)
        assert [m for m, _ in collector.received] == [
            "turn/started",
            "item/started",
            "item/agentMessage/delta",
            "item/completed",
            "thread/tokenUsage/updated",
            "turn/completed",
        ]
        # Correlación: threadId en todas; `turn/started` y `turn/completed`
        # correlacionan vía `turn.id` (shape verificado, sin campo turnId);
        # el resto lleva `turnId`.
        for method, params in collector.received:
            assert params["threadId"] == thread_id
            if method in ("turn/started", "turn/completed"):
                assert params["turn"]["id"] == "turn_1"
            else:
                assert params["turnId"] == "turn_1"

        assert collector.received[0][1]["turn"] == {"id": "turn_1", "status": "inProgress"}
        assert collector.received[1][1]["item"] == {"type": "agentMessage", "id": "item_1"}
        assert isinstance(collector.received[1][1]["startedAtMs"], int)

        delta = collector.received[2][1]
        assert delta["itemId"] == "item_1"
        assert delta["delta"] == "Hola desde el fake."

        completed = collector.received[3][1]["item"]
        assert completed["type"] == "agentMessage"
        assert completed["id"] == "item_1"
        assert completed["text"] == "Hola desde el fake."  # texto plano, sin parseo
        assert isinstance(collector.received[3][1]["completedAtMs"], int)

        # Usage: shape real de `thread/tokenUsage/updated`.
        token_usage = collector.received[4][1]["tokenUsage"]
        assert set(token_usage.keys()) == {"total", "last", "modelContextWindow"}
        for breakdown in (token_usage["total"], token_usage["last"]):
            assert set(breakdown.keys()) == {
                "inputTokens", "cachedInputTokens", "cacheWriteInputTokens",
                "outputTokens", "reasoningOutputTokens", "totalTokens",
            }
            assert all(isinstance(v, int) for v in breakdown.values())
        assert isinstance(token_usage["modelContextWindow"], int)

        assert collector.received[5][1]["turn"] == {
            "id": "turn_1", "status": "completed", "items": [],
        }

    @pytest.mark.asyncio(loop_scope="session")
    async def test_scripted_turn_without_usage_file_emits_no_usage_notification(self, monkeypatch, tmp_path):
        user_id = _uid(72)
        turn_file = tmp_path / "turn.txt"
        turn_file.write_text("Sin usage.", encoding="utf-8")
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "scripted_turn")
        monkeypatch.setenv("FAKE_CODEX_TURN_OUTPUT_FILE", str(turn_file))
        # Sin FAKE_CODEX_TOKEN_USAGE_FILE: NO se emite thread/tokenUsage/updated.
        server = await codex_manager.acquire(user_id)
        collector = _StreamingCollector(codex_manager, expected=5)

        thread_result = await server.request("thread/start", {})
        await server.request(
            "turn/start",
            {"threadId": thread_result["thread"]["id"], "input": {"type": "text", "text": "hola"}},
        )

        await asyncio.wait_for(collector.done.wait(), timeout=5)
        assert [m for m, _ in collector.received] == [
            "turn/started",
            "item/started",
            "item/agentMessage/delta",
            "item/completed",
            "turn/completed",
        ]

    @pytest.mark.asyncio(loop_scope="session")
    async def test_scripted_turn_per_turn_output_files(self, monkeypatch, tmp_path):
        user_id = _uid(73)
        # Convención por turno: <FILE>.1 y <FILE>.2 existen; el base no.
        (tmp_path / "turn.1").write_text("Primer turno.", encoding="utf-8")
        (tmp_path / "turn.2").write_text("Segundo turno.", encoding="utf-8")
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "scripted_turn")
        monkeypatch.setenv("FAKE_CODEX_TURN_OUTPUT_FILE", str(tmp_path / "turn"))
        server = await codex_manager.acquire(user_id)
        collector = _StreamingCollector(codex_manager, expected=10)

        thread_result = await server.request("thread/start", {})
        thread_id = thread_result["thread"]["id"]
        for _ in range(2):
            await server.request(
                "turn/start",
                {"threadId": thread_id, "input": {"type": "text", "text": "hola"}},
            )

        await asyncio.wait_for(collector.done.wait(), timeout=5)
        assert [m for m, _ in collector.received] == [
            "turn/started", "item/started", "item/agentMessage/delta",
            "item/completed", "turn/completed",
        ] * 2
        # Turno 1: turn_1/item_1 con <FILE>.1; turno 2: turn_2/item_2 con <FILE>.2.
        for i, (turn_id, item_id, text) in enumerate([
            ("turn_1", "item_1", "Primer turno."),
            ("turn_2", "item_2", "Segundo turno."),
        ]):
            block = collector.received[i * 5:(i + 1) * 5]
            assert all(p["threadId"] == thread_id for _, p in block)
            # `turn/started` y `turn/completed` (extremos del bloque)
            # correlacionan vía `turn.id` (shape sin campo turnId).
            assert block[0][1]["turn"]["id"] == turn_id
            assert block[4][1]["turn"]["id"] == turn_id
            assert all(p["turnId"] == turn_id for _, p in block[1:4])
            assert block[1][1]["item"]["id"] == item_id
            assert block[2][1]["itemId"] == item_id
            assert block[3][1]["item"]["text"] == text

    @pytest.mark.asyncio(loop_scope="session")
    async def test_scripted_turn_missing_output_file_raises_turn_output_read_error(self, monkeypatch, tmp_path):
        user_id = _uid(74)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "scripted_turn")
        monkeypatch.setenv("FAKE_CODEX_TURN_OUTPUT_FILE", str(tmp_path / "no-such-file.txt"))
        server = await codex_manager.acquire(user_id)
        # Error de ACEPTACIÓN en la response de turn/start (no notificación).
        with pytest.raises(CodexRequestError) as exc_info:
            await server.request(
                "turn/start",
                {"threadId": "thread_x", "input": {"type": "text", "text": "hola"}},
            )
        assert exc_info.value.code == "TurnOutputReadError"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_usage_limit_streaming_quota_notification_and_failed_turn(self, monkeypatch):
        user_id = _uid(75)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "usage_limit")
        server = await codex_manager.acquire(user_id)
        collector = _StreamingCollector(codex_manager, expected=2)

        thread_result = await server.request("thread/start", {})
        turn_result = await server.request(
            "turn/start",
            {"threadId": thread_result["thread"]["id"], "input": {"type": "text", "text": "hola"}},
        )
        assert turn_result["turn"]["status"] == "inProgress"

        await asyncio.wait_for(collector.done.wait(), timeout=5)
        method, params = collector.received[0]
        assert method == "error"
        assert params["error"] == {
            "message": "Usage limit exceeded for this ChatGPT plan",
            "codexErrorInfo": "usageLimitExceeded",
            "additionalDetails": None,
        }
        assert params["willRetry"] is False
        assert params["threadId"] == thread_result["thread"]["id"]

        method, params = collector.received[1]
        assert method == "turn/completed"
        assert params["turn"]["status"] == "failed"
        assert params["turn"]["error"]["codexErrorInfo"] == "usageLimitExceeded"
        assert params["turn"]["items"] == []

        # Guard de regresión (T04): un request no-turn sigue devolviendo error
        # object UsageLimitExceeded en la response.
        with pytest.raises(CodexRequestError) as exc_info:
            await server.request("account/logout", {})
        assert exc_info.value.code == "UsageLimitExceeded"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_stalled_turn_accepts_but_emits_no_notifications(self, monkeypatch):
        user_id = _uid(76)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "stalled_turn")
        server = await codex_manager.acquire(user_id)
        collector = _StreamingCollector(codex_manager, expected=1)

        thread_result = await server.request("thread/start", {})
        turn_result = await server.request(
            "turn/start",
            {"threadId": thread_result["thread"]["id"], "input": {"type": "text", "text": "hola"}},
        )
        assert turn_result["turn"]["status"] == "inProgress"

        # Turno aceptado pero sin ninguna notificación posterior: el cliente
        # debe caer en timeout esperando turn/completed.
        await asyncio.sleep(0.5)
        assert collector.received == []


class TestInitializeHandshake:
    """Ronda 4 (gate live, binario real codex 0.145.0): el app-server exige
    el handshake JSON-RPC `initialize` + notificación `initialized` al abrir
    la conexión y rechaza CUALQUIER request anterior con `CodexRequestError:
    Not initialized` (verificado contra el binario real, ver
    /tmp/opencode/codex_live.log). `acquire` debe devolver un server listo:
    el PRIMER mensaje que recibe el fake es `initialize` (con clientInfo), el
    segundo la notificación `initialized` (sin id, sin respuesta), y un
    request normal funciona después del handshake.
    """

    @pytest.mark.asyncio(loop_scope="session")
    async def test_handshake_initialize_and_initialized_before_any_request(self, monkeypatch, tmp_path):
        user_id = _uid(201)
        trace = tmp_path / "fake-received.jsonl"
        monkeypatch.setenv("FAKE_CODEX_TRACE_FILE", str(trace))
        server = await codex_manager.acquire(user_id)

        # Un request normal funciona tras el handshake (acquire ya completó
        # initialize + initialized; los tests existentes cubren el resto).
        result = await server.request("echo", {"x": 1})
        assert result == {"ok": True, "method": "echo", "params": {"x": 1}}

        # Traza del fake, en orden de lectura: el primer mensaje es el
        # request `initialize` (id 1, clientInfo del handshake), el segundo
        # la notificación `initialized` (sin id), y solo después el request
        # de la aplicación.
        received = [
            json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()
        ]
        assert len(received) >= 3
        assert received[0]["method"] == "initialize"
        assert received[0]["id"] == 1
        assert received[0]["params"]["clientInfo"] == {
            "name": "explainer",
            "title": "Explainer",
            "version": "0.1.0",
        }
        assert received[1]["method"] == "initialized"
        assert "id" not in received[1]
        assert received[2]["method"] == "echo"


class TestConcurrencyLimits:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_per_process_concurrency_semaphore_blocks_sixth(self):
        user_id = _uid(11)
        server = await codex_manager.acquire(user_id)
        assert CODEX_PER_PROCESS_MAX_CONCURRENCY == 5
        # Ocupar los 5 permisos del proceso desde el test (white-box): una
        # sexta petición debe quedar bloqueada hasta que se libere uno.
        for _ in range(CODEX_PER_PROCESS_MAX_CONCURRENCY):
            await server._concurrency_sem.acquire()
        task = asyncio.create_task(server.request("echo", {"i": "blocked"}))
        await asyncio.sleep(0.2)
        assert not task.done()
        server._concurrency_sem.release()
        result = await asyncio.wait_for(task, timeout=5)
        assert result["params"]["i"] == "blocked"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_global_capacity_raises_spawn_error_when_all_busy(self, monkeypatch):
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "slow_turn")
        assert CODEX_MAX_PROCESSES == 3
        tasks = []
        try:
            for i in range(CODEX_MAX_PROCESSES):
                server = await codex_manager.acquire(_uid(20 + i))
                tasks.append(asyncio.create_task(server.request("turn/start", {})))
            # Esperar a que las peticiones lentas estén en vuelo (el fake duerme
            # 30s antes de responder: los 3 procesos quedan ocupados).
            await asyncio.sleep(0.3)
            assert codex_manager.active_count == 3
            with pytest.raises(CodexSpawnError):
                await codex_manager.acquire(_uid(99))
            assert codex_manager.active_count == 3
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_lru_eviction_frees_capacity_before_spawn_error(self):
        a = await codex_manager.acquire(_uid(30))
        b = await codex_manager.acquire(_uid(31))
        c = await codex_manager.acquire(_uid(32))
        # Todos inactivos; el 4º acquire espera el semáforo global y, al agotar
        # CODEX_SPAWN_WAIT_SECONDS, evicta LRU el más antiguo (a) en vez de fallar.
        d = await codex_manager.acquire(_uid(33))
        assert codex_manager.active_count == 3
        assert not a.is_alive
        assert b.is_alive and c.is_alive and d.is_alive
        assert set(codex_manager._servers) == {_uid(31), _uid(32), _uid(33)}
        result = await d.request("echo", {"i": 33})
        assert result["params"]["i"] == 33


class TestLifecycle:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_idle_ttl_eviction_loop(self):
        root = tempfile.mkdtemp(prefix="codex-ttl-")
        try:
            manager = CodexAppServerManager(
                bin_path=_FAKE_BIN,
                home_root=root,
                idle_ttl_seconds=0.3,
            )
            server = await manager.acquire(_uid(40))
            assert manager.active_count == 1
            # El loop de evicción (iniciado en el primer acquire) lo expulsa al
            # superar CODEX_IDLE_TTL_SECONDS sin uso.
            await asyncio.sleep(0.9)
            assert manager.active_count == 0
            assert not server.is_alive
            await manager.shutdown()
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_evict_snapshots_encrypted_auth_json_and_cleans_home(self, monkeypatch):
        user_id = _uid(50)
        old_content = json.dumps({"tokens": {"old": True}})
        monkeypatch.setattr(
            "backend.supabase_data.get_user_provider_connection",
            lambda u: _linked_row(u, old_content),
        )
        server = await codex_manager.acquire(user_id)
        home = Path(_TEST_HOME_ROOT) / user_id
        # El app-server refrescó las credenciales en disco (auth.json nuevo).
        new_content = json.dumps({"tokens": {"new": True}, "refreshToken": "x"})
        (home / "auth.json").write_text(new_content, encoding="utf-8")

        upserts: list[tuple] = []

        def fake_upsert(u, *, status, encrypted_credentials=None, login_id=None,
                        plan_type=None, last_error=None):
            upserts.append((u, status, encrypted_credentials, plan_type))

        monkeypatch.setattr("backend.supabase_data.upsert_user_provider_connection", fake_upsert)
        await codex_manager.evict(user_id)

        assert len(upserts) == 1
        u, status, encrypted, plan_type = upserts[0]
        assert u == user_id
        assert status == "linked"
        assert plan_type == "plus"  # preservado de la fila leída
        assert decrypt_user_api_key(encrypted, user_id) == new_content
        # CODEX_HOME borrado y semáforos liberados.
        assert not home.exists()
        assert codex_manager.active_count == 0
        assert not server.is_alive

    @pytest.mark.asyncio(loop_scope="session")
    async def test_shutdown_idempotent_and_never_raises(self):
        await codex_manager.acquire(_uid(60))
        await codex_manager.acquire(_uid(61))
        await codex_manager.shutdown()
        await codex_manager.shutdown()  # segunda llamada: no-op
        assert codex_manager.active_count == 0
        # Con nada que cerrar tampoco lanza.
        await codex_manager.shutdown()


class TestEvictionAcquireSerialization:
    """F01: la evacuación de un tenant (LRU/evict) y un acquire concurrente
    del mismo user_id nunca comparten el mismo CODEX_HOME a la vez: el lock
    de evicción del tenant se mantiene durante TODO terminate/snapshot/
    cleanup y el acquire espera a que termine antes de restaurar/spawnear.
    """

    @pytest.mark.asyncio(loop_scope="session")
    async def test_lru_eviction_blocks_concurrent_acquire_until_cleanup_done(self):
        user_id = _uid(90)
        root = tempfile.mkdtemp(prefix="codex-evict-race-")
        try:
            manager = CodexAppServerManager(bin_path=_FAKE_BIN, home_root=root)
            server = await manager.acquire(user_id)
            assert manager.active_count == 1

            # Hooks para intercalar de forma determinista: la evacuación LRU
            # queda bloqueada a mitad del snapshot (el server ya fue sacado
            # del registro); mientras tanto un acquire concurrente del mismo
            # tenant intenta re-crear el proceso sobre el MISMO home.
            events: list[str] = []
            snapshot_started = asyncio.Event()
            let_snapshot_finish = asyncio.Event()
            restore_seen = asyncio.Event()

            real_snapshot = manager._snapshot_auth

            async def gated_snapshot(srv):
                events.append("snapshot_started")
                snapshot_started.set()
                await let_snapshot_finish.wait()
                await real_snapshot(srv)
                events.append("snapshot_done")

            real_restore = manager._restore_auth_json

            async def traced_restore(uid, home):
                events.append("restore_began")
                restore_seen.set()
                try:
                    await real_restore(uid, home)
                finally:
                    events.append("restore_done")

            real_cleanup = manager._cleanup_home

            def traced_cleanup(srv):
                real_cleanup(srv)
                events.append("home_cleaned")

            manager._snapshot_auth = gated_snapshot
            manager._restore_auth_json = traced_restore
            manager._cleanup_home = traced_cleanup

            evict_task = asyncio.create_task(manager._evict_lru_idle())
            await asyncio.wait_for(snapshot_started.wait(), timeout=5)
            # La evacuación está a mitad del cleanup (snapshot en curso) y el
            # server ya no está registrado: el acquire NO debe tocar el home
            # hasta que la evacuación termine por completo.
            acquire_task = asyncio.create_task(manager.acquire(user_id))
            try:
                await asyncio.wait_for(restore_seen.wait(), timeout=1.5)
                interleaved = True  # re-spawneó durante el cleanup: carrera
            except asyncio.TimeoutError:
                interleaved = False  # esperó al lock de evicción del tenant
            let_snapshot_finish.set()

            assert await asyncio.wait_for(evict_task, timeout=5)
            new_server = await asyncio.wait_for(acquire_task, timeout=5)

            # Nunca dos ciclos de vida sobre el mismo home: la restauración
            # del nuevo ciclo arranca solo tras el snapshot Y el borrado del
            # home del ciclo anterior.
            assert not interleaved
            assert "restore_began" in events
            assert events.index("restore_began") > events.index("snapshot_done")
            assert events.index("restore_began") > events.index("home_cleaned")
            assert new_server is not server
            assert new_server.is_alive
            assert manager.active_count == 1
            assert Path(root, user_id).is_dir()
            await manager.shutdown()
        finally:
            shutil.rmtree(root, ignore_errors=True)
