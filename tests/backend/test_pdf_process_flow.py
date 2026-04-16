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
from backend.pdf_ocr_cache import PdfOcrCacheEntry, PdfOcrParsedPage
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
        assert all(c["mime_type"] == "application/pdf" for c in explainer_calls)

        def _prompt_marking_current_part(total_parts: int, part_num: int) -> str:
            return f"Parte {part_num}/{total_parts} [PARTE ACTUAL]"

        part1_marker = _prompt_marking_current_part(2, 1)
        part2_marker = _prompt_marking_current_part(2, 2)
        part1_prompt = next(c["prompt"] for c in explainer_calls if part1_marker in c["prompt"])
        part2_prompt = next(c["prompt"] for c in explainer_calls if part2_marker in c["prompt"])
        assert "Páginas 1-3" in part1_prompt
        assert "Páginas 4-10" in part2_prompt
        assert part1_marker in part1_prompt
        assert part2_marker in part2_prompt

        # Sub-PDF page counts (buffer=1): part1 pages 1–3 → 1..4 → 4 pages; part2 4–10 → 3..10 → 8 pages
        assert sorted(segment_upload_page_counts) == [4, 8]

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
            "_prepare_mistral_pdf_ocr_context",
            lambda **kwargs: main.PreparedPdfOcrContext(
                source_pdf_path=pdf_path,
                cache_entry=PdfOcrCacheEntry(
                    source_sha256="sha256",
                    engine="mistral-native",
                    cache_path="cache.json",
                    cache_hit=True,
                    expected_page_numbers=(1, 2, 3, 4),
                    cached_page_numbers=(1, 2, 3, 4),
                    page_index=(
                        PdfOcrParsedPage(page_number=1, markdown="Page 1"),
                        PdfOcrParsedPage(page_number=2, markdown="Page 2"),
                        PdfOcrParsedPage(page_number=3, markdown="Page 3"),
                        PdfOcrParsedPage(page_number=4, markdown="Page 4"),
                    ),
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
