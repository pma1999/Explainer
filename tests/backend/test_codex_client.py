"""Unit tests for backend/codex_client.py y backend/codex_model_routing.py (T03).

Cubren el contrato congelado del cliente Codex sobre el wire-format STREAMING
del fake de T02 (`tests/backend/fake_codex_app_server.py`, read-only):
ciclo de turno FR-01 (response de `turn/start` sin texto ni usage; texto final
de `item/completed` agentMessage; usage de `thread/tokenUsage/updated`;
cierre en `turn/completed`; timeout en `stalled_turn`), request params v2
FR-01b (`thread/start` con `developerInstructions`, `turn/start` con
`input:[{type:"text",text}]` y `threadId`; sin `message`/`system`/
`temperature`/`threadID`/`response_format`), jerarquía de errores tipados
(aceptación por `code`; fallos de turno por `codexErrorInfo`), `CodexUsage`
con el mapeo congelado (defensivo, ceros si faltan campos), el reintento
conversacional ante JSON inválido (turno correctivo corto en el MISMO thread,
sin reenviar la fuente ni el system prompt), el timeout de espera de
`turn/completed` y la concurrencia estanca de dos llamadas simultáneas del
mismo usuario — siempre sin red ni credenciales reales.

Los tests corren sobre un único loop de sesión (igual que
test_codex_app_server.py) para que el singleton `codex_manager` (con
primitivas asyncio ligadas al loop) sea seguro de reutilizar entre tests.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from typing import Any

# --- Configuración del entorno ANTES de importar los módulos bajo test: el
# gestor lee sus límites de env en el import. Valores idénticos a los de
# test_codex_app_server.py para que el singleton compartido se comporte igual
# en cualquier orden de colección.
_FAKE_BIN = str(Path(__file__).resolve().parent / "fake_codex_app_server.py")
_TEST_HOME_ROOT = tempfile.mkdtemp(prefix="codex-client-tests-")
_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures_codex"
os.environ["CODEX_BIN_PATH"] = _FAKE_BIN
os.environ["CODEX_HOME_ROOT"] = _TEST_HOME_ROOT
os.environ["CODEX_SPAWN_WAIT_SECONDS"] = "0.3"
os.environ["CODEX_IDLE_TTL_SECONDS"] = "600"
os.environ["CODEX_REQUEST_TIMEOUT_SECONDS"] = "30"
os.environ["CODEX_MAX_PROCESSES"] = "3"
os.environ["CODEX_PER_PROCESS_MAX_CONCURRENCY"] = "5"
atexit.register(shutil.rmtree, _TEST_HOME_ROOT, True)

from backend import codex_client  # noqa: E402  (env configurado arriba)
from backend.agents.explainer_openrouter import (  # noqa: E402
    OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES,
)
from backend.codex_app_server import (  # noqa: E402
    CodexRequestError,
    codex_manager,
)
from backend.codex_client import (  # noqa: E402
    CODEX_AUTH_MESSAGE,
    CODEX_BUSY_MESSAGE,
    CODEX_RATE_LIMIT_MESSAGE,
    CODEX_TIMEOUT_MESSAGE,
    CODEX_TURN_FAILED_MESSAGE,
    CodexAuthError,
    CodexBusyError,
    CodexError,
    CodexRateLimitError,
    CodexTimeoutError,
    CodexUsage,
    call_codex_chat,
)
from backend.codex_model_routing import (  # noqa: E402
    CODEX_DEFAULT_EFFORT,
    CODEX_EFFORT_LEVELS,
    CODEX_EXPLAINER_MODELS,
    CODEX_MODEL,
    CODEX_MODEL_AUXILIARY,
    normalize_codex_effort,
)


def _uid(i: int) -> str:
    """UUID determinista de 36 chars (formato aceptado por el gestor)."""
    return f"{i:08d}-0000-4000-8000-{i:012d}"


def _params_input_text(params: dict) -> str:
    """Texto plano del `input` de un turn/start v2 (`input[0].text`)."""
    if not isinstance(params, dict):
        return ""
    items = params.get("input", [])
    if not isinstance(items, list):
        return ""
    return "".join(
        item.get("text", "")
        for item in items
        if isinstance(item, dict) and isinstance(item.get("text"), str)
    )


def _set_turn(monkeypatch, turn_file: Path, usage_file: Path | None = None) -> None:
    monkeypatch.setenv("FAKE_CODEX_SCENARIO", "scripted_turn")
    monkeypatch.setenv("FAKE_CODEX_TURN_OUTPUT_FILE", str(turn_file))
    if usage_file is not None:
        monkeypatch.setenv("FAKE_CODEX_TOKEN_USAGE_FILE", str(usage_file))


class _RecordingServer:
    """Envuelve un CodexAppServer y registra requests y results del cliente."""

    def __init__(self, server):
        self._server = server
        self.requests: list[tuple[str, dict | None]] = []
        self.results: list[Any] = []

    async def request(self, method, params=None, timeout=None):
        self.requests.append((method, params))
        if timeout is None:
            result = await self._server.request(method)
        else:
            result = await self._server.request(method, params, timeout=timeout)
        self.results.append(result)
        return result


class _RecordingManager:
    """Envuelve el singleton `codex_manager` para observar los requests."""

    def __init__(self, real):
        self._real = real
        self.servers: dict[str, _RecordingServer] = {}

    async def acquire(self, user_id):
        server = await self._real.acquire(user_id)
        recorded = _RecordingServer(server)
        self.servers.setdefault(user_id, recorded)
        return recorded


def _install_recording(monkeypatch) -> _RecordingManager:
    manager = _RecordingManager(codex_manager)
    monkeypatch.setattr(codex_client, "codex_manager", manager)
    return manager


@pytest.fixture(autouse=True)
def _codex_singleton_env(tmp_path_factory, monkeypatch):
    """Fija binario, home y límites del singleton `codex_manager` por test.

    `main.py` importa `backend.codex_app_server` al coleccionar test_api.py,
    creando el singleton con los valores por defecto del entorno ANTES de que
    este módulo asigne su env en el import. El parche por test (mismo patrón
    que test_codex_link_endpoints.py) lo hace determinista en cualquier orden
    de colección.
    """
    import backend.codex_app_server as codex_app_server

    home_root = tmp_path_factory.mktemp("codex-client-home")
    monkeypatch.setattr(codex_app_server.codex_manager, "_bin_path", _FAKE_BIN)
    monkeypatch.setattr(codex_app_server.codex_manager, "_home_root", home_root)
    monkeypatch.setattr(codex_app_server.codex_manager, "_spawn_wait_seconds", 0.3)
    monkeypatch.setattr(codex_app_server.codex_manager, "_max_processes", 3)
    monkeypatch.setenv("CODEX_HOME_ROOT", str(home_root))
    monkeypatch.setenv("CODEX_BIN_PATH", _FAKE_BIN)
    return home_root


@pytest.fixture(autouse=True)
def _no_supabase(monkeypatch):
    """Aísla los tests de Supabase: sin fila de conexión y sin persistencia."""
    import backend.supabase_data as supabase_data

    monkeypatch.setattr(
        supabase_data, "get_user_provider_connection", lambda user_id: None
    )
    monkeypatch.setattr(
        supabase_data, "upsert_user_provider_connection", lambda *args, **kwargs: None
    )


@pytest_asyncio.fixture(loop_scope="session", autouse=True)
async def _reset_manager():
    """Deja el singleton limpio tras cada test (shutdown es idempotente)."""
    yield
    await codex_manager.shutdown()


class TestModelRouting:
    def test_model_routing_constants(self):
        assert CODEX_MODEL == "gpt-5.6-luna"
        assert CODEX_MODEL_AUXILIARY == CODEX_MODEL
        assert CODEX_EXPLAINER_MODELS == frozenset({CODEX_MODEL})


class TestErrorHierarchy:
    def test_hierarchy_frozen_and_message_attribute(self):
        assert issubclass(CodexRateLimitError, CodexError)
        assert issubclass(CodexAuthError, CodexError)
        assert issubclass(CodexBusyError, CodexError)
        assert issubclass(CodexTimeoutError, CodexError)
        error = CodexError("mensaje")
        assert error.message == "mensaje"
        assert CodexRateLimitError(CODEX_RATE_LIMIT_MESSAGE).message == CODEX_RATE_LIMIT_MESSAGE
        # Constante aditiva FR-01: los mensajes UX existentes no cambian.
        assert CODEX_TURN_FAILED_MESSAGE == (
            "Codex no pudo completar el turno. Espera un poco e inténtalo de nuevo."
        )


class TestHappyPath:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_valid_json_turn_returns_parsed_data_and_usage(self, monkeypatch):
        user_id = _uid(201)
        _set_turn(
            monkeypatch,
            _FIXTURES_DIR / "turn_valid_json.json",
            _FIXTURES_DIR / "turn_valid_json.usage.json",
        )
        manager = _install_recording(monkeypatch)

        data, usage = await call_codex_chat(
            user_id=user_id,
            messages=[{"role": "user", "content": "Explica el teorema de Pitágoras."}],
            system_prompt="Eres un explainer experto.",
        )

        assert data == {"ok": True, "explicacion": "Teorema de Pitágoras"}
        assert isinstance(usage, CodexUsage)
        # Mapeo congelado del brief, campo a campo.
        assert usage.prompt_token_count == 1234  # inputTokens
        assert usage.tool_use_prompt_token_count == 12  # cacheWriteInputTokens
        assert usage.candidates_token_count == 567  # outputTokens
        assert usage.thoughts_token_count == 45  # reasoningOutputTokens
        assert usage.total_token_count == 1801  # totalTokens
        assert usage.cost_usd == 0.0
        assert usage.cost_source == "chatgpt_quota"
        assert usage.quota_requests == 1

        requests = manager.servers[user_id].requests
        assert [method for method, _ in requests] == ["thread/start", "turn/start"]
        thread_params = requests[0][1]
        assert thread_params["model"] == CODEX_MODEL
        assert thread_params["developerInstructions"] == "Eres un explainer experto."
        _, turn_params = requests[1]
        # Request params v2 (FR-01b): threadId + input + model; sin campos v1.
        assert turn_params["threadId"] == "thread_1"
        assert turn_params["input"] == [
            {"type": "text", "text": "Explica el teorema de Pitágoras."}
        ]
        assert turn_params["model"] == CODEX_MODEL
        assert not (
            set(("message", "system", "temperature", "threadID", "response_format"))
            & set(turn_params)
        )

        # La response de turn/start NO contiene texto ni usage (solo acepta
        # el turno): el cliente no lee nada más de ella.
        turn_result = manager.servers[user_id].results[1]
        assert turn_result == {
            "turn": {"id": "turn_1", "status": "inProgress", "items": []}
        }
        assert "text" not in str(turn_result)
        assert "usage" not in str(turn_result)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_usage_zero_when_turn_reports_no_usage(self, monkeypatch):
        user_id = _uid(202)
        _set_turn(monkeypatch, _FIXTURES_DIR / "turn_valid_json_no_usage.json")

        data, usage = await call_codex_chat(
            user_id=user_id,
            messages=[{"role": "user", "content": "Explica algo."}],
            system_prompt="Eres un explainer experto.",
        )

        assert data == {"ok": True, "explicacion": "Teorema de Pitágoras"}
        assert usage.prompt_token_count == 0
        assert usage.tool_use_prompt_token_count == 0
        assert usage.candidates_token_count == 0
        assert usage.thoughts_token_count == 0
        assert usage.total_token_count == 0
        assert usage.cost_usd == 0.0
        assert usage.cost_source == "chatgpt_quota"
        assert usage.quota_requests == 1

    @pytest.mark.asyncio(loop_scope="session")
    async def test_usage_partial_reported_fields_filled(self, monkeypatch):
        user_id = _uid(203)
        # `last` con solo inputTokens/totalTokens y `total` completo con otros
        # valores: se prefiere `last` y los campos ausentes son 0 (nunca se
        # hace fallback por campo a `total`).
        _set_turn(
            monkeypatch,
            _FIXTURES_DIR / "turn_partial_usage.json",
            _FIXTURES_DIR / "turn_partial_usage.usage.json",
        )

        _, usage = await call_codex_chat(
            user_id=user_id,
            messages=[{"role": "user", "content": "Explica algo."}],
            system_prompt="Eres un explainer experto.",
        )

        assert usage.prompt_token_count == 500
        assert usage.total_token_count == 900
        assert usage.candidates_token_count == 0
        assert usage.thoughts_token_count == 0
        assert usage.tool_use_prompt_token_count == 0

    @pytest.mark.asyncio(loop_scope="session")
    async def test_usage_falls_back_to_total_when_last_missing(self, monkeypatch):
        user_id = _uid(204)
        usage_file = Path(tempfile.mkdtemp()) / "usage_no_last.json"
        usage_file.write_text(
            json.dumps(
                {
                    "total": {
                        "inputTokens": 42,
                        "cachedInputTokens": 0,
                        "cacheWriteInputTokens": 3,
                        "outputTokens": 7,
                        "reasoningOutputTokens": 1,
                        "totalTokens": 49,
                    },
                    "modelContextWindow": 100000,
                }
            ),
            encoding="utf-8",
        )
        _set_turn(
            monkeypatch,
            _FIXTURES_DIR / "turn_valid_json_no_usage.json",
            usage_file,
        )

        _, usage = await call_codex_chat(
            user_id=user_id,
            messages=[{"role": "user", "content": "Explica algo."}],
            system_prompt="sys",
        )

        assert usage.prompt_token_count == 42
        assert usage.tool_use_prompt_token_count == 3
        assert usage.candidates_token_count == 7
        assert usage.thoughts_token_count == 1
        assert usage.total_token_count == 49

    @pytest.mark.asyncio(loop_scope="session")
    async def test_text_mode_returns_raw_text(self, monkeypatch):
        user_id = _uid(205)
        _set_turn(
            monkeypatch,
            _FIXTURES_DIR / "turn_text.json",
            _FIXTURES_DIR / "turn_text.usage.json",
        )

        data, usage = await call_codex_chat(
            user_id=user_id,
            messages=[{"role": "user", "content": "Dame texto plano."}],
            system_prompt="Eres un explainer experto.",
            response_format="text",
        )

        assert data == "Respuesta en texto plano."
        assert usage.prompt_token_count == 100
        assert usage.candidates_token_count == 20
        assert usage.total_token_count == 120


class TestConversationalRetry:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_invalid_json_retries_with_corrective_turn_then_succeeds(
        self, monkeypatch, tmp_path
    ):
        user_id = _uid(206)
        # Convención por turno del fake: el turno N lee `<FILE>.<N>` si existe.
        # Turno 1 → texto no-JSON; turno 2 (correctivo) → JSON válido. El
        # usage también sigue la convención: el devuelto es el del turno 2.
        turn_file = tmp_path / "turn_dynamic.json"
        turn_file.write_text(
            (_FIXTURES_DIR / "turn_invalid_json_text.json").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        turn_file_2 = tmp_path / "turn_dynamic.json.2"
        turn_file_2.write_text(
            (_FIXTURES_DIR / "turn_valid_json_retry.json").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        usage_file = tmp_path / "usage_dynamic.json"
        usage_file.write_text(
            json.dumps(
                {
                    "total": {
                        "inputTokens": 10,
                        "outputTokens": 2,
                        "totalTokens": 12,
                    },
                    "last": {
                        "inputTokens": 10,
                        "outputTokens": 2,
                        "totalTokens": 12,
                    },
                    "modelContextWindow": 100000,
                }
            ),
            encoding="utf-8",
        )
        usage_file_2 = tmp_path / "usage_dynamic.json.2"
        usage_file_2.write_text(
            json.dumps(
                {
                    "total": {
                        "inputTokens": 99,
                        "cachedInputTokens": 0,
                        "cacheWriteInputTokens": 5,
                        "outputTokens": 11,
                        "reasoningOutputTokens": 0,
                        "totalTokens": 110,
                    },
                    "last": {
                        "inputTokens": 99,
                        "cachedInputTokens": 0,
                        "cacheWriteInputTokens": 5,
                        "outputTokens": 11,
                        "reasoningOutputTokens": 0,
                        "totalTokens": 110,
                    },
                    "modelContextWindow": 100000,
                }
            ),
            encoding="utf-8",
        )
        _set_turn(monkeypatch, turn_file, usage_file)
        manager = _install_recording(monkeypatch)

        source = "Explica el teorema de Pitágoras."
        data, usage = await call_codex_chat(
            user_id=user_id,
            messages=[{"role": "user", "content": source}],
            system_prompt="Eres un explainer experto.",
        )

        assert data == {"ok": True, "explicacion": "Teorema corregido"}
        # El usage reportado es el del intento exitoso (turno 2).
        assert usage.prompt_token_count == 99
        assert usage.tool_use_prompt_token_count == 5
        assert usage.total_token_count == 110

        requests = manager.servers[user_id].requests
        assert [method for method, _ in requests] == [
            "thread/start",
            "turn/start",
            "turn/start",
        ]
        thread_id = "thread_1"
        assert requests[1][1]["threadId"] == "thread_1"
        # El turno correctivo es un NUEVO turn/start en el MISMO thread.
        assert requests[2][1]["threadId"] == "thread_1"
        # El turno correctivo es corto: no reenvía la fuente ni el system
        # prompt (el system viaja SOLO en thread/start.developerInstructions).
        _, corrective_params = requests[2]
        assert "system" not in corrective_params
        assert "developerInstructions" not in corrective_params
        corrective_text = _params_input_text(corrective_params)
        assert "JSON" in corrective_text
        assert source not in corrective_text
        assert corrective_params["model"] == CODEX_MODEL

    @pytest.mark.asyncio(loop_scope="session")
    async def test_json_retries_exhausted_raises_codex_error(self, monkeypatch):
        user_id = _uid(207)
        _set_turn(monkeypatch, _FIXTURES_DIR / "turn_invalid_json_text.json")
        manager = _install_recording(monkeypatch)

        source = "Fuente del proyecto."
        with pytest.raises(CodexError) as exc_info:
            await call_codex_chat(
                user_id=user_id,
                messages=[{"role": "user", "content": source}],
                system_prompt="System prompt.",
            )

        # Agotamiento de reintentos: CodexError base, no un subtipo mapeado.
        assert not isinstance(
            exc_info.value,
            (CodexRateLimitError, CodexAuthError, CodexBusyError, CodexTimeoutError),
        )
        assert "JSON" in str(exc_info.value)

        requests = manager.servers[user_id].requests
        expected_turns = OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES + 1
        assert [method for method, _ in requests] == [
            "thread/start",
            *(["turn/start"] * expected_turns),
        ]
        # Todos los turnos en el MISMO thread; los correctivos (desde
        # requests[2]) son cortos, sin fuente ni system/developerInstructions.
        assert all(
            params["threadId"] == "thread_1"
            for _, params in requests[1:]
        )
        for _, params in requests[2:]:
            corrective_text = _params_input_text(params)
            assert "JSON" in corrective_text
            assert source not in corrective_text
            assert "system" not in params
            assert "developerInstructions" not in params


class TestTurnFailureMapping:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_usage_limit_notification_maps_to_rate_limit_error(
        self, monkeypatch
    ):
        user_id = _uid(208)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "usage_limit")

        with pytest.raises(CodexRateLimitError) as exc_info:
            await call_codex_chat(
                user_id=user_id,
                messages=[{"role": "user", "content": "hola"}],
                system_prompt="sys",
            )
        assert exc_info.value.message == CODEX_RATE_LIMIT_MESSAGE

    def test_unauthorized_error_info_maps_to_auth_error(self):
        error = codex_client._map_turn_error(
            {"codexErrorInfo": "unauthorized"}, None
        )
        assert isinstance(error, CodexAuthError)
        assert error.message == CODEX_AUTH_MESSAGE

    def test_unknown_error_info_maps_to_generic_turn_failed(self):
        error = codex_client._map_turn_error(
            {"codexErrorInfo": "sessionBudgetExceeded"}, None
        )
        assert type(error) is CodexError
        assert error.message == CODEX_TURN_FAILED_MESSAGE

    def test_missing_error_maps_to_generic_turn_failed(self):
        error = codex_client._map_turn_error(None, None)
        assert type(error) is CodexError
        assert error.message == CODEX_TURN_FAILED_MESSAGE

    def test_unexpected_turn_completed_status_maps_to_generic(self):
        # `turn/completed` con status distinto de completed/failed → genérico.
        error = codex_client._map_turn_outcome("paused", None, None)
        assert type(error) is CodexError
        assert error.message == CODEX_TURN_FAILED_MESSAGE
        # completed es éxito y failed usa el mapeo de turn.error.
        assert codex_client._map_turn_outcome("completed", None, None) is None
        rate = codex_client._map_turn_outcome(
            "failed",
            {"codexErrorInfo": "usageLimitExceeded"},
            {"codexErrorInfo": "usageLimitExceeded"},
        )
        assert isinstance(rate, CodexRateLimitError)


class TestAcceptanceErrorMapping:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_usage_limit_exceeded_maps_to_rate_limit_error(self, monkeypatch):
        user_id = _uid(209)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "scripted_error")
        monkeypatch.setenv("FAKE_CODEX_ERROR_CODE", "UsageLimitExceeded")

        with pytest.raises(CodexRateLimitError) as exc_info:
            await call_codex_chat(
                user_id=user_id,
                messages=[{"role": "user", "content": "hola"}],
                system_prompt="sys",
            )
        assert exc_info.value.message == CODEX_RATE_LIMIT_MESSAGE

    @pytest.mark.asyncio(loop_scope="session")
    async def test_auth_refresh_error_maps_to_auth_error(self, monkeypatch):
        user_id = _uid(210)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "scripted_error")
        monkeypatch.setenv("FAKE_CODEX_ERROR_CODE", "AuthRefreshFailed")

        with pytest.raises(CodexAuthError) as exc_info:
            await call_codex_chat(
                user_id=user_id,
                messages=[{"role": "user", "content": "hola"}],
                system_prompt="sys",
            )
        assert exc_info.value.message == CODEX_AUTH_MESSAGE

    @pytest.mark.asyncio(loop_scope="session")
    async def test_unmapped_error_re_raised_as_codex_request_error(self, monkeypatch):
        user_id = _uid(211)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "scripted_error")
        monkeypatch.setenv("FAKE_CODEX_ERROR_CODE", "BadTurn")

        with pytest.raises(CodexRequestError) as exc_info:
            await call_codex_chat(
                user_id=user_id,
                messages=[{"role": "user", "content": "hola"}],
                system_prompt="sys",
            )
        assert exc_info.value.code == "BadTurn"


class TestTimeoutsAndCapacity:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_stalled_turn_times_out_waiting_for_completed(self, monkeypatch):
        user_id = _uid(212)
        # `stalled_turn`: el turno se acepta (inProgress) y NO llega ninguna
        # notificación posterior: el timeout de la espera de `turn/completed`
        # debe disparar CodexTimeoutError.
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "stalled_turn")

        with pytest.raises(CodexTimeoutError) as exc_info:
            await call_codex_chat(
                user_id=user_id,
                messages=[{"role": "user", "content": "hola"}],
                system_prompt="sys",
                timeout=0.5,
            )
        assert isinstance(exc_info.value, CodexError)
        assert exc_info.value.message == CODEX_TIMEOUT_MESSAGE

    @pytest.mark.asyncio(loop_scope="session")
    async def test_rpc_timeout_raises_codex_timeout_error(self, monkeypatch):
        user_id = _uid(213)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "slow_turn")

        with pytest.raises(CodexTimeoutError) as exc_info:
            await call_codex_chat(
                user_id=user_id,
                messages=[{"role": "user", "content": "hola"}],
                system_prompt="sys",
                timeout=0.2,
            )
        assert isinstance(exc_info.value, CodexError)
        assert exc_info.value.message

    @pytest.mark.asyncio(loop_scope="session")
    async def test_spawn_without_slot_raises_codex_busy_error(self, monkeypatch):
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "slow_turn")
        tasks = []
        try:
            # Ocupar los 3 procesos globales con peticiones lentas en vuelo.
            for i in range(3):
                server = await codex_manager.acquire(_uid(230 + i))
                tasks.append(asyncio.create_task(server.request("turn/start", {})))
            await asyncio.sleep(0.3)
            assert codex_manager.active_count == 3

            with pytest.raises(CodexBusyError) as exc_info:
                await call_codex_chat(
                    user_id=_uid(240),
                    messages=[{"role": "user", "content": "hola"}],
                    system_prompt="sys",
                )
            assert exc_info.value.message == CODEX_BUSY_MESSAGE
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


class TestEffortWire:
    """T01: `effort` en el wire de `turn/start`, nunca en `thread/start`.

    Observación vía `FAKE_CODEX_TRACE_FILE` (el fake de T02 apéndice cada
    request recibido, con sus params, a un JSONL; read-only).
    """

    @staticmethod
    def _set_trace(monkeypatch, tmp_path) -> Path:
        trace = tmp_path / "trace.jsonl"
        monkeypatch.setenv("FAKE_CODEX_TRACE_FILE", str(trace))
        return trace

    @staticmethod
    def _received(trace: Path) -> list[dict]:
        return [
            json.loads(line)
            for line in trace.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    @staticmethod
    def _turn_start_efforts(trace: Path) -> list:
        return [
            msg.get("params", {}).get("effort")
            for msg in TestEffortWire._received(trace)
            if msg.get("method") == "turn/start"
        ]

    @pytest.mark.asyncio(loop_scope="session")
    async def test_effort_xhigh_appears_in_turn_start_wire(self, monkeypatch, tmp_path):
        user_id = _uid(260)
        _set_turn(monkeypatch, _FIXTURES_DIR / "turn_valid_json.json")
        trace = self._set_trace(monkeypatch, tmp_path)

        data, _ = await call_codex_chat(
            user_id=user_id,
            messages=[{"role": "user", "content": "Explica algo."}],
            system_prompt="sys",
            effort="xhigh",
        )

        assert data == {"ok": True, "explicacion": "Teorema de Pitágoras"}
        assert self._turn_start_efforts(trace) == ["xhigh"]

    @pytest.mark.asyncio(loop_scope="session")
    async def test_no_effort_omits_key_from_turn_start_wire(self, monkeypatch, tmp_path):
        user_id = _uid(261)
        _set_turn(monkeypatch, _FIXTURES_DIR / "turn_valid_json.json")
        trace = self._set_trace(monkeypatch, tmp_path)

        await call_codex_chat(
            user_id=user_id,
            messages=[{"role": "user", "content": "Explica algo."}],
            system_prompt="sys",
        )

        turn_starts = [
            msg for msg in self._received(trace) if msg.get("method") == "turn/start"
        ]
        assert turn_starts
        assert all("effort" not in msg["params"] for msg in turn_starts)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_corrective_retry_turn_keeps_same_effort(self, monkeypatch, tmp_path):
        user_id = _uid(262)
        # Convención por turno del fake: el turno N lee `<FILE>.<N>` si existe.
        # Turno 1 → texto no-JSON; turno 2 (correctivo, mismo thread) → válido.
        turn_file = tmp_path / "effort_turn.json"
        turn_file.write_text(
            (_FIXTURES_DIR / "turn_invalid_json_text.json").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        (tmp_path / "effort_turn.json.2").write_text(
            (_FIXTURES_DIR / "turn_valid_json_retry.json").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        _set_turn(monkeypatch, turn_file)
        trace = self._set_trace(monkeypatch, tmp_path)

        data, _ = await call_codex_chat(
            user_id=user_id,
            messages=[{"role": "user", "content": "Fuente."}],
            system_prompt="sys",
            effort="high",
        )

        assert data == {"ok": True, "explicacion": "Teorema corregido"}
        assert self._turn_start_efforts(trace) == ["high", "high"]

    @pytest.mark.asyncio(loop_scope="session")
    async def test_empty_effort_normalizes_to_medium_on_wire(self, monkeypatch, tmp_path):
        """RC-01: `effort=""` se normaliza a medium (contrato congelado
        `None/'' → medium`), no es un 400: el wire lleva `"effort":"medium"`."""
        user_id = _uid(264)
        _set_turn(monkeypatch, _FIXTURES_DIR / "turn_valid_json.json")
        trace = self._set_trace(monkeypatch, tmp_path)

        data, _ = await call_codex_chat(
            user_id=user_id,
            messages=[{"role": "user", "content": "Explica algo."}],
            system_prompt="sys",
            effort="",
        )

        assert data == {"ok": True, "explicacion": "Teorema de Pitágoras"}
        assert self._turn_start_efforts(trace) == ["medium"]

    @pytest.mark.asyncio(loop_scope="session")
    async def test_thread_start_never_carries_effort_or_reasoning_config(
        self, monkeypatch, tmp_path
    ):
        user_id = _uid(263)
        _set_turn(monkeypatch, _FIXTURES_DIR / "turn_valid_json.json")
        trace = self._set_trace(monkeypatch, tmp_path)

        await call_codex_chat(
            user_id=user_id,
            messages=[{"role": "user", "content": "Explica algo."}],
            system_prompt="sys",
            effort="max",
        )

        thread_starts = [
            msg for msg in self._received(trace) if msg.get("method") == "thread/start"
        ]
        assert thread_starts
        for msg in thread_starts:
            assert "effort" not in msg["params"]
            # `config.model_reasoning_effort` NO existe en thread/start (receta
            # integration-effort.md §Gotchas 1-2): sin config ni reasoning_effort.
            assert "config" not in msg["params"]
            assert "model_reasoning_effort" not in msg["params"]


class TestEffortValidation:
    """RC-01/RC-02: semántica unificada de `normalize_codex_effort` (`None`/`""`
    → medium; solo strings NO vacíos fuera de la allowlist → ValueError) y
    validación local en `call_codex_chat` (defensa en profundidad para
    llamadores directos: error de programación, nunca 400 de API)."""

    def test_normalize_none_returns_medium(self):
        assert normalize_codex_effort(None) == CODEX_DEFAULT_EFFORT

    def test_normalize_empty_string_returns_medium(self):
        assert normalize_codex_effort("") == CODEX_DEFAULT_EFFORT

    def test_normalize_allowlist_value_passthrough(self):
        for level in CODEX_EFFORT_LEVELS:
            assert normalize_codex_effort(level) == level

    @pytest.mark.parametrize(
        "bad", ["none", "ultra", "auto", "extra_high", "minimal", "  ", "Medium"]
    )
    def test_normalize_non_empty_non_allowlist_raises_value_error(self, bad):
        with pytest.raises(ValueError, match="no soportado"):
            normalize_codex_effort(bad)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_call_codex_chat_rejects_unsupported_effort(self):
        """RC-02: una llamada directa con un valor fuera de la allowlist es un
        error de programación del llamador (ValueError) ANTES de tocar el
        server; nunca llega un valor arbitrario al wire."""
        with pytest.raises(ValueError, match="no soportado"):
            await call_codex_chat(
                user_id=_uid(265),
                messages=[{"role": "user", "content": "Explica algo."}],
                system_prompt="sys",
                effort="ultra",
            )


class TestConcurrentCalls:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_two_simultaneous_calls_same_user_do_not_cross(self, monkeypatch, tmp_path):
        """Concurrencia estanca: dos llamadas simultáneas del MISMO usuario.

        Cada `turn/start` produce un `turnId` distinto (turn_1/turn_2) y el
        fake lee `<FILE>.1`/`<FILE>.2` (y usage `.1`/`.2`): la correlación por
        `(user_id, turnId)` debe entregar a cada llamada exactamente su texto
        y su usage, sin cruces.
        """
        user_id = _uid(250)
        turn_file = tmp_path / "concurrent_turn.json"
        turn_file.write_text("texto base (no usado)", encoding="utf-8")
        (tmp_path / "concurrent_turn.json.1").write_text(
            json.dumps({"ok": True, "quien": "llamada A"}), encoding="utf-8"
        )
        (tmp_path / "concurrent_turn.json.2").write_text(
            json.dumps({"ok": True, "quien": "llamada B"}), encoding="utf-8"
        )
        usage_file = tmp_path / "concurrent_usage.json"
        usage_file.write_text("{}", encoding="utf-8")

        def _usage_doc(prompt: int, total: int) -> dict:
            return {
                "total": {
                    "inputTokens": prompt,
                    "cachedInputTokens": 0,
                    "cacheWriteInputTokens": 0,
                    "outputTokens": 1,
                    "reasoningOutputTokens": 0,
                    "totalTokens": total,
                },
                "last": {
                    "inputTokens": prompt,
                    "cachedInputTokens": 0,
                    "cacheWriteInputTokens": 0,
                    "outputTokens": 1,
                    "reasoningOutputTokens": 0,
                    "totalTokens": total,
                },
                "modelContextWindow": 100000,
            }

        (tmp_path / "concurrent_usage.json.1").write_text(
            json.dumps(_usage_doc(1000, 1100)), encoding="utf-8"
        )
        (tmp_path / "concurrent_usage.json.2").write_text(
            json.dumps(_usage_doc(2000, 2200)), encoding="utf-8"
        )
        _set_turn(monkeypatch, turn_file, usage_file)

        async def call(text: str):
            return await call_codex_chat(
                user_id=user_id,
                messages=[{"role": "user", "content": text}],
                system_prompt="sys",
                timeout=30,
            )

        results = await asyncio.gather(call("llamada A"), call("llamada B"))

        by_text = {json.dumps(data, sort_keys=True): usage for data, usage in results}
        assert set(by_text) == {
            json.dumps({"ok": True, "quien": "llamada A"}, sort_keys=True),
            json.dumps({"ok": True, "quien": "llamada B"}, sort_keys=True),
        }
        # Cada llamada recibió exactamente su usage (sin cruces).
        assert by_text[
            json.dumps({"ok": True, "quien": "llamada A"}, sort_keys=True)
        ].prompt_token_count == 1000
        assert by_text[
            json.dumps({"ok": True, "quien": "llamada B"}, sort_keys=True)
        ].prompt_token_count == 2000
