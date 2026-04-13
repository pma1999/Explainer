"""Integration-style tests: PDF project processing uses page ranges and sub-PDFs for agents."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

import main
from backend.gemini_model_routing import MODEL_AGENTS, MODEL_SEGMENTADOR
from backend.openrouter_client import OpenRouterPdfParseCacheEntry
from backend.segmentation_tema_coverage import (
    MAX_SEGMENTATION_COVERAGE_ATTEMPTS,
    SEGMENTATION_TEMA_COVERAGE_USER_MESSAGE,
)


def _usage(**kwargs):
    return SimpleNamespace(
        prompt_token_count=kwargs.get("prompt", 0),
        tool_use_prompt_token_count=kwargs.get("tool_prompt", 0),
        candidates_token_count=kwargs.get("candidates", 0),
        thoughts_token_count=kwargs.get("thoughts", 0),
        total_token_count=kwargs.get("total", 0),
    )


def _create_multi_page_pdf(num_pages: int) -> str:
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    for i in range(1, num_pages + 1):
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(width / 2, height - 50, f"Page {i}")
        c.showPage()
    c.save()
    return path


def _part_pdf_fields(num: int, title: str, p_start: int, p_end: int) -> dict:
    return {
        "numero": num,
        "titulo": title,
        "contenido": f"Contenido parte {num}",
        "identificacion": f"Desde página {p_start} hasta {p_end}",
        "pagina_inicio": p_start,
        "pagina_fin": p_end,
        "temas_cubiertos": [f"tema{num}"],
        "extension_estimada": "media",
        "complejidad": "media",
        "expansion_prevista": "alta",
    }


def test_process_project_pdf_agents_receive_subpdfs_not_full_document(monkeypatch):
    """Mirrors main.py PDF flow: segmentador sees full numbered PDF; each agent sees an extracted sub-PDF."""
    pdf_path = _create_multi_page_pdf(10)
    try:
        project = {
            "id": "proj-pdf-1",
            "name": "Doc PDF",
            "description": "Procesar todo",
            "pdf_filename": "test.pdf",
            "source_type": "pdf",
            "source_url": None,
            "status": "pending",
        }

        updates = []
        segmentador_calls = []
        explainer_calls = []
        upload_calls: list[str] = []
        segment_upload_page_counts: list[int] = []

        monkeypatch.setattr(main, "get_project", lambda pid, uid, include_internal=False: project)
        monkeypatch.setattr(
            main,
            "get_user_api_key",
            lambda uid, provider=None: "" if provider == main.PROVIDER_OPENROUTER else "AIzaFakeKey",
        )
        monkeypatch.setattr(main, "mask_api_key", lambda api_key: "AIza****")
        monkeypatch.setattr(
            main,
            "update_project",
            lambda pid, uid, payload: updates.append(deepcopy(payload)),
        )
        monkeypatch.setattr(main, "download_pdf_to_temp", lambda pid, uid: pdf_path)

        async def _send_event(project_id, payload):
            return None

        class _DummySSE:
            async def end_stream(self, project_id):
                return None

        monkeypatch.setattr(main, "send_event", _send_event)
        monkeypatch.setattr(main, "sse_manager", _DummySSE())

        from google import genai

        monkeypatch.setattr(genai, "Client", lambda api_key: object())

        def _fake_upload(client, path, max_retries=5):
            upload_calls.append(path)
            if "_segment" in os.path.basename(path) and os.path.isfile(path):
                segment_upload_page_counts.append(len(PdfReader(path).pages))
            stem = os.path.splitext(os.path.basename(path))[0]
            mime = "application/pdf"
            return SimpleNamespace(uri=f"uploaded://{stem}", mime_type=mime)

        monkeypatch.setattr(main, "upload_file_with_retry", _fake_upload)

        def _fake_segmentador(api_key, file_uri, description, model, mime_type, source_kind):
            segmentador_calls.append(
                {
                    "file_uri": file_uri,
                    "mime_type": mime_type,
                    "source_kind": source_kind,
                    "model": model,
                }
            )
            return (
                {
                    "analisis_texto": "Diez páginas de prueba",
                    "temas_identificados": ["tema1", "tema2"],
                    "decision_num_partes": 2,
                    "decision_justificacion": "Dos bloques MECE",
                    "partes": [
                        _part_pdf_fields(1, "Primera", 1, 3),
                        _part_pdf_fields(2, "Segunda", 4, 10),
                    ],
                    "consideraciones_estudiante": "Estudiar en orden",
                },
                _usage(total=100),
            )

        def _fake_explainer(api_key, file_uri, agent_prompt, model, mime_type):
            explainer_calls.append(
                {"file_uri": file_uri, "mime_type": mime_type, "prompt": agent_prompt, "model": model}
            )
            return ({"ok": True}, _usage())

        def _fake_recorrido(api_key, file_uri, agent_prompt, model, mime_type):
            return ({"ok": True}, _usage())

        def _fake_resources(api_key, file_uri, agent_prompt, model, mime_type):
            return ({"ok": True}, _usage())

        monkeypatch.setattr(main, "run_segmentador", _fake_segmentador)
        monkeypatch.setattr(main, "run_explainer", _fake_explainer)
        monkeypatch.setattr(main, "run_recorrido", _fake_recorrido)
        monkeypatch.setattr(main, "run_resources", _fake_resources)

        async def _fake_format(api_key, explainer_data):
            return (explainer_data, {"total_tokens": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0})

        monkeypatch.setattr(main, "format_explainer_content", _fake_format)

        asyncio.run(main._process_project("proj-pdf-1", "user-123"))

        assert segmentador_calls[0]["model"] == MODEL_SEGMENTADOR
        assert all(c["model"] == MODEL_AGENTS for c in explainer_calls)
        assert segmentador_calls[0]["mime_type"] == "application/pdf"
        assert segmentador_calls[0]["source_kind"] == "pdf"
        assert segmentador_calls[0]["file_uri"].startswith("uploaded://")
        # uploads: numbered full doc, then one sub-PDF per part
        assert len(upload_calls) >= 3
        assert upload_calls[0].endswith("_numbered.pdf") or "_numbered" in os.path.basename(upload_calls[0])

        assert len(explainer_calls) == 2
        uri_full = segmentador_calls[0]["file_uri"]
        assert explainer_calls[0]["file_uri"] != uri_full
        assert explainer_calls[1]["file_uri"] != uri_full
        assert explainer_calls[0]["file_uri"] != explainer_calls[1]["file_uri"]
        assert explainer_calls[0]["mime_type"] == "application/pdf"
        assert "Páginas 1-3" in explainer_calls[0]["prompt"]
        assert "Páginas 4-10" in explainer_calls[0]["prompt"]
        assert "Parte 1/2 [PARTE ACTUAL]" in explainer_calls[0]["prompt"]

        # Sub-PDF page counts (buffer=1): part1 pages 1–3 → 1..4 → 4 pages; part2 4–10 → 3..10 → 8 pages
        assert segment_upload_page_counts == [4, 8]

        assert any(p.get("status") == "completed" for p in updates)
    finally:
        if os.path.isfile(pdf_path):
            os.unlink(pdf_path)


def test_process_project_pdf_aborts_when_tema_mece_fails_all_retries(monkeypatch):
    """After MAX_SEGMENTATION_COVERAGE_ATTEMPTS invalid MECE outputs, project ends in error."""
    pdf_path = _create_multi_page_pdf(5)
    try:
        project = {
            "id": "proj-mece-fail",
            "name": "MECE fail",
            "description": "",
            "pdf_filename": "test.pdf",
            "source_type": "pdf",
            "source_url": None,
            "status": "pending",
        }
        updates = []
        seg_calls = []

        monkeypatch.setattr(main, "get_project", lambda pid, uid, include_internal=False: project)
        monkeypatch.setattr(
            main,
            "get_user_api_key",
            lambda uid, provider=None: "" if provider == main.PROVIDER_OPENROUTER else "AIzaFakeKey",
        )
        monkeypatch.setattr(main, "mask_api_key", lambda k: "AIza****")
        monkeypatch.setattr(main, "update_project", lambda pid, uid, p: updates.append(p))
        monkeypatch.setattr(main, "download_pdf_to_temp", lambda pid, uid: pdf_path)

        async def _send_event(project_id, payload):
            return None

        class _DummySSE:
            async def end_stream(self, project_id):
                return None

        monkeypatch.setattr(main, "send_event", _send_event)
        monkeypatch.setattr(main, "sse_manager", _DummySSE())

        from google import genai

        monkeypatch.setattr(genai, "Client", lambda api_key: object())
        monkeypatch.setattr(main, "upload_file_with_retry", lambda *a, **k: SimpleNamespace(uri="u://x", mime_type="application/pdf"))

        def _always_bad_segmentador(api_key, file_uri, description, model, mime_type, source_kind):
            seg_calls.append(description)
            return (
                {
                    "analisis_texto": "x",
                    "temas_identificados": ["solo_tema"],
                    "decision_num_partes": 1,
                    "decision_justificacion": "x",
                    "partes": [
                        {
                            "numero": 1,
                            "titulo": "P1",
                            "contenido": "c",
                            "identificacion": "i",
                            "pagina_inicio": 1,
                            "pagina_fin": 2,
                            "temas_cubiertos": [],
                            "extension_estimada": "m",
                            "complejidad": "m",
                            "expansion_prevista": "a",
                        }
                    ],
                    "consideraciones_estudiante": "c",
                },
                _usage(total=10),
            )

        monkeypatch.setattr(main, "run_segmentador", _always_bad_segmentador)

        asyncio.run(main._process_project("proj-mece-fail", "user-1"))

        assert len(seg_calls) == MAX_SEGMENTATION_COVERAGE_ATTEMPTS
        assert any(
            p.get("status") == "error" and p.get("partes_contenido") == {} for p in updates
        )
        err = next(p for p in reversed(updates) if p.get("status") == "error")
        assert err.get("error_message") == SEGMENTATION_TEMA_COVERAGE_USER_MESSAGE
        for i in range(1, MAX_SEGMENTATION_COVERAGE_ATTEMPTS):
            assert "<correccion_asignacion_temas>" in seg_calls[i]
    finally:
        if os.path.isfile(pdf_path):
            os.unlink(pdf_path)


def test_investiture_pdf_numbering_and_extract_matches_main_logic():
    """Spot-check on real root PDF: numbering preserves length; extract_page_range sizes match backend."""
    repo_root = Path(__file__).resolve().parents[2]
    matches = list(repo_root.glob("*Investiture*.pdf")) + list(repo_root.glob("*investiture*.pdf"))
    if not matches:
        pytest.skip("No Investiture PDF in repository root")

    from backend.pdf_utils import add_page_numbers, extract_page_range

    src = str(matches[0])
    numbered = add_page_numbers(src)
    seg_start = None
    seg_mid = None
    try:
        reader = PdfReader(numbered)
        total = len(reader.pages)
        assert total > 0

        seg_start = extract_page_range(numbered, 1, 2, buffer=1)
        assert len(PdfReader(seg_start).pages) == 3

        if total >= 16:
            seg_mid = extract_page_range(numbered, 10, 15, buffer=1)
            assert len(PdfReader(seg_mid).pages) == 8
    finally:
        for p in (numbered, seg_start, seg_mid):
            if p and os.path.isfile(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass


def test_process_project_pdf_respects_explicit_gemini_provider_even_if_openrouter_key_exists(monkeypatch):
    pdf_path = _create_multi_page_pdf(4)
    try:
        project = {
            "id": "proj-gemini-explicit",
            "name": "Doc PDF",
            "description": "Procesar todo",
            "pdf_filename": "test.pdf",
            "source_type": "pdf",
            "source_url": None,
            "status": "pending",
        }

        updates = []
        gemini_calls = []

        monkeypatch.setattr(main, "get_project", lambda pid, uid, include_internal=False: project)
        monkeypatch.setattr(
            main,
            "get_user_api_key",
            lambda uid, provider=None: "sk-or-v1-test" if provider == main.PROVIDER_OPENROUTER else "AIzaFakeKey",
        )
        monkeypatch.setattr(main, "mask_api_key", lambda api_key: "AIza****")
        monkeypatch.setattr(
            main,
            "update_project",
            lambda pid, uid, payload: updates.append(deepcopy(payload)),
        )
        monkeypatch.setattr(main, "download_pdf_to_temp", lambda pid, uid: pdf_path)

        async def _send_event(project_id, payload):
            return None

        class _DummySSE:
            async def end_stream(self, project_id):
                return None

        monkeypatch.setattr(main, "send_event", _send_event)
        monkeypatch.setattr(main, "sse_manager", _DummySSE())

        from google import genai

        monkeypatch.setattr(genai, "Client", lambda api_key: object())
        monkeypatch.setattr(
            main,
            "upload_file_with_retry",
            lambda *args, **kwargs: SimpleNamespace(uri="uploaded://segment", mime_type="application/pdf"),
        )
        monkeypatch.setattr(
            main,
            "run_page_classifier",
            lambda *args, **kwargs: (frozenset([1, 2, 3, 4]), _usage(), {}),
        )
        monkeypatch.setattr(
            main,
            "_prepare_openrouter_pdf_context",
            lambda **kwargs: (_ for _ in ()).throw(AssertionError("OpenRouter OCR no debería prepararse")),
        )
        monkeypatch.setattr(
            main,
            "run_segmentador",
            lambda *args, **kwargs: (
                {
                    "analisis_texto": "Cuatro páginas",
                    "temas_identificados": ["tema1"],
                    "decision_num_partes": 1,
                    "decision_justificacion": "Una parte",
                    "partes": [_part_pdf_fields(1, "Única", 1, 4)],
                    "consideraciones_estudiante": "Seguir el orden natural",
                },
                _usage(total=40),
            ),
        )

        def _fake_explainer(api_key, file_uri, agent_prompt, model, mime_type):
            gemini_calls.append({
                "file_uri": file_uri,
                "model": model,
                "mime_type": mime_type,
            })
            return (
                {
                    "introduccion": "Intro",
                    "desarrollo": [],
                    "conclusion": "Cierre",
                    "conexiones_contextuales": [],
                },
                _usage(total=22),
            )

        monkeypatch.setattr(main, "run_explainer", _fake_explainer)
        monkeypatch.setattr(
            main,
            "run_explainer_or",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("OpenRouter no debería ejecutarse")),
        )
        monkeypatch.setattr(main, "run_recorrido", lambda *args, **kwargs: ({"ok": True}, _usage()))
        monkeypatch.setattr(main, "run_resources", lambda *args, **kwargs: ({"ok": True}, _usage()))

        async def _fake_format(api_key, explainer_data):
            return (explainer_data, {"total_tokens": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0})

        monkeypatch.setattr(main, "format_explainer_content", _fake_format)

        asyncio.run(main._process_project("proj-gemini-explicit", "user-123", explainer_provider="gemini"))

        assert gemini_calls
        assert all(call["model"] == MODEL_AGENTS for call in gemini_calls)
        usage_updates = [payload["usage"] for payload in updates if "usage" in payload]
        assert usage_updates[0]["explainer_provider"] == "gemini"
        assert usage_updates[0]["explainer_model"] == MODEL_AGENTS
    finally:
        if os.path.isfile(pdf_path):
            os.unlink(pdf_path)


def test_process_project_pdf_uses_openrouter_only_when_selected(monkeypatch):
    pdf_path = _create_multi_page_pdf(4)
    try:
        project = {
            "id": "proj-openrouter-explicit",
            "name": "Doc PDF",
            "description": "Procesar todo",
            "pdf_filename": "test.pdf",
            "source_type": "pdf",
            "source_url": None,
            "status": "pending",
        }

        updates = []
        openrouter_calls = []

        monkeypatch.setattr(main, "get_project", lambda pid, uid, include_internal=False: project)
        monkeypatch.setattr(
            main,
            "get_user_api_key",
            lambda uid, provider=None: "sk-or-v1-test" if provider == main.PROVIDER_OPENROUTER else "AIzaFakeKey",
        )
        monkeypatch.setattr(main, "mask_api_key", lambda api_key: "AIza****")
        monkeypatch.setattr(
            main,
            "update_project",
            lambda pid, uid, payload: updates.append(deepcopy(payload)),
        )
        monkeypatch.setattr(main, "download_pdf_to_temp", lambda pid, uid: pdf_path)

        async def _send_event(project_id, payload):
            return None

        class _DummySSE:
            async def end_stream(self, project_id):
                return None

        monkeypatch.setattr(main, "send_event", _send_event)
        monkeypatch.setattr(main, "sse_manager", _DummySSE())

        from google import genai

        monkeypatch.setattr(genai, "Client", lambda api_key: object())
        monkeypatch.setattr(
            main,
            "upload_file_with_retry",
            lambda *args, **kwargs: SimpleNamespace(uri="uploaded://segment", mime_type="application/pdf"),
        )
        monkeypatch.setattr(
            main,
            "run_page_classifier",
            lambda *args, **kwargs: (frozenset([1, 2, 3, 4]), _usage(), {}),
        )
        monkeypatch.setattr(
            main,
            "_prepare_openrouter_pdf_context",
            lambda **kwargs: main.OpenRouterPreparedPdfContext(
                source_pdf_path=pdf_path,
                cache_entry=OpenRouterPdfParseCacheEntry(
                    source_sha256="sha256",
                    engine="mistral-ocr",
                    assistant_message=None,
                    cache_path="cache.json",
                    cache_hit=True,
                    expected_page_numbers=(1, 2, 3, 4),
                    cached_page_numbers=(1, 2, 3, 4),
                    page_index=(),
                ),
            ),
        )
        monkeypatch.setattr(
            main,
            "run_segmentador",
            lambda *args, **kwargs: (
                {
                    "analisis_texto": "Cuatro páginas",
                    "temas_identificados": ["tema1"],
                    "decision_num_partes": 1,
                    "decision_justificacion": "Una parte",
                    "partes": [_part_pdf_fields(1, "Única", 1, 4)],
                    "consideraciones_estudiante": "Seguir el orden natural",
                },
                _usage(total=40),
            ),
        )
        monkeypatch.setattr(
            main,
            "run_explainer",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Gemini explainer no debería ejecutarse")),
        )

        def _fake_openrouter_explainer(source_path, agent_prompt, model, mime_type, api_key, cache_entry=None, page_numbers=()):
            openrouter_calls.append({
                "source_path": source_path,
                "model": model,
                "mime_type": mime_type,
                "page_numbers": tuple(page_numbers),
            })
            return (
                {
                    "introduccion": "Intro",
                    "desarrollo": [],
                    "conclusion": "Cierre",
                    "conexiones_contextuales": [],
                },
                _usage(total=27),
            )

        monkeypatch.setattr(main, "run_explainer_or", _fake_openrouter_explainer)
        monkeypatch.setattr(main, "run_recorrido", lambda *args, **kwargs: ({"ok": True}, _usage()))
        monkeypatch.setattr(main, "run_resources", lambda *args, **kwargs: ({"ok": True}, _usage()))

        async def _fake_format(api_key, explainer_data):
            return (explainer_data, {"total_tokens": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0})

        monkeypatch.setattr(main, "format_explainer_content", _fake_format)

        asyncio.run(main._process_project("proj-openrouter-explicit", "user-123", explainer_provider="openrouter"))

        assert openrouter_calls
        assert all(call["model"] == main.OPENROUTER_EXPLAINER_MODEL for call in openrouter_calls)
        assert all(call["page_numbers"] == (1, 2, 3, 4) for call in openrouter_calls)
        usage_updates = [payload["usage"] for payload in updates if "usage" in payload]
        assert usage_updates[0]["explainer_provider"] == "openrouter"
        assert usage_updates[0]["explainer_model"] == main.OPENROUTER_EXPLAINER_MODEL
        assert usage_updates[0]["openrouter_pdf_priming_model"] == main.OPENROUTER_PDF_PRIMING_MODEL
    finally:
        if os.path.isfile(pdf_path):
            os.unlink(pdf_path)


def test_process_project_pdf_records_openrouter_ocr_diagnostic_artifact_when_present(monkeypatch):
    pdf_path = _create_multi_page_pdf(4)
    try:
        project = {
            "id": "proj-openrouter-diagnostic-artifact",
            "name": "Doc PDF",
            "description": "Procesar todo",
            "pdf_filename": "test.pdf",
            "source_type": "pdf",
            "source_url": None,
            "status": "pending",
        }

        timeline = []

        monkeypatch.setattr(main, "get_project", lambda pid, uid, include_internal=False: project)
        monkeypatch.setattr(
            main,
            "get_user_api_key",
            lambda uid, provider=None: "sk-or-v1-test" if provider == main.PROVIDER_OPENROUTER else "AIzaFakeKey",
        )
        monkeypatch.setattr(main, "mask_api_key", lambda api_key: "AIza****")
        monkeypatch.setattr(
            main,
            "update_project",
            lambda pid, uid, payload: timeline.append(("update_project", deepcopy(payload))),
        )
        monkeypatch.setattr(main, "download_pdf_to_temp", lambda pid, uid: pdf_path)

        async def _send_event(project_id, payload):
            timeline.append(("send_event", deepcopy(payload)))
            return None

        class _DummySSE:
            async def end_stream(self, project_id):
                return None

        monkeypatch.setattr(main, "send_event", _send_event)
        monkeypatch.setattr(main, "sse_manager", _DummySSE())

        from google import genai

        monkeypatch.setattr(genai, "Client", lambda api_key: object())
        monkeypatch.setattr(
            main,
            "upload_file_with_retry",
            lambda *args, **kwargs: SimpleNamespace(uri="uploaded://segment", mime_type="application/pdf"),
        )
        monkeypatch.setattr(
            main,
            "run_page_classifier",
            lambda *args, **kwargs: (frozenset([1, 2, 3, 4]), _usage(), {}),
        )
        monkeypatch.setattr(
            main,
            "_prepare_openrouter_pdf_context",
            lambda **kwargs: main.OpenRouterPreparedPdfContext(
                source_pdf_path=pdf_path,
                cache_entry=OpenRouterPdfParseCacheEntry(
                    source_sha256="sha256",
                    engine="mistral-ocr",
                    assistant_message=None,
                    cache_path="cache.json",
                    cache_hit=False,
                    expected_page_numbers=(1, 2, 3, 4),
                    cached_page_numbers=(1, 2, 3, 4),
                    page_index=(),
                    diagnostic_artifact_path="cache.json.missing-pages.json",
                ),
                priming_model=main.OPENROUTER_PDF_PRIMING_FALLBACK_MODEL,
            ),
        )
        monkeypatch.setattr(
            main,
            "run_segmentador",
            lambda *args, **kwargs: (
                {
                    "analisis_texto": "Cuatro páginas",
                    "temas_identificados": ["tema1"],
                    "decision_num_partes": 1,
                    "decision_justificacion": "Una parte",
                    "partes": [_part_pdf_fields(1, "Única", 1, 4)],
                    "consideraciones_estudiante": "Seguir el orden natural",
                },
                _usage(total=40),
            ),
        )
        monkeypatch.setattr(
            main,
            "run_explainer",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Gemini explainer no debería ejecutarse")),
        )
        monkeypatch.setattr(
            main,
            "run_explainer_or",
            lambda *args, **kwargs: (
                {
                    "introduccion": "Intro",
                    "desarrollo": [],
                    "conclusion": "Cierre",
                    "conexiones_contextuales": [],
                },
                _usage(total=27),
            ),
        )
        monkeypatch.setattr(main, "run_recorrido", lambda *args, **kwargs: ({"ok": True}, _usage()))
        monkeypatch.setattr(main, "run_resources", lambda *args, **kwargs: ({"ok": True}, _usage()))

        async def _fake_format(api_key, explainer_data):
            return explainer_data, {"total_tokens": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0}

        monkeypatch.setattr(main, "format_explainer_content", _fake_format)

        asyncio.run(
            main._process_project(
                "proj-openrouter-diagnostic-artifact",
                "user-123",
                explainer_provider="openrouter",
            )
        )

        part_started_idx = next(
            idx
            for idx, (kind, payload) in enumerate(timeline)
            if kind == "send_event" and payload.get("type") == "part_started"
        )
        artifact_update_indices = [
            idx
            for idx, (kind, payload) in enumerate(timeline)
            if kind == "update_project"
            and isinstance(payload.get("usage"), dict)
            and payload["usage"].get("openrouter_pdf_ocr_diagnostic_artifact") == "cache.json.missing-pages.json"
        ]
        artifact_event_indices = [
            idx
            for idx, (kind, payload) in enumerate(timeline)
            if kind == "send_event"
            and payload.get("type") == "usage_update"
            and isinstance(payload.get("usage"), dict)
            and payload["usage"].get("openrouter_pdf_ocr_diagnostic_artifact") == "cache.json.missing-pages.json"
        ]

        assert artifact_update_indices
        assert artifact_event_indices
        assert artifact_update_indices[0] < part_started_idx
        assert artifact_event_indices[0] < part_started_idx
    finally:
        if os.path.isfile(pdf_path):
            os.unlink(pdf_path)


def test_process_project_pdf_retries_subpart_when_scope_auditor_rejects(monkeypatch, caplog):
    pdf_path = _create_multi_page_pdf(4)
    try:
        caplog.set_level("WARNING", logger="main")
        project = {
            "id": "proj-subpart-audit",
            "name": "Doc PDF",
            "description": "Procesar todo",
            "pdf_filename": "test.pdf",
            "source_type": "pdf",
            "source_url": None,
            "status": "pending",
        }

        prompts_seen = []
        audit_attempts = {"count": 0}
        formatter_calls = {"count": 0}

        monkeypatch.setattr(main, "get_project", lambda pid, uid, include_internal=False: project)
        monkeypatch.setattr(main, "get_user_api_key", lambda uid, provider=None: "AIzaFakeKey")
        monkeypatch.setattr(main, "mask_api_key", lambda api_key: "AIza****")
        monkeypatch.setattr(main, "update_project", lambda pid, uid, payload: None)
        monkeypatch.setattr(main, "download_pdf_to_temp", lambda pid, uid: pdf_path)

        async def _send_event(project_id, payload):
            return None

        class _DummySSE:
            async def end_stream(self, project_id):
                return None

        monkeypatch.setattr(main, "send_event", _send_event)
        monkeypatch.setattr(main, "sse_manager", _DummySSE())

        from google import genai

        monkeypatch.setattr(genai, "Client", lambda api_key: object())
        monkeypatch.setattr(
            main,
            "upload_file_with_retry",
            lambda *args, **kwargs: SimpleNamespace(uri="uploaded://segment", mime_type="application/pdf"),
        )
        monkeypatch.setattr(main, "run_page_classifier", lambda *args, **kwargs: (frozenset([1, 2, 3, 4]), _usage(), {}))

        def _fake_segmentador(*args, **kwargs):
            base = _part_pdf_fields(1, "Única", 1, 4)
            base["temas_cubiertos"] = ["tema1", "tema2"]
            base["subpartes"] = [
                {
                    "numero_subparte": 1,
                    "titulo": "Primera",
                    "contenido": "Contenido inicial",
                    "identificacion": "NÚCLEO SEGÚN MARCAS PDF: páginas 1–2.",
                    "pagina_inicio": 1,
                    "pagina_fin": 2,
                    "temas_cubiertos": ["tema1"],
                    "delimitacion_explainer": {
                        "inicio": {"encabezado": "1.1", "ancla_texto": "primer texto"},
                        "fin": {"ancla_texto": "fin tema uno", "encabezado_siguiente_excluido": "1.2"},
                        "transicion_compartida": {"hay_transicion": False, "pagina": 0, "hasta_texto_inclusive": "", "desde_texto_inclusive": ""},
                    },
                },
                {
                    "numero_subparte": 2,
                    "titulo": "Segunda",
                    "contenido": "Contenido final",
                    "identificacion": "NÚCLEO SEGÚN MARCAS PDF: páginas 3–4.",
                    "pagina_inicio": 3,
                    "pagina_fin": 4,
                    "temas_cubiertos": ["tema2"],
                    "delimitacion_explainer": {
                        "inicio": {"encabezado": "1.2", "ancla_texto": "segundo texto"},
                        "fin": {"ancla_texto": "fin tema dos", "encabezado_siguiente_excluido": ""},
                        "transicion_compartida": {"hay_transicion": False, "pagina": 0, "hasta_texto_inclusive": "", "desde_texto_inclusive": ""},
                    },
                },
            ]
            return (
                {
                    "analisis_texto": "Cuatro páginas",
                    "temas_identificados": ["tema1", "tema2"],
                    "decision_num_partes": 1,
                    "decision_justificacion": "Una parte",
                    "partes": [base],
                    "consideraciones_estudiante": "Seguir el orden natural",
                },
                _usage(total=40),
            )

        monkeypatch.setattr(main, "run_segmentador", _fake_segmentador)

        def _fake_subpart_explainer(api_key, file_uri, agent_prompt, model, mime_type):
            prompts_seen.append(agent_prompt)
            return (
                {
                    "desarrollo": [
                        {
                            "titulo_seccion": "Bloque",
                            "explicacion_introductoria": "Contexto",
                            "subsecciones": [
                                {"titulo_subseccion": "Detalle", "explicacion_detallada": "Texto desarrollado"}
                            ],
                        }
                    ]
                },
                _usage(total=22),
            )

        monkeypatch.setattr(main, "run_subpart_explainer", _fake_subpart_explainer)
        monkeypatch.setattr(main, "run_recorrido", lambda *args, **kwargs: ({"ok": True}, _usage()))
        monkeypatch.setattr(main, "run_resources", lambda *args, **kwargs: ({"ok": True}, _usage()))

        async def _fake_format(api_key, explainer_data):
            formatter_calls["count"] += 1
            return explainer_data, {"total_tokens": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0}

        monkeypatch.setattr(main, "format_explainer_content", _fake_format)

        def _fake_auditor(**kwargs):
            from backend.subpart_scope_auditor import SubpartScopeAuditReport

            audit_attempts["count"] += 1
            if audit_attempts["count"] == 1:
                return (
                    SubpartScopeAuditReport(
                        is_valid=False,
                        invades_previous=(),
                        invades_next=("tema2",),
                        missing_current=("tema1",),
                        rationale="Invade la siguiente subparte.",
                    ),
                    _usage(total=7),
                )
            return (
                SubpartScopeAuditReport(
                    is_valid=True,
                    invades_previous=(),
                    invades_next=(),
                    missing_current=(),
                    rationale="OK",
                ),
                _usage(total=7),
            )

        monkeypatch.setattr(main, "run_subpart_scope_auditor", _fake_auditor)

        asyncio.run(main._process_project("proj-subpart-audit", "user-123"))

        assert len(prompts_seen) >= 2
        retry_prompt = next(prompt for prompt in prompts_seen if "<reescritura_alcance_subparte>" in prompt)
        assert "<reescritura_alcance_subparte>" in retry_prompt
        assert "Texto desarrollado" in retry_prompt
        assert "Invade la siguiente subparte." in retry_prompt
        assert "REESCRIBE desde cero el campo `desarrollo`." in retry_prompt
        assert "SUBPARTE ACTUAL (fuente de verdad):" in retry_prompt
        assert (
            "SUBPARTE ANTERIOR (NO desarrollar):" in retry_prompt
            or "SUBPARTE SIGUIENTE (NO desarrollar):" in retry_prompt
        )
        assert formatter_calls["count"] == 1
        assert not any("Error inesperado al formatear parte" in message for message in caplog.messages)
    finally:
        if os.path.isfile(pdf_path):
            os.unlink(pdf_path)


def test_process_project_pdf_openrouter_retry_reuses_cache_and_includes_rewrite_brief(monkeypatch, caplog):
    pdf_path = _create_multi_page_pdf(4)
    try:
        caplog.set_level("WARNING", logger="main")
        project = {
            "id": "proj-openrouter-subpart-audit",
            "name": "Doc PDF",
            "description": "Procesar todo",
            "pdf_filename": "test.pdf",
            "source_type": "pdf",
            "source_url": None,
            "status": "pending",
        }

        prompts_seen = []
        openrouter_calls = []
        audit_attempts = {"count": 0}
        formatter_calls = {"count": 0}
        shared_cache_entry = OpenRouterPdfParseCacheEntry(
            source_sha256="sha256",
            engine="mistral-ocr",
            assistant_message=None,
            cache_path="cache.json",
            cache_hit=True,
            expected_page_numbers=(1, 2, 3, 4),
            cached_page_numbers=(1, 2, 3, 4),
            page_index=(),
        )

        monkeypatch.setattr(main, "get_project", lambda pid, uid, include_internal=False: project)
        monkeypatch.setattr(
            main,
            "get_user_api_key",
            lambda uid, provider=None: "sk-or-v1-test" if provider == main.PROVIDER_OPENROUTER else "AIzaFakeKey",
        )
        monkeypatch.setattr(main, "mask_api_key", lambda api_key: "AIza****")
        monkeypatch.setattr(main, "update_project", lambda pid, uid, payload: None)
        monkeypatch.setattr(main, "download_pdf_to_temp", lambda pid, uid: pdf_path)

        async def _send_event(project_id, payload):
            return None

        class _DummySSE:
            async def end_stream(self, project_id):
                return None

        monkeypatch.setattr(main, "send_event", _send_event)
        monkeypatch.setattr(main, "sse_manager", _DummySSE())

        from google import genai

        monkeypatch.setattr(genai, "Client", lambda api_key: object())
        monkeypatch.setattr(
            main,
            "upload_file_with_retry",
            lambda *args, **kwargs: SimpleNamespace(uri="uploaded://segment", mime_type="application/pdf"),
        )
        monkeypatch.setattr(
            main,
            "run_page_classifier",
            lambda *args, **kwargs: (frozenset([1, 2, 3, 4]), _usage(), {}),
        )
        monkeypatch.setattr(
            main,
            "_prepare_openrouter_pdf_context",
            lambda **kwargs: main.OpenRouterPreparedPdfContext(
                source_pdf_path=pdf_path,
                cache_entry=shared_cache_entry,
            ),
        )

        def _fake_segmentador(*args, **kwargs):
            base = _part_pdf_fields(1, "Única", 1, 4)
            base["temas_cubiertos"] = ["tema1"]
            base["subpartes"] = [
                {
                    "numero_subparte": 1,
                    "titulo": "Única subparte",
                    "contenido": "Contenido único",
                    "identificacion": "NÚCLEO SEGÚN MARCAS PDF: páginas 1–4.",
                    "pagina_inicio": 1,
                    "pagina_fin": 4,
                    "temas_cubiertos": ["tema1"],
                    "delimitacion_explainer": {
                        "inicio": {"encabezado": "1.1", "ancla_texto": "primer texto"},
                        "fin": {"ancla_texto": "fin tema uno", "encabezado_siguiente_excluido": ""},
                        "transicion_compartida": {"hay_transicion": False, "pagina": 0, "hasta_texto_inclusive": "", "desde_texto_inclusive": ""},
                    },
                }
            ]
            return (
                {
                    "analisis_texto": "Cuatro páginas",
                    "temas_identificados": ["tema1"],
                    "decision_num_partes": 1,
                    "decision_justificacion": "Una parte",
                    "partes": [base],
                    "consideraciones_estudiante": "Seguir el orden natural",
                },
                _usage(total=40),
            )

        monkeypatch.setattr(main, "run_segmentador", _fake_segmentador)
        monkeypatch.setattr(
            main,
            "run_subpart_explainer",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Gemini subpart explainer no debería ejecutarse")),
        )

        def _fake_openrouter_subpart_explainer(
            source_path,
            agent_prompt,
            model,
            mime_type,
            api_key,
            cache_entry=None,
            page_numbers=(),
        ):
            prompts_seen.append(agent_prompt)
            openrouter_calls.append(
                {
                    "source_path": source_path,
                    "model": model,
                    "mime_type": mime_type,
                    "cache_entry": cache_entry,
                    "page_numbers": tuple(page_numbers),
                }
            )
            return (
                {
                    "desarrollo": [
                        {
                            "titulo_seccion": "Bloque OpenRouter",
                            "explicacion_introductoria": "Contexto OpenRouter",
                            "subsecciones": [
                                {
                                    "titulo_subseccion": "Detalle OpenRouter",
                                    "explicacion_detallada": "Texto OpenRouter previo",
                                }
                            ],
                        }
                    ]
                },
                _usage(total=31),
            )

        monkeypatch.setattr(main, "run_subpart_explainer_or", _fake_openrouter_subpart_explainer)
        monkeypatch.setattr(main, "run_recorrido", lambda *args, **kwargs: ({"ok": True}, _usage()))
        monkeypatch.setattr(main, "run_resources", lambda *args, **kwargs: ({"ok": True}, _usage()))

        async def _fake_format(api_key, explainer_data):
            formatter_calls["count"] += 1
            return explainer_data, {"total_tokens": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0}

        monkeypatch.setattr(main, "format_explainer_content", _fake_format)

        def _fake_auditor(**kwargs):
            from backend.subpart_scope_auditor import SubpartScopeAuditReport

            audit_attempts["count"] += 1
            if audit_attempts["count"] == 1:
                return (
                    SubpartScopeAuditReport(
                        is_valid=False,
                        invades_previous=(),
                        invades_next=("tema_ajeno",),
                        missing_current=("tema1",),
                        rationale="El desarrollo mezcla alcance ajeno.",
                    ),
                    _usage(total=9),
                )
            return (
                SubpartScopeAuditReport(
                    is_valid=True,
                    invades_previous=(),
                    invades_next=(),
                    missing_current=(),
                    rationale="OK",
                ),
                _usage(total=9),
            )

        monkeypatch.setattr(main, "run_subpart_scope_auditor", _fake_auditor)

        asyncio.run(
            main._process_project(
                "proj-openrouter-subpart-audit",
                "user-123",
                explainer_provider="openrouter",
            )
        )

        assert len(openrouter_calls) == 2
        assert openrouter_calls[0]["cache_entry"] is shared_cache_entry
        assert openrouter_calls[1]["cache_entry"] is shared_cache_entry
        assert openrouter_calls[0]["page_numbers"] == (1, 2, 3, 4)
        assert openrouter_calls[1]["page_numbers"] == (1, 2, 3, 4)
        retry_prompt = prompts_seen[1]
        assert "<reescritura_alcance_subparte>" in retry_prompt
        assert "Texto OpenRouter previo" in retry_prompt
        assert "El desarrollo mezcla alcance ajeno." in retry_prompt
        assert "REESCRIBE desde cero el campo `desarrollo`." in retry_prompt
        assert formatter_calls["count"] == 1
        assert not any("Error inesperado al formatear parte" in message for message in caplog.messages)
    finally:
        if os.path.isfile(pdf_path):
            os.unlink(pdf_path)


def test_process_project_pdf_openrouter_prepares_only_content_pages_for_mistral_context(monkeypatch):
    pdf_path = _create_multi_page_pdf(5)
    try:
        project = {
            "id": "proj-openrouter-mistral-backfill",
            "name": "Doc PDF",
            "description": "Procesar todo",
            "pdf_filename": "test.pdf",
            "source_type": "pdf",
            "source_url": None,
            "status": "pending",
        }

        prepare_calls = []

        monkeypatch.setattr(main, "get_project", lambda pid, uid, include_internal=False: project)
        monkeypatch.setattr(
            main,
            "get_user_api_key",
            lambda uid, provider=None: (
                "AIzaFakeKey"
                if provider == main.PROVIDER_GEMINI
                else "sk-or-v1-test"
                if provider == main.PROVIDER_OPENROUTER
                else "mistral-test-key"
            ),
        )
        monkeypatch.setattr(main, "mask_api_key", lambda api_key: "****")
        monkeypatch.setattr(main, "update_project", lambda pid, uid, payload: None)
        monkeypatch.setattr(main, "download_pdf_to_temp", lambda pid, uid: pdf_path)
        async def _send_event(*args, **kwargs):
            return None

        class _DummySSE:
            async def end_stream(self, *args, **kwargs):
                return None

        monkeypatch.setattr(main, "send_event", _send_event)
        monkeypatch.setattr(main, "sse_manager", _DummySSE())
        monkeypatch.setattr(main, "upload_file_with_retry", lambda *args, **kwargs: SimpleNamespace(uri="uploaded://segment", mime_type="application/pdf"))
        monkeypatch.setattr(main, "run_page_classifier", lambda *args, **kwargs: (frozenset([1, 2, 4, 5]), _usage(), {}))
        monkeypatch.setattr(
            main,
            "_prepare_mistral_pdf_ocr_context",
            lambda **kwargs: prepare_calls.append(kwargs) or main.PreparedPdfOcrContext(
                source_pdf_path=pdf_path,
                cache_entry=SimpleNamespace(
                    cache_hit=False,
                    cache_path="cache.json",
                    expected_page_numbers=(1, 2, 4, 5),
                    cached_page_numbers=(1, 2, 4, 5),
                    page_index=(),
                ),
            ),
        )
        monkeypatch.setattr(main, "run_segmentador", lambda *args, **kwargs: ({
            "analisis_texto": "Cinco páginas",
            "temas_identificados": ["tema1"],
            "decision_num_partes": 1,
            "decision_justificacion": "Una parte",
            "partes": [{
                "numero": 1,
                "titulo": "Única",
                "contenido": "Contenido único",
                "identificacion": "Páginas 1-5",
                "pagina_inicio": 1,
                "pagina_fin": 5,
                "temas_cubiertos": ["tema1"],
                "extension_estimada": "media",
                "complejidad": "media",
                "expansion_prevista": "alta",
                "subpartes": [],
            }],
            "consideraciones_estudiante": "Orden natural",
        }, _usage(total=20)))
        monkeypatch.setattr(main, "run_explainer_or", lambda *args, **kwargs: ({"introduccion": "", "desarrollo": [], "conclusion": "", "conexiones_contextuales": []}, _usage()))
        monkeypatch.setattr(main, "run_recorrido", lambda *args, **kwargs: ({"ok": True}, _usage()))
        monkeypatch.setattr(main, "run_resources", lambda *args, **kwargs: ({"ok": True}, _usage()))
        async def _fake_format(*args, **kwargs):
            return (
                {"introduccion": "", "desarrollo": [], "conclusion": "", "conexiones_contextuales": []},
                {"total_tokens": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0},
            )

        monkeypatch.setattr(main, "format_explainer_content", _fake_format)

        asyncio.run(main._process_project("proj-openrouter-mistral-backfill", "user-123", explainer_provider="openrouter"))

        assert prepare_calls[0]["content_page_set"] == frozenset({1, 2, 4, 5})
    finally:
        if os.path.isfile(pdf_path):
            os.unlink(pdf_path)
