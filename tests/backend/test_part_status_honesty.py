"""Honest part/project status tests (A2 + A3): no more "falsos completados".

Covers:
- _format_and_finalize_part: failed on explainer error dict / Exception / formatter
  exception / Supabase persistence failure; part_completed only on real success.
- _failed_part_ids helper.
- _process_project: project completed with failed_parts when a part failed.
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import main


def _run_format_and_finalize(monkeypatch, partes, explainer_data, *, update_result=None, formatter_side_effect=None):
    """Run _format_and_finalize_part with format/send/update mocked. Returns emitted events."""
    events = []

    async def _send_event(project_id, payload):
        events.append(payload)

    if formatter_side_effect is not None:
        async def _raise_format(*args, **kwargs):
            raise formatter_side_effect
    else:
        async def _raise_format(api_key, explainer_data, target_language="es-ES"):
            return (explainer_data, {"total_tokens": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0})

    import main as m

    monkeypatch.setattr(m, "format_explainer_content", _raise_format)
    monkeypatch.setattr(m, "send_event", _send_event)
    monkeypatch.setattr(m, "update_project", lambda project_id, user_id, updates: update_result)

    asyncio.run(
        m._format_and_finalize_part(
            "proj-1",
            "user-1",
            "AIzaFakeKey",
            1,
            explainer_data,
            partes,
        )
    )
    return events


class TestFormatAndFinalizePartHonestStatus:
    def test_explainer_error_dict_marks_failed_and_emits_part_failed(self, monkeypatch):
        partes = {"1": {}}
        events = _run_format_and_finalize(
            monkeypatch,
            partes,
            {"error": "All explainer calls failed"},
            update_result={"id": "proj-1"},
        )
        assert partes["1"]["status"] == "failed"
        assert "All explainer calls failed" in partes["1"]["error_message"]
        assert [e["type"] for e in events] == ["part_failed"]
        assert events[0]["part_id"] == 1

    def test_explainer_exception_marks_failed_and_emits_part_failed(self, monkeypatch):
        partes = {"1": {}}
        events = _run_format_and_finalize(
            monkeypatch,
            partes,
            ValueError("boom"),
            update_result={"id": "proj-1"},
        )
        assert partes["1"]["status"] == "failed"
        assert "boom" in partes["1"]["error_message"]
        assert [e["type"] for e in events] == ["part_failed"]

    def test_formatter_exception_marks_failed_and_emits_part_failed(self, monkeypatch):
        partes = {"1": {}}
        events = _run_format_and_finalize(
            monkeypatch,
            partes,
            {"ok": True},
            update_result={"id": "proj-1"},
            formatter_side_effect=RuntimeError("formatter exploded"),
        )
        assert partes["1"]["status"] == "failed"
        assert "formatter exploded" in partes["1"]["error_message"]
        assert [e["type"] for e in events] == ["part_failed"]

    def test_happy_path_marks_completed_and_emits_part_completed(self, monkeypatch):
        partes = {"1": {}}
        events = _run_format_and_finalize(
            monkeypatch,
            partes,
            {"ok": True},
            update_result={"id": "proj-1"},
        )
        assert partes["1"]["status"] == "completed"
        assert "error_message" not in partes["1"]
        assert [e["type"] for e in events] == ["part_completed"]
        assert events[0]["part_id"] == 1

    def test_persistence_failure_marks_failed_and_emits_part_failed_not_part_completed(self, monkeypatch):
        partes = {"1": {}}
        events = _run_format_and_finalize(
            monkeypatch,
            partes,
            {"ok": True},
            update_result=None,  # update_project devolvió None → persistencia fallida
        )
        assert partes["1"]["status"] == "failed"
        assert partes["1"]["error_message"] == "No se pudo guardar la parte en Supabase"
        assert [e["type"] for e in events] == ["part_failed"]
        assert events[0]["message"] == "No se pudo guardar la parte en Supabase"


class TestFailedPartIds:
    def test_detects_failed_parts(self):
        partes = {
            "1": {"status": "completed"},
            "2": {"status": "failed"},
            "3": {"status": "failed", "error_message": "x"},
        }
        assert main._failed_part_ids(partes) == [2, 3]

    def test_empty_when_none_failed(self):
        assert main._failed_part_ids({"1": {"status": "completed"}}) == []
        assert main._failed_part_ids({}) == []


def _usage(**kwargs):
    return SimpleNamespace(
        prompt_token_count=kwargs.get("prompt", 0),
        tool_use_prompt_token_count=kwargs.get("tool_prompt", 0),
        candidates_token_count=kwargs.get("candidates", 0),
        thoughts_token_count=kwargs.get("thoughts", 0),
        total_token_count=kwargs.get("total", 0),
    )


def _run_process_project(monkeypatch, *, finalize_behaviour):
    """Run _process_project end-to-end for a web project with one part.

    finalize_behaviour: "failed" | "completed" — controls the fake formatter task.
    Returns (updates, events).
    """
    project = {
        "id": "proj-web-1",
        "name": "Artículo web",
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
    }

    updates = []
    events = []

    monkeypatch.setattr(main, "get_project", lambda project_id, user_id, include_internal=False: project)
    monkeypatch.setattr(
        main,
        "get_user_api_key",
        lambda user_id, provider=None: "" if provider == main.PROVIDER_OPENROUTER else "AIzaFakeKey",
    )
    monkeypatch.setattr(main, "mask_api_key", lambda api_key: "AIza****")
    monkeypatch.setattr(main, "update_project", lambda project_id, user_id, payload: updates.append(payload) or {"id": project_id})

    async def _send_event(project_id, payload):
        events.append(payload)

    class _DummySSE:
        async def end_stream(self, project_id):
            return None

    monkeypatch.setattr(main, "send_event", _send_event)
    monkeypatch.setattr(main, "sse_manager", _DummySSE())

    from google import genai

    monkeypatch.setattr(genai, "Client", lambda api_key: object())

    def _fake_upload(client, path, max_retries=5):
        stem = os.path.splitext(os.path.basename(path))[0]
        return SimpleNamespace(uri=f"uploaded://{stem}", mime_type="text/plain")

    monkeypatch.setattr(main, "upload_file_with_retry", _fake_upload)

    def _fake_segmentador(api_key, file_uri, description, model, mime_type, source_kind, target_language="es-ES"):
        return (
            {
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
            },
            _usage(),
        )

    def _fake_explainer(api_key, file_uri, agent_prompt, model, mime_type, target_language="es-ES"):
        return ({"ok": True}, _usage())

    def _fake_recorrido(api_key, file_uri, agent_prompt, model, mime_type, target_language="es-ES"):
        return ({"ok": True}, _usage())

    def _fake_resources(api_key, file_uri, agent_prompt, model, mime_type, target_language="es-ES"):
        return ({"ok": True}, _usage())

    monkeypatch.setattr(main, "run_segmentador", _fake_segmentador)
    monkeypatch.setattr(main, "run_explainer", _fake_explainer)
    monkeypatch.setattr(main, "run_recorrido", _fake_recorrido)
    monkeypatch.setattr(main, "run_resources", _fake_resources)

    async def _fake_finalize(project_id, user_id, api_key, part_id, explainer_data, partes_contenido, **kwargs):
        if finalize_behaviour == "failed":
            partes_contenido[str(part_id)]["status"] = "failed"
            partes_contenido[str(part_id)]["error_message"] = "Simulated failure"
            await main.send_event(project_id, {"type": "part_failed", "part_id": part_id, "message": "Simulated failure"})
        else:
            partes_contenido[str(part_id)]["status"] = "completed"
            await main.send_event(project_id, {"type": "part_completed", "part_id": part_id})

    monkeypatch.setattr(main, "_format_and_finalize_part", _fake_finalize)

    asyncio.run(main._process_project("proj-web-1", "user-123"))
    return updates, events


class TestProcessProjectFailedParts:
    def test_project_completed_with_failed_parts_when_a_part_failed(self, monkeypatch):
        updates, events = _run_process_project(monkeypatch, finalize_behaviour="failed")

        final_update = next(p for p in reversed(updates) if p.get("status") == "completed")
        assert final_update["failed_parts"] == [1]

        completed_events = [e for e in events if e.get("type") == "completed"]
        assert completed_events == [{"type": "completed", "has_failed_parts": True, "failed_parts": [1]}]
        assert [e["type"] for e in events].count("part_failed") == 1

    def test_project_completed_plain_when_all_parts_ok(self, monkeypatch):
        updates, events = _run_process_project(monkeypatch, finalize_behaviour="completed")

        final_update = next(p for p in reversed(updates) if p.get("status") == "completed")
        assert "failed_parts" not in final_update

        completed_events = [e for e in events if e.get("type") == "completed"]
        assert completed_events == [{"type": "completed"}]
