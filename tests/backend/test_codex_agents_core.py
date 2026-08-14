"""Unit tests para las variantes Codex de agentes núcleo (T05).

Cubren el contrato congelado de `plan.md` → Cross-task interfaces:
`run_explainer_codex`, `run_subpart_explainer_codex`,
`run_explainer_codex_validated`, `run_subpart_explainer_codex_validated`,
`run_with_codex_explainer_validation` (backend/agents/explainer_codex.py) y
`run_segmentador_codex` (segmentador.py) / `run_page_classifier_codex`
(page_classifier.py): corrutinas async, `user_id` en la posición de `api_key`
de las variantes `_ds`, retorno `(data, CodexUsage)` / `(data, CodexUsage,
list)` las validadas, reintentos deterministas y errores tipados — siempre a
través del fake de T02 (`tests/backend/fake_codex_app_server.py`, read-only)
vía `CODEX_BIN_PATH` y salidas de turno scripted con fixtures JSON propios de
`tests/backend/fixtures_codex/`; sin red ni credenciales reales.

Los tests corren sobre un único loop de sesión (igual que test_codex_client.py)
para que el singleton `codex_manager` sea seguro de reutilizar entre tests.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

# --- Configuración del entorno ANTES de importar los módulos bajo test: el
# gestor lee sus límites de env en el import. Valores idénticos a los de
# test_codex_client.py para que el singleton compartido se comporte igual en
# cualquier orden de colección.
_FAKE_BIN = str(Path(__file__).resolve().parent / "fake_codex_app_server.py")
_TEST_HOME_ROOT = tempfile.mkdtemp(prefix="codex-agents-tests-")
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
from backend.agents import explainer_codex, page_classifier, segmentador  # noqa: E402
from backend.agents.completeness_validator import (  # noqa: E402
    MAX_EXPLAINER_VALIDATION_RETRIES,
    ExplainerValidationError,
)
from backend.agents.explainer_openrouter import (  # noqa: E402
    OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES,
    build_openrouter_explainer_system_prompt,
)
from backend.codex_app_server import codex_manager  # noqa: E402
from backend.codex_client import (  # noqa: E402
    CODEX_RATE_LIMIT_MESSAGE,
    CODEX_TIMEOUT_MESSAGE,
    CodexError,
    CodexRateLimitError,
    CodexTimeoutError,
    CodexUsage,
)
from backend.codex_model_routing import CODEX_MODEL  # noqa: E402

SOURCE_TEXT = (
    "Fuente de prueba: el teorema de Pitagoras relaciona los catetos "
    "y la hipotenusa de un triangulo rectangulo."
)


def _uid(i: int) -> str:
    """UUID determinista de 36 chars (formato aceptado por el gestor)."""
    return f"{i:08d}-0000-4000-8000-{i:012d}"


def _fixture(name: str) -> str:
    return (_FIXTURES_DIR / name).read_text(encoding="utf-8")


def _write_source(tmp_path) -> Path:
    source = tmp_path / "fuente.txt"
    source.write_text(SOURCE_TEXT, encoding="utf-8")
    return source


def _params_message_text(params: dict) -> str:
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


def _turn_texts(requests: list[tuple[str, dict | None]]) -> list[str]:
    return [_params_message_text(params) for method, params in requests if method == "turn/start"]


def _turn_params(requests: list[tuple[str, dict | None]]) -> list[dict]:
    return [params for method, params in requests if method == "turn/start"]


class _RecordingServer:
    """Envuelve un CodexAppServer y registra los requests del cliente."""

    def __init__(self, server):
        self._server = server
        self.requests: list[tuple[str, dict | None]] = []

    async def request(self, method, params=None, timeout=None):
        self.requests.append((method, params))
        if timeout is None:
            return await self._server.request(method)
        return await self._server.request(method, params, timeout=timeout)


class _RecordingManager:
    """Envuelve el singleton `codex_manager` para observar los requests.

    El wrapper se cachea por `user_id` (igual que el gestor real): cada
    `call_codex_chat` re-adquiere el proceso del tenant, y todas las llamadas
    de un mismo test deben quedar registradas en la MISMA lista.
    """

    def __init__(self, real):
        self._real = real
        self.servers: dict[str, _RecordingServer] = {}

    async def acquire(self, user_id):
        if user_id in self.servers:
            return self.servers[user_id]
        server = await self._real.acquire(user_id)
        recorded = _RecordingServer(server)
        self.servers[user_id] = recorded
        return recorded


def _install_recording(monkeypatch) -> _RecordingManager:
    manager = _RecordingManager(codex_manager)
    monkeypatch.setattr(codex_client, "codex_manager", manager)
    return manager


def _set_turn_file(monkeypatch, turn_file: Path) -> None:
    monkeypatch.setenv("FAKE_CODEX_SCENARIO", "scripted_turn")
    monkeypatch.setenv("FAKE_CODEX_TURN_OUTPUT_FILE", str(turn_file))


def _set_usage_file(monkeypatch, usage_file: Path) -> None:
    """Fija el fichero de usage compañero (wire-format FR-01: el usage viaja
    en la notificación `thread/tokenUsage/updated`, no en el turno)."""
    monkeypatch.setenv("FAKE_CODEX_TOKEN_USAGE_FILE", str(usage_file))


def _script_turns(monkeypatch, turn_file: Path, fixture_names: list[str]) -> None:
    """Salidas de turno deterministas y secuenciales.

    El fake lee el fichero de salida en CADA turn/start; el hook sobre
    `_parse_turn_json` reescribe el fichero tras parsear el turno N con el
    contenido del turno N+1, de modo que la secuencia de fixtures es exacta.
    """
    calls = {"n": 0}
    real_parse = codex_client._parse_turn_json

    def switching_parse(text):
        index = calls["n"]
        calls["n"] += 1
        if index + 1 < len(fixture_names):
            turn_file.write_text(_fixture(fixture_names[index + 1]), encoding="utf-8")
        return real_parse(text)

    monkeypatch.setattr(codex_client, "_parse_turn_json", switching_parse)


@pytest.fixture(autouse=True)
def _codex_singleton_env(tmp_path_factory, monkeypatch):
    """Fija binario, home y límites del singleton `codex_manager` por test."""
    import backend.codex_app_server as codex_app_server

    home_root = tmp_path_factory.mktemp("codex-agents-home")
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


class TestExplainerCodex:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_run_explainer_codex_happy_path(self, monkeypatch, tmp_path):
        user_id = _uid(301)
        _set_turn_file(monkeypatch, _FIXTURES_DIR / "turn_explainer_full.json")
        _set_usage_file(monkeypatch, _FIXTURES_DIR / "turn_explainer_full.usage.json")
        manager = _install_recording(monkeypatch)

        result, usage = await explainer_codex.run_explainer_codex(
            str(_write_source(tmp_path)),
            "Parte 1: El teorema de Pitagoras",
            mime_type="text/plain",
            user_id=user_id,
        )

        assert result["introduccion"].startswith("El teorema de Pitagoras")
        assert result["desarrollo"][0]["titulo_seccion"] == "Enunciado del teorema"
        assert result["desarrollo"][0]["subsecciones"][0]["titulo_subseccion"] == (
            "Formulacion algebraica"
        )
        assert result["conclusion"]
        assert isinstance(usage, CodexUsage)
        assert usage.cost_usd == 0.0
        assert usage.cost_source == "chatgpt_quota"
        assert usage.quota_requests == 1
        assert usage.prompt_token_count == 1200
        assert usage.candidates_token_count == 340

        requests = manager.servers[user_id].requests
        assert [method for method, _ in requests] == ["thread/start", "turn/start"]
        _, params = requests[1]
        # Wire v2 (FR-01b): model + input; temperature NO se envía.
        assert params["model"] == CODEX_MODEL
        assert "temperature" not in params
        assert "teorema" in _params_message_text(params)
        # El system prompt viaja en thread/start.developerInstructions.
        assert requests[0][1]["developerInstructions"] == (
            build_openrouter_explainer_system_prompt("es-ES")
        )

    @pytest.mark.asyncio(loop_scope="session")
    async def test_run_explainer_codex_invalid_payload_retries_then_codex_error(
        self, monkeypatch, tmp_path
    ):
        user_id = _uid(302)
        _set_turn_file(monkeypatch, _FIXTURES_DIR / "turn_explainer_invalid.json")
        manager = _install_recording(monkeypatch)

        with pytest.raises(CodexError) as exc_info:
            await explainer_codex.run_explainer_codex(
                str(_write_source(tmp_path)),
                "Parte 1: El teorema de Pitagoras",
                mime_type="text/plain",
                user_id=user_id,
            )
        # Espejo de `_call_deepseek_with_validation_retries`: en el último
        # intento se re-lanza el error de contrato del payload.
        assert str(exc_info.value).startswith("Campo inválido en desarrollo")
        # No es un subtipo mapeado del cliente: es el error de contrato del agente.
        assert not isinstance(exc_info.value, CodexRateLimitError)

        requests = manager.servers[user_id].requests
        expected_turns = OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES + 1
        # Espejo de `_call_deepseek_with_validation_retries`: cada intento es
        # una llamada completa nueva (thread/start + turn/start) que re-envía
        # la fuente y valida el payload.
        assert [method for method, _ in requests] == [
            "thread/start",
            "turn/start",
        ] * expected_turns
        # Espejo de `_call_deepseek_with_validation_retries`: cada intento
        # re-envía la llamada completa (fuente incluida) y valida el payload.
        for text in _turn_texts(requests):
            assert SOURCE_TEXT in text

    @pytest.mark.asyncio(loop_scope="session")
    async def test_run_explainer_codex_timeout_propagates_codex_timeout_error(
        self, monkeypatch, tmp_path
    ):
        """Timeout del cliente: el agente propaga `CodexTimeoutError` tal cual.

        Escenario `slow_turn` del fake de T02 (responde tras
        `FAKE_CODEX_SLOW_DELAY_SECONDS` > timeout del request), igual que
        `test_codex_client.py::test_timeout_raises_codex_timeout_error`. La
        firma congelada del agente no expone `timeout`, así que se inyecta un
        timeout corto por monkeypatch sobre la referencia `call_codex_chat`
        del módulo del agente (el cliente y el fake reales hacen el trabajo).

        El flujo del explainer espera `call_codex_chat` FUERA de cualquier
        try/except (los únicos catches son de validación de payload, tras la
        llamada): el error tipado debe salir sin remapearse a `CodexError`
        genérico ni envolverse.
        """
        user_id = _uid(311)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "slow_turn")
        # Retardo del fake > timeout del request: el timeout es determinista.
        monkeypatch.setenv("FAKE_CODEX_SLOW_DELAY_SECONDS", "5")

        real_call = explainer_codex.call_codex_chat

        async def _short_timeout_call(*args, **kwargs):
            kwargs["timeout"] = 0.2
            return await real_call(*args, **kwargs)

        monkeypatch.setattr(explainer_codex, "call_codex_chat", _short_timeout_call)

        with pytest.raises(CodexTimeoutError) as exc_info:
            await explainer_codex.run_explainer_codex(
                str(_write_source(tmp_path)),
                "Parte 1: El teorema de Pitagoras",
                mime_type="text/plain",
                user_id=user_id,
            )
        # Error tipado sin remapear ni envolver: es exactamente el tipo que
        # lanza el cliente (no un `CodexError` genérico del agente).
        assert type(exc_info.value) is CodexTimeoutError
        # Contrato de usuario que consumirá el pipeline: el mensaje UX del
        # cliente (mismo shape `.message` que el test de rate-limit).
        assert exc_info.value.message == CODEX_TIMEOUT_MESSAGE

    @pytest.mark.asyncio(loop_scope="session")
    async def test_run_subpart_explainer_codex_happy_path(self, monkeypatch, tmp_path):
        user_id = _uid(303)
        _set_turn_file(monkeypatch, _FIXTURES_DIR / "turn_explainer_subpart.json")
        manager = _install_recording(monkeypatch)

        result, usage = await explainer_codex.run_subpart_explainer_codex(
            str(_write_source(tmp_path)),
            "Subparte 1.1: Formulacion algebraica",
            mime_type="text/plain",
            user_id=user_id,
        )

        assert set(result) == {"desarrollo"}
        assert result["desarrollo"][0]["subsecciones"][0]["titulo_subseccion"] == (
            "Ecuacion principal"
        )
        assert isinstance(usage, CodexUsage)
        assert usage.quota_requests == 1
        requests = manager.servers[user_id].requests
        assert [method for method, _ in requests] == ["thread/start", "turn/start"]

    @pytest.mark.asyncio(loop_scope="session")
    async def test_run_explainer_codex_validated_retries_on_incomplete(
        self, monkeypatch, tmp_path
    ):
        user_id = _uid(304)
        turn_file = tmp_path / "turn_scripted.json"
        turn_file.write_text(_fixture("turn_explainer_full.json"), encoding="utf-8")
        _set_turn_file(monkeypatch, turn_file)
        _script_turns(
            monkeypatch,
            turn_file,
            [
                "turn_explainer_full.json",
                "turn_validator_reject.json",
                "turn_explainer_full.json",
                "turn_validator_accept.json",
            ],
        )
        manager = _install_recording(monkeypatch)
        source_path = _write_source(tmp_path)

        result, usage, validator_usages = await explainer_codex.run_explainer_codex_validated(
            str(source_path),
            "Parte 1: El teorema de Pitagoras",
            mime_type="text/plain",
            user_id=user_id,
            validator_user_id=user_id,
        )

        assert result["desarrollo"][0]["titulo_seccion"] == "Enunciado del teorema"
        assert isinstance(usage, CodexUsage)
        assert usage.quota_requests == 1
        # Dos turnos de validación (rechazo + aceptación), cada uno con su
        # quota_requests=1: el coste de la validación es honesto.
        assert len(validator_usages) == 2
        assert all(isinstance(item, CodexUsage) for item in validator_usages)
        assert sum(item.quota_requests for item in validator_usages) == 2

        requests = manager.servers[user_id].requests
        assert [method for method, _ in requests] == [
            "thread/start",
            "turn/start",
        ] * 4
        turn_texts = _turn_texts(requests)
        # El reintento conversacional añade el turno anterior + el feedback:
        # el primer user message (con la fuente) se mantiene byte-idéntico y el
        # feedback de validación aparece dentro del mensaje del reintento.
        assert turn_texts[2].startswith(turn_texts[0])
        assert "explicacion_anterior_no_valida" in turn_texts[2]
        assert "regenérala completa" in turn_texts[2]

    @pytest.mark.asyncio(loop_scope="session")
    async def test_run_subpart_explainer_codex_validated_happy_path(
        self, monkeypatch, tmp_path
    ):
        user_id = _uid(305)
        turn_file = tmp_path / "turn_scripted.json"
        turn_file.write_text(_fixture("turn_explainer_subpart.json"), encoding="utf-8")
        _set_turn_file(monkeypatch, turn_file)
        _script_turns(
            monkeypatch,
            turn_file,
            ["turn_explainer_subpart.json", "turn_validator_accept.json"],
        )
        manager = _install_recording(monkeypatch)

        result, usage, validator_usages = (
            await explainer_codex.run_subpart_explainer_codex_validated(
                str(_write_source(tmp_path)),
                "Subparte 1.1: Formulacion algebraica",
                mime_type="text/plain",
                user_id=user_id,
                validator_user_id=user_id,
            )
        )

        assert set(result) == {"desarrollo"}
        assert isinstance(usage, CodexUsage)
        assert len(validator_usages) == 1
        assert isinstance(validator_usages[0], CodexUsage)
        requests = manager.servers[user_id].requests
        assert [method for method, _ in requests] == ["thread/start", "turn/start"] * 2

    @pytest.mark.asyncio(loop_scope="session")
    async def test_run_explainer_codex_validated_exhausted_raises_validation_error(
        self, monkeypatch, tmp_path
    ):
        user_id = _uid(306)
        turn_file = tmp_path / "turn_scripted.json"
        turn_file.write_text(_fixture("turn_explainer_full.json"), encoding="utf-8")
        _set_turn_file(monkeypatch, turn_file)
        _script_turns(
            monkeypatch,
            turn_file,
            [
                "turn_explainer_full.json",
                "turn_validator_reject.json",
                "turn_explainer_full.json",
                "turn_validator_reject.json",
                "turn_explainer_full.json",
                "turn_validator_reject.json",
            ],
        )
        manager = _install_recording(monkeypatch)

        with pytest.raises(ExplainerValidationError) as exc_info:
            await explainer_codex.run_explainer_codex_validated(
                str(_write_source(tmp_path)),
                "Parte 1: El teorema de Pitagoras",
                mime_type="text/plain",
                user_id=user_id,
                validator_user_id=user_id,
            )

        assert exc_info.value.label == f"Explainer Codex [{CODEX_MODEL}]"
        assert exc_info.value.report.is_complete is False
        # 3 evaluaciones (inicial + MAX_EXPLAINER_VALIDATION_RETRIES): 3 llamadas
        # explainer + 3 validaciones.
        requests = manager.servers[user_id].requests
        assert [method for method, _ in requests] == [
            "thread/start",
            "turn/start",
        ] * (2 * (MAX_EXPLAINER_VALIDATION_RETRIES + 1))


class TestSegmentadorCodex:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_run_segmentador_codex_happy_path_and_conversation_retry(
        self, monkeypatch
    ):
        user_id = _uid(307)
        _set_turn_file(monkeypatch, _FIXTURES_DIR / "turn_segmentador.json")
        manager = _install_recording(monkeypatch)
        source_text = (
            "=== BLOQUE 1 ===\nIntroduccion a la geometria plana.\n"
            "=== BLOQUE 2 ===\nTriangulos y el teorema de Pitagoras."
        )
        description = "Segmenta este documento academico en partes."

        data, usage, conversation = await segmentador.run_segmentador_codex(
            user_id, source_text, description
        )

        assert data["decision_num_partes"] == 2
        assert data["partes"][0]["titulo"] == "Fundamentos de geometria"
        assert isinstance(usage, CodexUsage)
        assert usage.quota_requests == 1
        assert len(conversation) == 2
        assert conversation[0]["role"] == "user"
        assert conversation[1]["role"] == "assistant"

        # Retry por cobertura: misma firma, conversación previa + corrección.
        data2, usage2, conversation2 = await segmentador.run_segmentador_codex(
            user_id,
            source_text,
            description,
            conversation=conversation,
            correction="La cobertura no es completa: falta la ultima pagina.",
        )
        assert data2["decision_num_partes"] == 2
        assert isinstance(usage2, CodexUsage)
        # Prefijo byte-idéntico: system + primer user message no cambian.
        assert conversation2[0]["content"] == conversation[0]["content"]
        assert conversation2[1]["content"] == conversation[1]["content"]
        assert conversation2[2]["role"] == "user"
        assert "cobertura" in conversation2[2]["content"]
        assert conversation2[3]["role"] == "assistant"

        requests = manager.servers[user_id].requests
        assert [method for method, _ in requests] == [
            "thread/start",
            "turn/start",
        ] * 2
        # Wire v2 (FR-01b): el system prompt viaja en thread/start y es
        # idéntico entre llamadas; temperature NO se envía en turn/start.
        thread_params = [
            params for method, params in requests if method == "thread/start"
        ]
        assert len(thread_params) == 2
        assert thread_params[0]["developerInstructions"] == (
            thread_params[1]["developerInstructions"]
        )
        assert thread_params[0]["developerInstructions"]
        turn_params = _turn_params(requests)
        assert "temperature" not in turn_params[0]
        turn_texts = _turn_texts(requests)
        assert turn_texts[1].startswith(turn_texts[0])

    @pytest.mark.asyncio(loop_scope="session")
    async def test_run_segmentador_codex_non_object_json_raises_codex_error(
        self, monkeypatch
    ):
        user_id = _uid(308)
        _set_turn_file(monkeypatch, _FIXTURES_DIR / "turn_json_array.json")

        with pytest.raises(CodexError, match="no devolvió un objeto JSON"):
            await segmentador.run_segmentador_codex(
                user_id, "Fuente de prueba.", "Segmenta."
            )


class TestPageClassifierCodex:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_run_page_classifier_codex_happy_path(self, monkeypatch):
        user_id = _uid(309)
        _set_turn_file(monkeypatch, _FIXTURES_DIR / "turn_classifier.json")
        _set_usage_file(monkeypatch, _FIXTURES_DIR / "turn_classifier.usage.json")
        manager = _install_recording(monkeypatch)

        content_pages, usage, raw = await page_classifier.run_page_classifier_codex(
            user_id, "OCR de prueba.", 5
        )

        assert content_pages == frozenset({1, 2, 3, 5})
        assert raw["total_paginas"] == 5
        assert isinstance(usage, CodexUsage)
        assert usage.quota_requests == 1
        assert usage.prompt_token_count == 700

        requests = manager.servers[user_id].requests
        assert [method for method, _ in requests] == ["thread/start", "turn/start"]
        _, params = requests[1]
        # Wire v2 (FR-01b): model + input; temperature NO se envía.
        assert params["model"] == CODEX_MODEL
        assert "temperature" not in params

    @pytest.mark.asyncio(loop_scope="session")
    async def test_run_page_classifier_codex_rate_limit_error(self, monkeypatch):
        user_id = _uid(310)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "scripted_error")
        monkeypatch.setenv("FAKE_CODEX_ERROR_CODE", "UsageLimitExceeded")

        with pytest.raises(CodexRateLimitError) as exc_info:
            await page_classifier.run_page_classifier_codex(user_id, "OCR.", 5)
        assert exc_info.value.message == CODEX_RATE_LIMIT_MESSAGE
