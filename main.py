"""Explainer API con autenticación Supabase y persistencia en Postgres + Storage."""

import asyncio
import concurrent.futures
import functools
import inspect
import json
import math
import os
import re
import time
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, AsyncGenerator, Literal
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(override=True)

from backend.logging_config import setup_logging, get_logger, set_context, clear_context, LogContext

from backend.auth import get_current_user_id, get_user_id_from_token
from backend.supabase_data import (
    create_project as supabase_create_project,
    get_project,
    get_project_by_share_token,
    create_share_token,
    revoke_share_token,
    list_projects_summary,
    update_project,
    delete_project,
    export_projects_payload,
    import_projects_payload,
    download_pdf_to_temp,
    get_user_api_key,
    set_user_api_key,
    delete_user_api_key,
    has_user_api_key,
    get_user_api_key_status,
    delete_project_source_object,
    list_projects_with_stored_source_objects,
    PROVIDER_GEMINI,
    PROVIDER_OPENROUTER,
    PROVIDER_MISTRAL,
    PROVIDER_DEEPSEEK,
    PROVIDER_TAVILY,
    SOURCE_OBJECT_STATUS_STORED,
)
from backend.crypto import mask_api_key
from backend.sse_manager import sse_manager, send_event
from backend.rate_limit import api_key_rate_limit, project_create_rate_limit
from backend.pricing import calculate_cost
from backend.gemini_model_routing import (
    MODEL_AGENTS,
    MODEL_CLASSIFIER,
    MODEL_EXPLAINER,
    MODEL_MERMAID,
    MODEL_SEGMENTADOR,
)

from backend.gemini_client import upload_file_with_retry, GeminiError, GeminiRateLimitError
from backend.agents.segmentador import DEFAULT_DESCRIPTION, run_segmentador, run_segmentador_ds, run_segmentador_or
from backend.agents.page_classifier import run_page_classifier, run_page_classifier_ds, run_page_classifier_or
from backend.segmentation_page_coverage import (
    MAX_PAGE_COVERAGE_ATTEMPTS,
    SEGMENTATION_PAGE_COVERAGE_USER_MESSAGE,
    build_page_coverage_retry_suffix,
    validate_page_coverage,
)
from pypdf import PdfReader
from backend.agents.explainer import (
    run_explainer_validated as run_explainer,
    run_subpart_explainer_validated as run_subpart_explainer,
)
from backend.agents.explainer_openrouter import (
    run_explainer_or_validated as run_explainer_or,
    run_subpart_explainer_or_validated as run_subpart_explainer_or,
    OPENROUTER_MODEL_AGENTS as OPENROUTER_EXPLAINER_MODEL,
    OPENROUTER_PDF_PARSER_ENGINE,
    OPENROUTER_PDF_PRIMING_MODEL,
    OPENROUTER_PDF_PRIMING_FALLBACK_MODEL,
)
from backend.agents.explainer_deepseek import (
    run_explainer_ds_validated as run_explainer_ds,
    run_subpart_explainer_ds_validated as run_subpart_explainer_ds,
)
from backend.agents.completeness_validator import (
    COMPLETENESS_VALIDATOR_MODEL,
    DEEPSEEK_COMPLETENESS_VALIDATOR_MODEL,
    OPENROUTER_COMPLETENESS_VALIDATOR_MODEL,
    ExplainerScopeItem,
    ExplainerSourceEvidence,
    ExplainerValidationContext,
    ExplainerValidationError,
)
from backend.agents.recorrido import run_recorrido, run_recorrido_ds, run_recorrido_or
from backend.agents.resources import run_resources, run_resources_ds, run_resources_or
from backend.agents.mermaid_agent import generate_mermaid, assemble_explanation_text
from backend.agents.formatter import format_explainer_content, format_explainer_content_ds, format_explainer_content_or
from backend.agents.language_policy import normalize_target_language
from backend.middleware import SecurityHeadersMiddleware, RequestLoggingMiddleware
from backend.openrouter_client import OpenRouterPdfParseCacheEntry
from backend.openrouter_model_routing import OPENROUTER_MODEL_AUXILIARY
from backend.deepseek_model_routing import (
    DEEPSEEK_EXPLAINER_MODELS,
    DEEPSEEK_MODEL_AUXILIARY,
    DEEPSEEK_MODEL_V4_FLASH,
    DEEPSEEK_MODEL_V4_PRO,
)
from backend.mistral_ocr_client import (
    MISTRAL_OCR_ENGINE,
    MISTRAL_OCR_MODEL,
    get_or_prime_mistral_pdf_ocr_cache,
)
from backend.pdf_ocr_cache import (
    PdfOcrCacheEntry,
    PdfOcrError,
    render_pdf_pages_with_xml_tags,
)
from backend.pdf_utils import add_page_numbers, extract_page_range
from backend.url_extraction import (
    WebExtractionError,
    build_text_blocks,
    extract_web_content,
    normalize_public_web_url,
    render_block_marked_document,
    slice_block_range,
    write_text_document_temp,
)
from backend.subpart_scope import (
    build_subpart_negative_scope_block,
    build_subpart_scope_contract_block,
)
from backend.project_progress import handle_update_section_progress, handle_update_subsection_progress


# Configurar logging al importar el módulo
setup_logging()
logger = get_logger("main")

# Max concurrent parts in the agent phase (prep + explainer/recorrido/resources); formatters run outside this limit.
MAX_CONCURRENT_PARTS = 5

ExplainerProvider = Literal["gemini", "openrouter", "deepseek"]
OpenRouterExplainerModel = str
DeepSeekExplainerModel = Literal["deepseek-v4-pro", "deepseek-v4-flash"]

EXPLAINER_PROVIDER_GEMINI: ExplainerProvider = "gemini"
EXPLAINER_PROVIDER_OPENROUTER: ExplainerProvider = "openrouter"
EXPLAINER_PROVIDER_DEEPSEEK: ExplainerProvider = "deepseek"
OPENROUTER_EXPLAINER_MODELS: frozenset[str] = frozenset(
    {
        "xiaomi/mimo-v2.5-pro",
        "xiaomi/mimo-v2.5",
        "deepseek/deepseek-v4-pro",
    }
)
INTERRUPTED_PDF_PROCESS_ERROR_MESSAGE = (
    "El procesamiento se interrumpió por un reinicio del servidor. "
    "Vuelve a subir el PDF para reintentarlo."
)
MISSING_PDF_SOURCE_ERROR_MESSAGE = (
    "El PDF original de este proyecto ya no está disponible. "
    "Vuelve a subirlo para reintentar el análisis."
)
ACTIVE_PROJECT_STATUSES = frozenset({"uploading", "segmenting", "processing"})


class ProcessProjectRequest(BaseModel):
    explainer_provider: ExplainerProvider = EXPLAINER_PROVIDER_GEMINI
    openrouter_model: OpenRouterExplainerModel | None = None
    target_language: str = "es-ES"
    deepseek_model: DeepSeekExplainerModel | None = None
    openrouter_provider: str | None = None
    openrouter_provider_only: bool = False


def _resolve_explainer_model(
    explainer_provider: ExplainerProvider,
    openrouter_model: OpenRouterExplainerModel | str | None = None,
    deepseek_model: DeepSeekExplainerModel | str | None = None,
) -> str:
    if explainer_provider == EXPLAINER_PROVIDER_OPENROUTER:
        if openrouter_model is None:
            return OPENROUTER_EXPLAINER_MODEL
        if not isinstance(openrouter_model, str):
            raise ValueError("Se requiere un modelo OpenRouter")
        model = openrouter_model.strip()
        if not model:
            raise ValueError("Se requiere un modelo OpenRouter")
        if not re.fullmatch(r"[\w.-]+/[\w.:-]+", model):
            raise ValueError(f"Modelo OpenRouter inválido: '{model}'. Debe tener formato 'org/modelo'")
        if len(model) > 128:
            raise ValueError(f"Modelo OpenRouter demasiado largo: {len(model)} caracteres")
        return model
    if explainer_provider == EXPLAINER_PROVIDER_DEEPSEEK:
        if deepseek_model:
            model = str(deepseek_model).strip()
            if model not in DEEPSEEK_EXPLAINER_MODELS:
                raise ValueError(f"Modelo DeepSeek no soportado: {model}")
            return model
        return DEEPSEEK_MODEL_V4_PRO
    return MODEL_AGENTS


def _build_openrouter_provider_routing(provider: str | None, only: bool) -> dict | None:
    if not provider or not isinstance(provider, str):
        return None
    slug = provider.strip().lower()
    if not slug:
        return None
    if not re.fullmatch(r"[\w.-]+", slug):
        return None
    if len(slug) > 64:
        return None
    routing: dict = {"order": [slug]}
    if only:
        routing["allow_fallbacks"] = False
    return routing


def _reconcile_stored_pdf_sources_on_startup() -> None:
    """Converge leftover source PDFs after deploys/restarts.

    BackgroundTasks are process-local, so an app restart can leave PDF objects in
    Supabase Storage even though the job can no longer resume. We mark interrupted
    jobs as error and retry storage cleanup idempotently on every startup.
    """
    try:
        projects = list_projects_with_stored_source_objects()
    except Exception as exc:
        logger.warning("[Startup] No se pudo listar PDFs pendientes de cleanup: %s", exc)
        return

    for project in projects:
        project_id = project.get("id")
        user_id = project.get("user_id")
        status = project.get("status")
        if not project_id or not user_id:
            continue
        if status == "pending":
            continue
        if status in ACTIVE_PROJECT_STATUSES:
            update_project(
                project_id,
                user_id,
                {
                    "status": "error",
                    "error_message": INTERRUPTED_PDF_PROCESS_ERROR_MESSAGE,
                },
            )
        try:
            delete_project_source_object(project_id, user_id, project=project)
            logger.info(
                "[Startup] PDF fuente reconciliado y eliminado",
                extra={"project_id": project_id, "status": status},
            )
        except Exception as exc:
            logger.warning(
                "[Startup] No se pudo eliminar el PDF fuente pendiente (project_id=%s): %s",
                project_id,
                exc,
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=64,
        thread_name_prefix="explainer-worker",
    )
    loop = asyncio.get_event_loop()
    loop.set_default_executor(executor)
    logger.info(
        "[Startup] Explainer API iniciada - Persistencia en Supabase "
        "(ThreadPoolExecutor max_workers=64)"
    )
    await asyncio.to_thread(_reconcile_stored_pdf_sources_on_startup)
    try:
        yield
    finally:
        executor.shutdown(wait=False)
        logger.info("[Shutdown] Cerrando aplicación y ThreadPoolExecutor")


app = FastAPI(title="Explainer API", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

def _validate_gemini_api_key(api_key: str) -> str:
    """Validate and normalize Gemini API key. Raises HTTPException on invalid input."""
    key = (api_key or "").strip()
    if not key.startswith("AIza") or len(key) < 20 or len(key) > 64:
        raise HTTPException(status_code=400, detail="API key de Gemini inválida")
    return key


def _validate_openrouter_api_key(api_key: str) -> str:
    """Validate and normalize OpenRouter API key. Raises HTTPException on invalid input."""
    key = (api_key or "").strip()
    if not key.startswith("sk-or-") or len(key) < 20 or len(key) > 200:
        raise HTTPException(status_code=400, detail="API key de OpenRouter inválida (debe empezar por sk-or-)")
    return key


def _validate_mistral_api_key(api_key: str) -> str:
    """Validate and normalize Mistral API key. Raises HTTPException on invalid input."""
    key = (api_key or "").strip()
    if len(key) < 20 or len(key) > 300 or any(ch.isspace() for ch in key):
        raise HTTPException(status_code=400, detail="API key de Mistral inválida")
    return key


def _validate_deepseek_api_key(api_key: str) -> str:
    """Validate and normalize DeepSeek API key. Raises HTTPException on invalid input."""
    key = (api_key or "").strip()
    if len(key) < 20 or len(key) > 300 or any(ch.isspace() for ch in key):
        raise HTTPException(status_code=400, detail="API key de DeepSeek inválida")
    return key


def _validate_tavily_api_key(api_key: str) -> str:
    """Validate and normalize Tavily API key. Raises HTTPException on invalid input."""
    key = (api_key or "").strip()
    if not key.startswith("tvly-") or len(key) < 20 or len(key) > 300 or any(ch.isspace() for ch in key):
        raise HTTPException(status_code=400, detail="API key de Tavily inválida (debe empezar por tvly-)")
    return key


# ---- Gemini key endpoints ----

@app.post("/api/settings/api-key")
@api_key_rate_limit
async def api_set_api_key(
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
    api_key: str = Form(...),
):
    """Store user's Gemini API key (BYOK)."""
    api_key = _validate_gemini_api_key(api_key)
    set_user_api_key(user_id, api_key, provider=PROVIDER_GEMINI)
    logger.info("[API Key] User %s... configured Gemini key: %s", user_id[:8], mask_api_key(api_key))
    return {"ok": True}


@app.delete("/api/settings/api-key")
@api_key_rate_limit
async def api_delete_api_key(
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
):
    """Delete user's Gemini API key."""
    delete_user_api_key(user_id, provider=PROVIDER_GEMINI)
    logger.info("[API Key] User %s... deleted Gemini key", user_id[:8])
    return {"ok": True}


# ---- OpenRouter key endpoints ----

@app.post("/api/settings/api-key/openrouter")
@api_key_rate_limit
async def api_set_openrouter_key(
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
    api_key: str = Form(...),
):
    """Store user's OpenRouter API key (BYOK)."""
    api_key = _validate_openrouter_api_key(api_key)
    set_user_api_key(user_id, api_key, provider=PROVIDER_OPENROUTER)
    logger.info("[API Key] User %s... configured OpenRouter key: %s", user_id[:8], mask_api_key(api_key))
    return {"ok": True}


@app.delete("/api/settings/api-key/openrouter")
@api_key_rate_limit
async def api_delete_openrouter_key(
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
):
    """Delete user's OpenRouter API key."""
    delete_user_api_key(user_id, provider=PROVIDER_OPENROUTER)
    logger.info("[API Key] User %s... deleted OpenRouter key", user_id[:8])
    return {"ok": True}


# ---- Mistral key endpoints ----

@app.post("/api/settings/api-key/mistral")
@api_key_rate_limit
async def api_set_mistral_key(
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
    api_key: str = Form(...),
):
    """Store user's Mistral API key (BYOK)."""
    api_key = _validate_mistral_api_key(api_key)
    set_user_api_key(user_id, api_key, provider=PROVIDER_MISTRAL)
    logger.info("[API Key] User %s... configured Mistral key: %s", user_id[:8], mask_api_key(api_key))
    return {"ok": True}


@app.delete("/api/settings/api-key/mistral")
@api_key_rate_limit
async def api_delete_mistral_key(
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
):
    """Delete user's Mistral API key."""
    delete_user_api_key(user_id, provider=PROVIDER_MISTRAL)
    logger.info("[API Key] User %s... deleted Mistral key", user_id[:8])
    return {"ok": True}


# ---- DeepSeek key endpoints ----

@app.post("/api/settings/api-key/deepseek")
@api_key_rate_limit
async def api_set_deepseek_key(
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
    api_key: str = Form(...),
):
    """Store user's DeepSeek API key (BYOK)."""
    api_key = _validate_deepseek_api_key(api_key)
    set_user_api_key(user_id, api_key, provider=PROVIDER_DEEPSEEK)
    logger.info("[API Key] User %s... configured DeepSeek key: %s", user_id[:8], mask_api_key(api_key))
    return {"ok": True}


@app.delete("/api/settings/api-key/deepseek")
@api_key_rate_limit
async def api_delete_deepseek_key(
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
):
    """Delete user's DeepSeek API key."""
    delete_user_api_key(user_id, provider=PROVIDER_DEEPSEEK)
    logger.info("[API Key] User %s... deleted DeepSeek key", user_id[:8])
    return {"ok": True}


# ---- Tavily key endpoints ----

@app.post("/api/settings/api-key/tavily")
@api_key_rate_limit
async def api_set_tavily_key(
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
    api_key: str = Form(...),
):
    """Store user's Tavily API key (BYOK)."""
    api_key = _validate_tavily_api_key(api_key)
    set_user_api_key(user_id, api_key, provider=PROVIDER_TAVILY)
    logger.info("[API Key] User %s... configured Tavily key: %s", user_id[:8], mask_api_key(api_key))
    return {"ok": True}


@app.delete("/api/settings/api-key/tavily")
@api_key_rate_limit
async def api_delete_tavily_key(
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
):
    """Delete user's Tavily API key."""
    delete_user_api_key(user_id, provider=PROVIDER_TAVILY)
    logger.info("[API Key] User %s... deleted Tavily key", user_id[:8])
    return {"ok": True}


# ---- Status (all providers) ----

@app.get("/api/settings/api-key/status")
async def api_api_key_status(user_id: Annotated[str, Depends(get_current_user_id)]):
    """Get API key status for all providers."""
    return get_user_api_key_status(user_id)


def _extract_youtube_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""

    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$',  # Just the video ID
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _is_valid_youtube_url(url: str) -> bool:
    """Check if URL is a valid YouTube video URL."""
    return _extract_youtube_video_id(url) is not None


def _normalize_web_source_url(url: str) -> str:
    """Validate and normalize a public web URL."""
    return normalize_public_web_url(url)


@app.post("/api/projects")
@project_create_rate_limit
async def api_create_project(
    user_id: Annotated[str, Depends(get_current_user_id)],
    name: str = Form(...),
    description: str = Form(""),
    file: UploadFile | None = File(None),
    youtube_url: str | None = Form(None),
    web_url: str | None = Form(None),
):
    """Create a project from a PDF upload, a YouTube URL, or a public web URL."""

    normalized_youtube = (youtube_url or "").strip() or None
    normalized_web = (web_url or "").strip() or None

    provided_sources = [
        bool(file),
        bool(normalized_youtube),
        bool(normalized_web),
    ]
    if sum(provided_sources) > 1:
        raise HTTPException(
            status_code=400,
            detail="Proporciona solo una fuente: un PDF, una URL de YouTube o una URL web.",
        )

    if sum(provided_sources) == 0:
        raise HTTPException(
            status_code=400,
            detail="Debes proporcionar un archivo PDF, una URL de YouTube o una URL web.",
        )

    if file:
        # PDF source
        pdf_filename = file.filename or "documento.pdf"
        pdf_content = await file.read()
        project = supabase_create_project(
            user_id=user_id,
            name=name,
            description=description,
            pdf_filename=pdf_filename,
            pdf_content=pdf_content,
            source_type="pdf",
            source_url=None,
        )
    elif normalized_youtube:
        # YouTube source
        if not _is_valid_youtube_url(normalized_youtube):
            raise HTTPException(status_code=400, detail="URL de YouTube inválida. Usa formato: https://www.youtube.com/watch?v=VIDEO_ID")

        video_id = _extract_youtube_video_id(normalized_youtube)
        pdf_filename = f"YouTube: {video_id}"

        project = supabase_create_project(
            user_id=user_id,
            name=name,
            description=description,
            pdf_filename=pdf_filename,
            pdf_content=None,
            source_type="youtube",
            source_url=normalized_youtube,
        )
    else:
        try:
            validated_web_url = _normalize_web_source_url(normalized_web or "")
        except WebExtractionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        parsed = urlparse(validated_web_url)
        source_label = parsed.netloc or "web"
        pdf_filename = f"Web: {source_label}"

        project = supabase_create_project(
            user_id=user_id,
            name=name,
            description=description,
            pdf_filename=pdf_filename,
            pdf_content=None,
            source_type="web",
            source_url=validated_web_url,
        )

    return project


@app.get("/api/projects")
async def api_list_projects(user_id: Annotated[str, Depends(get_current_user_id)]):
    return list_projects_summary(user_id)


@app.get("/api/projects/export")
async def api_export_projects(user_id: Annotated[str, Depends(get_current_user_id)]):
    return export_projects_payload(user_id)


@app.post("/api/projects/import")
async def api_import_projects(
    user_id: Annotated[str, Depends(get_current_user_id)],
    file: UploadFile = File(...),
):
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Debes subir un archivo JSON")
    raw = await file.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
        result = import_projects_payload(user_id, payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Backup inválido: {exc}") from exc
    return {"ok": True, **result}


@app.get("/api/projects/{project_id}")
async def api_get_project(
    user_id: Annotated[str, Depends(get_current_user_id)],
    project_id: str,
):
    project = get_project(project_id, user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return project


@app.get("/api/shared/{share_token}")
async def api_get_shared_project(share_token: str):
    """Public endpoint: get sanitized project by share token. No auth required."""
    project = get_project_by_share_token(share_token)
    if not project:
        raise HTTPException(status_code=404, detail="Enlace no válido o expirado")
    return project


@app.post("/api/projects/{project_id}/share")
async def api_create_share(
    user_id: Annotated[str, Depends(get_current_user_id)],
    project_id: str,
):
    """Create share link for a completed project. Returns share_token and share_url."""
    token = create_share_token(project_id, user_id)
    if not token:
        project = get_project(project_id, user_id)
        if not project:
            raise HTTPException(status_code=404, detail="Proyecto no encontrado")
        if project.get("status") != "completed":
            raise HTTPException(status_code=400, detail="Solo se pueden compartir proyectos completados")
        raise HTTPException(status_code=400, detail="No se pudo crear el enlace")
    base = os.environ.get("FRONTEND_URL", "http://localhost:3000").rstrip("/")
    share_url = f"{base}/#/s/{token}"
    return {"share_token": token, "share_url": share_url}


@app.delete("/api/projects/{project_id}/share")
async def api_revoke_share(
    user_id: Annotated[str, Depends(get_current_user_id)],
    project_id: str,
):
    """Revoke share link for a project."""
    if not get_project(project_id, user_id):
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    revoke_share_token(project_id, user_id)
    return {"ok": True}


@app.patch("/api/projects/{project_id}/progress")
async def api_update_progress(
    user_id: Annotated[str, Depends(get_current_user_id)],
    project_id: str,
    body: dict = Body(...),
):
    """Mark or unmark a section as read. Body: { "part_id": 3, "completed": true|false }.
    If completed is omitted, defaults to True (mark as read)."""
    return handle_update_section_progress(user_id, project_id, body)


@app.patch("/api/projects/{project_id}/progress/subsection")
async def api_update_subsection_progress(
    user_id: Annotated[str, Depends(get_current_user_id)],
    project_id: str,
    body: dict = Body(...),
):
    """Update subsection progress. Body: {
        subsection_id: str, part_id: int,
        completed?: bool, is_last_read?: bool
    }."""
    return handle_update_subsection_progress(user_id, project_id, body)


@app.delete("/api/projects/{project_id}")
async def api_delete_project(
    user_id: Annotated[str, Depends(get_current_user_id)],
    project_id: str,
):
    if not get_project(project_id, user_id):
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    delete_project(project_id, user_id)
    return {"ok": True}


def _build_content_pages_prefix(content_page_set: frozenset[int], total_pages: int) -> str:
    """Build the <paginas_contenido_verificado> block injected into the segmentador prompt."""
    if not content_page_set:
        return ""
    sorted_pages = sorted(content_page_set)
    ranges: list[str] = []
    start = prev = sorted_pages[0]
    for p in sorted_pages[1:]:
        if p == prev + 1:
            prev = p
        else:
            ranges.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = p
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    content_str = ", ".join(ranges)

    non_content = sorted(set(range(1, total_pages + 1)) - content_page_set)
    if non_content:
        nc_ranges: list[str] = []
        s = pr = non_content[0]
        for p in non_content[1:]:
            if p == pr + 1:
                pr = p
            else:
                nc_ranges.append(f"{s}-{pr}" if s != pr else str(s))
                s = pr = p
        nc_ranges.append(f"{s}-{pr}" if s != pr else str(s))
        non_content_str = f"\nPáginas sin contenido (accesorias, pueden excluirse): {', '.join(nc_ranges)}"
    else:
        non_content_str = ""

    return (
        "<paginas_contenido_verificado>\n"
        f"Páginas con contenido sustantivo (DEBEN cubrirse): {content_str}{non_content_str}\n"
        f"Primera página de contenido (la primera parte DEBE empezar aquí o antes): {sorted_pages[0]}\n"
        f"Última página de contenido (la última parte DEBE terminar aquí o después): {sorted_pages[-1]}\n"
        "RESTRICCIÓN OBLIGATORIA: Los rangos pagina_inicio/pagina_fin de las partes deben cubrir "
        "colectivamente TODAS las páginas de contenido, sin huecos ni solapamientos entre partes. "
        "Las subpartes de cada parte deben ser contiguas y cubrir exactamente el rango de su parte padre.\n"
        "</paginas_contenido_verificado>\n\n"
    )


def _build_pdf_table_of_contents(segmentation: dict, num_partes: int) -> str:
    toc_lines = ["TABLA DE CONTENIDOS DEL DOCUMENTO COMPLETO:"]
    for p in segmentation["partes"]:
        pg_start = p.get("pagina_inicio", "?")
        pg_end = p.get("pagina_fin", "?")
        toc_lines.append(
            f"  Parte {p['numero']}/{num_partes}: \"{p['titulo']}\" (Páginas {pg_start}-{pg_end})"
        )
    return "\n".join(toc_lines)


def _select_openrouter_pdf_pages(
    content_page_set: frozenset[int],
    *,
    start_page: int | None,
    end_page: int | None,
    buffer: int = 1,
) -> tuple[int, ...]:
    """Select the exact original-page subset that OpenRouter should see.

    Selection is always constrained to substantive-content pages discovered by
    the classifier. When no explicit page range is available, the whole
    OCR-cached content-page set is used.
    """
    if not content_page_set:
        return ()

    ordered_pages = tuple(sorted(content_page_set))
    if start_page is None or end_page is None:
        return ordered_pages

    lower = start_page - max(buffer, 0)
    upper = end_page + max(buffer, 0)
    return tuple(page for page in ordered_pages if lower <= page <= upper)


@dataclass(frozen=True, slots=True)
class OpenRouterPreparedPdfContext:
    source_pdf_path: str
    cache_entry: OpenRouterPdfParseCacheEntry
    priming_model: str = OPENROUTER_PDF_PRIMING_MODEL


@dataclass(frozen=True, slots=True)
class PreparedPdfOcrContext:
    source_pdf_path: str
    cache_entry: PdfOcrCacheEntry
    ocr_model: str = MISTRAL_OCR_MODEL


def _prepare_mistral_pdf_ocr_context(
    *,
    source_path: str,
    content_page_set: frozenset[int],
    api_key: str,
    engine: str,
) -> "PreparedPdfOcrContext":
    """Prepare Mistral native OCR cache for the content pages of a PDF.

    The cache is keyed by the source document itself, not by a reconstructed
    per-run subset PDF. This allows future executions to reuse already
    processed pages even if the classifier adds or removes pages.
    """
    cache_entry = get_or_prime_mistral_pdf_ocr_cache(
        source_path=source_path,
        api_key=api_key,
        model=MISTRAL_OCR_MODEL,
        engine=engine,
        filename="document.pdf",
        expected_page_numbers=tuple(sorted(content_page_set)),
    )
    return PreparedPdfOcrContext(
        source_pdf_path=source_path,
        cache_entry=cache_entry,
        ocr_model=MISTRAL_OCR_MODEL,
    )


def _render_mistral_ocr_pages_for_agents(
    *,
    cache_entry: PdfOcrCacheEntry,
    page_numbers: tuple[int, ...] | list[int],
) -> str:
    """Render cached OCR pages with XML page boundary tags for OpenRouter agents."""
    pages = tuple(int(page) for page in page_numbers)
    if not pages:
        raise PdfOcrError("No se proporcionaron páginas OCR para el agente OpenRouter.")
    return render_pdf_pages_with_xml_tags(cache_entry=cache_entry, page_numbers=pages)


def _build_text_table_of_contents(segmentation: dict, num_partes: int) -> str:
    toc_lines = ["TABLA DE CONTENIDOS DEL TEXTO COMPLETO:"]
    for p in segmentation["partes"]:
        block_start = p.get("bloque_inicio", "?")
        block_end = p.get("bloque_fin", "?")
        toc_lines.append(
            f"  Parte {p['numero']}/{num_partes}: \"{p['titulo']}\" (Bloques {block_start}-{block_end})"
        )
    return "\n".join(toc_lines)


def _build_youtube_table_of_contents(segmentation: dict, num_partes: int) -> str:
    toc_lines = ["TABLA DE CONTENIDOS DEL MATERIAL (fuente audiovisual):"]
    for p in segmentation["partes"]:
        toc_lines.append(f"  Parte {p['numero']}/{num_partes}: \"{p['titulo']}\"")
    return "\n".join(toc_lines)


def _optional_int(parte: dict, key: str) -> int | None:
    v = parte.get(key)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _strip_str(value: object | None) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


@dataclass(frozen=True, slots=True)
class PartHandoffContext:
    """Structured segmentador output passed to downstream agents for coverage and continuity."""

    titulo: str
    resumen_alcance: str
    intent_usuario: str | None
    continuidad_previa: str | None
    vision_global_division: str | None


def _part_handoff_base(
    parte: dict,
    *,
    intent_usuario: str | None,
    continuidad_previa: str | None,
    vision_global_division: str | None,
) -> PartHandoffContext:
    num = parte.get("numero")
    titulo = str(parte.get("titulo") or "").strip() or (f"Parte {num}" if num is not None else "Parte")
    resumen = str(parte.get("contenido") or "").strip()
    return PartHandoffContext(
        titulo=titulo,
        resumen_alcance=resumen,
        intent_usuario=intent_usuario,
        continuidad_previa=continuidad_previa,
        vision_global_division=vision_global_division,
    )


def _continuity_block_from_previous_part(prev: dict) -> str:
    """Use segmentador summaries only (no explainer output required)."""
    lines: list[str] = []
    t = str(prev.get("titulo") or "").strip()
    if t:
        lines.append(f"Módulo anterior en el temario: «{t}».")
    body = str(prev.get("contenido") or "").strip()
    if body:
        lines.append("Alcance que el segmentador asignó a ese módulo (orientación, no sustituye al texto fuente):")
        lines.append(body)
    return "\n".join(lines) if lines else ""


def _find_parte_by_numero(partes: list[dict], numero: int) -> dict | None:
    for p in partes:
        if p.get("numero") == numero:
            return p
    return None


def _adjacent_subparts_for_audit(
    *,
    partes_segmentadas: list[dict],
    current_parte: dict,
    subpart_idx: int,
) -> tuple[dict | None, dict | None]:
    """Return previous/next subpart for auditing, crossing part boundaries when needed.

    Resolution order:
    1) Neighbor inside the same part.
    2) Nearest previous/next part (by segmentation order) that contains subparts.
    """
    current_subpartes = current_parte.get("subpartes") or []
    previous_sp = current_subpartes[subpart_idx - 1] if subpart_idx > 0 else None
    next_sp = current_subpartes[subpart_idx + 1] if subpart_idx + 1 < len(current_subpartes) else None

    if previous_sp is not None and next_sp is not None:
        return previous_sp, next_sp

    part_pos = next((i for i, p in enumerate(partes_segmentadas) if p is current_parte), -1)
    if part_pos < 0:
        current_num = current_parte.get("numero")
        part_pos = next(
            (i for i, p in enumerate(partes_segmentadas) if p.get("numero") == current_num),
            -1,
        )
    if part_pos < 0:
        return previous_sp, next_sp

    if previous_sp is None:
        for pos in range(part_pos - 1, -1, -1):
            candidate_subparts = partes_segmentadas[pos].get("subpartes") or []
            if candidate_subparts:
                previous_sp = candidate_subparts[-1]
                break

    if next_sp is None:
        for pos in range(part_pos + 1, len(partes_segmentadas)):
            candidate_subparts = partes_segmentadas[pos].get("subpartes") or []
            if candidate_subparts:
                next_sp = candidate_subparts[0]
                break

    return previous_sp, next_sp


def _item_number(value: object, total: int | None = None) -> str:
    if value is None:
        return ""
    base = str(value).strip()
    if not base:
        return ""
    return f"{base}/{total}" if total else base


def _scope_anchors_from_subpart(subparte: dict) -> tuple[str, ...]:
    raw = subparte.get("delimitacion_explainer") or {}
    if not isinstance(raw, dict):
        return ()
    inicio = raw.get("inicio") or {}
    fin = raw.get("fin") or {}
    transicion = raw.get("transicion_compartida") or {}
    anchors: list[str] = []
    for value in (
        inicio.get("encabezado") if isinstance(inicio, dict) else None,
        inicio.get("ancla_texto") if isinstance(inicio, dict) else None,
        fin.get("ancla_texto") if isinstance(fin, dict) else None,
        fin.get("encabezado_siguiente_excluido") if isinstance(fin, dict) else None,
        transicion.get("hasta_texto_inclusive") if isinstance(transicion, dict) else None,
        transicion.get("desde_texto_inclusive") if isinstance(transicion, dict) else None,
    ):
        normalized = str(value or "").strip()
        if normalized:
            anchors.append(normalized)
    return tuple(anchors)


def _scope_item_from_part(parte: dict, *, total_parts: int | None = None) -> ExplainerScopeItem:
    return ExplainerScopeItem(
        kind="part",
        number=_item_number(parte.get("numero"), total_parts),
        title=str(parte.get("titulo") or "").strip(),
        content=str(parte.get("contenido") or "").strip(),
        identification=str(parte.get("identificacion") or "").strip(),
        page_start=_optional_int(parte, "pagina_inicio"),
        page_end=_optional_int(parte, "pagina_fin"),
        block_start=_optional_int(parte, "bloque_inicio"),
        block_end=_optional_int(parte, "bloque_fin"),
    )


def _scope_item_from_subpart(subparte: dict | None, *, total_subparts: int | None = None) -> ExplainerScopeItem | None:
    if subparte is None:
        return None
    return ExplainerScopeItem(
        kind="subpart",
        number=_item_number(subparte.get("numero_subparte"), total_subparts),
        title=str(subparte.get("titulo") or "").strip(),
        content=str(subparte.get("contenido") or "").strip(),
        identification=str(subparte.get("identificacion") or "").strip(),
        anchors=_scope_anchors_from_subpart(subparte),
        page_start=_optional_int(subparte, "pagina_inicio"),
        page_end=_optional_int(subparte, "pagina_fin"),
        block_start=_optional_int(subparte, "bloque_inicio"),
        block_end=_optional_int(subparte, "bloque_fin"),
    )


def _build_subpart_validation_context(
    *,
    partes_segmentadas: list[dict],
    current_parte: dict,
    subpart_idx: int,
) -> ExplainerValidationContext:
    subpartes = current_parte.get("subpartes") or []
    current_subpart = subpartes[subpart_idx]
    previous_sp, next_sp = _adjacent_subparts_for_audit(
        partes_segmentadas=partes_segmentadas,
        current_parte=current_parte,
        subpart_idx=subpart_idx,
    )
    return ExplainerValidationContext(
        scope_kind="subpart",
        current=_scope_item_from_subpart(current_subpart, total_subparts=len(subpartes)) or ExplainerScopeItem(
            kind="subpart",
            title="",
        ),
        parent=_scope_item_from_part(current_parte, total_parts=len(partes_segmentadas)),
        previous_neighbor=_scope_item_from_subpart(previous_sp),
        next_neighbor=_scope_item_from_subpart(next_sp),
    )


def _build_part_validation_context(
    *,
    partes_segmentadas: list[dict],
    current_parte: dict,
) -> ExplainerValidationContext:
    part_pos = next((i for i, p in enumerate(partes_segmentadas) if p is current_parte), -1)
    if part_pos < 0:
        current_num = current_parte.get("numero")
        part_pos = next((i for i, p in enumerate(partes_segmentadas) if p.get("numero") == current_num), -1)

    if part_pos < 0:
        previous_part = None
        next_part = None
    else:
        previous_part = partes_segmentadas[part_pos - 1] if part_pos > 0 else None
        next_part = partes_segmentadas[part_pos + 1] if part_pos + 1 < len(partes_segmentadas) else None
    return ExplainerValidationContext(
        scope_kind="part",
        current=_scope_item_from_part(current_parte, total_parts=len(partes_segmentadas)),
        previous_neighbor=_scope_item_from_part(previous_part, total_parts=len(partes_segmentadas)) if previous_part else None,
        next_neighbor=_scope_item_from_part(next_part, total_parts=len(partes_segmentadas)) if next_part else None,
    )


def _with_validation_source_evidence(
    context: ExplainerValidationContext,
    source_evidence: ExplainerSourceEvidence | None,
) -> ExplainerValidationContext:
    if source_evidence is None:
        return context
    return ExplainerValidationContext(
        scope_kind=context.scope_kind,
        current=context.current,
        parent=context.parent,
        previous_neighbor=context.previous_neighbor,
        next_neighbor=context.next_neighbor,
        source_evidence=source_evidence,
    )


def _scope_pages_from_item(item: ExplainerScopeItem) -> tuple[int, ...]:
    if item.page_start is None or item.page_end is None or item.page_start > item.page_end:
        return ()
    return tuple(range(item.page_start, item.page_end + 1))


def _select_validation_ocr_pages(
    content_page_set: frozenset[int],
    item: ExplainerScopeItem,
) -> tuple[int, ...]:
    if item.page_start is None or item.page_end is None or item.page_start > item.page_end:
        return ()
    if not content_page_set:
        return ()
    return tuple(
        page
        for page in sorted(content_page_set)
        if item.page_start <= page <= item.page_end
    )


def _build_mistral_ocr_validation_evidence(
    *,
    cache_entry: PdfOcrCacheEntry,
    content_page_set: frozenset[int],
    context: ExplainerValidationContext,
    explainer_pages: tuple[int, ...] | list[int] = (),
) -> ExplainerSourceEvidence | None:
    # El validador debe ver EXACTAMENTE las mismas páginas (incluido el buffer) que
    # recibió el explainer; así no puede marcar como fuera de alcance contenido que el
    # explainer tenía legítimamente en su fuente. Solo si no hay ventana del explainer
    # (p. ej. documentos sin clasificación de páginas) se cae al rango núcleo de la unidad.
    if explainer_pages:
        pages = tuple(sorted({int(page) for page in explainer_pages}))
    else:
        pages = _select_validation_ocr_pages(content_page_set, context.current)
    if not pages:
        return None
    try:
        # Mismo render con etiquetas <pagina_N> que usa el explainer, para que el bloque
        # OCR del validador sea byte-equivalente al de la generación que evalúa.
        source_text = render_pdf_pages_with_xml_tags(
            cache_entry=cache_entry,
            page_numbers=pages,
        )
    except PdfOcrError as exc:
        logger.warning(
            "[Process] No se pudo reutilizar OCR Mistral para validar alcance: %s",
            exc,
            extra={"error_type": type(exc).__name__, "pages": pages},
        )
        return None
    return ExplainerSourceEvidence(
        kind="ocr_text",
        label="OCR Mistral: mismas páginas exactas que recibió el explainer",
        text=source_text,
        pages=pages,
        note=(
            "Ventana de páginas idéntica a la del explainer (incluye buffer si lo hubo); "
            "delimitada por etiquetas <pagina_N>. No se relanza OCR."
        ),
    )


def _build_gemini_file_validation_evidence(
    *,
    file_uri: str,
    mime_type: str,
    context: ExplainerValidationContext,
) -> ExplainerSourceEvidence | None:
    if not file_uri or not mime_type:
        return None
    return ExplainerSourceEvidence(
        kind="gemini_file",
        label="Archivo PDF reutilizado por Files API de Gemini",
        file_uri=file_uri,
        mime_type=mime_type,
        pages=_scope_pages_from_item(context.current),
        note=(
            "Es el mismo archivo enviado a los agentes; puede incluir buffer o la parte completa, "
            "por lo que el validador debe aplicar las paginas/anclas del contrato actual."
        ),
    )


def _call_agent_with_optional_validation_context(
    fn: Callable[..., Any],
    *args: Any,
    validation_context: ExplainerValidationContext | None,
    target_language: str = "es-ES",
) -> Any:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(*args, validation_context=validation_context, target_language=target_language)

    accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values())
    call_kwargs: dict[str, Any] = {}
    if accepts_kwargs or "validation_context" in signature.parameters:
        call_kwargs["validation_context"] = validation_context
    if accepts_kwargs or "target_language" in signature.parameters:
        call_kwargs["target_language"] = target_language
    return fn(*args, **call_kwargs)


def _unpack_explainer_result(sp_result: Any) -> tuple[dict, Any, list[Any]]:
    if not isinstance(sp_result, (tuple, list)):
        raise RuntimeError("Resultado de explainer inválido: se esperaba una tupla.")
    if len(sp_result) == 3:
        data, usage, validator_usages = sp_result
        return data, usage, list(validator_usages or [])
    if len(sp_result) == 2:
        data, usage = sp_result
        return data, usage, []
    raise RuntimeError(f"Resultado de explainer inválido: tupla de longitud {len(sp_result)}.")


def _assemble_part_explainer(
    parte: dict,
    subpart_desarrollos: list[list[dict]],
) -> dict:
    """Assemble the final explainer dict for a part.

    - introduccion, conclusion, conexiones_contextuales come from the segmentador
      (which has global document vision).
    - desarrollo sections are concatenated from all subpart explainer outputs in order.
    """
    desarrollo_merged: list[dict] = []
    for sp_desarrollo in subpart_desarrollos:
        desarrollo_merged.extend(sp_desarrollo)

    return {
        "introduccion": parte.get("introduccion", ""),
        "desarrollo": desarrollo_merged,
        "conclusion": parte.get("conclusion", ""),
        "conexiones_contextuales": parte.get("conexiones_contextuales") or [],
    }
def _format_handoff_section(ctx: PartHandoffContext, *, part_id: int, num_partes: int) -> str:
    blocks: list[str] = []
    blocks.append("CONTEXTO DEL SEGMENTADOR Y DEL USUARIO")
    blocks.append(
        "Lo siguiente resume decisiones ya tomadas sobre este documento. "
        "La fuente de verdad sigue siendo el archivo adjunto y la identificación textual; "
        "usa este bloque como contrato de alcance y hilo conductor."
    )

    if ctx.intent_usuario:
        blocks.append("")
        blocks.append("Preferencias o instrucciones del usuario (aplicar siempre que sean compatibles con el texto fuente):")
        blocks.append(ctx.intent_usuario)

    if ctx.vision_global_division:
        blocks.append("")
        blocks.append("Visión global de la división didáctica (segmentador):")
        blocks.append(ctx.vision_global_division)

    if ctx.continuidad_previa:
        blocks.append("")
        blocks.append(f"Continuidad respecto a la parte {part_id - 1}/{num_partes}:")
        blocks.append(ctx.continuidad_previa)

    blocks.append("")
    blocks.append(f"Parte actual — título asignado por el segmentador: «{ctx.titulo}».")

    if ctx.resumen_alcance:
        blocks.append("")
        blocks.append("Alcance declarado de esta parte (segmentador):")
        blocks.append(ctx.resumen_alcance)

    return "\n".join(blocks)


def _pdf_scope_instructions(
    *,
    mode: Literal["subpdf_buffered", "full_document"],
    part_id: int,
    num_partes: int,
    nucleo_inicio: int | None,
    nucleo_fin: int | None,
    nucleo_unit: Literal["parte", "subparte"] = "parte",
    subparte_num: int | None = None,
    subparte_total: int | None = None,
) -> str:
    if mode == "subpdf_buffered":
        if nucleo_inicio is not None and nucleo_fin is not None:
            is_sp = nucleo_unit == "subparte"
            unit_goal = "subparte" if is_sp else "parte"
            ejecucion_line = (
                f"Esta ejecución: Subparte {subparte_num}/{subparte_total} "
                f"de la Parte {part_id}/{num_partes}.\n\n"
                if (
                    is_sp
                    and subparte_num is not None
                    and subparte_total is not None
                )
                else f"Esta ejecución: Parte {part_id}/{num_partes}.\n\n"
            )
            pdf_carry = (
                "NOTA IMPORTANTE: El PDF adjunto es el recorte de **toda la parte** (±1 página de buffer), "
                "no solo las páginas del núcleo siguiente. "
            ) if is_sp else ""

            exclusividad = ""
            if is_sp:
                exclusividad = (
                    "\n\nEXCLUSIVIDAD (obligatorio):\n"
                    "- Tu salida debe cubrir **solo** el contenido del núcleo indicado (esta subparte). "
                    "No desarrolles temas o párrafos que, según la identificación de la subparte, correspondan "
                    "a otra subparte de la misma parte.\n"
                    "- Si el núcleo comparte una página con la subparte anterior o siguiente, cíñete a la sección "
                    "«PÁGINA … COMPARTIDA» de la identificación: explica únicamente el fragmento asignado a "
                    "**esta** subparte; no repitas ni anticipes lo que corresponde a la otra.\n"
                    "- El buffer sirve solo para continuidad de lectura en los bordes; no conviertas páginas de buffer "
                    "en un segundo núcleo de estudio.\n"
                )

            return (
                "ALCANCE DEL PDF ADJUNTO (LECTURA)\n"
                f"{pdf_carry}"
                f"Objetivo de estudio (NÚCLEO de {unit_goal}): páginas {nucleo_inicio}–{nucleo_fin} "
                f"(marcas «— Página X / N —»).\n\n"
                f"{ejecucion_line}"
                "- Páginas NÚCLEO: intervalo anterior; ahí está todo lo que debes explicar con plenitud.\n"
                "- Páginas solo de CONTEXTO (buffer): úsalas solo para recuperar enunciados partidos en el corte, "
                "coherencia entre páginas colindantes o referencias inmediatas. "
                "No las desarrolles como bloques didácticos independientes, no les asignes peso similar al núcleo "
                "y no inventes exigencias de estudio basadas únicamente en el buffer."
                f"{exclusividad}"
                f"\nParte {part_id}/{num_partes}: procesa únicamente este módulo; "
                "el temario de otras partes no es objeto de esta ejecución."
            )
        return (
            "ALCANCE DEL PDF ADJUNTO (LECTURA)\n"
            "El archivo es un recorte local del documento con hasta una página de contexto a cada lado del tramo "
            + ("principal de esta subparte (buffer), para no perder párrafos cortados entre módulos.\n\n"
               if nucleo_unit == "subparte"
               else "principal de esta parte (buffer), para no perder párrafos cortados entre módulos.\n\n")
            + ("- NÚCLEO: delimita el bloque principal usando la identificación de la subparte y el contrato de alcance; "
               if nucleo_unit == "subparte"
               else "- NÚCLEO: delimita el bloque principal usando la identificación de la parte y el contrato de alcance; ")
            + "ahí reside el objetivo de estudio.\n"
            + "- CONTEXTO (buffer): solo continuidad en los bordes; no lo desarrolles como temario independiente "
            + "ni bases de estudio aisladas.\n\n"
            + (
                f"Subparte {subparte_num}/{subparte_total} de la Parte {part_id}/{num_partes}: desarrolla exclusivamente este módulo; "
                "el resto del documento completo no es objeto de este procesamiento."
                if (
                    nucleo_unit == "subparte"
                    and subparte_num is not None
                    and subparte_total is not None
                )
                else f"Parte {part_id}/{num_partes}: desarrolla exclusivamente este módulo; el resto del documento completo "
                "no es objeto de este procesamiento."
            )
        )
    nucleus_hint = ""
    if nucleo_inicio is not None and nucleo_fin is not None:
        nucleus_hint = (
            f" El segmentador sitúa el núcleo de esta parte en las páginas {nucleo_inicio}–{nucleo_fin} "
            "(marcas visibles en el PDF)."
        )
    return (
        "ALCANCE DEL PDF ADJUNTO (LECTURA)\n"
        "El archivo contiene el documento completo."
        f"{nucleus_hint}\n\n"
        + (
            (
                f"Desarrolla exclusivamente la Subparte {subparte_num}/{subparte_total} "
                f"de la Parte {part_id}/{num_partes} según el contrato de alcance y la identificación. "
                "No desarrolles bloques pertenecientes a subpartes vecinas ni conviertas el resto del documento en desarrollo sustantivo."
            )
            if (
                nucleo_unit == "subparte"
                and subparte_num is not None
                and subparte_total is not None
            )
            else (
                f"Desarrolla exclusivamente la Parte {part_id}/{num_partes} según el contrato de alcance y la identificación. "
                "No sustituyas el material de otras partes por contenido de este módulo. "
                "Si necesitas enlaces mínimos con el resto del temario, limítalos a menciones breves."
            )
        )
    )


def _text_scope_instructions(
    part_id: int,
    num_partes: int,
    bloque_inicio: int,
    bloque_fin: int,
    *,
    nucleo_unit: Literal["parte", "subparte"] = "parte",
    subparte_num: int | None = None,
    subparte_total: int | None = None,
) -> str:
    exclusivity = (
        f"Desarrolla exclusivamente la Subparte {subparte_num}/{subparte_total} de la Parte {part_id}/{num_partes}; "
        "el resto del texto adjunto y cualquier bloque vecino quedan fuera de alcance."
        if (
            nucleo_unit == "subparte"
            and subparte_num is not None
            and subparte_total is not None
        )
        else f"Desarrolla exclusivamente la Parte {part_id}/{num_partes}; "
    )
    return (
        "ALCANCE DEL TEXTO ADJUNTO\n"
        f"El archivo incluye exactamente los bloques {bloque_inicio}–{bloque_fin} de la segmentación "
        "(sin páginas de buffer: el corte es preciso). "
        f"{exclusivity}"
        "la tabla de contenidos aporta panorama global, pero no añadas temario fuera de los bloques adjuntos."
    )


def _youtube_scope_instructions(
    part_id: int,
    num_partes: int,
    *,
    nucleo_unit: Literal["parte", "subparte"] = "parte",
    subparte_num: int | None = None,
    subparte_total: int | None = None,
) -> str:
    exclusivity = (
        f"Procesa únicamente la Subparte {subparte_num}/{subparte_total} de la Parte {part_id}/{num_partes} "
        "según el contrato de alcance y la identificación. No desarrolles material de subpartes vecinas. "
        if (
            nucleo_unit == "subparte"
            and subparte_num is not None
            and subparte_total is not None
        )
        else f"Procesa únicamente la Parte {part_id}/{num_partes} según el contrato de alcance y la identificación. "
    )
    return (
        "ALCANCE DE LA FUENTE ADJUNTA\n"
        f"{exclusivity}"
        "La tabla de contenidos sitúa el módulo dentro del conjunto del material."
    )


def _build_pdf_agent_prompt(
    table_of_contents: str,
    identificacion: str,
    part_id: int,
    num_partes: int,
    handoff: PartHandoffContext,
    current_parte: dict,
    partes_segmentadas: list[dict],
    *,
    pdf_scope_mode: Literal["subpdf_buffered", "full_document"],
    nucleo_inicio: int | None,
    nucleo_fin: int | None,
) -> str:
    toc_with_marker = table_of_contents.replace(
        f"  Parte {part_id}/{num_partes}:",
        f"  ▶ Parte {part_id}/{num_partes} [PARTE ACTUAL]:",
    )
    handoff_body = _format_handoff_section(handoff, part_id=part_id, num_partes=num_partes)
    part_scope_contract = _build_part_scope_contract_block(
        current_parte,
        part_id=part_id,
        num_partes=num_partes,
    )
    negative_scope = _build_part_negative_scope_block(current_parte, partes_segmentadas)
    scope = _pdf_scope_instructions(
        mode=pdf_scope_mode,
        part_id=part_id,
        num_partes=num_partes,
        nucleo_inicio=nucleo_inicio,
        nucleo_fin=nucleo_fin,
    )
    return (
        f"{part_scope_contract}\n\n"
        f"---\n\n"
        f"{negative_scope}\n\n"
        f"---\n\n"
        f"{toc_with_marker}\n\n"
        f"---\n\n"
        f"{handoff_body}\n\n"
        f"---\n\n"
        f"{scope}\n\n"
        f"---\n\n"
        f"IDENTIFICACIÓN PRECISA DE LA PARTE (texto del segmentador):\n{identificacion}"
    )


def _build_text_agent_prompt(
    table_of_contents: str,
    identificacion: str,
    part_id: int,
    num_partes: int,
    handoff: PartHandoffContext,
    current_parte: dict,
    partes_segmentadas: list[dict],
    *,
    bloque_inicio: int,
    bloque_fin: int,
) -> str:
    toc_with_marker = table_of_contents.replace(
        f"  Parte {part_id}/{num_partes}:",
        f"  ▶ Parte {part_id}/{num_partes} [PARTE ACTUAL]:",
    )
    handoff_body = _format_handoff_section(handoff, part_id=part_id, num_partes=num_partes)
    part_scope_contract = _build_part_scope_contract_block(
        current_parte,
        part_id=part_id,
        num_partes=num_partes,
    )
    negative_scope = _build_part_negative_scope_block(current_parte, partes_segmentadas)
    scope = _text_scope_instructions(part_id, num_partes, bloque_inicio, bloque_fin)
    return (
        f"{part_scope_contract}\n\n"
        f"---\n\n"
        f"{negative_scope}\n\n"
        f"---\n\n"
        f"{toc_with_marker}\n\n"
        f"---\n\n"
        f"{handoff_body}\n\n"
        f"---\n\n"
        f"{scope}\n\n"
        f"---\n\n"
        f"IDENTIFICACIÓN PRECISA DE LA PARTE (texto del segmentador):\n{identificacion}"
    )


def _build_youtube_agent_prompt(
    table_of_contents: str,
    identificacion: str,
    part_id: int,
    num_partes: int,
    handoff: PartHandoffContext,
    current_parte: dict,
    partes_segmentadas: list[dict],
) -> str:
    toc_with_marker = table_of_contents.replace(
        f"  Parte {part_id}/{num_partes}:",
        f"  ▶ Parte {part_id}/{num_partes} [PARTE ACTUAL]:",
    )
    handoff_body = _format_handoff_section(handoff, part_id=part_id, num_partes=num_partes)
    part_scope_contract = _build_part_scope_contract_block(
        current_parte,
        part_id=part_id,
        num_partes=num_partes,
    )
    negative_scope = _build_part_negative_scope_block(current_parte, partes_segmentadas)
    scope = _youtube_scope_instructions(part_id, num_partes)
    return (
        f"{part_scope_contract}\n\n"
        f"---\n\n"
        f"{negative_scope}\n\n"
        f"---\n\n"
        f"{toc_with_marker}\n\n"
        f"---\n\n"
        f"{handoff_body}\n\n"
        f"---\n\n"
        f"{scope}\n\n"
        f"---\n\n"
        f"IDENTIFICACIÓN PRECISA DE LA PARTE (texto del segmentador):\n{identificacion}"
    )


def _build_subpart_context(
    subparte: dict,
    all_subpartes: list[dict],
    part_id: int,
    num_partes: int,
) -> str:
    sp_num = subparte.get("numero_subparte", 1)
    total_sp = len(all_subpartes)
    sp_titulo = subparte.get("titulo", f"Subparte {sp_num}")
    sp_contenido = subparte.get("contenido", "")

    lines: list[str] = []
    lines.append("ALCANCE PEDAGÓGICO DE LA SUBPARTE")
    lines.append(f"Estás explicando la SUBPARTE {sp_num}/{total_sp} de la Parte {part_id}/{num_partes}.")
    lines.append("Desarrolla SOLO el contenido asignado a esta subparte.")
    lines.append("")
    lines.append(f"Título: «{sp_titulo}»")
    if sp_contenido:
        lines.append(f"Contenido propio: {sp_contenido}")
    lines.append(
        "Genera exclusivamente el desarrollo explicativo de esta subparte. "
        "La exhaustividad se aplica solo a este fragmento objetivo y no autoriza a invadir "
        "otros bloques de la parte ni del documento completo."
    )
    return "\n".join(lines)


def _build_part_scope_contract_block(parte: dict, *, part_id: int, num_partes: int) -> str:
    title = str(parte.get("titulo") or "").strip() or f"Parte {part_id}"
    lines = [
        "CONTRATO ESTRUCTURADO DE ALCANCE DE LA PARTE",
        "Este contrato manda sobre cualquier otra señal contextual: desarrolla solo la parte actual.",
        f"Parte objetivo: {part_id}/{num_partes}",
        f"Título permitido: «{title}»",
    ]

    pagina_inicio = _optional_int(parte, "pagina_inicio")
    pagina_fin = _optional_int(parte, "pagina_fin")
    if pagina_inicio is not None and pagina_fin is not None:
        lines.append(f"Páginas núcleo: {pagina_inicio}-{pagina_fin}")

    bloque_inicio = _optional_int(parte, "bloque_inicio")
    bloque_fin = _optional_int(parte, "bloque_fin")
    if bloque_inicio is not None and bloque_fin is not None:
        lines.append(f"Bloques núcleo: {bloque_inicio}-{bloque_fin}")

    contenido = str(parte.get("contenido") or "").strip()
    if contenido:
        lines.append(f"Contenido propio de la parte: {contenido}")

    identificacion = str(parte.get("identificacion") or "").strip()
    if identificacion:
        lines.append(f"Identificación literal de apoyo: {identificacion}")

    lines.extend(
        [
            "",
            "Todo el resto del documento funciona únicamente como contexto aclaratorio y queda fuera del desarrollo sustantivo.",
        ]
    )
    return "\n".join(lines)


def _build_part_negative_scope_block(current_parte: dict, partes_segmentadas: list[dict]) -> str:
    current_num = current_parte.get("numero")
    current_pos = next((i for i, parte in enumerate(partes_segmentadas) if parte is current_parte), -1)
    if current_pos < 0:
        current_pos = next(
            (i for i, parte in enumerate(partes_segmentadas) if parte.get("numero") == current_num),
            -1,
        )

    previous_part = partes_segmentadas[current_pos - 1] if current_pos > 0 else None
    next_part = (
        partes_segmentadas[current_pos + 1]
        if current_pos >= 0 and current_pos + 1 < len(partes_segmentadas)
        else None
    )

    lines = ["FRONTERAS NEGATIVAS (NO DESARROLLAR)"]
    for neighbor, role in ((previous_part, "anterior"), (next_part, "siguiente")):
        if not neighbor:
            continue
        neighbor_number = _item_number(neighbor.get("numero"), len(partes_segmentadas))
        title = str(neighbor.get("titulo") or "").strip() or "?"
        lines.append(f"- Parte {neighbor_number} ({role}): «{title}»")

        contenido = str(neighbor.get("contenido") or "").strip()
        if contenido:
            lines.append(f"  Contenido vecino fuera de alcance: {contenido}")

        identificacion = str(neighbor.get("identificacion") or "").strip()
        if identificacion:
            lines.append(f"  Identificación vecina fuera de alcance: {identificacion}")
    return "\n".join(lines)


def _build_subpart_pdf_prompt(
    table_of_contents: str,
    parte: dict,
    subparte: dict,
    all_subpartes: list[dict],
    part_id: int,
    num_partes: int,
    handoff: PartHandoffContext,
    *,
    pdf_scope_mode: Literal["subpdf_buffered", "full_document"],
    nucleo_inicio: int | None,
    nucleo_fin: int | None,
) -> str:
    """Build the prompt for a subpart explainer call on a PDF source."""
    toc_with_marker = table_of_contents.replace(
        f"  Parte {part_id}/{num_partes}:",
        f"  ▶ Parte {part_id}/{num_partes} [PARTE ACTUAL]:",
    )
    handoff_body = _format_handoff_section(handoff, part_id=part_id, num_partes=num_partes)

    # Use subpart page range for scope instructions
    sp_pi = _optional_int(subparte, "pagina_inicio") or nucleo_inicio
    sp_pf = _optional_int(subparte, "pagina_fin") or nucleo_fin
    sp_no = _optional_int(subparte, "numero_subparte")
    scope = _pdf_scope_instructions(
        mode=pdf_scope_mode,
        part_id=part_id,
        num_partes=num_partes,
        nucleo_inicio=sp_pi,
        nucleo_fin=sp_pf,
        nucleo_unit="subparte",
        subparte_num=sp_no,
        subparte_total=len(all_subpartes),
    )

    subpart_ctx = _build_subpart_context(subparte, all_subpartes, part_id, num_partes)
    scope_contract = build_subpart_scope_contract_block(subparte)
    negative_scope = build_subpart_negative_scope_block(subparte, all_subpartes)
    sp_identificacion = subparte.get("identificacion", parte.get("identificacion", ""))

    return (
        f"{scope_contract}\n\n"
        f"---\n\n"
        f"{negative_scope}\n\n"
        f"---\n\n"
        f"{subpart_ctx}\n\n"
        f"---\n\n"
        f"{toc_with_marker}\n\n"
        f"---\n\n"
        f"{handoff_body}\n\n"
        f"---\n\n"
        f"{scope}\n\n"
        f"---\n\n"
        f"IDENTIFICACIÓN LEGIBLE DE APOYO (texto del segmentador):\n{sp_identificacion}"
    )


def _build_subpart_text_prompt(
    table_of_contents: str,
    parte: dict,
    subparte: dict,
    all_subpartes: list[dict],
    part_id: int,
    num_partes: int,
    handoff: PartHandoffContext,
    *,
    bloque_inicio: int,
    bloque_fin: int,
) -> str:
    """Build the prompt for a subpart explainer call on a text/web source."""
    toc_with_marker = table_of_contents.replace(
        f"  Parte {part_id}/{num_partes}:",
        f"  ▶ Parte {part_id}/{num_partes} [PARTE ACTUAL]:",
    )
    handoff_body = _format_handoff_section(handoff, part_id=part_id, num_partes=num_partes)

    sp_bi = subparte.get("bloque_inicio", bloque_inicio)
    sp_bf = subparte.get("bloque_fin", bloque_fin)
    scope = _text_scope_instructions(
        part_id,
        num_partes,
        int(sp_bi),
        int(sp_bf),
        nucleo_unit="subparte",
        subparte_num=_optional_int(subparte, "numero_subparte"),
        subparte_total=len(all_subpartes),
    )

    subpart_ctx = _build_subpart_context(subparte, all_subpartes, part_id, num_partes)
    scope_contract = build_subpart_scope_contract_block(subparte)
    negative_scope = build_subpart_negative_scope_block(subparte, all_subpartes)
    sp_identificacion = subparte.get("identificacion", parte.get("identificacion", ""))

    return (
        f"{scope_contract}\n\n"
        f"---\n\n"
        f"{negative_scope}\n\n"
        f"---\n\n"
        f"{subpart_ctx}\n\n"
        f"---\n\n"
        f"{toc_with_marker}\n\n"
        f"---\n\n"
        f"{handoff_body}\n\n"
        f"---\n\n"
        f"{scope}\n\n"
        f"---\n\n"
        f"IDENTIFICACIÓN LEGIBLE DE APOYO (texto del segmentador):\n{sp_identificacion}"
    )


def _build_subpart_youtube_prompt(
    table_of_contents: str,
    parte: dict,
    subparte: dict,
    all_subpartes: list[dict],
    part_id: int,
    num_partes: int,
    handoff: PartHandoffContext,
) -> str:
    """Build the prompt for a subpart explainer call on a YouTube source."""
    toc_with_marker = table_of_contents.replace(
        f"  Parte {part_id}/{num_partes}:",
        f"  ▶ Parte {part_id}/{num_partes} [PARTE ACTUAL]:",
    )
    handoff_body = _format_handoff_section(handoff, part_id=part_id, num_partes=num_partes)
    scope = _youtube_scope_instructions(
        part_id,
        num_partes,
        nucleo_unit="subparte",
        subparte_num=_optional_int(subparte, "numero_subparte"),
        subparte_total=len(all_subpartes),
    )

    subpart_ctx = _build_subpart_context(subparte, all_subpartes, part_id, num_partes)
    scope_contract = build_subpart_scope_contract_block(subparte)
    negative_scope = build_subpart_negative_scope_block(subparte, all_subpartes)
    sp_identificacion = subparte.get("identificacion", parte.get("identificacion", ""))

    return (
        f"{scope_contract}\n\n"
        f"---\n\n"
        f"{negative_scope}\n\n"
        f"---\n\n"
        f"{subpart_ctx}\n\n"
        f"---\n\n"
        f"{toc_with_marker}\n\n"
        f"---\n\n"
        f"{handoff_body}\n\n"
        f"---\n\n"
        f"{scope}\n\n"
        f"---\n\n"
        f"IDENTIFICACIÓN LEGIBLE DE APOYO (texto del segmentador):\n{sp_identificacion}"
    )


def _parse_text_source_evaluation(segmentation: dict[str, object]) -> dict[str, object]:
    evaluation = segmentation.get("evaluacion_fuente")
    if not isinstance(evaluation, dict):
        raise WebExtractionError(
            "El segmentador no devolvió la evaluación de integridad necesaria para la fuente web."
        )

    is_segmentable = evaluation.get("es_segmentable")
    if not isinstance(is_segmentable, bool):
        raise WebExtractionError(
            "El segmentador devolvió una evaluación inválida para la fuente web."
        )

    reason = str(evaluation.get("motivo") or "").strip()
    if not reason:
        reason = (
            "El segmentador considera que la fuente es segmentable."
            if is_segmentable
            else "El segmentador considera que el texto extraído no es contenido real segmentable."
        )

    clues_raw = evaluation.get("indicios")
    if clues_raw is None:
        clues: list[str] = []
    elif isinstance(clues_raw, list):
        clues = [str(item).strip() for item in clues_raw if str(item).strip()]
    else:
        raise WebExtractionError(
            "El segmentador devolvió indicios inválidos para la evaluación de la fuente web."
        )

    return {
        "es_segmentable": is_segmentable,
        "motivo": reason,
        "indicios": clues,
    }


def _build_web_segmentation_rejection_message(evaluation: dict[str, object]) -> str:
    reason = str(evaluation.get("motivo") or "").strip()
    clues = [str(item).strip() for item in (evaluation.get("indicios") or []) if str(item).strip()]

    message = (
        "Se abortó el procesamiento porque el texto extraído de la URL parece un scrape defectuoso "
        "o no corresponde a contenido real segmentable."
    )
    if reason:
        message = f"{message} {reason}"
    if clues:
        message = f"{message} Indicios detectados: {', '.join(clues[:3])}."
    return message


async def _format_and_finalize_part(
    project_id: str,
    user_id: str,
    api_key: str,
    part_id: int,
    explainer_data: dict,
    partes_contenido: dict,
    *,
    use_openrouter: bool = False,
    openrouter_api_key: str = "",
    target_language: str = "es-ES",
    use_deepseek: bool = False,
    deepseek_api_key: str = "",
) -> None:
    """Background task: format explainer content then persist and notify.

    Fires independently of other sections so that the main processing loop can
    start the next section's agents without waiting for formatting to finish.
    The `part_completed` SSE event is only sent once formatting is done.
    """
    fmt_start = time.time()
    fmt_usage: dict = {}
    try:
        is_markdown_format = isinstance(explainer_data, dict) and explainer_data.get("_format") == "markdown"
        if not isinstance(explainer_data, Exception) and isinstance(explainer_data, dict) and not is_markdown_format:
            if use_deepseek:
                formatted, fmt_usage = await format_explainer_content_ds(
                    deepseek_api_key, explainer_data, target_language
                )
            elif use_openrouter:
                formatted, fmt_usage = await format_explainer_content_or(
                    openrouter_api_key, explainer_data, target_language
                )
            else:
                formatted, fmt_usage = await format_explainer_content(api_key, explainer_data, target_language)
            partes_contenido[str(part_id)]["explainer"] = formatted
            partes_contenido[str(part_id)]["formatter_usage"] = fmt_usage
            logger.info(
                f"[Format] Parte {part_id} formateada en {int((time.time() - fmt_start) * 1000)}ms "
                f"(tokens: {fmt_usage.get('total_tokens', 0)}, coste: ${fmt_usage.get('cost', 0.0):.6f})",
                extra={
                    "part_id": part_id,
                    "elapsed_ms": int((time.time() - fmt_start) * 1000),
                    "formatter_tokens": fmt_usage.get("total_tokens", 0),
                    "formatter_cost": fmt_usage.get("cost", 0.0),
                },
            )
    except Exception as exc:
        logger.warning(
            f"[Format] Error inesperado al formatear parte {part_id}, se conserva el original: {exc}",
            extra={"part_id": part_id, "error": str(exc)[:300]},
        )
    finally:
        partes_contenido[str(part_id)]["formatter_version"] = 1
        partes_contenido[str(part_id)]["status"] = "completed"
        update_project(project_id, user_id, {"partes_contenido": partes_contenido})
        await send_event(project_id, {"type": "part_completed", "part_id": part_id})


async def _process_project(
    project_id: str,
    user_id: str,
    explainer_provider: ExplainerProvider = EXPLAINER_PROVIDER_GEMINI,
    openrouter_model: OpenRouterExplainerModel | str | None = None,
    deepseek_model: DeepSeekExplainerModel | str | None = None,
    target_language: str = "es-ES",
    openrouter_provider_routing: dict | None = None,
) -> None:
    process_start_time = time.time()
    project: dict[str, Any] | None = None
    source_type = "pdf"
    pdf_temp_path = None
    numbered_pdf_path = None
    segment_pdf_paths: list[str] = []
    pdf_total_pages: int = 0
    content_page_set: frozenset[int] = frozenset()
    mistral_pdf_prepare_task: asyncio.Task | None = None
    mistral_pdf_context: PreparedPdfOcrContext | None = None
    temp_paths: list[str] = []
    web_blocks = []
    source_mime_type = "application/pdf"
    source_kind = "pdf"
    source_title = ""
    resolved_source_url = ""
    source_metadata: dict[str, object] = {}
    openrouter_full_source_text = ""
    use_openrouter_explainer = explainer_provider == EXPLAINER_PROVIDER_OPENROUTER
    target_language_obj = normalize_target_language(target_language)
    target_language_code = target_language_obj.code
    use_deepseek_explainer = explainer_provider == EXPLAINER_PROVIDER_DEEPSEEK
    use_text_provider_explainer = use_openrouter_explainer or use_deepseek_explainer
    try:
        explainer_model = _resolve_explainer_model(
            explainer_provider,
            openrouter_model,
            deepseek_model,
        )
    except ValueError as exc:
        await send_event(project_id, {"type": "error", "message": str(exc)})
        update_project(project_id, user_id, {"status": "error", "error_message": str(exc)})
        return
    classifier_model = (
        OPENROUTER_MODEL_AUXILIARY
        if use_openrouter_explainer
        else DEEPSEEK_MODEL_AUXILIARY
        if use_deepseek_explainer
        else MODEL_CLASSIFIER
    )
    segmentation_model = (
        OPENROUTER_MODEL_AUXILIARY
        if use_openrouter_explainer
        else DEEPSEEK_MODEL_AUXILIARY
        if use_deepseek_explainer
        else MODEL_SEGMENTADOR
    )
    auxiliary_agents_model = (
        OPENROUTER_MODEL_AUXILIARY
        if use_openrouter_explainer
        else DEEPSEEK_MODEL_AUXILIARY
        if use_deepseek_explainer
        else MODEL_AGENTS
    )
    validator_model = (
        OPENROUTER_COMPLETENESS_VALIDATOR_MODEL
        if use_openrouter_explainer
        else DEEPSEEK_COMPLETENESS_VALIDATOR_MODEL
        if use_deepseek_explainer
        else COMPLETENESS_VALIDATOR_MODEL
    )

    # Establecer contexto de logging
    with LogContext(project_id=project_id, user_id=user_id):
        logger.info(
            f"[Process] Iniciando procesamiento de proyecto",
            extra={"project_id": project_id, "user_id": user_id[:8] + "..."}
        )

    try:
        project = get_project(project_id, user_id, include_internal=True)
        if not project:
            logger.error(f"[Process] Proyecto no encontrado: {project_id}")
            await send_event(project_id, {"type": "error", "message": "Proyecto no encontrado"})
            return

        source_type = project.get("source_type", "pdf")
        source_metadata = {**(project.get("source_metadata") or {}), "target_language": target_language_code}
        update_project(project_id, user_id, {"source_metadata": source_metadata})
        logger.info(
            f"[Process] Proyecto cargado: {project.get('name', 'unnamed')}",
            extra={
                "project_name": project.get("name", "unnamed"),
                "source_type": source_type,
                "current_status": project.get("status", "unknown"),
            }
        )

        if use_text_provider_explainer and source_type == "youtube":
            logger.info(
                "[Process] YouTube no soportado en provider directo, usando Gemini automáticamente",
                extra={"project_id": project_id, "source_type": source_type},
            )
            use_openrouter_explainer = False
            use_deepseek_explainer = False
            use_text_provider_explainer = False
            explainer_provider = EXPLAINER_PROVIDER_GEMINI
            explainer_model = MODEL_AGENTS
            classifier_model = MODEL_CLASSIFIER
            segmentation_model = MODEL_SEGMENTADOR
            auxiliary_agents_model = MODEL_AGENTS
            validator_model = COMPLETENESS_VALIDATOR_MODEL

        # Get user's API keys (BYOK) from Supabase.
        api_key = get_user_api_key(user_id, provider=PROVIDER_GEMINI) or ""
        requires_gemini_key = not use_deepseek_explainer
        if requires_gemini_key and not api_key:
            logger.error(f"[Process] API key Gemini no configurada para user: {user_id[:8]}...")
            await send_event(project_id, {"type": "error", "message": "No hay API key de Gemini configurada. Configúrala en Ajustes."})
            update_project(project_id, user_id, {"status": "error", "error_message": "API key no configurada"})
            return

        openrouter_api_key = ""
        deepseek_api_key = ""
        tavily_api_key = ""
        mistral_api_key = ""
        if use_openrouter_explainer:
            openrouter_api_key = get_user_api_key(user_id, provider=PROVIDER_OPENROUTER) or ""
            if not openrouter_api_key:
                logger.error(f"[Process] API key OpenRouter no configurada para user: {user_id[:8]}...")
                await send_event(
                    project_id,
                    {
                        "type": "error",
                        "message": (
                            "No hay API key de OpenRouter configurada. "
                            "Guárdala en Ajustes para usar OpenRouter en este flujo."
                        ),
                    },
                )
                update_project(project_id, user_id, {"status": "error", "error_message": "API key OpenRouter no configurada"})
                return
            mistral_api_key = get_user_api_key(user_id, provider=PROVIDER_MISTRAL) or ""
            if source_type == "pdf" and not mistral_api_key:
                logger.error(f"[Process] API key Mistral no configurada para PDF con OpenRouter: {user_id[:8]}...")
                await send_event(
                    project_id,
                    {
                        "type": "error",
                        "message": (
                            "No hay API key de Mistral configurada. "
                            "Guárdala en Ajustes para usar OCR nativo en PDFs con OpenRouter."
                        ),
                    },
                )
                update_project(project_id, user_id, {"status": "error", "error_message": "API key Mistral no configurada"})
                return
        elif use_deepseek_explainer:
            deepseek_api_key = get_user_api_key(user_id, provider=PROVIDER_DEEPSEEK) or ""
            if not deepseek_api_key:
                logger.error(f"[Process] API key DeepSeek no configurada para user: {user_id[:8]}...")
                await send_event(
                    project_id,
                    {
                        "type": "error",
                        "message": (
                            "No hay API key de DeepSeek configurada. "
                            "Guárdala en Ajustes para usar DeepSeek directo en este flujo."
                        ),
                    },
                )
                update_project(project_id, user_id, {"status": "error", "error_message": "API key DeepSeek no configurada"})
                return
            tavily_api_key = get_user_api_key(user_id, provider=PROVIDER_TAVILY) or ""
            if not tavily_api_key:
                logger.error(f"[Process] API key Tavily no configurada para DeepSeek: {user_id[:8]}...")
                await send_event(
                    project_id,
                    {
                        "type": "error",
                        "message": (
                            "No hay API key de Tavily configurada. "
                            "Guárdala en Ajustes para que DeepSeek pueda verificar recursos con búsquedas web."
                        ),
                    },
                )
                update_project(project_id, user_id, {"status": "error", "error_message": "API key Tavily no configurada"})
                return
            mistral_api_key = get_user_api_key(user_id, provider=PROVIDER_MISTRAL) or ""
            if source_type == "pdf" and not mistral_api_key:
                logger.error(f"[Process] API key Mistral no configurada para PDF con DeepSeek: {user_id[:8]}...")
                await send_event(
                    project_id,
                    {
                        "type": "error",
                        "message": (
                            "No hay API key de Mistral configurada. "
                            "Guárdala en Ajustes para usar OCR nativo en PDFs con DeepSeek."
                        ),
                    },
                )
                update_project(project_id, user_id, {"status": "error", "error_message": "API key Mistral no configurada"})
                return

        active_key_for_log = (
            openrouter_api_key
            if use_openrouter_explainer
            else deepseek_api_key
            if use_deepseek_explainer
            else api_key
        )
        logger.info(f"[Process] Usando API key principal: {mask_api_key(active_key_for_log)}")

        from google import genai
        client = genai.Client(api_key=api_key) if api_key else None
        logger.info(
            "[Process] Enrutamiento de modelos: classifier=%s, segmentador=%s, agents=%s, validator=%s, explainer_provider=%s, explainer_model=%s",
            classifier_model,
            segmentation_model,
            auxiliary_agents_model,
            validator_model,
            explainer_provider,
            explainer_model,
        )

        cumulative_usage = {
            "classifier_model": classifier_model,
            "segmentation_model": segmentation_model,
            "agents_model": auxiliary_agents_model,
            "validator_model": validator_model,
            "formatter_model": (
                OPENROUTER_MODEL_AUXILIARY
                if use_openrouter_explainer
                else DEEPSEEK_MODEL_AUXILIARY
                if use_deepseek_explainer
                else MODEL_AGENTS
            ),
            "explainer_provider": explainer_provider,
            "explainer_model": explainer_model,
            "prompt_tokens": 0,
            "tool_use_prompt_tokens": 0,
            "candidates_tokens": 0,
            "thoughts_tokens": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
        }
        if use_openrouter_explainer:
            cumulative_usage["openrouter_pdf_parser_engine"] = OPENROUTER_PDF_PARSER_ENGINE
            cumulative_usage["openrouter_pdf_priming_model"] = OPENROUTER_PDF_PRIMING_MODEL
        if use_deepseek_explainer:
            cumulative_usage["deepseek_search_provider"] = "tavily"
            cumulative_usage["deepseek_pdf_parser_engine"] = MISTRAL_OCR_ENGINE
        await asyncio.to_thread(update_project, project_id, user_id, {"usage": cumulative_usage})

        usage_lock = asyncio.Lock()

        def _update_usage(usage_meta, phase: str = "unknown", *, cost_model: str):
            if not usage_meta:
                return
            p = getattr(usage_meta, "prompt_token_count", 0) or 0
            tp = getattr(usage_meta, "tool_use_prompt_token_count", 0) or 0
            c = getattr(usage_meta, "candidates_token_count", 0) or 0
            t = getattr(usage_meta, "thoughts_token_count", 0) or 0
            tt = getattr(usage_meta, "total_token_count", 0) or 0
            cumulative_usage["prompt_tokens"] += p + tp
            cumulative_usage["tool_use_prompt_tokens"] += tp
            cumulative_usage["candidates_tokens"] += c
            cumulative_usage["thoughts_tokens"] += t
            cumulative_usage["total_tokens"] += tt
            raw_cost_usd = getattr(usage_meta, "cost_usd", None)
            if (
                isinstance(raw_cost_usd, (int, float))
                and math.isfinite(raw_cost_usd)
                and raw_cost_usd >= 0
            ):
                cost = round(float(raw_cost_usd), 6)
                cost_source = "openrouter_real"
            else:
                cost = calculate_cost(cost_model, usage_meta)
                cost_source = "estimated_pricing"
            cumulative_usage["total_cost"] += cost

            logger.debug(
                f"[Process] Uso de tokens actualizado - fase: {phase}",
                extra={
                    "phase": phase,
                    "cost_model": cost_model,
                    "cost_source": cost_source,
                    "tokens_this_call": tt,
                    "cost_this_call": round(cost, 6),
                    "cumulative_total": cumulative_usage["total_tokens"],
                    "cumulative_cost": round(cumulative_usage["total_cost"], 6),
                }
            )

        async def _locked_apply_usage(usage_meta, phase: str = "unknown", *, cost_model: str) -> None:
            async with usage_lock:
                _update_usage(usage_meta, phase=phase, cost_model=cost_model)
                await asyncio.to_thread(update_project, project_id, user_id, {"usage": cumulative_usage})

        # Determine source type and get file_uri
        source_type = project.get("source_type", "pdf")
        file_uri = None

        if source_type == "youtube":
            # For YouTube, use the source_url directly as file_uri
            file_uri = project.get("source_url")
            if not file_uri:
                logger.error("[Process] URL de YouTube no encontrada en el proyecto")
                await send_event(project_id, {"type": "error", "message": "URL de YouTube no encontrada en el proyecto"})
                update_project(project_id, user_id, {"status": "error", "error_message": "URL de YouTube no configurada"})
                return

            logger.info(f"[Process] Usando URL de YouTube: {file_uri[:80]}...")
            resolved_source_url = file_uri

            # Skip "uploading" phase for YouTube - just update status to segmenting
            update_project(project_id, user_id, {"file_uri": file_uri, "status": "segmenting"})
            await send_event(project_id, {"type": "segmenting"})

        elif source_type == "web":
            source_url = project.get("source_url")
            if not source_url:
                logger.error("[Process] URL web no encontrada en el proyecto")
                await send_event(project_id, {"type": "error", "message": "URL web no encontrada en el proyecto"})
                update_project(project_id, user_id, {"status": "error", "error_message": "URL web no configurada"})
                return

            logger.info("[Process] Iniciando preparación de fuente web")
            await send_event(project_id, {"type": "uploading"})
            update_project(project_id, user_id, {"status": "uploading"})

            source_text = project.get("source_text")
            source_metadata = {**(project.get("source_metadata") or {}), "target_language": target_language_code}
            extraction_usage = None

            if not source_text:
                extracted_content, extraction_usage = await asyncio.to_thread(
                    extract_web_content,
                    source_url,
                    api_key if not use_deepseek_explainer else None,
                    MODEL_AGENTS,
                )
                source_text = extracted_content.text
                source_title = extracted_content.title
                resolved_source_url = extracted_content.resolved_url
                source_metadata = {
                    **source_metadata,
                    **(extracted_content.metadata or {}),
                    "target_language": target_language_code,
                    "title": extracted_content.title,
                    "resolved_url": extracted_content.resolved_url,
                    "content_type": extracted_content.content_type,
                    "extraction_method": extracted_content.extraction_method,
                }
                update_project(
                    project_id,
                    user_id,
                    {
                        "source_text": source_text,
                        "source_metadata": source_metadata,
                        "pdf_filename": f"Web: {source_title[:120] or 'URL pública'}",
                    },
                )
            else:
                source_title = source_metadata.get("title") or project.get("name") or project.get("pdf_filename") or "Texto web"
                resolved_source_url = source_metadata.get("resolved_url") or source_url

            if extraction_usage:
                await _locked_apply_usage(extraction_usage, phase="web_extraction", cost_model=MODEL_AGENTS)
                await send_event(project_id, {"type": "usage_update", "usage": cumulative_usage})

            web_blocks = await asyncio.to_thread(build_text_blocks, source_text)
            if not web_blocks:
                raise WebExtractionError(
                    "La URL no contiene suficiente texto utilizable tras la extracción. "
                    "Se aborta el procesamiento para no malgastar tokens."
                )

            source_title = source_title or "Texto web"
            resolved_source_url = resolved_source_url or source_url
            source_metadata = {
                **source_metadata,
                "title": source_title,
                "resolved_url": resolved_source_url,
                "block_count": len(web_blocks),
                "word_count": len(source_text.split()),
            }
            update_project(project_id, user_id, {"source_metadata": source_metadata})

            web_document = await asyncio.to_thread(
                render_block_marked_document,
                title=source_title,
                source_url=resolved_source_url,
                blocks=web_blocks,
            )
            openrouter_full_source_text = web_document
            web_temp_path = await asyncio.to_thread(write_text_document_temp, web_document)
            temp_paths.append(web_temp_path)

            if use_text_provider_explainer:
                file_uri = f"{explainer_provider}-text://{project_id}/full-source"
                source_mime_type = "text/plain"
                upload_duration = 0.0
            else:
                upload_start = time.time()
                if client is None:
                    raise RuntimeError("Cliente Gemini no inicializado para subir la fuente web.")
                uploaded_file = await asyncio.to_thread(lambda: upload_file_with_retry(client, web_temp_path, max_retries=5))
                upload_duration = (time.time() - upload_start) * 1000
                file_uri = uploaded_file.uri
                source_mime_type = getattr(uploaded_file, "mime_type", None) or "text/plain"
            source_kind = "text"

            logger.info(
                f"[Process] Fuente web preparada en {int(upload_duration)}ms",
                extra={
                    "file_uri": file_uri,
                    "upload_duration_ms": int(upload_duration),
                    "block_count": len(web_blocks),
                    "resolved_url": resolved_source_url,
                    "text_provider_inline_source": use_text_provider_explainer,
                }
            )

            project_update: dict[str, Any] = {"status": "segmenting"}
            if not use_text_provider_explainer:
                project_update["file_uri"] = file_uri
            update_project(project_id, user_id, project_update)
            await send_event(project_id, {"type": "segmenting"})

        else:
            # PDF source type
            logger.info("[Process] Iniciando fase de upload de PDF")
            await send_event(project_id, {"type": "uploading"})
            update_project(project_id, user_id, {"status": "uploading"})

            pdf_temp_path = download_pdf_to_temp(project_id, user_id)
            if not pdf_temp_path:
                logger.error("[Process] No se pudo descargar el PDF del almacenamiento")
                await send_event(project_id, {"type": "error", "message": "No se pudo descargar el PDF."})
                update_project(project_id, user_id, {"status": "error", "error_message": "PDF no encontrado en almacenamiento"})
                return

            logger.info(f"[Process] PDF descargado temporalmente: {pdf_temp_path}")
            temp_paths.append(pdf_temp_path)

            # Page count is read from the original PDF (same for both flows).
            pdf_total_pages = len(PdfReader(pdf_temp_path).pages)

            if use_text_provider_explainer:
                # Direct text-provider flows: Mistral extracts text via PDF structure, so no
                # visual page-number watermarks are needed. Use the original PDF directly.
                logger.info(
                    "[Process] Preparando OCR canónico de Mistral al inicio del flujo textual",
                    extra={
                        "pdf_total_pages": pdf_total_pages,
                        "mistral_ocr_engine": MISTRAL_OCR_ENGINE,
                        "explainer_provider": explainer_provider,
                    },
                )
                mistral_pdf_context = await asyncio.to_thread(
                    _prepare_mistral_pdf_ocr_context,
                    source_path=pdf_temp_path,
                    content_page_set=frozenset(range(1, pdf_total_pages + 1)),
                    api_key=mistral_api_key,
                    engine=MISTRAL_OCR_ENGINE,
                )
                file_uri = f"mistral-ocr://{mistral_pdf_context.cache_entry.source_sha256}"
                source_mime_type = "application/pdf"
                openrouter_full_source_text = _render_mistral_ocr_pages_for_agents(
                    cache_entry=mistral_pdf_context.cache_entry,
                    page_numbers=tuple(range(1, pdf_total_pages + 1)),
                )
                logger.info(
                    "[Process] OCR canónico de Mistral preparado para provider textual",
                    extra={
                        "file_uri": file_uri,
                        "cache_hit": mistral_pdf_context.cache_entry.cache_hit,
                        "cached_pages_count": len(mistral_pdf_context.cache_entry.cached_page_numbers),
                        "source_chars": len(openrouter_full_source_text),
                        "explainer_provider": explainer_provider,
                    },
                )
            else:
                # Gemini flow: add visible page-number watermarks before uploading.
                # Gemini processes the PDF visually, so the watermarks let it identify
                # absolute page numbers regardless of where in the document it is reading.
                logger.info("[Process] Añadiendo numeración de páginas al PDF")
                numbered_pdf_path = await asyncio.to_thread(add_page_numbers, pdf_temp_path)
                logger.info(f"[Process] PDF numerado creado: {numbered_pdf_path}")
                temp_paths.append(numbered_pdf_path)
                upload_start = time.time()
                if client is None:
                    raise RuntimeError("Cliente Gemini no inicializado para subir el PDF numerado.")
                uploaded_file = await asyncio.to_thread(lambda: upload_file_with_retry(client, numbered_pdf_path, max_retries=5))
                upload_duration = (time.time() - upload_start) * 1000

                file_uri = uploaded_file.uri
                source_mime_type = getattr(uploaded_file, "mime_type", None) or "application/pdf"
                logger.info(
                    f"[Process] Upload completado en {int(upload_duration)}ms",
                    extra={
                        "file_uri": file_uri,
                        "upload_duration_ms": int(upload_duration),
                    }
                )

            update_project(project_id, user_id, {"file_uri": file_uri, "status": "segmenting"})
            await send_event(project_id, {"type": "segmenting"})

        # Clasificador de páginas (solo para PDF): identifica qué páginas son contenido vs. accesorias
        if source_type == "pdf" and file_uri and pdf_total_pages > 0:
            try:
                if use_openrouter_explainer:
                    if not mistral_pdf_context or not openrouter_full_source_text:
                        raise PdfOcrError(
                            "OCR Mistral no disponible para el clasificador OpenRouter."
                        )
                    content_page_set, clf_usage, _clf_raw = await asyncio.to_thread(
                        run_page_classifier_or,
                        openrouter_api_key,
                        openrouter_full_source_text,
                        pdf_total_pages,
                    )
                elif use_deepseek_explainer:
                    if not mistral_pdf_context or not openrouter_full_source_text:
                        raise PdfOcrError(
                            "OCR Mistral no disponible para el clasificador DeepSeek."
                        )
                    content_page_set, clf_usage, _clf_raw = await asyncio.to_thread(
                        run_page_classifier_ds,
                        deepseek_api_key,
                        openrouter_full_source_text,
                        pdf_total_pages,
                    )
                else:
                    content_page_set, clf_usage, _clf_raw = await asyncio.to_thread(
                        run_page_classifier,
                        api_key,
                        file_uri,
                        pdf_total_pages,
                        MODEL_CLASSIFIER,
                    )
                await _locked_apply_usage(clf_usage, phase="page_classifier", cost_model=classifier_model)
                await send_event(project_id, {"type": "usage_update", "usage": cumulative_usage})
                clf_cost = (
                    getattr(clf_usage, "cost_usd", None) or 0.0
                    if use_openrouter_explainer
                    else calculate_cost(classifier_model, clf_usage)
                )
                logger.info(
                    "[Process] Clasificador: %d páginas de contenido de %d (coste ~$%.6f USD)",
                    len(content_page_set),
                    pdf_total_pages,
                    clf_cost,
                    extra={
                        "content_pages_count": len(content_page_set),
                        "total_pages": pdf_total_pages,
                        "classifier_cost_usd": clf_cost,
                    },
                )
            except Exception as clf_err:
                if use_text_provider_explainer:
                    raise
                content_page_set = frozenset(range(1, pdf_total_pages + 1))
                logger.warning(
                    "[Process] Clasificador de páginas falló, asumiendo todas como contenido: %s",
                    clf_err,
                    extra={"error_type": type(clf_err).__name__},
                )

            if (
                not use_text_provider_explainer
                and mistral_api_key
                and content_page_set
                and source_type == "pdf"
            ):
                logger.info(
                    "[Process] Preparando OCR canónico de Mistral sobre páginas con contenido",
                    extra={
                        "content_pages_count": len(content_page_set),
                        "mistral_ocr_engine": MISTRAL_OCR_ENGINE,
                    },
                )
                mistral_pdf_prepare_task = asyncio.create_task(
                    asyncio.to_thread(
                        _prepare_mistral_pdf_ocr_context,
                        source_path=pdf_temp_path,
                        content_page_set=content_page_set,
                        api_key=mistral_api_key,
                        engine=MISTRAL_OCR_ENGINE,
                    )
                )

        # Fase de segmentación (con validación de cobertura de páginas y reintentos)
        logger.info("[Process] Iniciando segmentación del documento")
        seg_start = time.time()
        segmentation: dict | None = None
        page_report = None
        is_pdf_seg = source_type == "pdf"
        content_pages_prefix = (
            _build_content_pages_prefix(content_page_set, pdf_total_pages)
            if is_pdf_seg and content_page_set
            else ""
        )
        MAX_COMBINED_ATTEMPTS = MAX_PAGE_COVERAGE_ATTEMPTS
        base_desc = project["description"].strip() or DEFAULT_DESCRIPTION
        # DeepSeek-only: retries continue the SAME conversation (system + source resent once,
        # then cached) instead of rebuilding the prompt. OR/Gemini keep the seg_description rebuild.
        seg_ds_conversation: list[dict] | None = None

        for seg_attempt in range(MAX_COMBINED_ATTEMPTS):
            correction_suffix: str | None = None
            if seg_attempt == 0:
                seg_description = content_pages_prefix + base_desc
            else:
                assert segmentation is not None
                assert page_report is not None and not page_report.is_valid
                correction_suffix = build_page_coverage_retry_suffix(
                    attempt=seg_attempt,
                    segmentation=segmentation,
                    report=page_report,
                    content_page_set=content_page_set,
                )
                seg_description = content_pages_prefix + base_desc + "\n\n" + correction_suffix

            if use_text_provider_explainer:
                if is_pdf_seg:
                    if not openrouter_full_source_text:
                        raise PdfOcrError(
                            "OCR Mistral no disponible para el segmentador textual."
                        )
                else:
                    if not openrouter_full_source_text:
                        raise WebExtractionError(
                            "El documento web está vacío y no puede ser segmentado."
                        )
                segmentador_source_text = openrouter_full_source_text
                if use_openrouter_explainer:
                    segmentation, usage_meta = await asyncio.to_thread(
                        run_segmentador_or,
                        openrouter_api_key,
                        segmentador_source_text,
                        seg_description,
                        source_kind,
                        target_language=target_language_code,
                    )
                elif seg_attempt == 0:
                    segmentation, usage_meta, seg_ds_conversation = await asyncio.to_thread(
                        run_segmentador_ds,
                        deepseek_api_key,
                        segmentador_source_text,
                        content_pages_prefix + base_desc,
                        source_kind,
                        target_language=target_language_code,
                    )
                else:
                    # Retry: continúa la conversación; no se reenvía la fuente (cache hit).
                    segmentation, usage_meta, seg_ds_conversation = await asyncio.to_thread(
                        run_segmentador_ds,
                        deepseek_api_key,
                        segmentador_source_text,
                        base_desc,
                        source_kind,
                        target_language=target_language_code,
                        conversation=seg_ds_conversation,
                        correction=correction_suffix,
                    )
            else:
                segmentation, usage_meta = await asyncio.to_thread(
                    run_segmentador,
                    api_key,
                    file_uri,
                    seg_description,
                    MODEL_SEGMENTADOR,
                    source_mime_type,
                    source_kind,
                    target_language=target_language_code,
                )
            phase = "segmentation" if seg_attempt == 0 else f"segmentation_retry_{seg_attempt}"
            await _locked_apply_usage(usage_meta, phase=phase, cost_model=segmentation_model)
            await send_event(project_id, {"type": "usage_update", "usage": cumulative_usage})

            page_report = (
                validate_page_coverage(segmentation, content_page_set)
                if is_pdf_seg
                else None
            )

            both_valid = page_report is None or page_report.is_valid

            if both_valid:
                if seg_attempt > 0:
                    logger.info(
                        "[Process] Segmentación corregida tras reintento (páginas)",
                        extra={"project_id": project_id, "seg_attempt": seg_attempt},
                    )
                break

            logger.warning(
                "[Process] Validación de páginas fallida; se reintentará el segmentador si quedan intentos",
                extra={
                    "project_id": project_id,
                    "seg_attempt": seg_attempt,
                    "page_valid": False,
                    "page_part_errors": len(page_report.part_errors),
                    "page_subpart_errors": len(page_report.subpart_errors),
                },
            )
        else:
            assert segmentation is not None
            error_bits = []
            if page_report and not page_report.is_valid:
                if page_report.part_errors:
                    error_bits.append(f"{len(page_report.part_errors)} error(es) de rango en partes")
                if page_report.subpart_errors:
                    error_bits.append(f"{len(page_report.subpart_errors)} error(es) de rango en subpartes")
            detail = "; ".join(error_bits) if error_bits else "inconsistencias en rangos de página"
            logger.error(
                "[Process] Segmentación abortada tras agotar reintentos",
                extra={
                    "project_id": project_id,
                    "attempts": MAX_COMBINED_ATTEMPTS,
                    "detail": detail,
                },
            )
            update_project(
                project_id,
                user_id,
                {
                    "segmentation": segmentation,
                    "partes_contenido": {},
                    "status": "error",
                    "error_message": SEGMENTATION_PAGE_COVERAGE_USER_MESSAGE,
                },
            )
            await send_event(
                project_id,
                {"type": "error", "message": SEGMENTATION_PAGE_COVERAGE_USER_MESSAGE},
            )
            return

        seg_duration = (time.time() - seg_start) * 1000

        num_partes = len(segmentation.get("partes", []))
        logger.info(
            f"[Process] Segmentación completada: {num_partes} partes en {int(seg_duration)}ms",
            extra={
                "num_partes": num_partes,
                "segmentation_duration_ms": int(seg_duration),
            }
        )

        is_pdf_source = source_type == "pdf"
        is_text_source = source_type == "web"
        is_youtube_source = source_type == "youtube"

        if is_text_source:
            text_source_evaluation = _parse_text_source_evaluation(segmentation)
            source_metadata = {
                **source_metadata,
                "segmentador_evaluacion_fuente": text_source_evaluation,
            }
            if not text_source_evaluation["es_segmentable"]:
                error_message = _build_web_segmentation_rejection_message(text_source_evaluation)
                logger.warning(
                    "[Process] Segmentación rechazada por bad scrape detectado",
                    extra={
                        "project_id": project_id,
                        "motivo": text_source_evaluation["motivo"],
                        "indicios": text_source_evaluation["indicios"],
                    }
                )
                update_project(project_id, user_id, {
                    "segmentation": segmentation,
                    "partes_contenido": {},
                    "source_metadata": source_metadata,
                    "status": "error",
                    "error_message": error_message,
                })
                await send_event(project_id, {"type": "error", "message": error_message})
                return

        partes_preview = [{"numero": p["numero"], "titulo": p["titulo"]} for p in segmentation["partes"]]
        partes_contenido = {}
        for parte in segmentation["partes"]:
            partes_contenido[str(parte["numero"])] = {
                "status": "pending",
                "explainer": None,
                "recorrido": None,
                "resources": None,
            }

        update_payload = {
            "segmentation": segmentation,
            "partes_contenido": partes_contenido,
            "status": "processing",
        }
        if is_text_source:
            update_payload["source_metadata"] = source_metadata
        update_project(project_id, user_id, update_payload)
        await send_event(project_id, {"type": "segmented", "partes": partes_preview})

        # Build Table of Contents for downstream agents
        table_of_contents = ""
        if is_pdf_source:
            table_of_contents = _build_pdf_table_of_contents(segmentation, num_partes)
            logger.info(
                f"[Process] Tabla de contenidos PDF generada ({num_partes} entradas)",
                extra={"toc_preview": table_of_contents[:300]}
            )
        elif is_text_source:
            table_of_contents = _build_text_table_of_contents(segmentation, num_partes)
            logger.info(
                f"[Process] Tabla de contenidos textual generada ({num_partes} entradas)",
                extra={"toc_preview": table_of_contents[:300]}
            )
        elif is_youtube_source:
            table_of_contents = _build_youtube_table_of_contents(segmentation, num_partes)
            logger.info(
                f"[Process] Tabla de contenidos YouTube generada ({num_partes} entradas)",
                extra={"toc_preview": table_of_contents[:300]}
            )

        if mistral_pdf_prepare_task is not None:
            try:
                mistral_pdf_context = await mistral_pdf_prepare_task
                diagnostic_artifact_path = getattr(
                    mistral_pdf_context.cache_entry,
                    "diagnostic_artifact_path",
                    None,
                )
                if diagnostic_artifact_path:
                    logger.info(
                        "[Process] OCR artefacto de páginas no resueltas: %s",
                        diagnostic_artifact_path,
                        extra={"diagnostic_artifact_path": diagnostic_artifact_path},
                    )
                logger.info(
                    "[Process] OCR canónico de Mistral preparado",
                    extra={
                        "cache_hit": mistral_pdf_context.cache_entry.cache_hit,
                        "cached_pages_count": len(mistral_pdf_context.cache_entry.cached_page_numbers),
                    },
                )
            except Exception as exc:
                mistral_pdf_context = None
                logger.warning(
                    "[Process] No se pudo preparar el OCR canónico de Mistral; se usará el flujo local por parte: %s",
                    exc,
                    extra={"error_type": type(exc).__name__},
                )

        partes_segmentadas: list[dict] = segmentation["partes"]
        user_intent = _strip_str(project.get("description"))
        consideraciones = _strip_str(segmentation.get("consideraciones_estudiante"))

        # Procesar cada parte (hasta MAX_CONCURRENT_PARTS en la fase de agentes a la vez).
        logger.info(f"[Process] Comenzando procesamiento de {num_partes} partes")
        part_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PARTS)

        # SSE events may interleave per part_id; clients key off part_id (see spec 2026-04-08).
        async def process_one_parte(parte: dict) -> tuple[asyncio.Task, list[str], list[str]]:
            """Run agent phase under part_semaphore; return formatter Task and temp paths to merge."""
            local_segment_pdf_paths: list[str] = []
            local_temp_paths: list[str] = []

            part_id = parte["numero"]
            identificacion = parte["identificacion"]

            try:
                part_index = int(part_id)
            except (TypeError, ValueError):
                part_index = -1

            continuidad_previa: str | None = None
            if part_index > 1:
                prev_parte = _find_parte_by_numero(partes_segmentadas, part_index - 1)
                if prev_parte:
                    continuidad_previa = _strip_str(_continuity_block_from_previous_part(prev_parte))

            vision_global_division = consideraciones if part_index == 1 else None
            handoff = _part_handoff_base(
                parte,
                intent_usuario=user_intent,
                continuidad_previa=continuidad_previa,
                vision_global_division=vision_global_division,
            )

            # Establecer contexto para esta parte
            with LogContext(project_id=project_id, user_id=user_id, part_id=part_id):
                logger.info(
                    f"[Process] Procesando parte {part_id}/{num_partes}: {parte.get('titulo', 'Sin título')}",
                    extra={
                        "part_id": part_id,
                        "part_title": parte.get("titulo", "Sin título")[:50],
                        "part_num": part_id,
                        "total_parts": num_partes,
                    }
                )

            partes_contenido[str(part_id)]["status"] = "processing"
            await asyncio.to_thread(update_project, project_id, user_id, {"partes_contenido": partes_contenido})
            await send_event(project_id, {"type": "part_started", "part_id": part_id})

            async with part_semaphore:
                part_start = time.time()

                # For PDF: extract sub-PDF with relevant pages and upload it
                # For Web: upload only the exact text blocks for this part
                # For YouTube: use the full file_uri as before
                agent_file_uri = file_uri
                agent_mime_type = source_mime_type
                agent_prompt = identificacion
                segment_temp_path = None
                openrouter_page_scopes: list[tuple[int, ...]] = []
                openrouter_part_source_text = ""

                nucleo_pi = _optional_int(parte, "pagina_inicio")
                nucleo_pf = _optional_int(parte, "pagina_fin")

                if is_pdf_source:
                    pdf_scope_mode: Literal["subpdf_buffered", "full_document"] = "full_document"

                    if not use_text_provider_explainer and numbered_pdf_path:
                        # Gemini flow: extract a sub-PDF for this part and upload it.
                        # Text-provider flows skip this — they work entirely from OCR text.
                        pagina_inicio = parte.get("pagina_inicio")
                        pagina_fin = parte.get("pagina_fin")
                        subpdf_buffered_ok = False

                        if pagina_inicio and pagina_fin:
                            try:
                                logger.info(
                                    f"[Process] Extrayendo páginas {pagina_inicio}-{pagina_fin} (±1 buffer) para parte {part_id}",
                                    extra={"pagina_inicio": pagina_inicio, "pagina_fin": pagina_fin}
                                )
                                segment_temp_path = await asyncio.to_thread(
                                    extract_page_range, numbered_pdf_path, pagina_inicio, pagina_fin, buffer=1
                                )
                                local_segment_pdf_paths.append(segment_temp_path)
                                local_temp_paths.append(segment_temp_path)

                                seg_upload_start = time.time()
                                segment_uploaded = await asyncio.to_thread(
                                    lambda p=segment_temp_path: upload_file_with_retry(client, p, max_retries=5)
                                )
                                seg_upload_duration = (time.time() - seg_upload_start) * 1000
                                agent_file_uri = segment_uploaded.uri
                                agent_mime_type = getattr(segment_uploaded, "mime_type", None) or "application/pdf"
                                subpdf_buffered_ok = True

                                logger.info(
                                    f"[Process] Sub-PDF parte {part_id} subido en {int(seg_upload_duration)}ms",
                                    extra={
                                        "segment_uri": agent_file_uri,
                                        "seg_upload_duration_ms": int(seg_upload_duration),
                                    }
                                )
                            except Exception as seg_err:
                                logger.warning(
                                    f"[Process] Error extrayendo sub-PDF para parte {part_id}, usando PDF completo: {seg_err}",
                                    extra={"error_type": type(seg_err).__name__}
                                )
                                agent_file_uri = file_uri
                        else:
                            logger.warning(
                                f"[Process] Parte {part_id} sin pagina_inicio/pagina_fin, usando PDF completo"
                            )

                        pdf_scope_mode = "subpdf_buffered" if subpdf_buffered_ok else "full_document"

                    # Build part-level prompt (for recorrido and resources) — both flows.
                    agent_prompt = _build_pdf_agent_prompt(
                        table_of_contents,
                        identificacion,
                        part_id,
                        num_partes,
                        handoff,
                        parte,
                        partes_segmentadas,
                        pdf_scope_mode=pdf_scope_mode,
                        nucleo_inicio=nucleo_pi,
                        nucleo_fin=nucleo_pf,
                    )

                    # Build subpart-level prompts and page scopes — both flows.
                    subpartes = parte.get("subpartes") or []
                    if subpartes:
                        subpart_prompts = [
                            _build_subpart_pdf_prompt(
                                table_of_contents, parte, sp, subpartes,
                                part_id, num_partes, handoff,
                                pdf_scope_mode=pdf_scope_mode,
                                nucleo_inicio=nucleo_pi, nucleo_fin=nucleo_pf,
                            )
                            for sp in subpartes
                        ]
                        openrouter_page_scopes = [
                            _select_openrouter_pdf_pages(
                                content_page_set,
                                start_page=_optional_int(sp, "pagina_inicio") or nucleo_pi,
                                end_page=_optional_int(sp, "pagina_fin") or nucleo_pf,
                                buffer=1,
                            )
                            for sp in subpartes
                        ]
                    else:
                        subpart_prompts = [agent_prompt]
                        openrouter_page_scopes = [
                            _select_openrouter_pdf_pages(
                                content_page_set,
                                start_page=nucleo_pi,
                                end_page=nucleo_pf,
                                buffer=1,
                            )
                        ]

                    if use_text_provider_explainer:
                        if mistral_pdf_context is None:
                            raise PdfOcrError(
                                "OCR Mistral no disponible para agentes textuales de PDF."
                            )
                        openrouter_part_pages = _select_openrouter_pdf_pages(
                            content_page_set,
                            start_page=nucleo_pi,
                            end_page=nucleo_pf,
                            buffer=1,
                        )
                        openrouter_part_source_text = _render_mistral_ocr_pages_for_agents(
                            cache_entry=mistral_pdf_context.cache_entry,
                            page_numbers=openrouter_part_pages,
                        )

                elif is_text_source:
                    bloque_inicio = parte.get("bloque_inicio")
                    bloque_fin = parte.get("bloque_fin")
                    if bloque_inicio is None or bloque_fin is None:
                        raise WebExtractionError(
                            f"La parte {part_id} no incluye bloque_inicio/bloque_fin válidos. "
                            "Se aborta para no procesar texto fuera de rango."
                        )

                    selected_blocks = await asyncio.to_thread(slice_block_range, web_blocks, int(bloque_inicio), int(bloque_fin))
                    part_document = await asyncio.to_thread(
                        render_block_marked_document,
                        title=source_title or project.get("name") or "Texto web",
                        source_url=resolved_source_url or project.get("source_url") or "",
                        blocks=selected_blocks,
                    )
                    segment_temp_path = await asyncio.to_thread(write_text_document_temp, part_document)
                    local_temp_paths.append(segment_temp_path)
                    openrouter_part_source_text = part_document

                    if use_text_provider_explainer:
                        seg_upload_duration = 0.0
                        agent_file_uri = f"{explainer_provider}-text://{project_id}/part/{part_id}"
                        agent_mime_type = "text/plain"
                    else:
                        seg_upload_start = time.time()
                        if client is None:
                            raise RuntimeError("Cliente Gemini no inicializado para subir el segmento textual.")
                        segment_uploaded = await asyncio.to_thread(
                            lambda p=segment_temp_path: upload_file_with_retry(client, p, max_retries=5)
                        )
                        seg_upload_duration = (time.time() - seg_upload_start) * 1000
                        agent_file_uri = segment_uploaded.uri
                        agent_mime_type = getattr(segment_uploaded, "mime_type", None) or "text/plain"

                    logger.info(
                        f"[Process] Segmento textual parte {part_id} preparado en {int(seg_upload_duration)}ms",
                        extra={
                            "segment_uri": agent_file_uri,
                            "seg_upload_duration_ms": int(seg_upload_duration),
                            "bloque_inicio": bloque_inicio,
                            "bloque_fin": bloque_fin,
                            "text_provider_inline_source": use_text_provider_explainer,
                        }
                    )

                    # Build part-level prompt (for recorrido and resources)
                    agent_prompt = _build_text_agent_prompt(
                        table_of_contents,
                        identificacion,
                        part_id,
                        num_partes,
                        handoff,
                        parte,
                        partes_segmentadas,
                        bloque_inicio=int(bloque_inicio),
                        bloque_fin=int(bloque_fin),
                    )

                    # Build subpart-level prompts (for explainer)
                    subpartes = parte.get("subpartes") or []
                    if subpartes:
                        subpart_prompts = [
                            _build_subpart_text_prompt(
                                table_of_contents, parte, sp, subpartes,
                                part_id, num_partes, handoff,
                                bloque_inicio=int(bloque_inicio), bloque_fin=int(bloque_fin),
                            )
                            for sp in subpartes
                        ]
                    else:
                        subpart_prompts = [agent_prompt]

                elif is_youtube_source:
                    agent_prompt = _build_youtube_agent_prompt(
                        table_of_contents,
                        identificacion,
                        part_id,
                        num_partes,
                        handoff,
                        parte,
                        partes_segmentadas,
                    )

                    # Build subpart-level prompts (for explainer)
                    subpartes = parte.get("subpartes") or []
                    if subpartes:
                        subpart_prompts = [
                            _build_subpart_youtube_prompt(
                                table_of_contents, parte, sp, subpartes,
                                part_id, num_partes, handoff,
                            )
                            for sp in subpartes
                        ]
                    else:
                        subpart_prompts = [agent_prompt]

                subpartes_for_validation = parte.get("subpartes") or []
                if subpartes_for_validation:
                    subpart_validation_contexts = [
                        _build_subpart_validation_context(
                            partes_segmentadas=partes_segmentadas,
                            current_parte=parte,
                            subpart_idx=i,
                        )
                        for i in range(len(subpartes_for_validation))
                    ]
                else:
                    subpart_validation_contexts = [
                        _build_part_validation_context(
                            partes_segmentadas=partes_segmentadas,
                            current_parte=parte,
                        )
                    ]

                num_subparts = len(subpart_prompts)
                if len(subpart_validation_contexts) != num_subparts:
                    raise RuntimeError(
                        "Los contextos de validación no coinciden con el número de subprompts generados."
                    )
                use_subpart_explainer = bool(parte.get("subpartes"))

                logger.info(
                    f"[Process] Parte {part_id}: {num_subparts} subparte(s) — ejecutando agentes en paralelo",
                    extra={"part_id": part_id, "num_subparts": num_subparts}
                )

                # Fail fast before building any coroutines if OR source text is missing
                if use_text_provider_explainer and not openrouter_part_source_text:
                    raise RuntimeError(
                        "No hay texto fuente inline para los agentes textuales de esta parte."
                    )

                # Execute all subpart explainers + recorrido + resources in parallel
                agents_start = time.time()
                use_text_canonical = use_text_provider_explainer and is_pdf_source and mistral_pdf_context is not None
                use_text_direct = use_text_provider_explainer and not use_text_canonical and segment_temp_path is not None
                use_text_provider_part = use_text_canonical or use_text_direct
                text_provider_api_key = openrouter_api_key if use_openrouter_explainer else deepseek_api_key
                text_provider_explainer_fn = (
                    functools.partial(run_explainer_or, provider_routing=openrouter_provider_routing)
                    if use_openrouter_explainer else run_explainer_ds
                )
                text_provider_subpart_fn = (
                    functools.partial(run_subpart_explainer_or, provider_routing=openrouter_provider_routing)
                    if use_openrouter_explainer
                    else run_subpart_explainer_ds
                )
                if is_pdf_source:
                    enriched_validation_contexts: list[ExplainerValidationContext] = []
                    for idx, validation_context in enumerate(subpart_validation_contexts):
                        # Páginas reales que recibió el explainer de esta unidad (con buffer).
                        explainer_pages = (
                            tuple(openrouter_page_scopes[idx])
                            if idx < len(openrouter_page_scopes)
                            else ()
                        )
                        source_evidence: ExplainerSourceEvidence | None = None
                        if use_text_canonical and mistral_pdf_context is not None:
                            source_evidence = _build_mistral_ocr_validation_evidence(
                                cache_entry=mistral_pdf_context.cache_entry,
                                content_page_set=content_page_set,
                                context=validation_context,
                                explainer_pages=explainer_pages,
                            )
                        if source_evidence is None:
                            source_evidence = _build_gemini_file_validation_evidence(
                                file_uri=agent_file_uri,
                                mime_type=agent_mime_type,
                                context=validation_context,
                            )
                        enriched_validation_contexts.append(
                            _with_validation_source_evidence(validation_context, source_evidence)
                        )
                    subpart_validation_contexts = enriched_validation_contexts

                if use_subpart_explainer:
                    explainer_fn_sp = run_subpart_explainer

                    def _make_subpart_task(idx: int):
                        sp_prompt = subpart_prompts[idx]
                        validation_context = subpart_validation_contexts[idx]
                        if use_text_provider_part:
                            if use_text_canonical:
                                return asyncio.to_thread(
                                    _call_agent_with_optional_validation_context,
                                    text_provider_subpart_fn,
                                    mistral_pdf_context.source_pdf_path,
                                    sp_prompt,
                                    explainer_model,
                                    "application/pdf",
                                    text_provider_api_key,
                                    text_provider_api_key,
                                    mistral_pdf_context.cache_entry,
                                    tuple(openrouter_page_scopes[idx]),
                                    validation_context=validation_context,
                                    target_language=target_language_code,
                                )
                            return asyncio.to_thread(
                                _call_agent_with_optional_validation_context,
                                text_provider_subpart_fn,
                                segment_temp_path,
                                sp_prompt,
                                explainer_model,
                                agent_mime_type,
                                text_provider_api_key,
                                text_provider_api_key,
                                validation_context=validation_context,
                                target_language=target_language_code,
                            )
                        return asyncio.to_thread(
                            _call_agent_with_optional_validation_context,
                            explainer_fn_sp,
                            api_key,
                            agent_file_uri,
                            sp_prompt,
                            MODEL_AGENTS,
                            agent_mime_type,
                            validation_context=validation_context,
                            target_language=target_language_code,
                        )

                    if use_text_canonical:
                        if len(openrouter_page_scopes) != len(subpart_prompts):
                            raise RuntimeError(
                                "Las páginas del provider textual no coinciden con el número de subprompts generados."
                            )
                    parallel_explainer = [_make_subpart_task(i) for i in range(num_subparts)]
                elif use_text_provider_part:
                    if use_text_canonical:
                        if len(openrouter_page_scopes) != len(subpart_prompts):
                            raise RuntimeError(
                                "Las páginas del provider textual no coinciden con el número de subprompts generados."
                            )
                        parallel_explainer = [
                            asyncio.to_thread(
                                _call_agent_with_optional_validation_context,
                                text_provider_explainer_fn,
                                mistral_pdf_context.source_pdf_path,
                                sp_prompt,
                                explainer_model,
                                "application/pdf",
                                text_provider_api_key,
                                text_provider_api_key,
                                mistral_pdf_context.cache_entry,
                                page_scope,
                                validation_context=subpart_validation_contexts[idx],
                                target_language=target_language_code,
                            )
                            for idx, (sp_prompt, page_scope) in enumerate(zip(subpart_prompts, openrouter_page_scopes))
                        ]
                    else:
                        parallel_explainer = [
                            asyncio.to_thread(
                                _call_agent_with_optional_validation_context,
                                text_provider_explainer_fn,
                                segment_temp_path,
                                sp_prompt,
                                explainer_model,
                                agent_mime_type,
                                text_provider_api_key,
                                text_provider_api_key,
                                validation_context=subpart_validation_contexts[idx],
                                target_language=target_language_code,
                            )
                            for idx, sp_prompt in enumerate(subpart_prompts)
                        ]
                else:
                    explainer_fn = run_explainer
                    parallel_explainer = [
                        asyncio.to_thread(
                            _call_agent_with_optional_validation_context,
                            explainer_fn,
                            api_key,
                            agent_file_uri,
                            sp_prompt,
                            MODEL_AGENTS,
                            agent_mime_type,
                            validation_context=subpart_validation_contexts[idx],
                            target_language=target_language_code,
                        )
                        for idx, sp_prompt in enumerate(subpart_prompts)
                    ]
                if use_openrouter_explainer:
                    recorrido_task = asyncio.to_thread(
                        run_recorrido_or,
                        openrouter_api_key,
                        openrouter_part_source_text,
                        agent_prompt,
                        target_language=target_language_code,
                    )
                    resources_task = asyncio.to_thread(
                        run_resources_or,
                        openrouter_api_key,
                        openrouter_part_source_text,
                        agent_prompt,
                        target_language=target_language_code,
                    )
                elif use_deepseek_explainer:
                    recorrido_task = asyncio.to_thread(
                        run_recorrido_ds,
                        deepseek_api_key,
                        openrouter_part_source_text,
                        agent_prompt,
                        target_language=target_language_code,
                    )
                    resources_task = asyncio.to_thread(
                        run_resources_ds,
                        deepseek_api_key,
                        tavily_api_key,
                        openrouter_part_source_text,
                        agent_prompt,
                        target_language=target_language_code,
                    )
                else:
                    recorrido_task = asyncio.to_thread(
                        run_recorrido,
                        api_key,
                        agent_file_uri,
                        agent_prompt,
                        MODEL_AGENTS,
                        agent_mime_type,
                        target_language=target_language_code,
                    )
                    resources_task = asyncio.to_thread(
                        run_resources,
                        api_key,
                        agent_file_uri,
                        agent_prompt,
                        MODEL_AGENTS,
                        agent_mime_type,
                        target_language=target_language_code,
                    )

                results = await asyncio.gather(
                    *parallel_explainer,
                    recorrido_task,
                    resources_task,
                    return_exceptions=True,
                )
                agents_duration = (time.time() - agents_start) * 1000

                # Split results: first N are subpart explainers, then recorrido, then resources
                subpart_results = results[:num_subparts]
                recorrido_result = results[num_subparts]
                resources_result = results[num_subparts + 1]

                # Process subpart explainer results
                # Each sp_result is (result_dict, usage, validator_usages_list) or Exception.
                subpart_desarrollos: list[list[dict]] = []
                for i, sp_result in enumerate(subpart_results):
                    if isinstance(sp_result, Exception):
                        if isinstance(sp_result, ExplainerValidationError):
                            raise sp_result
                        logger.error(
                            f"[Process] Error en explainer subparte {i+1}/{num_subparts} de parte {part_id}: {str(sp_result)}",
                            extra={"part_id": part_id, "subpart": i+1, "error_type": type(sp_result).__name__}
                        )
                    else:
                        sp_data, _, _ = _unpack_explainer_result(sp_result)
                        subpart_desarrollos.append(sp_data.get("desarrollo") or [])

                # Assemble: intro/conclusion/conexiones from segmentador + subpart results
                if use_subpart_explainer:
                    assembled_explainer = _assemble_part_explainer(parte, subpart_desarrollos)
                else:
                    # Fallback: no subparts — use the full explainer output as-is.
                    # Both Gemini and OpenRouter now return the same structured shape.
                    if subpart_results and not isinstance(subpart_results[0], Exception):
                        assembled_explainer = _unpack_explainer_result(subpart_results[0])[0]
                    else:
                        assembled_explainer = {"error": "All explainer calls failed"}

                # Process recorrido and resources results
                recorrido_data, usage_rec = recorrido_result if not isinstance(recorrido_result, Exception) else (recorrido_result, None)
                resources_data, usage_res = resources_result if not isinstance(resources_result, Exception) else (resources_result, None)

                async with usage_lock:
                    for i, sp_result in enumerate(subpart_results):
                        if not isinstance(sp_result, Exception):
                            # sp_result is (result_dict, explainer_usage, validator_usages_list)
                            _, sp_usage, sp_val_usages = _unpack_explainer_result(sp_result)
                            if sp_usage:
                                _update_usage(
                                    sp_usage,
                                    phase=f"part_{part_id}_explainer_sp{i+1}",
                                    cost_model=explainer_model,
                                )
                            for j, val_usage in enumerate(sp_val_usages or []):
                                _update_usage(
                                    val_usage,
                                    phase=f"part_{part_id}_validator_sp{i+1}_{j+1}",
                                    cost_model=validator_model,
                                )
                    if usage_rec:
                        _update_usage(usage_rec, phase=f"part_{part_id}_recorrido", cost_model=auxiliary_agents_model)
                    if usage_res:
                        _update_usage(usage_res, phase=f"part_{part_id}_resources", cost_model=auxiliary_agents_model)
                    await asyncio.to_thread(update_project, project_id, user_id, {"usage": cumulative_usage})
                    await send_event(project_id, {"type": "usage_update", "usage": cumulative_usage})

                # Store explainer (assembled) and notify
                if isinstance(assembled_explainer, dict) and "error" in assembled_explainer:
                    partes_contenido[str(part_id)]["explainer"] = assembled_explainer
                else:
                    partes_contenido[str(part_id)]["explainer"] = assembled_explainer
                await send_event(project_id, {"type": "agent_completed", "part_id": part_id, "agent": "explainer"})

                # Store recorrido and resources
                for result, agent_name in [
                    (recorrido_data, "recorrido"),
                    (resources_data, "resources"),
                ]:
                    if isinstance(result, Exception):
                        logger.error(
                            f"[Process] Error en agente {agent_name} para parte {part_id}: {str(result)}",
                            extra={
                                "part_id": part_id,
                                "agent": agent_name,
                                "error_type": type(result).__name__,
                                "error_message": str(result)[:500],
                            }
                        )
                        partes_contenido[str(part_id)][agent_name] = {"error": str(result)}
                    else:
                        logger.debug(f"[Process] Agente {agent_name} completado para parte {part_id}")
                        partes_contenido[str(part_id)][agent_name] = result
                    await send_event(project_id, {"type": "agent_completed", "part_id": part_id, "agent": agent_name})

                agents_elapsed_ms = int((time.time() - part_start) * 1000)
                logger.info(
                    f"[Process] Agentes de parte {part_id} completados en {agents_elapsed_ms}ms "
                    f"({num_subparts} subparte(s), agentes: {int(agents_duration)}ms) — iniciando formatter en background",
                    extra={
                        "part_id": part_id,
                        "num_subparts": num_subparts,
                        "agents_elapsed_ms": agents_elapsed_ms,
                        "agents_duration_ms": int(agents_duration),
                        "cumulative_tokens": cumulative_usage["total_tokens"],
                        "cumulative_cost": round(cumulative_usage["total_cost"], 6),
                    }
                )

            # Fire the formatter as a background task so the next section's agents
            # can start immediately without waiting for this formatting pass.
            # The formatter task itself sets status=completed, saves to Supabase,
            # and sends the part_completed SSE event when it finishes.
            formatter_task = asyncio.create_task(
                _format_and_finalize_part(
                    project_id,
                    user_id,
                    api_key,
                    part_id,
                    assembled_explainer,
                    partes_contenido,
                    use_openrouter=use_openrouter_explainer,
                    openrouter_api_key=openrouter_api_key,
                    target_language=target_language_code,
                    use_deepseek=use_deepseek_explainer,
                    deepseek_api_key=deepseek_api_key,
                )
            )
            return formatter_task, local_segment_pdf_paths, local_temp_paths

        part_results = await asyncio.gather(
            *[process_one_parte(p) for p in partes_segmentadas],
        )
        formatter_tasks: list[asyncio.Task] = []
        for formatter_task, seg_paths, tmp_paths in part_results:
            formatter_tasks.append(formatter_task)
            segment_pdf_paths.extend(seg_paths)
            temp_paths.extend(tmp_paths)

        # Esperar a que todos los formatters terminen antes de marcar el proyecto como completado.
        # Los formatter_tasks ya se están ejecutando en paralelo con los agentes de secciones
        # posteriores; aquí solo esperamos a que los últimos en terminar concluyan.
        if formatter_tasks:
            logger.info(
                f"[Process] Esperando a {len(formatter_tasks)} formatter task(s) pendientes…"
            )
            await asyncio.gather(*formatter_tasks, return_exceptions=True)

        # Aggregate formatter costs from partes_contenido (all tasks finished → no race).
        total_fmt_input = total_fmt_output = 0
        total_fmt_cost = 0.0
        for pdata in partes_contenido.values():
            fu = pdata.get("formatter_usage") or {}
            total_fmt_input  += fu.get("input_tokens", 0)
            total_fmt_output += fu.get("output_tokens", 0)
            total_fmt_cost   += fu.get("cost", 0.0)

        if total_fmt_cost > 0:
            cumulative_usage["formatter_tokens"] = total_fmt_input + total_fmt_output
            cumulative_usage["formatter_cost"]   = round(total_fmt_cost, 6)
            cumulative_usage["total_cost"]       = round(
                cumulative_usage["total_cost"] + total_fmt_cost, 6
            )
            update_project(project_id, user_id, {"usage": cumulative_usage})
            await send_event(project_id, {"type": "usage_update", "usage": cumulative_usage})
            logger.info(
                f"[Process] Coste del formatter: ${total_fmt_cost:.6f} "
                f"({total_fmt_input + total_fmt_output} tokens)",
                extra={
                    "formatter_tokens": total_fmt_input + total_fmt_output,
                    "formatter_cost": round(total_fmt_cost, 6),
                    "cumulative_cost": round(cumulative_usage["total_cost"], 6),
                },
            )

        # Marcar proyecto como completado
        total_duration = (time.time() - process_start_time) * 1000
        logger.info(
            f"[Process] Proyecto completado exitosamente en {int(total_duration)}ms",
            extra={
                "total_duration_ms": int(total_duration),
                "total_parts_processed": num_partes,
                "total_tokens": cumulative_usage["total_tokens"],
                "total_cost": round(cumulative_usage["total_cost"], 6),
                "source_type": source_type,
            }
        )

        update_project(project_id, user_id, {"status": "completed"})
        await send_event(project_id, {"type": "completed"})

    except ExplainerValidationError as exc:
        error_msg = (
            "Se abortó el procesamiento porque el validador confirmó que una explicación "
            f"seguía fuera de alcance o incompleta tras los reintentos: {exc.report.reason}"
        )
        logger.error(
            "[Process] Validación de explainer fallida: %s",
            exc.report.reason[:300],
            extra={
                "error_type": "ExplainerValidationError",
                "project_id": project_id,
                "label": exc.label,
                "is_complete": exc.report.is_complete,
                "scope_status": exc.report.scope_status,
            },
        )
        update_project(project_id, user_id, {"status": "error", "error_message": error_msg})
        await send_event(project_id, {"type": "error", "message": error_msg})
    except GeminiRateLimitError as exc:
        # Error específico de rate limit - mensaje amigable
        error_msg = (
            "Se ha excedido el límite de peticiones a Gemini API (429). "
            "El sistema reintentó automáticamente varias veces sin éxito. "
            "Por favor, espera unos minutos e intenta de nuevo, "
            "o considera solicitar un aumento de cuota en Google AI Studio."
        )
        logger.error(
            f"[Process] Error de rate limit (429): {exc.message[:200]}",
            extra={
                "error_type": "GeminiRateLimitError",
                "status_code": 429,
                "project_id": project_id,
            }
        )
        update_project(project_id, user_id, {"status": "error", "error_message": error_msg})
        await send_event(project_id, {"type": "error", "message": error_msg})
    except GeminiError as exc:
        # Error específico de Gemini API con código de estado
        if exc.status_code == 500:
            error_msg = (
                "Error interno en Gemini API (500). "
                "El sistema reintentó automáticamente pero el servicio sigue fallando. "
                "Espera unos minutos e inténtalo de nuevo."
            )
        elif exc.status_code == 503:
            error_msg = (
                "Servicio Gemini API temporalmente no disponible (503). "
                "El sistema reintentó varias veces sin éxito. "
                "Por favor, espera unos minutos e intenta de nuevo."
            )
        elif exc.status_code == 504:
            error_msg = (
                "Timeout procesando la petición en Gemini API (504). "
                "El texto puede ser demasiado largo o complejo. "
                "Prueba con un documento más corto o espera e inténtalo de nuevo."
            )
        elif exc.status_code == 400:
            error_msg = f"Error en la petición a Gemini API (400): {exc.message}"
        elif exc.status_code == 403:
            error_msg = (
                "Error de permisos en Gemini API (403). "
                "Verifica que tu API key sea válida y tenga acceso a los modelos Gemini necesarios."
            )
        else:
            error_msg = f"Error en Gemini API (code={exc.status_code}): {exc.message}"

        logger.error(
            f"[Process] Error de Gemini API ({exc.status_code}): {exc.message[:200]}",
            extra={
                "error_type": "GeminiError",
                "status_code": exc.status_code,
                "project_id": project_id,
                "error_details": exc.details if hasattr(exc, "details") else None,
            }
        )
        update_project(project_id, user_id, {"status": "error", "error_message": error_msg})
        await send_event(project_id, {"type": "error", "message": error_msg})
    except Exception as exc:
        # Error genérico - mostrar mensaje simplificado pero log completo
        error_str = str(exc)
        if len(error_str) > 200:
            error_str_short = error_str[:200] + "..."
        else:
            error_str_short = error_str
        error_msg = f"Error inesperado durante el procesamiento: {error_str_short}"

        logger.exception(
            f"[Process] Error inesperado: {error_str[:500]}",
            extra={
                "error_type": type(exc).__name__,
                "project_id": project_id,
                "user_id": user_id[:8] + "..." if len(user_id) > 8 else user_id,
            }
        )
        update_project(project_id, user_id, {"status": "error", "error_message": error_msg})
        await send_event(project_id, {"type": "error", "message": error_msg})
    finally:
        if mistral_pdf_prepare_task is not None:
            try:
                if not mistral_pdf_prepare_task.done():
                    mistral_pdf_prepare_task.cancel()
                    try:
                        await mistral_pdf_prepare_task
                    except asyncio.CancelledError:
                        pass
                elif mistral_pdf_context is None:
                    mistral_pdf_prepare_task.result()  # surface stored exception for logging
            except Exception as exc:
                logger.debug(
                    "[Process] Cierre del task OCR canónico Mistral sin contexto reutilizable",
                    extra={
                        "project_id": project_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:300],
                    },
                )

        # Clean up all temporary files created during processing.
        for temp_path in dict.fromkeys(temp_paths):
            if temp_path and os.path.isfile(temp_path):
                try:
                    os.unlink(temp_path)
                    logger.debug(f"[Process] Archivo temporal eliminado: {temp_path}")
                except OSError as e:
                    logger.warning(f"[Process] No se pudo eliminar archivo temporal {temp_path}: {e}")
        if (
            source_type == "pdf"
            and project is not None
            and project.get("source_object_status") == SOURCE_OBJECT_STATUS_STORED
        ):
            try:
                await asyncio.to_thread(
                    delete_project_source_object,
                    project_id,
                    user_id,
                    project=project,
                )
                logger.info(
                    "[Process] PDF fuente eliminado de Supabase tras finalizar el procesamiento",
                    extra={"project_id": project_id},
                )
            except Exception as exc:
                logger.warning(
                    "[Process] No se pudo eliminar el PDF fuente en Supabase (project_id=%s): %s",
                    project_id,
                    exc,
                )
        await sse_manager.end_stream(project_id)
        logger.debug(f"[Process] Stream SSE cerrado para proyecto: {project_id}")


@app.post("/api/projects/{project_id}/reformat")
async def api_reformat_project(
    project_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> dict:
    """Apply the markdown formatting pass to all unformatted completed parts.

    This endpoint is idempotent: parts that already have `formatter_version`
    set are skipped.  All eligible parts are formatted in a single parallel
    batch (asyncio.gather), so total latency is roughly equal to the time
    needed to format the largest single section.
    """
    project = get_project(project_id, user_id, include_internal=True)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    if project["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail="El proyecto debe estar completado para poder reformatear.",
        )

    project_usage = project.get("usage") or {}
    use_openrouter = project_usage.get("explainer_provider") == EXPLAINER_PROVIDER_OPENROUTER
    use_deepseek = project_usage.get("explainer_provider") == EXPLAINER_PROVIDER_DEEPSEEK

    if use_openrouter:
        api_key = get_user_api_key(user_id, provider=PROVIDER_OPENROUTER)
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No hay API key de OpenRouter configurada. "
                    "Guárdala en Ajustes para reformatear este proyecto."
                ),
            )
    elif use_deepseek:
        api_key = get_user_api_key(user_id, provider=PROVIDER_DEEPSEEK)
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No hay API key de DeepSeek configurada. "
                    "Guárdala en Ajustes para reformatear este proyecto."
                ),
            )
    else:
        api_key = get_user_api_key(user_id, provider=PROVIDER_GEMINI)
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail="No hay API key de Gemini configurada. Configúrala en Ajustes.",
            )

    partes_contenido: dict = dict(project.get("partes_contenido") or {})

    reformat_target_language = normalize_target_language((project.get("source_metadata") or {}).get("target_language")).code

    async def _fmt_part(pid: str, part_data: dict) -> tuple[str, dict]:
        explainer = part_data.get("explainer")
        if (
            explainer
            and isinstance(explainer, dict)
            and "error" not in explainer
        ):
            if use_deepseek:
                formatted, fmt_usage = await format_explainer_content_ds(api_key, explainer, reformat_target_language)
            elif use_openrouter:
                formatted, fmt_usage = await format_explainer_content_or(api_key, explainer, reformat_target_language)
            else:
                formatted, fmt_usage = await format_explainer_content(api_key, explainer, reformat_target_language)
            return pid, {**part_data, "explainer": formatted, "formatter_usage": fmt_usage, "formatter_version": 1}
        # No explainer or explainer errored — just mark version so we skip next time.
        return pid, {**part_data, "formatter_usage": {}, "formatter_version": 1}

    # Only process parts that are completed, have explainer data, and haven't
    # been formatted yet.
    tasks = [
        _fmt_part(pid, dict(pdata))
        for pid, pdata in partes_contenido.items()
        if (
            pdata.get("status") == "completed"
            and pdata.get("explainer")
            and not pdata.get("formatter_version")
        )
    ]

    if not tasks:
        logger.info(
            f"[Reformat] Proyecto {project_id}: sin partes pendientes de formateo.",
            extra={"project_id": project_id},
        )
        return {"ok": True, "reformatted": 0}

    logger.info(
        f"[Reformat] Proyecto {project_id}: reformateando {len(tasks)} parte(s) en paralelo…",
        extra={"project_id": project_id, "total_parts": len(tasks)},
    )
    reformat_start = time.time()

    results = await asyncio.gather(*tasks, return_exceptions=True)

    reformatted = 0
    total_fmt_input = total_fmt_output = 0
    total_fmt_cost = 0.0
    for r in results:
        if isinstance(r, Exception):
            logger.warning(
                f"[Reformat] Error en una parte: {r}",
                extra={"error": str(r)[:300]},
            )
            continue
        pid, updated_part = r
        partes_contenido[pid] = updated_part
        fu = updated_part.get("formatter_usage") or {}
        total_fmt_input  += fu.get("input_tokens", 0)
        total_fmt_output += fu.get("output_tokens", 0)
        total_fmt_cost   += fu.get("cost", 0.0)
        reformatted += 1

    if reformatted > 0:
        update_project(project_id, user_id, {"partes_contenido": partes_contenido})

    # Update project-level usage with formatter costs.
    if total_fmt_cost > 0:
        project_usage: dict = dict(project.get("usage") or {})
        project_usage["formatter_tokens"] = (
            project_usage.get("formatter_tokens", 0) + total_fmt_input + total_fmt_output
        )
        project_usage["formatter_cost"] = round(
            project_usage.get("formatter_cost", 0.0) + total_fmt_cost, 6
        )
        project_usage["total_cost"] = round(
            project_usage.get("total_cost", 0.0) + total_fmt_cost, 6
        )
        update_project(project_id, user_id, {"usage": project_usage})

    elapsed_ms = int((time.time() - reformat_start) * 1000)
    logger.info(
        f"[Reformat] Proyecto {project_id}: {reformatted}/{len(tasks)} partes formateadas "
        f"en {elapsed_ms}ms (coste formatter: ${total_fmt_cost:.6f})",
        extra={
            "project_id": project_id,
            "reformatted": reformatted,
            "total": len(tasks),
            "elapsed_ms": elapsed_ms,
            "formatter_cost": round(total_fmt_cost, 6),
        },
    )
    return {"ok": True, "reformatted": reformatted, "formatter_cost": round(total_fmt_cost, 6)}


@app.post("/api/projects/{project_id}/process")
async def api_process_project(
    user_id: Annotated[str, Depends(get_current_user_id)],
    project_id: str,
    background_tasks: BackgroundTasks,
    payload: ProcessProjectRequest | None = Body(default=None),
):
    """Start processing a project using the user's own API key (BYOK)."""
    explainer_provider = payload.explainer_provider if payload else EXPLAINER_PROVIDER_GEMINI
    openrouter_model = payload.openrouter_model if payload else None
    deepseek_model = payload.deepseek_model if payload else None
    openrouter_provider = payload.openrouter_provider if payload else None
    openrouter_provider_only = payload.openrouter_provider_only if payload else False
    try:
        target_language_obj = normalize_target_language(payload.target_language if payload else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    target_language_code = target_language_obj.code
    try:
        explainer_model = _resolve_explainer_model(
            explainer_provider,
            openrouter_model,
            deepseek_model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info(
        f"[API] Solicitud de procesamiento recibida",
        extra={
            "project_id": project_id,
            "user_id": user_id[:8] + "..." if len(user_id) > 8 else user_id,
            "endpoint": "POST /api/projects/{project_id}/process",
            "explainer_provider": explainer_provider,
            "explainer_model": explainer_model,
            "target_language": target_language_code,
        }
    )

    project = get_project(project_id, user_id, include_internal=True)
    if not project:
        logger.warning(f"[API] Proyecto no encontrado: {project_id}")
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    if project["status"] not in ("pending", "error"):
        logger.warning(
            f"[API] Proyecto ya está en estado '{project['status']}'",
            extra={"project_id": project_id, "current_status": project["status"]}
        )
        raise HTTPException(status_code=400, detail=f"El proyecto ya está en estado '{project['status']}'")

    source_object_status = project.get("source_object_status")
    if (
        project.get("source_type") == "pdf"
        and source_object_status is not None
        and source_object_status != SOURCE_OBJECT_STATUS_STORED
    ):
        logger.warning(
            "[API] Reintento de procesamiento sin PDF fuente disponible",
            extra={
                "project_id": project_id,
                "source_object_status": source_object_status,
            },
        )
        raise HTTPException(status_code=400, detail=MISSING_PDF_SOURCE_ERROR_MESSAGE)

    source_type = project.get("source_type", "pdf")
    requires_gemini_key = (
        explainer_provider != EXPLAINER_PROVIDER_DEEPSEEK
        or source_type == "youtube"
    )
    if requires_gemini_key and not has_user_api_key(user_id, provider=PROVIDER_GEMINI):
        logger.warning(f"[API] Usuario sin API key configurada: {user_id[:8]}...")
        raise HTTPException(status_code=400, detail="No hay API key de Gemini configurada. Configúrala en Ajustes.")

    if explainer_provider == EXPLAINER_PROVIDER_OPENROUTER and source_type != "youtube":
        # YouTube always falls back to Gemini automatically — skip OpenRouter key checks for that source type
        if not has_user_api_key(user_id, provider=PROVIDER_OPENROUTER):
            logger.warning(f"[API] Usuario sin API key OpenRouter configurada: {user_id[:8]}...")
            raise HTTPException(
                status_code=400,
                detail="No hay API key de OpenRouter configurada. Guárdala en Ajustes para usar OpenRouter en este flujo.",
            )
        if source_type == "pdf" and not has_user_api_key(user_id, provider=PROVIDER_MISTRAL):
            logger.warning(f"[API] Usuario sin API key Mistral configurada para PDF con OpenRouter: {user_id[:8]}...")
            raise HTTPException(
                status_code=400,
                detail="No hay API key de Mistral configurada. Guárdala en Ajustes para usar OCR nativo en PDFs con OpenRouter.",
            )
    elif explainer_provider == EXPLAINER_PROVIDER_DEEPSEEK and source_type != "youtube":
        # YouTube always falls back to Gemini automatically — skip DeepSeek key checks for that source type.
        if not has_user_api_key(user_id, provider=PROVIDER_DEEPSEEK):
            logger.warning(f"[API] Usuario sin API key DeepSeek configurada: {user_id[:8]}...")
            raise HTTPException(
                status_code=400,
                detail="No hay API key de DeepSeek configurada. Guárdala en Ajustes para usar DeepSeek directo.",
            )
        if not has_user_api_key(user_id, provider=PROVIDER_TAVILY):
            logger.warning(f"[API] Usuario sin API key Tavily configurada: {user_id[:8]}...")
            raise HTTPException(
                status_code=400,
                detail="No hay API key de Tavily configurada. Guárdala en Ajustes para verificar recursos con DeepSeek.",
            )
        if source_type == "pdf" and not has_user_api_key(user_id, provider=PROVIDER_MISTRAL):
            logger.warning(f"[API] Usuario sin API key Mistral configurada para PDF con DeepSeek: {user_id[:8]}...")
            raise HTTPException(
                status_code=400,
                detail="No hay API key de Mistral configurada. Guárdala en Ajustes para usar OCR nativo en PDFs con DeepSeek.",
            )

    logger.info(
        f"[API] Iniciando procesamiento en background",
        extra={
            "project_id": project_id,
            "project_name": project.get("name", "unnamed"),
            "source_type": source_type,
            "segmentation_model": MODEL_SEGMENTADOR,
            "agents_model": MODEL_AGENTS,
            "explainer_provider": explainer_provider,
            "explainer_model": explainer_model,
            "target_language": target_language_code,
        }
    )
    openrouter_provider_routing = _build_openrouter_provider_routing(
        openrouter_provider, openrouter_provider_only
    )
    background_tasks.add_task(
        _process_project,
        project_id,
        user_id,
        explainer_provider,
        openrouter_model,
        deepseek_model,
        target_language_code,
        openrouter_provider_routing,
    )
    return {
        "ok": True,
        "status": "started",
        "explainer_provider": explainer_provider,
        "explainer_model": explainer_model,
        "target_language": target_language_code,
    }


@app.post("/api/projects/{project_id}/parts/{part_id}/mermaid")
async def api_generate_mermaid(
    user_id: Annotated[str, Depends(get_current_user_id)],
    project_id: str,
    part_id: str,
) -> dict:
    """Generate (or return cached) Mermaid diagram for a completed part."""
    project = get_project(project_id, user_id, include_internal=True)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    if project["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail="El proyecto debe estar completado para generar el esquema.",
        )

    partes_contenido: dict = dict(project.get("partes_contenido") or {})
    part_data = partes_contenido.get(part_id)
    if not part_data:
        raise HTTPException(status_code=404, detail=f"Parte {part_id} no encontrada")

    explainer = part_data.get("explainer")
    if not explainer or isinstance(explainer, dict) and explainer.get("error"):
        raise HTTPException(
            status_code=400,
            detail="La explicación de esta parte no está disponible o tiene errores.",
        )

    # Cache hit — return immediately without calling the API
    cached = part_data.get("mermaid")
    if cached and isinstance(cached, dict) and not cached.get("error"):
        return {"ok": True, "mermaid": cached, "cached": True}

    api_key = get_user_api_key(user_id)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="No hay API key de Gemini configurada. Configúrala en Ajustes.",
        )

    explanation_text = assemble_explanation_text(explainer)

    try:
        result_dict, usage_meta = await asyncio.to_thread(
            generate_mermaid, api_key, explanation_text, MODEL_MERMAID
        )
    except Exception as exc:
        err_str = str(exc)
        logger.error(
            f"[Mermaid] Error generando diagrama para parte {part_id}: {err_str[:300]}",
            extra={"project_id": project_id, "part_id": part_id},
        )
        partes_contenido[part_id] = {**part_data, "mermaid": {"error": err_str}}
        update_project(project_id, user_id, {"partes_contenido": partes_contenido})
        raise HTTPException(status_code=500, detail=f"Error generando el esquema: {err_str[:200]}")

    partes_contenido[part_id] = {**part_data, "mermaid": result_dict}
    update_project(project_id, user_id, {"partes_contenido": partes_contenido})

    if usage_meta:
        project_usage: dict = dict(project.get("usage") or {})
        mermaid_tokens = (
            getattr(usage_meta, "prompt_token_count", 0)
            + getattr(usage_meta, "candidates_token_count", 0)
            + getattr(usage_meta, "thoughts_token_count", 0)
        )
        project_usage["mermaid_tokens"] = project_usage.get("mermaid_tokens", 0) + mermaid_tokens
        update_project(project_id, user_id, {"usage": project_usage})

    logger.info(
        f"[Mermaid] Diagrama generado para proyecto {project_id} parte {part_id}",
        extra={"project_id": project_id, "part_id": part_id},
    )
    return {"ok": True, "mermaid": result_dict, "cached": False}


@app.get("/api/projects/{project_id}/events")
async def api_project_events(
    project_id: str,
    token: str | None = Query(None, alias="token"),
):
    user_id = get_user_id_from_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Token requerido (query: token=...)")
    if not get_project(project_id, user_id):
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    async def generate() -> AsyncGenerator[str, None]:
        async for event in sse_manager.subscribe_events(project_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\\n\\n"
            if event.get("type") == "stream_end":
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# config.js se regenera en cada arranque (start.bat / build) desde EXPLAINER_SUPABASE_*.
# Debe servirse SIN caché: si el navegador reutiliza una copia vieja (p. ej. de un arranque
# previo sin config), el frontend ve SUPABASE_URL/ANON_KEY vacíos y muestra
# "Supabase no configurado". no-store fuerza recarga fresca siempre.
@app.get("/config.js")
async def frontend_config_js():
    config_path = os.path.join("frontend", "config.js")
    if not os.path.isfile(config_path):
        raise HTTPException(status_code=404, detail="config.js no generado")
    return FileResponse(
        config_path,
        media_type="text/javascript",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


# ---- OpenRouter live models proxy (TTL cache + graceful degradation) ----

_cache: dict = {}
_cache_lock = threading.Lock()
CACHE_TTL = 3600  # 1 hour


def _cache_get(key: tuple) -> tuple[Any, bool]:
    """Return (value, stale=False) from cache, or (None, False) on miss."""
    with _cache_lock:
        if key in _cache:
            value, ts = _cache[key]
            if time.monotonic() - ts < CACHE_TTL:
                return value, False
    return None, False


def _cache_set(key: tuple, value: Any) -> None:
    with _cache_lock:
        _cache[key] = (value, time.monotonic())


def _cache_get_stale(key: tuple) -> tuple[Any, bool]:
    """Return cached value even if expired (for degradation)."""
    with _cache_lock:
        if key in _cache:
            return _cache[key][0], True
    return None, False


async def _fetch_openrouter_models() -> tuple[list[dict], bool]:
    """Returns (normalized_models_list, stale_bool) or raises."""
    # 1. Try cache first (non-stale)
    cached, _ = _cache_get(("models",))
    if cached is not None:
        return cached, False

    # 2. Fetch from OpenRouter
    try:
        resp = await asyncio.to_thread(
            lambda: requests.get(
                "https://openrouter.ai/api/v1/models",
                headers={"User-Agent": "Explainer/1.0"},
                params={"output_modalities": "text"},
                timeout=15,
            )
        )
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            normalized = [
                {
                    "id": m["id"],
                    "name": m.get("name", m["id"]),
                    "context_length": m.get("context_length", 0),
                    "prompt_price": float(m.get("pricing", {}).get("prompt", 0)),
                    "completion_price": float(m.get("pricing", {}).get("completion", 0)),
                }
                for m in data
                if m.get("id")
                and "text" in (m.get("architecture", {}).get("output_modalities") or [])
            ]
            _cache_set(("models",), normalized)
            return normalized, False
    except Exception:
        pass

    # 3. Degradation: serve stale cache
    stale, _ = _cache_get_stale(("models",))
    if stale is not None:
        return stale, True

    # 4. Nothing works
    raise HTTPException(
        status_code=503,
        detail="No se pudo obtener la lista de modelos de OpenRouter. Inténtalo de nuevo en un momento.",
    )


async def _fetch_openrouter_endpoints(model: str) -> tuple[list[str], bool]:
    """Returns (providers_list, stale_bool) or raises."""
    # 1. Try cache first (non-stale)
    cached, _ = _cache_get(("endpoints", model))
    if cached is not None:
        return cached, False

    # 2. Fetch from OpenRouter
    try:
        resp = await asyncio.to_thread(
            lambda: requests.get(
                f"https://openrouter.ai/api/v1/models/{model}/endpoints",
                headers={"User-Agent": "Explainer/1.0"},
                timeout=15,
            )
        )
        if resp.status_code == 200:
            payload = resp.json()
            endpoints = payload.get("data", {}).get("endpoints", [])
            providers = [
                ep.get("id") or ep.get("slug") or ep.get("name") or ""
                for ep in endpoints
                if isinstance(ep, dict)
                and (ep.get("id") or ep.get("slug") or ep.get("name"))
            ]
            _cache_set(("endpoints", model), providers)
            return providers, False
    except Exception:
        pass

    # 3. Degradation: serve stale cache
    stale, _ = _cache_get_stale(("endpoints", model))
    if stale is not None:
        return stale, True

    # 4. Nothing works
    raise HTTPException(
        status_code=503,
        detail=(
            f"No se pudieron obtener los endpoints de OpenRouter "
            f"para el modelo '{model}'. Inténtalo de nuevo en un momento."
        ),
    )


def _validate_model_id(model: str) -> str:
    """Validate model id format. Returns cleaned model id or raises 400."""
    model = model.strip()
    if not re.match(r"^[\w.-]+/[\w.:-]+$", model):
        raise HTTPException(
            status_code=400,
            detail=f"ID de modelo inválido: '{model}'. Debe tener formato 'author/slug'.",
        )
    return model


@app.get("/api/openrouter/models")
async def get_openrouter_models(user_id: str = Depends(get_current_user_id)):
    """Return cached or live list of OpenRouter models."""
    models, stale = await _fetch_openrouter_models()
    return {
        "models": models,
        "stale": stale,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


@app.get("/api/openrouter/models/endpoints")
async def get_openrouter_endpoints(
    model: str = Query(..., description="Model ID in 'author/slug' format"),
    user_id: str = Depends(get_current_user_id),
):
    """Return cached or live list of providers/endpoints for a model."""
    validated_model = _validate_model_id(model)
    providers, stale = await _fetch_openrouter_endpoints(validated_model)
    return {
        "providers": providers,
        "stale": stale,
    }


if os.environ.get("ENVIRONMENT") != "production":
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
else:
    @app.get("/")
    async def root():
        return FileResponse("frontend/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
