"""Unit tests para las variantes Codex de la familia (T06).

Cubre `run_recorrido_codex`, `run_resources_codex` (sin búsqueda web en v1),
`run_review_codex` y `format_explainer_content_codex` (contrato
`(data, CodexUsage)` / `(dict, dict)`), siempre a través del fake de T02
(`tests/backend/fake_codex_app_server.py`, read-only) vía `CODEX_BIN_PATH`
con salidas `scripted_turn` desde fixtures JSON propios
(`tests/backend/fixtures_codex/`) — sin red ni credenciales reales.

Escenarios:
- Cada variante feliz con payload determinista y `CodexUsage` con conteos.
- Payload no-objeto (JSON array) → `CodexError` en recorrido/resources.
- Review: payload inválido → reintento (máx
  `OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES`) → éxito o `CodexError`.
- `CodexRateLimitError` propagado (incluido el bucle de reintentos de review).
- Formatter: campos en paralelo (una llamada por campo, conteos agregados,
  coste 0) y `_empty_formatter_usage()` sin campos.

Los tests corren sobre un único loop de sesión (igual que test_codex_client.py)
para que el singleton `codex_manager` sea seguro de reutilizar entre tests.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

# --- Configuración del entorno ANTES de importar los módulos bajo test: el
# gestor lee sus límites de env en el import. Valores idénticos a los de
# test_codex_client.py para que el singleton compartido se comporte igual
# en cualquier orden de colección.
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

import backend.agents.formatter as formatter_module  # noqa: E402
import backend.agents.recorrido as recorrido_module  # noqa: E402
import backend.agents.resources as resources_module  # noqa: E402
import backend.agents.review as review_module  # noqa: E402
from backend.agents.explainer_openrouter import (  # noqa: E402
    OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES,
)
from backend.agents.formatter import (  # noqa: E402
    _empty_formatter_usage,
    format_explainer_content_codex,
)
from backend.agents.recorrido import (  # noqa: E402
    build_recorrido_openrouter_system_instruction,
    run_recorrido_codex,
)
from backend.agents.resources import (  # noqa: E402
    build_resources_codex_system_instruction,
    run_resources_codex,
)
from backend.agents.review import run_review_codex  # noqa: E402
from backend.codex_app_server import codex_manager  # noqa: E402
from backend.codex_client import (  # noqa: E402
    CODEX_RATE_LIMIT_MESSAGE,
    CodexError,
    CodexRateLimitError,
    CodexUsage,
)
from backend.codex_model_routing import CODEX_MODEL  # noqa: E402


def _uid(i: int) -> str:
    """UUID determinista de 36 chars (formato aceptado por el gestor)."""
    return f"{i:08d}-0000-4000-8000-{i:012d}"


def _turn_payload(fixture_name: str) -> dict:
    """Payload JSON parseado desde el texto del fixture de turno.

    Wire-format FR-01: el fixture es TEXTO PLANO UTF-8 con el texto final
    (sin wrapper `role/content/usage`); el usage viaja en ficheros compañeros
    `turn_*.usage.json` (notificación `thread/tokenUsage/updated`).
    """
    raw = (_FIXTURES_DIR / fixture_name).read_text(encoding="utf-8")
    return json.loads(raw)


def _set_scripted_turn(monkeypatch, fixture_name: str) -> None:
    monkeypatch.setenv("FAKE_CODEX_SCENARIO", "scripted_turn")
    monkeypatch.setenv(
        "FAKE_CODEX_TURN_OUTPUT_FILE", str(_FIXTURES_DIR / fixture_name)
    )


def _set_usage_file(monkeypatch, fixture_name: str) -> None:
    """Fija el fichero de usage compañero (mapeo congelado FR-01)."""
    monkeypatch.setenv(
        "FAKE_CODEX_TOKEN_USAGE_FILE", str(_FIXTURES_DIR / fixture_name)
    )


def _install_capturing_wrapper(monkeypatch, module, captured: dict):
    """Envuelve `call_codex_chat` del módulo con un wrapper que captura kwargs
    y delega en el cliente real (el fake de T02)."""
    real = module.call_codex_chat

    async def wrapper(**kwargs):
        captured.update(kwargs)
        return await real(**kwargs)

    monkeypatch.setattr(module, "call_codex_chat", wrapper)


@pytest.fixture(autouse=True)
def _codex_singleton_env(tmp_path_factory, monkeypatch):
    """Fija binario, home y límites del singleton `codex_manager` por test
    (mismo patrón que test_codex_client.py / test_codex_link_endpoints.py)."""
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


class TestRecorridoCodex:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_happy_path_returns_payload_and_usage(self, monkeypatch):
        user_id = _uid(601)
        _set_scripted_turn(monkeypatch, "turn_recorrido_valid.json")
        _set_usage_file(monkeypatch, "turn_recorrido_valid.usage.json")
        captured: dict = {}
        _install_capturing_wrapper(monkeypatch, recorrido_module, captured)

        data, usage = await run_recorrido_codex(
            user_id, "Fuente de la parte.", "Parte 1 del texto."
        )

        expected = _turn_payload("turn_recorrido_valid.json")
        assert data == expected
        assert data["recorrido_anotado"][0]["anotacion"] == (
            "Anotación determinista de prueba."
        )
        assert isinstance(usage, CodexUsage)
        assert usage.prompt_token_count == 100
        assert usage.candidates_token_count == 50
        assert usage.thoughts_token_count == 5
        assert usage.total_token_count == 155
        assert usage.cost_usd == 0.0
        assert usage.cost_source == "chatgpt_quota"
        assert usage.quota_requests == 1
        # Contrato del transporte: user_id en la posición de api_key, builder
        # de prompts existente, modelo por defecto y JSON object.
        assert captured["user_id"] == user_id
        assert captured["model"] == CODEX_MODEL
        assert captured["response_format"] == "json_object"
        assert captured["system_prompt"] == (
            build_recorrido_openrouter_system_instruction("es-ES")
        )
        message = captured["messages"][0]["content"]
        assert "<fuente_de_la_parte>" in message
        assert "Parte 1 del texto." in message

    @pytest.mark.asyncio(loop_scope="session")
    async def test_non_object_json_raises_codex_error(self, monkeypatch):
        user_id = _uid(602)
        _set_scripted_turn(monkeypatch, "turn_recorrido_array_json.json")

        with pytest.raises(CodexError, match="no devolvió un objeto JSON"):
            await run_recorrido_codex(user_id, "Fuente.", "Parte.")

    @pytest.mark.asyncio(loop_scope="session")
    async def test_rate_limit_error_propagates(self, monkeypatch):
        user_id = _uid(603)
        monkeypatch.setenv("FAKE_CODEX_SCENARIO", "usage_limit")

        with pytest.raises(CodexRateLimitError, match=CODEX_RATE_LIMIT_MESSAGE):
            await run_recorrido_codex(user_id, "Fuente.", "Parte.")


class TestResourcesCodex:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_happy_path_without_web_search(self, monkeypatch):
        user_id = _uid(604)
        _set_scripted_turn(monkeypatch, "turn_resources_valid.json")
        _set_usage_file(monkeypatch, "turn_resources_valid.usage.json")
        captured: dict = {}
        _install_capturing_wrapper(monkeypatch, resources_module, captured)

        data, usage = await run_resources_codex(
            user_id, "Fuente de la parte.", "Parte 1 del texto."
        )

        expected = _turn_payload("turn_resources_valid.json")
        assert data == expected
        assert data["ejes_tematicos"][0]["recursos"][0]["titulo"] == "Libro de prueba"
        assert isinstance(usage, CodexUsage)
        assert usage.prompt_token_count == 200
        assert usage.candidates_token_count == 80
        assert usage.thoughts_token_count == 10
        assert usage.total_token_count == 290
        assert usage.cost_usd == 0.0
        assert usage.quota_requests == 1
        assert captured["user_id"] == user_id
        assert captured["model"] == CODEX_MODEL
        assert captured["response_format"] == "json_object"
        # v1 sin búsqueda web: el prompt del sistema lo declara y no referencia
        # herramientas (Tavily/OpenRouter).
        assert "sin búsqueda web" in captured["system_prompt"]
        assert "tavily" not in captured["system_prompt"].lower()
        assert "openrouter_web_search" not in captured["system_prompt"]
        message = captured["messages"][0]["content"]
        assert "Recomienda desde tu conocimiento" in message

    def test_codex_system_instruction_declares_no_web_search(self):
        instruction = build_resources_codex_system_instruction("es-ES")
        assert instruction.startswith("<system_instruction>")
        assert "sin búsqueda web" in instruction
        assert "tavily_search" not in instruction.lower()
        assert "openrouter_web_search" not in instruction
        assert "titulo_mapa" in instruction
        assert "nota_de_integridad" in instruction

    @pytest.mark.asyncio(loop_scope="session")
    async def test_non_object_json_raises_codex_error(self, monkeypatch):
        user_id = _uid(605)
        _set_scripted_turn(monkeypatch, "turn_recorrido_array_json.json")

        with pytest.raises(CodexError, match="no devolvió un objeto JSON"):
            await run_resources_codex(user_id, "Fuente.", "Parte.")


class TestReviewCodex:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_happy_path_returns_validated_payload(self, monkeypatch):
        user_id = _uid(606)
        _set_scripted_turn(monkeypatch, "turn_review_valid.json")
        _set_usage_file(monkeypatch, "turn_review_valid.usage.json")
        captured: dict = {}
        _install_capturing_wrapper(monkeypatch, review_module, captured)

        review, usage = await run_review_codex(
            user_id, {"introduccion": "Contenido."}, "Parte 1"
        )

        assert len(review["preguntas"]) == 5
        assert review["nota"] == "Consejo de estudio breve."
        assert review["preguntas"][0]["pregunta"] == "¿Pregunta uno?"
        assert isinstance(usage, CodexUsage)
        assert usage.prompt_token_count == 300
        assert usage.candidates_token_count == 120
        assert usage.thoughts_token_count == 15
        assert usage.total_token_count == 435
        assert usage.cost_usd == 0.0
        assert usage.quota_requests == 1
        assert captured["user_id"] == user_id
        assert captured["model"] == CODEX_MODEL
        assert captured["system_prompt"] == review_module.build_review_system_instruction(
            "es-ES"
        )

    @pytest.mark.asyncio(loop_scope="session")
    async def test_invalid_payload_retries_then_succeeds(self, monkeypatch):
        user_id = _uid(607)
        valid_payload = _turn_payload("turn_review_valid.json")
        calls = {"n": 0}

        async def fake_call_codex_chat(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"preguntas": [], "nota": ""}, CodexUsage(prompt_token_count=1)
            return valid_payload, CodexUsage(prompt_token_count=2)

        monkeypatch.setattr(review_module, "call_codex_chat", fake_call_codex_chat)

        review, usage = await run_review_codex(
            user_id, {"introduccion": "Contenido."}, "Parte 1"
        )

        assert calls["n"] == 2
        assert len(review["preguntas"]) == 5
        assert usage.prompt_token_count == 2

    @pytest.mark.asyncio(loop_scope="session")
    async def test_invalid_payload_exhausted_raises_codex_error(self, monkeypatch):
        user_id = _uid(608)
        calls = {"n": 0}

        async def fake_call_codex_chat(**kwargs):
            calls["n"] += 1
            return {"preguntas": [], "nota": ""}, CodexUsage()

        monkeypatch.setattr(review_module, "call_codex_chat", fake_call_codex_chat)

        with pytest.raises(CodexError):
            await run_review_codex(user_id, {"introduccion": "Contenido."}, "Parte 1")

        assert calls["n"] == OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES + 1

    @pytest.mark.asyncio(loop_scope="session")
    async def test_rate_limit_error_not_swallowed_by_retry_loop(self, monkeypatch):
        user_id = _uid(609)
        calls = {"n": 0}

        async def fake_call_codex_chat(**kwargs):
            calls["n"] += 1
            raise CodexRateLimitError(CODEX_RATE_LIMIT_MESSAGE)

        monkeypatch.setattr(review_module, "call_codex_chat", fake_call_codex_chat)

        with pytest.raises(CodexRateLimitError, match=CODEX_RATE_LIMIT_MESSAGE):
            await run_review_codex(user_id, {"introduccion": "Contenido."}, "Parte 1")

        assert calls["n"] == 1


class TestFormatterCodex:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_parallel_fields_and_usage_summary(self, monkeypatch):
        user_id = _uid(610)
        _set_scripted_turn(monkeypatch, "turn_formatter_markdown.json")
        _set_usage_file(monkeypatch, "turn_formatter_markdown.usage.json")
        calls = {"n": 0}
        real = formatter_module.call_codex_chat

        async def counting_wrapper(**kwargs):
            calls["n"] += 1
            return await real(**kwargs)

        monkeypatch.setattr(formatter_module, "call_codex_chat", counting_wrapper)

        data = {
            "introduccion": "Intro sin formato.",
            "conclusion": "Conclusión sin formato.",
            "desarrollo": [
                {
                    "titulo_seccion": "Sección 1",
                    "explicacion_introductoria": "Explicación introductoria.",
                    "subsecciones": [
                        {
                            "titulo_subseccion": "Sub 1",
                            "explicacion_detallada": "Detalle de la sub 1.",
                        }
                    ],
                }
            ],
            "conexiones_contextuales": [
                {
                    "seccion_temario_relacionada": "Tema 1",
                    "descripcion_conexion": "Conexión con el tema 1.",
                }
            ],
        }

        result, usage_summary = await format_explainer_content_codex(
            user_id, data, "es-ES"
        )

        # 5 campos de prosa → 5 llamadas en paralelo (una por campo).
        assert calls["n"] == 5
        formatted = "**Texto formateado** determinista de prueba."
        assert result["introduccion"] == formatted
        assert result["conclusion"] == formatted
        assert result["desarrollo"][0]["explicacion_introductoria"] == formatted
        assert (
            result["desarrollo"][0]["subsecciones"][0]["explicacion_detallada"]
            == formatted
        )
        assert result["conexiones_contextuales"][0]["descripcion_conexion"] == formatted
        # Los títulos (no-prosa) no se tocan.
        assert result["desarrollo"][0]["titulo_seccion"] == "Sección 1"
        # Resumen de usage: conteos reportados por campo × 5, coste 0.
        assert usage_summary["input_tokens"] == 1234 * 5
        assert usage_summary["output_tokens"] == (567 + 45) * 5
        assert usage_summary["thoughts_tokens"] == 45 * 5
        assert usage_summary["total_tokens"] == (1234 + 567 + 45) * 5
        assert usage_summary["cost"] == 0.0

    @pytest.mark.asyncio(loop_scope="session")
    async def test_no_fields_returns_empty_formatter_usage(self, monkeypatch):
        user_id = _uid(611)
        empty = {
            "introduccion": "",
            "conclusion": "",
            "desarrollo": [],
            "conexiones_contextuales": [],
        }

        result, usage_summary = await format_explainer_content_codex(
            user_id, empty, "es-ES"
        )

        assert result == empty
        assert usage_summary == _empty_formatter_usage()
