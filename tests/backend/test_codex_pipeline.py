"""Wiring del pipeline codex en main.py (T07) — fake app-server + auth_client.

Cubre el contrato de global-constraints.md §Pipeline wiring: proveedor
`codex` de principio a fin en `_process_project` (selección de agentes por
fase, `user_id` en la posición de `api_key`, corrutinas await-eadas directo),
pre-checks de `api_process_project` (vínculo `linked`, Mistral para PDF, regla
`requires_gemini_key`), ramas codex de review/reformat, acumulación de
`codex_quota_requests` con coste 0, fallback YouTube→Gemini y
`part_failed` + SSE con el mensaje UX tipado ante `CodexRateLimitError`.

Infraestructura: fixture `auth_client`-like (override de `get_current_user_id`
con UUID válido para el gestor Codex) + el fake app-server de T02
(`tests/backend/fake_codex_app_server.py`, read-only) vía `CODEX_BIN_PATH`,
ejercido en los tests de agentes reales con salidas de turno scripted desde
`tests/backend/fixtures_codex/`. El pipeline E2E sustituye solo los agentes
codex por fakes deterministas (patrón de `test_part_status_honesty.py`): el
wire-format de cada agente ya está probado en T05/T06 y en el smoke test de
este mismo fichero.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# --- Entorno del singleton del app-server ANTES de importar main: el gestor
# lee sus límites de env en el momento de uso; valores idénticos a los de
# test_codex_client.py para que el singleton compartido se comporte igual en
# cualquier orden de colección.
_FAKE_BIN = str(Path(__file__).resolve().parent / "fake_codex_app_server.py")
_TEST_HOME_ROOT = tempfile.mkdtemp(prefix="codex-pipeline-tests-")
_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures_codex"
os.environ["CODEX_BIN_PATH"] = _FAKE_BIN
os.environ["CODEX_HOME_ROOT"] = _TEST_HOME_ROOT
os.environ["CODEX_SPAWN_WAIT_SECONDS"] = "0.3"
os.environ["CODEX_IDLE_TTL_SECONDS"] = "600"
os.environ["CODEX_REQUEST_TIMEOUT_SECONDS"] = "30"
os.environ["CODEX_MAX_PROCESSES"] = "3"
os.environ["CODEX_PER_PROCESS_MAX_CONCURRENCY"] = "5"
atexit.register(shutil.rmtree, _TEST_HOME_ROOT, True)

# Estabilización del env compartido de la suite (patrón de
# test_codex_env_lazy.py): este módulo es el último de la familia codex en
# colección y su `CODEX_HOME_ROOT` pisaría el home de los tests de T02 (que
# lo aseveran contra su propia constante de módulo). Si T02 está en la
# corrida, se re-afirma su home; este fichero no depende del env (el smoke
# test parchea `_home_root` del singleton por test).
if "test_codex_app_server" in sys.modules:
    import test_codex_app_server as _t02_module  # ya importado: sin efectos

    os.environ["CODEX_HOME_ROOT"] = _t02_module._TEST_HOME_ROOT

import main as main_module  # noqa: E402
from backend.agents import formatter as formatter_module  # noqa: E402
from backend.auth import get_current_user_id  # noqa: E402
from backend.codex_client import (  # noqa: E402
    CODEX_AUTH_MESSAGE,
    CODEX_RATE_LIMIT_MESSAGE,
    CodexAuthError,
    CodexRateLimitError,
    CodexUsage,
)
from backend.codex_model_routing import CODEX_MODEL  # noqa: E402

CODEX_LINK_REQUIRED_MESSAGE = (
    "Vincula tu cuenta ChatGPT en Ajustes para usar Codex (GPT-5.6 Luna)."
)

_UID_COUNTER = [0]


def _uid(i: int) -> str:
    """UUID determinista de 36 chars (formato aceptado por el gestor)."""
    return f"{i:08d}-0000-4000-8000-{i:012d}"


def _new_uid() -> str:
    _UID_COUNTER[0] += 1
    return _uid(900 + _UID_COUNTER[0])


# ---------------------------------------------------------------------------
# Fixtures compartidas
# ---------------------------------------------------------------------------

@pytest.fixture
def codex_auth_client(client):
    """auth_client-like: get_current_user_id → UUID válido para Codex."""
    user_id = _new_uid()
    app = client.app
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    yield client, user_id
    app.dependency_overrides.pop(get_current_user_id, None)


def _usage(**kwargs) -> CodexUsage:
    """CodexUsage determinista (cuota ChatGPT: coste 0, 1 petición)."""
    return CodexUsage(
        prompt_token_count=kwargs.get("prompt", 100),
        tool_use_prompt_token_count=kwargs.get("tool_prompt", 0),
        candidates_token_count=kwargs.get("candidates", 60),
        thoughts_token_count=kwargs.get("thoughts", 0),
        total_token_count=kwargs.get("total", 160),
    )


# ---------------------------------------------------------------------------
# Pre-checks de api_process_project (HTTP, auth_client)
# ---------------------------------------------------------------------------

def _project_dict(*, source_type: str = "web", status: str = "pending") -> dict:
    return {
        "id": "proj-codex-1",
        "name": "Proyecto codex",
        "description": "",
        "pdf_filename": "fuente.pdf" if source_type == "pdf" else "Web: ejemplo",
        "source_type": source_type,
        "source_url": (
            "https://www.youtube.com/watch?v=abcd1234"
            if source_type == "youtube"
            else "https://example.com/articulo"
        ),
        "source_text": "" if source_type == "pdf" else "Texto de ejemplo.",
        "source_metadata": {},
        "status": status,
        "source_object_status": None,
    }


class TestProcessPreChecksCodex:
    """Regla `requires_gemini_key` y pre-checks codex (4 proveedores × 3 fuentes)."""

    def _stub_supabase(self, monkeypatch, *, linked: bool):
        monkeypatch.setattr(
            main_module.supabase_data,
            "get_user_provider_connection",
            lambda user_id: {"status": "linked"} if linked else {"status": "none"},
        )
        monkeypatch.setattr(main_module, "get_project", lambda *a, **k: _project_dict())
        monkeypatch.setattr(main_module, "has_user_api_key", lambda user_id, provider: False)
        monkeypatch.setattr(main_module, "update_project", lambda *a, **k: {"id": "proj-codex-1"})

        async def _noop_process(*args, **kwargs):
            return None

        monkeypatch.setattr(main_module, "_process_project", _noop_process)

    def test_codex_without_link_returns_400(self, monkeypatch, codex_auth_client):
        client, _ = codex_auth_client
        self._stub_supabase(monkeypatch, linked=False)
        resp = client.post(
            "/api/projects/proj-codex-1/process",
            json={"explainer_provider": "codex"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == CODEX_LINK_REQUIRED_MESSAGE

    def test_codex_pdf_without_mistral_returns_400(self, monkeypatch, codex_auth_client):
        client, _ = codex_auth_client
        monkeypatch.setattr(main_module, "get_project", lambda *a, **k: _project_dict(source_type="pdf"))
        monkeypatch.setattr(main_module, "has_user_api_key", lambda user_id, provider: False)
        monkeypatch.setattr(
            main_module.supabase_data,
            "get_user_provider_connection",
            lambda user_id: {"status": "linked"},
        )
        monkeypatch.setattr(main_module, "update_project", lambda *a, **k: {"id": "proj-codex-1"})

        async def _noop_process(*args, **kwargs):
            return None

        monkeypatch.setattr(main_module, "_process_project", _noop_process)
        resp = client.post(
            "/api/projects/proj-codex-1/process",
            json={"explainer_provider": "codex"},
        )
        assert resp.status_code == 400
        assert "Mistral" in resp.json()["detail"]
        assert "OCR nativo en PDFs con Codex" in resp.json()["detail"]

    def test_codex_linked_web_starts_and_persists_explainer_config(
        self, monkeypatch, codex_auth_client
    ):
        client, user_id = codex_auth_client
        updates = []
        monkeypatch.setattr(main_module, "get_project", lambda *a, **k: _project_dict())
        monkeypatch.setattr(main_module, "has_user_api_key", lambda user_id, provider: False)
        monkeypatch.setattr(
            main_module.supabase_data,
            "get_user_provider_connection",
            lambda user_id: {"status": "linked"},
        )
        monkeypatch.setattr(
            main_module, "update_project",
            lambda project_id, uid, payload: updates.append(payload) or {"id": project_id},
        )

        async def _noop_process(*args, **kwargs):
            return None

        monkeypatch.setattr(main_module, "_process_project", _noop_process)

        resp = client.post(
            "/api/projects/proj-codex-1/process",
            json={"explainer_provider": "codex"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"
        assert resp.json()["explainer_provider"] == "codex"
        assert resp.json()["explainer_model"] == CODEX_MODEL
        config = next(p for p in updates if "explainer_config" in p)["explainer_config"]
        assert config == {"provider": "codex", "model": CODEX_MODEL, "openrouter_model": None, "deepseek_model": None}

    @pytest.mark.parametrize(
        ("provider", "source_type", "expects_gemini"),
        [
            ("gemini", "web", True),
            ("gemini", "pdf", True),
            ("gemini", "youtube", True),
            ("openrouter", "web", True),
            ("openrouter", "pdf", True),
            ("openrouter", "youtube", True),
            ("deepseek", "web", False),
            ("deepseek", "pdf", False),
            ("deepseek", "youtube", True),
            ("codex", "web", False),
            ("codex", "pdf", False),
            ("codex", "youtube", True),
        ],
    )
    def test_requires_gemini_key_matrix(
        self, monkeypatch, codex_auth_client, provider, source_type, expects_gemini
    ):
        """`requires_gemini_key = provider in (gemini, openrouter) or youtube`."""
        client, _ = codex_auth_client
        monkeypatch.setattr(
            main_module, "get_project",
            lambda *a, **k: _project_dict(source_type=source_type),
        )
        calls = {}

        def _fake_has(user_id, provider=None):
            calls[provider] = calls.get(provider, 0) + 1
            return False

        monkeypatch.setattr(main_module, "has_user_api_key", _fake_has)
        monkeypatch.setattr(
            main_module.supabase_data,
            "get_user_provider_connection",
            lambda user_id: {"status": "linked"},
        )
        monkeypatch.setattr(main_module, "update_project", lambda *a, **k: {"id": "proj-codex-1"})

        async def _noop_process(*args, **kwargs):
            return None

        monkeypatch.setattr(main_module, "_process_project", _noop_process)
        resp = client.post(
            "/api/projects/proj-codex-1/process",
            json={"explainer_provider": provider},
        )
        if expects_gemini:
            assert resp.status_code == 400
            assert "Gemini" in resp.json()["detail"]
            assert calls.get(main_module.PROVIDER_GEMINI, 0) >= 1
        else:
            # Sin key Gemini: el pre-check NO debe exigirla.
            assert resp.status_code != 400 or "Gemini" not in resp.json().get("detail", "")
            assert calls.get(main_module.PROVIDER_GEMINI, 0) == 0


# ---------------------------------------------------------------------------
# Pipeline _process_project con proveedor codex (agentes codex mockeados)
# ---------------------------------------------------------------------------

def _web_project() -> dict:
    return {
        "id": "proj-codex-1",
        "name": "Artículo codex",
        "description": "",
        "pdf_filename": "Web: example.com",
        "source_type": "web",
        "source_url": "https://example.com/article",
        "source_text": (
            "Primer bloque con contenido suficiente para abrir el análisis.\n\n"
            "Segundo bloque que desarrolla la idea principal del texto."
        ),
        "source_metadata": {"title": "Artículo de ejemplo", "resolved_url": "https://example.com/article"},
        "status": "pending",
        "source_object_status": None,
    }


def _segmentation_dict() -> dict:
    return {
        "meta_obra": {},
        "evaluacion_fuente": {
            "es_segmentable": True,
            "motivo": "Contenido real.",
            "indicios": ["Coherente"],
        },
        "partes": [
            {
                "numero": 1,
                "titulo": "Parte 1",
                "contenido": "Contenido de la primera parte",
                "identificacion": "Desde el bloque 1 hasta el bloque 1",
                "bloque_inicio": 1,
                "bloque_fin": 1,
                "extension_estimada": "media",
                "complejidad": "media",
                "expansion_prevista": "alta",
            }
        ],
        "analisis_texto": "Texto corto",
        "decision_num_partes": 1,
        "decision_justificacion": "Una unidad",
        "consideraciones_estudiante": "Estudiarlo",
    }


def _explainer_dict() -> dict:
    return {
        "introduccion": "Introducción determinista.",
        "desarrollo": [
            {
                "titulo_seccion": "Sección 1",
                "subsecciones": [{"titulo_subseccion": "Sub 1", "contenido": "Contenido"}],
            }
        ],
        "conclusion": "Conclusión determinista.",
        "conexiones_contextuales": [],
    }


class _FakeCodexAgents:
    """Agentes codex deterministas que registran los argumentos recibidos."""

    def __init__(self):
        self.segmentador_calls = []
        self.explainer_calls = []
        self.recorrido_calls = []
        self.resources_calls = []
        self.formatter_calls = []
        self.explainer_error: Exception | None = None

    async def run_segmentador_codex(self, api_key, source_text, description, source_kind="pdf",
                                    model=CODEX_MODEL, target_language="es-ES", *,
                                    conversation=None, correction=None):
        self.segmentador_calls.append(
            {"api_key": api_key, "source_kind": source_kind, "model": model,
             "conversation": conversation, "correction": correction}
        )
        return _segmentation_dict(), _usage(prompt=200, total=260), []

    async def run_explainer_codex(self, source_path, identificacion, model=CODEX_MODEL,
                                  mime_type="application/pdf", user_id="", validator_user_id="",
                                  pdf_cache_entry=None, page_numbers=None,
                                  validation_context=None, target_language="es-ES"):
        self.explainer_calls.append(
            {"source_path": source_path, "model": model, "mime_type": mime_type,
             "user_id": user_id, "validator_user_id": validator_user_id,
             "page_numbers": page_numbers}
        )
        if self.explainer_error is not None:
            raise self.explainer_error
        return _explainer_dict(), _usage(prompt=400, total=500), []

    async def run_recorrido_codex(self, user_id, source_text, identificacion,
                                  model=CODEX_MODEL, target_language="es-ES"):
        self.recorrido_calls.append({"user_id": user_id, "model": model})
        return {"recorrido_anotado": []}, _usage(prompt=50, total=60)

    async def run_resources_codex(self, user_id, source_text, identificacion,
                                  model=CODEX_MODEL, target_language="es-ES"):
        self.resources_calls.append({"user_id": user_id, "model": model})
        return {"titulo_mapa": "Mapa determinista", "ejes_tematicos": []}, _usage(prompt=50, total=60)

    async def format_explainer_content_codex(self, user_id, explainer_data, target_language="es-ES"):
        self.formatter_calls.append({"user_id": user_id, "target_language": target_language})
        return explainer_data, {
            "input_tokens": 0, "output_tokens": 0, "thoughts_tokens": 0,
            "total_tokens": 0, "cost": 0.0, "quota_requests": 2,
        }


def _run_codex_pipeline(monkeypatch, *, user_id: str, agents: _FakeCodexAgents,
                        project: dict | None = None) -> tuple[list, list]:
    """Ejecuta `_process_project` con proveedor codex; devuelve (updates, events)."""
    updates = []
    events = []

    monkeypatch.setattr(main_module, "get_project", lambda project_id, uid, include_internal=False: project or _web_project())
    monkeypatch.setattr(
        main_module, "get_user_api_key",
        lambda uid, provider=None: "AIzaFakeKey" if provider == main_module.PROVIDER_GEMINI else "",
    )
    monkeypatch.setattr(main_module, "update_project", lambda project_id, uid, payload: updates.append(payload) or {"id": project_id})
    monkeypatch.setattr(main_module, "run_segmentador_codex", agents.run_segmentador_codex)
    monkeypatch.setattr(main_module, "run_explainer_codex", agents.run_explainer_codex)
    monkeypatch.setattr(main_module, "run_recorrido_codex", agents.run_recorrido_codex)
    monkeypatch.setattr(main_module, "run_resources_codex", agents.run_resources_codex)
    monkeypatch.setattr(main_module, "format_explainer_content_codex", agents.format_explainer_content_codex)

    async def _send_event(project_id, payload):
        events.append(payload)

    class _DummySSE:
        async def end_stream(self, project_id):
            return None

    monkeypatch.setattr(main_module, "send_event", _send_event)
    monkeypatch.setattr(main_module, "sse_manager", _DummySSE())

    from google import genai

    monkeypatch.setattr(genai, "Client", lambda api_key: object())
    return updates, events


class TestProcessProjectCodex:
    pytestmark = pytest.mark.asyncio(loop_scope="session")

    async def test_full_codex_pipeline_states_parts_and_usage(self, monkeypatch):
        user_id = _uid(701)
        agents = _FakeCodexAgents()
        updates, events = _run_codex_pipeline(monkeypatch, user_id=user_id, agents=agents)

        await main_module._process_project("proj-codex-1", user_id, "codex")

        # Estados observados: uploading → segmenting → completed.
        statuses = [u["status"] for u in updates if "status" in u]
        assert "uploading" in statuses and "segmenting" in statuses
        final_update = next(p for p in reversed(updates) if p.get("status") == "completed")
        assert "failed_parts" not in final_update

        # Eventos: part_completed, completed sin fallos.
        assert {"type": "part_completed", "part_id": 1} in events
        assert {"type": "completed"} in events
        assert all(e["type"] != "part_failed" for e in events)

        # Partes guardadas con status completed y explainer formateado.
        partes = next(p for p in updates if "partes_contenido" in p)["partes_contenido"]
        assert partes["1"]["status"] == "completed"
        assert partes["1"]["explainer"]["desarrollo"][0]["titulo_seccion"] == "Sección 1"

        # `user_id` ocupa la posición de `api_key` en todas las variantes.
        assert agents.segmentador_calls and agents.segmentador_calls[0]["api_key"] == user_id
        assert agents.explainer_calls and agents.explainer_calls[0]["user_id"] == user_id
        assert agents.explainer_calls[0]["validator_user_id"] == user_id
        assert agents.recorrido_calls and agents.recorrido_calls[0]["user_id"] == user_id
        assert agents.resources_calls and agents.resources_calls[0]["user_id"] == user_id
        assert agents.formatter_calls and agents.formatter_calls[0]["user_id"] == user_id

        # Modelo fijo gpt-5.6-luna en todas las fases.
        for call in agents.segmentador_calls + agents.explainer_calls:
            assert call["model"] == CODEX_MODEL

        # Uso: `codex_quota_requests` acumulado (1 por llamada) y coste 0.
        # RC-01: los 2 turnos del formatter se suman una sola vez a la cuota.
        usage = next(p for p in reversed(updates) if "usage" in p)["usage"]
        assert usage["codex_quota_requests"] == 6  # segmentador + explainer + recorrido + resources + 2 formatter
        assert usage["total_cost"] == 0.0
        assert usage["explainer_provider"] == "codex"
        assert usage["explainer_model"] == CODEX_MODEL

    async def test_youtube_falls_back_to_gemini_and_never_calls_codex_agents(self, monkeypatch):
        user_id = _uid(702)
        agents = _FakeCodexAgents()
        project = _web_project()
        project["source_type"] = "youtube"
        project["source_url"] = "https://www.youtube.com/watch?v=abcd1234"
        updates, events = _run_codex_pipeline(monkeypatch, user_id=user_id, agents=agents, project=project)

        gemini_seg = []
        gemini_explainer = []
        gemini_recorrido = []
        gemini_resources = []
        gemini_formatter = []

        def _fake_segmentador(api_key, file_uri, description, model, mime_type, source_kind, target_language="es-ES"):
            gemini_seg.append({"api_key": api_key, "file_uri": file_uri})
            return _segmentation_dict(), SimpleNamespace(
                prompt_token_count=1, tool_use_prompt_token_count=0,
                candidates_token_count=1, thoughts_token_count=0,
                total_token_count=2, cost_usd=None,
            )

        def _fake_explainer(api_key, file_uri, agent_prompt, model, mime_type, validation_context=None, target_language="es-ES"):
            gemini_explainer.append({"api_key": api_key})
            return _explainer_dict(), SimpleNamespace(
                prompt_token_count=1, tool_use_prompt_token_count=0,
                candidates_token_count=1, thoughts_token_count=0,
                total_token_count=2, cost_usd=None,
            )

        def _fake_recorrido(api_key, file_uri, agent_prompt, model, mime_type, target_language="es-ES"):
            gemini_recorrido.append({"api_key": api_key})
            return {"recorrido_anotado": []}, SimpleNamespace(
                prompt_token_count=1, tool_use_prompt_token_count=0,
                candidates_token_count=1, thoughts_token_count=0,
                total_token_count=2, cost_usd=None,
            )

        def _fake_resources(api_key, file_uri, agent_prompt, model, mime_type, target_language="es-ES"):
            gemini_resources.append({"api_key": api_key})
            return {"titulo_mapa": "M", "ejes_tematicos": []}, SimpleNamespace(
                prompt_token_count=1, tool_use_prompt_token_count=0,
                candidates_token_count=1, thoughts_token_count=0,
                total_token_count=2, cost_usd=None,
            )

        async def _fake_formatter(api_key, explainer_data, target_language="es-ES"):
            gemini_formatter.append({"api_key": api_key})
            return explainer_data, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost": 0.0}

        monkeypatch.setattr(main_module, "run_segmentador", _fake_segmentador)
        monkeypatch.setattr(main_module, "run_explainer", _fake_explainer)
        monkeypatch.setattr(main_module, "run_recorrido", _fake_recorrido)
        monkeypatch.setattr(main_module, "run_resources", _fake_resources)
        monkeypatch.setattr(main_module, "format_explainer_content", _fake_formatter)

        await main_module._process_project("proj-codex-1", user_id, "codex")

        # El fallback YouTube→Gemini resetea el proveedor: nunca se llama a codex.
        assert agents.segmentador_calls == []
        assert agents.explainer_calls == []
        assert agents.recorrido_calls == []
        assert agents.resources_calls == []
        assert agents.formatter_calls == []

        # Gemini sí se usó (con la API key del usuario).
        assert gemini_seg and gemini_seg[0]["api_key"] == "AIzaFakeKey"
        assert gemini_explainer and gemini_explainer[0]["api_key"] == "AIzaFakeKey"
        assert gemini_recorrido and gemini_recorrido[0]["api_key"] == "AIzaFakeKey"
        assert gemini_resources and gemini_resources[0]["api_key"] == "AIzaFakeKey"
        assert gemini_formatter and gemini_formatter[0]["api_key"] == "AIzaFakeKey"

        final_update = next(p for p in reversed(updates) if p.get("status") == "completed")
        assert "failed_parts" not in final_update
        assert {"type": "completed"} in events

        # La cuota codex queda a 0: el fallback no consume peticiones ChatGPT.
        usage = next(p for p in reversed(updates) if "usage" in p)["usage"]
        assert usage["codex_quota_requests"] == 0

    async def test_codex_rate_limit_in_part_emits_part_failed_with_quota_message(self, monkeypatch):
        user_id = _uid(703)
        agents = _FakeCodexAgents()
        agents.explainer_error = CodexRateLimitError(CODEX_RATE_LIMIT_MESSAGE)
        updates, events = _run_codex_pipeline(monkeypatch, user_id=user_id, agents=agents)

        await main_module._process_project("proj-codex-1", user_id, "codex")

        # part_failed + SSE con el mensaje UX tipado (sin stack).
        failed = [e for e in events if e["type"] == "part_failed"]
        assert len(failed) == 1
        assert failed[0]["part_id"] == 1
        assert failed[0]["message"] == CODEX_RATE_LIMIT_MESSAGE

        # El proyecto completa con la parte fallida registrada.
        final_update = next(p for p in reversed(updates) if p.get("status") == "completed")
        assert final_update["failed_parts"] == [1]
        assert {"type": "completed", "has_failed_parts": True, "failed_parts": [1]} in events

        # La parte queda marcada failed con el mensaje UX (honestidad de estado).
        partes = next(p for p in updates if "partes_contenido" in p)["partes_contenido"]
        assert partes["1"]["status"] == "failed"
        assert partes["1"]["error_message"] == CODEX_RATE_LIMIT_MESSAGE

        # La cuota de la llamada que falló SÍ se acumula (el error es posterior a la llamada).
        usage = next(p for p in reversed(updates) if "usage" in p)["usage"]
        assert usage["codex_quota_requests"] >= 1
        assert usage["total_cost"] == 0.0


# ---------------------------------------------------------------------------
# Review y reformat por rama codex (HTTP, auth_client)
# ---------------------------------------------------------------------------

class TestPartReviewCodexBranch:
    def _project(self) -> dict:
        return {
            "id": "proj-codex-1",
            "name": "Proyecto codex",
            "description": "",
            "source_type": "web",
            "status": "completed",
            "explainer_config": {"provider": "codex", "model": CODEX_MODEL},
            "usage": {"explainer_provider": "codex"},
            "segmentation": {"partes": [{"numero": 1, "titulo": "Parte 1"}]},
            "partes_contenido": {
                "1": {"explainer": _explainer_dict()},
            },
        }

    def _stub(self, monkeypatch, codex_auth_client, *, linked: bool, review_error: Exception | None = None):
        client, user_id = codex_auth_client
        monkeypatch.setattr(main_module, "get_project", lambda *a, **k: self._project())
        monkeypatch.setattr(
            main_module.supabase_data,
            "get_user_provider_connection",
            lambda uid: {"status": "linked"} if linked else {"status": "none"},
        )
        updates = []
        monkeypatch.setattr(
            main_module, "update_project",
            lambda project_id, uid, payload: updates.append(payload) or {"id": project_id},
        )
        calls = []

        async def _fake_review(uid, explainer_content, part_title, target_language="es-ES", model=CODEX_MODEL):
            calls.append({"user_id": uid, "model": model, "target_language": target_language})
            if review_error is not None:
                raise review_error
            return {
                "preguntas": [
                    {
                        "pregunta": "¿Qué es el teorema de Pitágoras?",
                        "opciones": ["a", "b", "c", "d"],
                        "respuesta_correcta": "a",
                        "explicacion": "Explicación determinista.",
                    }
                ]
            }, _usage(prompt=10, total=15)

        monkeypatch.setattr(main_module, "run_review_codex", _fake_review)
        return client, user_id, calls, updates

    def test_review_codex_branch_uses_user_id_and_accumulates_quota(self, monkeypatch, codex_auth_client):
        client, user_id, calls, updates = self._stub(monkeypatch, codex_auth_client, linked=True)
        resp = client.post("/api/projects/proj-codex-1/parts/1/review", json={})
        assert resp.status_code == 200
        assert resp.json()["cached"] is False
        assert resp.json()["review"]["preguntas"][0]["pregunta"].startswith("¿Qué es")

        assert len(calls) == 1
        assert calls[0]["user_id"] == user_id
        assert calls[0]["model"] == CODEX_MODEL

        # Uso: `codex_quota_requests` acumulado con coste 0.
        usage = next(p for p in updates if "usage" in p)["usage"]
        assert usage["codex_quota_requests"] == 1
        assert usage["total_cost"] == 0.0

    def test_review_codex_without_link_returns_400(self, monkeypatch, codex_auth_client):
        client, _, calls, _ = self._stub(monkeypatch, codex_auth_client, linked=False)
        resp = client.post("/api/projects/proj-codex-1/parts/1/review", json={})
        assert resp.status_code == 400
        assert resp.json()["detail"] == CODEX_LINK_REQUIRED_MESSAGE
        assert calls == []

    def test_review_codex_rate_limit_returns_429_with_frozen_message(self, monkeypatch, codex_auth_client):
        client, _, calls, _ = self._stub(
            monkeypatch, codex_auth_client, linked=True,
            review_error=CodexRateLimitError(CODEX_RATE_LIMIT_MESSAGE),
        )
        resp = client.post("/api/projects/proj-codex-1/parts/1/review", json={})
        assert resp.status_code == 429
        assert resp.json()["detail"] == CODEX_RATE_LIMIT_MESSAGE
        assert len(calls) == 1

    def test_review_codex_auth_error_returns_400_relink_message(self, monkeypatch, codex_auth_client):
        client, _, calls, _ = self._stub(
            monkeypatch, codex_auth_client, linked=True,
            review_error=CodexAuthError(CODEX_AUTH_MESSAGE),
        )
        resp = client.post("/api/projects/proj-codex-1/parts/1/review", json={})
        assert resp.status_code == 400
        assert resp.json()["detail"] == CODEX_AUTH_MESSAGE
        assert len(calls) == 1


class TestReformatCodexBranch:
    def test_reformat_codex_branch_uses_user_id_and_accumulates_zero_cost(self, monkeypatch, codex_auth_client):
        client, user_id = codex_auth_client
        project = {
            "id": "proj-codex-1",
            "name": "Proyecto codex",
            "status": "completed",
            "source_metadata": {"target_language": "es-ES"},
            "usage": {"explainer_provider": "codex", "codex_quota_requests": 4},
            "partes_contenido": {
                "1": {"status": "completed", "explainer": _explainer_dict()},
            },
        }
        monkeypatch.setattr(main_module, "get_project", lambda *a, **k: project)
        calls = []
        updates = []

        async def _fake_formatter(uid, explainer_data, target_language="es-ES"):
            calls.append({"user_id": uid, "target_language": target_language})
            return explainer_data, {
                "input_tokens": 5, "output_tokens": 3, "thoughts_tokens": 0,
                "total_tokens": 8, "cost": 0.0, "quota_requests": 2,
            }

        monkeypatch.setattr(main_module, "format_explainer_content_codex", _fake_formatter)
        monkeypatch.setattr(
            main_module, "update_project",
            lambda project_id, uid, payload: updates.append(payload) or {"id": project_id},
        )

        resp = client.post("/api/projects/proj-codex-1/reformat")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "reformatted": 1, "formatter_cost": 0.0}

        assert len(calls) == 1
        assert calls[0]["user_id"] == user_id
        assert calls[0]["target_language"] == "es-ES"

        # Acumulación en project_usage: tokens presentes, coste USD 0.
        # RC-01: las 2 peticiones nuevas del formatter se suman a la cuota previa.
        usage = next(p for p in updates if "usage" in p)["usage"]
        assert usage["formatter_tokens"] == 8
        assert usage["formatter_cost"] == 0.0
        assert usage["total_cost"] == 0.0
        assert usage["codex_quota_requests"] == 6  # 4 previa + 2 nuevas del formatter


class TestFormatterCodexQuotaSummary:
    """RC-01: el resumen del formatter Codex expone `quota_requests` con el
    número de peticiones de cuota de todos los turnos (campos en paralelo),
    para que main.py las acumule una sola vez en los dos caminos."""

    pytestmark = pytest.mark.asyncio(loop_scope="session")

    async def test_codex_formatter_summary_counts_parallel_turns(self, monkeypatch):
        user_id = _uid(802)
        data = _explainer_dict()  # introduccion + conclusion → 2 turnos en paralelo
        calls = []

        async def fake_format_text_codex(uid, text, context="", target_language="es-ES"):
            calls.append({"user_id": uid, "text": text})
            return text + " [FMT]", _usage(prompt=5, candidates=3, total=8)

        monkeypatch.setattr(formatter_module, "_format_text_codex", fake_format_text_codex)

        result, usage_summary = await formatter_module.format_explainer_content_codex(
            user_id, data, "es-ES"
        )

        assert len(calls) == 2  # más de un turno (peticiones de cuota > 1)
        assert all(c["user_id"] == user_id for c in calls)
        assert result["introduccion"].endswith(" [FMT]")
        assert result["conclusion"].endswith(" [FMT]")
        assert usage_summary["quota_requests"] == 2  # 1 CodexUsage por turno
        assert usage_summary["input_tokens"] == 10
        assert usage_summary["cost"] == 0.0


# ---------------------------------------------------------------------------
# Smoke: las variantes codex que main.py cablea funcionan contra el fake
# app-server de T02 (wire-format real, subproceso).
# ---------------------------------------------------------------------------

def _write_source(tmp_path: Path) -> Path:
    src = tmp_path / "fuente.txt"
    src.write_text(
        "El teorema de Pitagoras relaciona los catetos y la hipotenusa de un "
        "triangulo rectangulo: a^2 + b^2 = c^2.",
        encoding="utf-8",
    )
    return src


def _set_turn_file(monkeypatch, turn_file: Path) -> None:
    monkeypatch.setenv("FAKE_CODEX_SCENARIO", "scripted_turn")
    monkeypatch.setenv("FAKE_CODEX_TURN_OUTPUT_FILE", str(turn_file))


def _script_turns(monkeypatch, turn_file: Path, fixture_names: list[str]) -> None:
    """Salidas de turno secuenciales: escribe la primera y reescribe tras cada turno."""
    turn_file.write_text(
        (_FIXTURES_DIR / fixture_names[0]).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _set_turn_file(monkeypatch, turn_file)
    calls = {"n": 0}

    import backend.codex_client as codex_client

    real_parse = codex_client._parse_turn_json

    def switching_parse(text):
        index = calls["n"]
        calls["n"] += 1
        if index + 1 < len(fixture_names):
            turn_file.write_text(
                (_FIXTURES_DIR / fixture_names[index + 1]).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        return real_parse(text)

    monkeypatch.setattr(codex_client, "_parse_turn_json", switching_parse)


class TestCodexAgentsAgainstFake:
    pytestmark = pytest.mark.asyncio(loop_scope="session")

    @pytest_asyncio.fixture(loop_scope="session")
    async def _codex_manager_env(self, tmp_path_factory, monkeypatch):
        """Fija binario, home y límites del singleton por test (patrón T05/T06)."""
        import backend.codex_app_server as codex_app_server
        import backend.supabase_data as supabase_data

        home_root = tmp_path_factory.mktemp("codex-pipeline-agents-home")
        monkeypatch.setattr(codex_app_server.codex_manager, "_bin_path", _FAKE_BIN)
        monkeypatch.setattr(codex_app_server.codex_manager, "_home_root", home_root)
        monkeypatch.setattr(codex_app_server.codex_manager, "_spawn_wait_seconds", 0.3)
        monkeypatch.setattr(codex_app_server.codex_manager, "_max_processes", 3)
        monkeypatch.setenv("CODEX_HOME_ROOT", str(home_root))
        monkeypatch.setenv("CODEX_BIN_PATH", _FAKE_BIN)
        # El manager consulta la conexión al restaurar auth.json en el spawn
        # (patrón `_no_supabase` de T05/T06): sin fila y sin persistencia.
        monkeypatch.setattr(
            supabase_data, "get_user_provider_connection", lambda user_id: None
        )
        monkeypatch.setattr(
            supabase_data, "upsert_user_provider_connection", lambda *args, **kwargs: None
        )
        yield codex_app_server.codex_manager
        await codex_app_server.codex_manager.shutdown()

    @pytest.mark.asyncio(loop_scope="session")
    async def test_wired_codex_agents_run_against_fake_app_server(self, monkeypatch, tmp_path, _codex_manager_env):
        user_id = _uid(801)
        _set_turn_file(monkeypatch, _FIXTURES_DIR / "turn_segmentador.json")

        segmentation, seg_usage, conversation = await main_module.run_segmentador_codex(
            user_id, "Texto fuente determinista.", "Descripción", "text",
            target_language="es-ES",
        )
        assert segmentation["partes"][0]["numero"] == 1
        assert isinstance(seg_usage, CodexUsage)
        assert seg_usage.cost_usd == 0.0
        assert seg_usage.quota_requests == 1

        user_id_2 = _uid(802)
        turn_file = tmp_path / "turns.json"
        _script_turns(monkeypatch, turn_file, ["turn_explainer_full.json", "turn_validator_accept.json"])
        result, usage, validator_usages = await main_module.run_explainer_codex(
            str(_write_source(tmp_path)),
            "Parte 1: El teorema de Pitagoras",
            mime_type="text/plain",
            user_id=user_id_2,
            validator_user_id=user_id_2,
        )
        assert result["desarrollo"][0]["titulo_seccion"] == "Enunciado del teorema"
        assert isinstance(usage, CodexUsage)
        assert usage.cost_usd == 0.0
        assert len(validator_usages) == 1
