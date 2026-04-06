"""Backend tests for robust web URL support."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

from backend.pricing import calculate_cost
from backend.url_extraction import (
    ExtractedWebContent,
    FetchedWebPage,
    WebExtractionError,
    _extract_deterministically,
    build_text_blocks,
    extract_web_content,
    normalize_public_web_url,
    render_block_marked_document,
    slice_block_range,
)
import main
from backend.gemini_model_routing import MODEL_AGENTS, MODEL_SEGMENTADOR


def _usage(
    *,
    prompt: int = 0,
    tool_prompt: int = 0,
    candidates: int = 0,
    thoughts: int = 0,
    total: int = 0,
):
    return SimpleNamespace(
        prompt_token_count=prompt,
        tool_use_prompt_token_count=tool_prompt,
        candidates_token_count=candidates,
        thoughts_token_count=thoughts,
        total_token_count=total or (prompt + tool_prompt + candidates + thoughts),
    )


def test_normalize_public_web_url_removes_fragment(monkeypatch):
    monkeypatch.setattr("backend.url_extraction._ensure_public_hostname", lambda hostname: None)
    assert normalize_public_web_url("https://example.com/path#intro") == "https://example.com/path"


def test_normalize_public_web_url_rejects_private_host():
    try:
        normalize_public_web_url("http://localhost:8000/article")
        assert False, "Expected WebExtractionError"
    except WebExtractionError as exc:
        assert "locales" in str(exc).lower() or "privada" in str(exc).lower()


def test_build_text_blocks_and_slice_range_preserve_content():
    text = (
        "Primer bloque con contenido suficiente para arrancar la segmentación.\n\n"
        "Segundo bloque con más detalle y continuidad temática.\n\n"
        "Tercer bloque para cerrar el argumento general."
    )
    blocks = build_text_blocks(text, max_chars=70)
    assert len(blocks) >= 2

    document = render_block_marked_document(
        title="Artículo de prueba",
        source_url="https://example.com/article",
        blocks=blocks,
    )
    assert "=== BLOQUE 1 ===" in document

    selected = slice_block_range(blocks, 1, 2)
    assert selected[0].number == 1
    assert selected[-1].number == 2


def test_extract_web_content_uses_deterministic_pipeline(monkeypatch):
    fetched = FetchedWebPage(
        requested_url="https://example.com/article",
        resolved_url="https://example.com/article",
        content_type="text/html",
        status_code=200,
        body_text="<html><body>ok</body></html>",
        title="Artículo",
    )
    monkeypatch.setattr("backend.url_extraction._ensure_public_hostname", lambda hostname: None)
    monkeypatch.setattr("backend.url_extraction._fetch_web_page", lambda url: fetched)
    monkeypatch.setattr(
        "backend.url_extraction._extract_deterministically",
        lambda body_text, content_type, url: (
            (
                "Texto extraído de forma determinista con suficiente longitud para ser aceptado por "
                "la heurística de calidad, manteniendo varias frases, varios conceptos y un volumen "
                "de palabras claramente superior al mínimo requerido para iniciar el procesamiento."
            ),
            "trafilatura",
        ),
    )

    gemini_calls = []

    def _unexpected_fallback(**kwargs):
        gemini_calls.append(kwargs)
        return None, None

    monkeypatch.setattr("backend.url_extraction._extract_with_gemini_url_context", _unexpected_fallback)

    extracted, usage_meta = extract_web_content(
        "https://example.com/article#frag",
        api_key="AIzaFakeKey",
        model=MODEL_AGENTS,
    )

    assert usage_meta is None
    assert extracted.extraction_method == "trafilatura"
    assert extracted.text.startswith("Texto extraído")
    assert gemini_calls == []


def test_extract_web_content_aborts_when_no_pipeline_succeeds(monkeypatch):
    fetched = FetchedWebPage(
        requested_url="https://example.com/article",
        resolved_url="https://example.com/article",
        content_type="text/html",
        status_code=200,
        body_text="<html><body>vacío</body></html>",
        title="Artículo",
    )
    monkeypatch.setattr("backend.url_extraction._ensure_public_hostname", lambda hostname: None)
    monkeypatch.setattr("backend.url_extraction._fetch_web_page", lambda url: fetched)
    monkeypatch.setattr("backend.url_extraction._extract_deterministically", lambda body_text, content_type, url: ("", "none"))
    monkeypatch.setattr("backend.url_extraction._extract_with_gemini_url_context", lambda **kwargs: (None, _usage()))

    try:
        extract_web_content("https://example.com/article", api_key="AIzaFakeKey", model=MODEL_AGENTS)
        assert False, "Expected WebExtractionError"
    except WebExtractionError as exc:
        assert "no se pudo extraer" in str(exc).lower()


def test_extract_deterministically_prefers_higher_quality_candidate(monkeypatch):
    html = "<html lang='en'><body>placeholder</body></html>"
    monkeypatch.setattr(
        "backend.url_extraction._extract_with_trafilatura",
        lambda html_text, url: "Texto corto pero válido. " * 12,
    )
    monkeypatch.setattr(
        "backend.url_extraction._extract_with_readability",
        lambda html_text: (
            "This is a much more complete article body with multiple paragraphs and enough detail "
            "to clearly outperform the shorter extraction. " * 20
        ),
    )
    monkeypatch.setattr("backend.url_extraction._extract_with_goose3", lambda html_text: "")
    monkeypatch.setattr("backend.url_extraction._extract_with_justext", lambda html_text: "")
    monkeypatch.setattr("backend.url_extraction._extract_visible_text_from_html", lambda html_text: "")

    text, method = _extract_deterministically(html, "text/html", "https://example.com/article")

    assert method == "readability"
    assert "much more complete article body" in text


def test_extract_web_content_uses_browser_render_before_gemini(monkeypatch):
    fetched = FetchedWebPage(
        requested_url="https://example.com/article",
        resolved_url="https://example.com/article",
        content_type="text/html",
        status_code=200,
        body_text="<html><body>placeholder</body></html>",
        title="Artículo",
        fetch_method="curl_impersonation",
    )
    rendered = FetchedWebPage(
        requested_url="https://example.com/article",
        resolved_url="https://example.com/article",
        content_type="text/html",
        status_code=200,
        body_text="<html><body>rendered</body></html>",
        title="Artículo renderizado",
        fetch_method="browser_render",
    )
    monkeypatch.setattr("backend.url_extraction._ensure_public_hostname", lambda hostname: None)
    monkeypatch.setattr("backend.url_extraction._fetch_web_page", lambda url: fetched)
    monkeypatch.setattr("backend.url_extraction._render_web_page_in_browser", lambda url: rendered)

    calls = {"count": 0}

    def _fake_extract(body_text, content_type, url):
        calls["count"] += 1
        if calls["count"] == 1:
            return "", "none"
        return (
            "Texto renderizado con suficiente longitud para ser aceptado por la heurística de calidad "
            "sin necesidad de consumir la herramienta URL context de Gemini en esta ruta de recuperación, "
            "manteniendo varias frases, varios conceptos y claramente más palabras de las exigidas por "
            "el umbral mínimo configurado para iniciar el procesamiento posterior.",
            "trafilatura",
        )

    gemini_calls = []

    monkeypatch.setattr("backend.url_extraction._extract_deterministically", _fake_extract)
    monkeypatch.setattr(
        "backend.url_extraction._extract_with_gemini_url_context",
        lambda **kwargs: gemini_calls.append(kwargs) or (None, _usage()),
    )

    extracted, usage_meta = extract_web_content(
        "https://example.com/article",
        api_key="AIzaFakeKey",
        model=MODEL_AGENTS,
    )

    assert usage_meta is None
    assert extracted.extraction_method == "trafilatura_browser_render"
    assert extracted.metadata["browser_rendered"] is True
    assert extracted.metadata["fetch_method"] == "browser_render"
    assert gemini_calls == []


def test_extract_web_content_tries_gemini_after_recoverable_fetch_error(monkeypatch):
    monkeypatch.setattr("backend.url_extraction._ensure_public_hostname", lambda hostname: None)
    monkeypatch.setattr(
        "backend.url_extraction._fetch_web_page",
        lambda url: (_ for _ in ()).throw(
            WebExtractionError(
                "403 anti-bot",
                status_code=403,
                allow_gemini_fallback=True,
            )
        ),
    )
    monkeypatch.setattr("backend.url_extraction._render_web_page_in_browser", lambda url: None)

    fallback_result = ExtractedWebContent(
        requested_url="https://example.com/article",
        resolved_url="https://example.com/article",
        title="Artículo rescatado",
        text=(
            "Texto extraído mediante URL context con suficiente longitud para validar "
            "la recuperación tras un fallo de acceso directo al sitio."
        ),
        content_type="text/html",
        extraction_method="gemini_url_context",
        metadata={"url_retrieval_statuses": ["URL_RETRIEVAL_STATUS_SUCCESS"]},
    )

    monkeypatch.setattr(
        "backend.url_extraction._extract_with_gemini_url_context",
        lambda **kwargs: (fallback_result, _usage(tool_prompt=2500)),
    )

    extracted, usage_meta = extract_web_content(
        "https://example.com/article",
        api_key="AIzaFakeKey",
        model=MODEL_AGENTS,
    )

    assert extracted.extraction_method == "gemini_url_context"
    assert usage_meta.tool_use_prompt_token_count == 2500


def test_calculate_cost_includes_tool_use_prompt_tokens():
    usage = {
        "prompt_token_count": 1_000,
        "tool_use_prompt_token_count": 9_000,
        "candidates_token_count": 2_000,
        "thoughts_token_count": 0,
    }
    cost = calculate_cost("gemini-3-flash-preview", usage)
    assert cost == 0.011


def test_process_project_web_routes_segmentador_and_agents_with_text_mime(monkeypatch):
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
        "source_metadata": {
            "title": "Artículo de ejemplo",
            "resolved_url": "https://example.com/article",
        },
        "status": "pending",
    }

    updates = []
    segmentador_calls = []
    explainer_calls = []
    recorrido_calls = []
    resources_calls = []

    monkeypatch.setattr(main, "get_project", lambda project_id, user_id, include_internal=False: project)
    monkeypatch.setattr(
        main,
        "get_user_api_key",
        lambda user_id, provider=None: "" if provider == main.PROVIDER_OPENROUTER else "AIzaFakeKey",
    )
    monkeypatch.setattr(main, "mask_api_key", lambda api_key: "AIza****")
    monkeypatch.setattr(main, "update_project", lambda project_id, user_id, payload: updates.append(payload))

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
        stem = os.path.splitext(os.path.basename(path))[0]
        return SimpleNamespace(uri=f"uploaded://{stem}", mime_type="text/plain")

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
                "evaluacion_fuente": {
                    "es_segmentable": True,
                    "motivo": "El texto extraído corresponde a contenido real y estudiable.",
                    "indicios": ["Desarrollo temático coherente", "Bloques con contenido sustantivo"],
                },
                "temas_identificados": ["tema principal"],
                "partes": [
                    {
                        "numero": 1,
                        "titulo": "Parte 1",
                        "contenido": "Contenido de la primera parte",
                        "identificacion": "Desde el bloque 1 hasta el bloque 1",
                        "bloque_inicio": 1,
                        "bloque_fin": 1,
                        "temas_cubiertos": ["tema principal"],
                        "extension_estimada": "media",
                        "complejidad": "media",
                        "expansion_prevista": "alta",
                    }
                ],
                "analisis_texto": "Texto corto",
                "decision_num_partes": 1,
                "decision_justificacion": "Una sola unidad temática",
                "consideraciones_estudiante": "Conviene estudiarlo de una vez",
            },
            _usage(),
        )

    def _fake_explainer(api_key, file_uri, agent_prompt, model, mime_type):
        explainer_calls.append(
            {"file_uri": file_uri, "mime_type": mime_type, "prompt": agent_prompt, "model": model}
        )
        return ({"ok": True}, _usage())

    def _fake_recorrido(api_key, file_uri, agent_prompt, model, mime_type):
        recorrido_calls.append({"file_uri": file_uri, "mime_type": mime_type, "model": model})
        return ({"ok": True}, _usage())

    def _fake_resources(api_key, file_uri, agent_prompt, model, mime_type):
        resources_calls.append({"file_uri": file_uri, "mime_type": mime_type, "model": model})
        return ({"ok": True}, _usage())

    monkeypatch.setattr(main, "run_segmentador", _fake_segmentador)
    monkeypatch.setattr(main, "run_explainer", _fake_explainer)
    monkeypatch.setattr(main, "run_recorrido", _fake_recorrido)
    monkeypatch.setattr(main, "run_resources", _fake_resources)

    asyncio.run(main._process_project("proj-web-1", "user-123"))

    assert segmentador_calls[0]["model"] == MODEL_SEGMENTADOR
    assert explainer_calls[0]["model"] == MODEL_AGENTS
    assert recorrido_calls[0]["model"] == MODEL_AGENTS
    assert resources_calls[0]["model"] == MODEL_AGENTS
    assert segmentador_calls[0]["mime_type"] == "text/plain"
    assert segmentador_calls[0]["source_kind"] == "text"
    assert explainer_calls[0]["mime_type"] == "text/plain"
    assert recorrido_calls[0]["mime_type"] == "text/plain"
    assert resources_calls[0]["mime_type"] == "text/plain"
    assert explainer_calls[0]["file_uri"] != segmentador_calls[0]["file_uri"]
    assert any(payload.get("status") == "completed" for payload in updates)


def test_process_project_web_aborts_when_segmentador_detects_bad_scrape(monkeypatch):
    project = {
        "id": "proj-web-bad-scrape",
        "name": "Artículo roto",
        "description": "",
        "pdf_filename": "Web: bad-scrape",
        "source_type": "web",
        "source_url": "https://example.com/challenge",
        "source_text": (
            "Texto de prueba que simula una extracción ruidosa para comprobar que el "
            "segmentador puede rechazarla antes de lanzar agentes downstream."
        ),
        "source_metadata": {
            "title": "Extracción dudosa",
            "resolved_url": "https://example.com/challenge",
        },
        "status": "pending",
    }

    updates = []
    events = []
    segmentador_calls = []
    explainer_calls = []
    recorrido_calls = []
    resources_calls = []

    monkeypatch.setattr(main, "get_project", lambda project_id, user_id, include_internal=False: project)
    monkeypatch.setattr(
        main,
        "get_user_api_key",
        lambda user_id, provider=None: "" if provider == main.PROVIDER_OPENROUTER else "AIzaFakeKey",
    )
    monkeypatch.setattr(main, "mask_api_key", lambda api_key: "AIza****")
    monkeypatch.setattr(main, "update_project", lambda project_id, user_id, payload: updates.append(payload))

    async def _send_event(project_id, payload):
        events.append(payload)
        return None

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
                "evaluacion_fuente": {
                    "es_segmentable": False,
                    "motivo": "El contenido parece un challenge anti-bot y no un artículo real.",
                    "indicios": [
                        "Predominio de boilerplate del sitio",
                        "Ausencia de cuerpo temático real",
                        "Señales de verificación humana",
                    ],
                },
                "temas_identificados": [],
                "partes": [],
                "analisis_texto": "El texto parece un scrape defectuoso sin contenido sustantivo.",
                "decision_num_partes": 0,
                "decision_justificacion": "No debe segmentarse porque no representa contenido real estudiable.",
                "consideraciones_estudiante": "Conviene abortar y no procesar esta URL.",
            },
            _usage(),
        )

    def _fake_explainer(api_key, file_uri, agent_prompt, model, mime_type):
        explainer_calls.append({"file_uri": file_uri, "mime_type": mime_type, "prompt": agent_prompt})
        return ({"ok": True}, _usage())

    def _fake_recorrido(api_key, file_uri, agent_prompt, model, mime_type):
        recorrido_calls.append({"file_uri": file_uri, "mime_type": mime_type})
        return ({"ok": True}, _usage())

    def _fake_resources(api_key, file_uri, agent_prompt, model, mime_type):
        resources_calls.append({"file_uri": file_uri, "mime_type": mime_type})
        return ({"ok": True}, _usage())

    monkeypatch.setattr(main, "run_segmentador", _fake_segmentador)
    monkeypatch.setattr(main, "run_explainer", _fake_explainer)
    monkeypatch.setattr(main, "run_recorrido", _fake_recorrido)
    monkeypatch.setattr(main, "run_resources", _fake_resources)

    asyncio.run(main._process_project("proj-web-bad-scrape", "user-123"))

    assert segmentador_calls[0]["model"] == MODEL_SEGMENTADOR
    assert segmentador_calls[0]["mime_type"] == "text/plain"
    assert segmentador_calls[0]["source_kind"] == "text"
    assert explainer_calls == []
    assert recorrido_calls == []
    assert resources_calls == []
    assert not any(payload.get("status") == "processing" for payload in updates)

    error_update = next(payload for payload in reversed(updates) if payload.get("status") == "error")
    assert error_update["partes_contenido"] == {}
    assert error_update["segmentation"]["evaluacion_fuente"]["es_segmentable"] is False
    assert error_update["source_metadata"]["segmentador_evaluacion_fuente"]["es_segmentable"] is False
    assert "scrape defectuoso" in error_update["error_message"].lower()
    assert any(event.get("type") == "error" for event in events)
