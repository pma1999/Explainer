"""Explainer API con autenticación Supabase y persistencia en Postgres + Storage."""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from typing import Annotated, AsyncGenerator
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile

ALLOWED_MODELS = {"gemini-3-flash-preview", "gemini-3.1-pro-preview"}
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
    list_projects,
    update_project,
    set_section_read_status,
    delete_project,
    export_projects_payload,
    import_projects_payload,
    download_pdf_to_temp,
    get_user_api_key,
    set_user_api_key,
    delete_user_api_key,
    has_user_api_key,
    get_user_api_key_status,
)
from backend.crypto import mask_api_key
from backend.sse_manager import sse_manager, send_event
from backend.rate_limit import api_key_rate_limit, project_create_rate_limit
from backend.pricing import calculate_cost
from backend.gemini_client import upload_file_with_retry, GeminiError, GeminiRateLimitError
from backend.agents.segmentador import run_segmentador
from backend.agents.explainer import run_explainer
from backend.agents.recorrido import run_recorrido
from backend.agents.resources import run_resources
from backend.agents.formatter import format_explainer_content
from backend.middleware import SecurityHeadersMiddleware, RequestLoggingMiddleware
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


# Configurar logging al importar el módulo
setup_logging()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[Startup] Explainer API iniciada - Persistencia en Supabase")
    yield
    logger.info("[Shutdown] Cerrando aplicación")


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


@app.post("/api/settings/api-key")
@api_key_rate_limit
async def api_set_api_key(
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
    api_key: str = Form(...),
):
    """Store user's API key (BYOK)."""
    api_key = _validate_gemini_api_key(api_key)
    set_user_api_key(user_id, api_key, provider="google_gemini")
    logger.info("[API Key] User %s... configured API key: %s", user_id[:8], mask_api_key(api_key))
    return {"ok": True}


@app.delete("/api/settings/api-key")
@api_key_rate_limit
async def api_delete_api_key(
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
):
    """Delete user's API key."""
    delete_user_api_key(user_id)
    logger.info("[API Key] User %s... deleted their API key", user_id[:8])
    return {"ok": True}


@app.get("/api/settings/api-key/status")
async def api_api_key_status(user_id: Annotated[str, Depends(get_current_user_id)]):
    """Get API key status for the authenticated user."""
    return get_user_api_key_status(user_id)


def _extract_youtube_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    import re

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
    return list_projects(user_id)


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
    part_id = body.get("part_id")
    if part_id is None:
        raise HTTPException(status_code=400, detail="part_id requerido")
    try:
        part_id = int(part_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="part_id debe ser un número")

    completed = body.get("completed", True)
    if not isinstance(completed, bool):
        completed = True

    project = get_project(project_id, user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    partes = project.get("segmentation") or {}
    partes_list = partes.get("partes") or []
    if not any(p.get("numero") == part_id for p in partes_list):
        raise HTTPException(status_code=400, detail="Sección no encontrada")

    contenido = project.get("partes_contenido") or {}
    part_status = contenido.get(str(part_id), {}).get("status")
    if part_status != "completed":
        raise HTTPException(status_code=400, detail="El contenido de esta sección aún no está listo")

    updated = set_section_read_status(project_id, user_id, part_id, completed)
    if not updated:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return updated


@app.delete("/api/projects/{project_id}")
async def api_delete_project(
    user_id: Annotated[str, Depends(get_current_user_id)],
    project_id: str,
):
    if not get_project(project_id, user_id):
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    delete_project(project_id, user_id)
    return {"ok": True}


def _build_pdf_table_of_contents(segmentation: dict, num_partes: int) -> str:
    toc_lines = ["TABLA DE CONTENIDOS DEL DOCUMENTO COMPLETO:"]
    for p in segmentation["partes"]:
        pg_start = p.get("pagina_inicio", "?")
        pg_end = p.get("pagina_fin", "?")
        toc_lines.append(
            f"  Parte {p['numero']}/{num_partes}: \"{p['titulo']}\" (Páginas {pg_start}-{pg_end})"
        )
    return "\n".join(toc_lines)


def _build_text_table_of_contents(segmentation: dict, num_partes: int) -> str:
    toc_lines = ["TABLA DE CONTENIDOS DEL TEXTO COMPLETO:"]
    for p in segmentation["partes"]:
        block_start = p.get("bloque_inicio", "?")
        block_end = p.get("bloque_fin", "?")
        toc_lines.append(
            f"  Parte {p['numero']}/{num_partes}: \"{p['titulo']}\" (Bloques {block_start}-{block_end})"
        )
    return "\n".join(toc_lines)


def _build_pdf_agent_prompt(table_of_contents: str, identificacion: str, part_id: int, num_partes: int) -> str:
    toc_with_marker = table_of_contents.replace(
        f"  Parte {part_id}/{num_partes}:",
        f"  ▶ Parte {part_id}/{num_partes} [PARTE ACTUAL]:"
    )
    return (
        f"{toc_with_marker}\n\n"
        f"---\n\n"
        f"INSTRUCCIONES PARA ESTA PARTE:\n"
        f"Procesa ÚNICAMENTE la Parte {part_id}/{num_partes}. "
        f"El PDF adjunto contiene las páginas relevantes para esta parte. "
        f"La tabla de contenidos anterior muestra la estructura completa del documento "
        f"para que tengas contexto de dónde se sitúa esta parte.\n\n"
        f"IDENTIFICACIÓN DE LA PARTE:\n{identificacion}"
    )


def _build_text_agent_prompt(table_of_contents: str, identificacion: str, part_id: int, num_partes: int) -> str:
    toc_with_marker = table_of_contents.replace(
        f"  Parte {part_id}/{num_partes}:",
        f"  ▶ Parte {part_id}/{num_partes} [PARTE ACTUAL]:"
    )
    return (
        f"{toc_with_marker}\n\n"
        f"---\n\n"
        f"INSTRUCCIONES PARA ESTA PARTE:\n"
        f"Procesa ÚNICAMENTE la Parte {part_id}/{num_partes}. "
        f"El archivo de texto adjunto contiene exclusivamente los bloques relevantes de esta parte. "
        f"La tabla de contenidos anterior muestra la estructura completa del texto para que "
        f"tengas contexto global sin salirte del tramo adjunto.\n\n"
        f"IDENTIFICACIÓN DE LA PARTE:\n{identificacion}"
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
) -> None:
    """Background task: format explainer content then persist and notify.

    Fires independently of other sections so that the main processing loop can
    start the next section's agents without waiting for formatting to finish.
    The `part_completed` SSE event is only sent once formatting is done.
    """
    fmt_start = time.time()
    try:
        if not isinstance(explainer_data, Exception) and isinstance(explainer_data, dict):
            formatted = await format_explainer_content(api_key, explainer_data)
            partes_contenido[str(part_id)]["explainer"] = formatted
            logger.info(
                f"[Format] Parte {part_id} formateada en {int((time.time() - fmt_start) * 1000)}ms",
                extra={"part_id": part_id, "elapsed_ms": int((time.time() - fmt_start) * 1000)},
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


async def _process_project(project_id: str, user_id: str, model_name: str = "gemini-3-flash-preview") -> None:
    process_start_time = time.time()
    pdf_temp_path = None
    numbered_pdf_path = None
    segment_pdf_paths: list[str] = []
    temp_paths: list[str] = []
    web_blocks = []
    source_mime_type = "application/pdf"
    source_kind = "pdf"
    source_title = ""
    resolved_source_url = ""
    source_metadata: dict[str, object] = {}

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
        logger.info(
            f"[Process] Proyecto cargado: {project.get('name', 'unnamed')}",
            extra={
                "project_name": project.get("name", "unnamed"),
                "source_type": source_type,
                "current_status": project.get("status", "unknown"),
            }
        )

        # Get user's API key (BYOK) from Supabase
        api_key = get_user_api_key(user_id)
        if not api_key:
            logger.error(f"[Process] API key no configurada para user: {user_id[:8]}...")
            await send_event(project_id, {"type": "error", "message": "No hay API key de Gemini configurada. Configúrala en Ajustes."})
            update_project(project_id, user_id, {"status": "error", "error_message": "API key no configurada"})
            return

        logger.info(f"[Process] Usando API key: {mask_api_key(api_key)}")

        from google import genai
        client = genai.Client(api_key=api_key)
        logger.info(f"[Process] Modelo seleccionado: {model_name}")

        cumulative_usage = {
            "model": model_name,
            "prompt_tokens": 0,
            "tool_use_prompt_tokens": 0,
            "candidates_tokens": 0,
            "thoughts_tokens": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
        }

        def _update_usage(usage_meta, phase: str = "unknown"):
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
            cost = calculate_cost(model_name, usage_meta)
            cumulative_usage["total_cost"] += cost
            update_project(project_id, user_id, {"usage": cumulative_usage})

            logger.debug(
                f"[Process] Uso de tokens actualizado - fase: {phase}",
                extra={
                    "phase": phase,
                    "tokens_this_call": tt,
                    "cost_this_call": round(cost, 6),
                    "cumulative_total": cumulative_usage["total_tokens"],
                    "cumulative_cost": round(cumulative_usage["total_cost"], 6),
                }
            )

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
            source_metadata = project.get("source_metadata") or {}
            extraction_usage = None

            if not source_text:
                extracted_content, extraction_usage = await asyncio.to_thread(
                    extract_web_content,
                    source_url,
                    api_key,
                    model_name,
                )
                source_text = extracted_content.text
                source_title = extracted_content.title
                resolved_source_url = extracted_content.resolved_url
                source_metadata = {
                    **(extracted_content.metadata or {}),
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
                _update_usage(extraction_usage, phase="web_extraction")
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
            web_temp_path = await asyncio.to_thread(write_text_document_temp, web_document)
            temp_paths.append(web_temp_path)

            upload_start = time.time()
            uploaded_file = await asyncio.to_thread(lambda: upload_file_with_retry(client, web_temp_path, max_retries=5))
            upload_duration = (time.time() - upload_start) * 1000
            file_uri = uploaded_file.uri
            source_mime_type = getattr(uploaded_file, "mime_type", None) or "text/plain"
            source_kind = "text"

            logger.info(
                f"[Process] Fuente web preparada y subida en {int(upload_duration)}ms",
                extra={
                    "file_uri": file_uri,
                    "upload_duration_ms": int(upload_duration),
                    "block_count": len(web_blocks),
                    "resolved_url": resolved_source_url,
                }
            )

            update_project(project_id, user_id, {"file_uri": file_uri, "status": "segmenting"})
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

            # Add visible page numbers to the PDF before uploading
            logger.info("[Process] Añadiendo numeración de páginas al PDF")
            numbered_pdf_path = await asyncio.to_thread(add_page_numbers, pdf_temp_path)
            logger.info(f"[Process] PDF numerado creado: {numbered_pdf_path}")
            temp_paths.append(numbered_pdf_path)

            upload_start = time.time()
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

        # Fase de segmentación
        logger.info("[Process] Iniciando segmentación del documento")
        seg_start = time.time()
        segmentation, usage_meta = await asyncio.to_thread(
            run_segmentador,
            api_key,
            file_uri,
            project["description"],
            model_name,
            source_mime_type,
            source_kind,
        )
        seg_duration = (time.time() - seg_start) * 1000

        _update_usage(usage_meta, phase="segmentation")
        await send_event(project_id, {"type": "usage_update", "usage": cumulative_usage})

        num_partes = len(segmentation.get("partes", []))
        temas_identificados = len(segmentation.get("temas_identificados", []))
        logger.info(
            f"[Process] Segmentación completada: {num_partes} partes, {temas_identificados} temas en {int(seg_duration)}ms",
            extra={
                "num_partes": num_partes,
                "temas_identificados": temas_identificados,
                "segmentation_duration_ms": int(seg_duration),
            }
        )

        is_pdf_source = source_type == "pdf"
        is_text_source = source_type == "web"

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

        # Procesar cada parte
        logger.info(f"[Process] Comenzando procesamiento de {num_partes} partes")
        formatter_tasks: list[asyncio.Task] = []

        for parte in segmentation["partes"]:
            part_id = parte["numero"]
            identificacion = parte["identificacion"]

            # Establecer contexto para esta parte
            with LogContext(project_id=project_id, user_id=user_id, part_id=part_id):
                part_start = time.time()
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
            update_project(project_id, user_id, {"partes_contenido": partes_contenido})
            await send_event(project_id, {"type": "part_started", "part_id": part_id})

            # For PDF: extract sub-PDF with relevant pages and upload it
            # For Web: upload only the exact text blocks for this part
            # For YouTube: use the full file_uri as before
            agent_file_uri = file_uri
            agent_mime_type = source_mime_type
            agent_prompt = identificacion
            segment_temp_path = None

            if is_pdf_source and numbered_pdf_path:
                pagina_inicio = parte.get("pagina_inicio")
                pagina_fin = parte.get("pagina_fin")

                if pagina_inicio and pagina_fin:
                    try:
                        # Extract sub-PDF with buffer pages
                        logger.info(
                            f"[Process] Extrayendo páginas {pagina_inicio}-{pagina_fin} (±1 buffer) para parte {part_id}",
                            extra={"pagina_inicio": pagina_inicio, "pagina_fin": pagina_fin}
                        )
                        segment_temp_path = await asyncio.to_thread(
                            extract_page_range, numbered_pdf_path, pagina_inicio, pagina_fin, buffer=1
                        )
                        segment_pdf_paths.append(segment_temp_path)
                        temp_paths.append(segment_temp_path)

                        # Upload sub-PDF to Gemini
                        seg_upload_start = time.time()
                        segment_uploaded = await asyncio.to_thread(
                            lambda p=segment_temp_path: upload_file_with_retry(client, p, max_retries=5)
                        )
                        seg_upload_duration = (time.time() - seg_upload_start) * 1000
                        agent_file_uri = segment_uploaded.uri
                        agent_mime_type = getattr(segment_uploaded, "mime_type", None) or "application/pdf"

                        logger.info(
                            f"[Process] Sub-PDF parte {part_id} subido en {int(seg_upload_duration)}ms",
                            extra={
                                "segment_uri": agent_file_uri,
                                "seg_upload_duration_ms": int(seg_upload_duration),
                            }
                        )
                    except Exception as seg_err:
                        # Fallback: use full PDF if sub-PDF extraction fails
                        logger.warning(
                            f"[Process] Error extrayendo sub-PDF para parte {part_id}, usando PDF completo: {seg_err}",
                            extra={"error_type": type(seg_err).__name__}
                        )
                        agent_file_uri = file_uri
                else:
                    logger.warning(
                        f"[Process] Parte {part_id} sin pagina_inicio/pagina_fin, usando PDF completo"
                    )

                agent_prompt = _build_pdf_agent_prompt(table_of_contents, identificacion, part_id, num_partes)
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
                temp_paths.append(segment_temp_path)

                seg_upload_start = time.time()
                segment_uploaded = await asyncio.to_thread(
                    lambda p=segment_temp_path: upload_file_with_retry(client, p, max_retries=5)
                )
                seg_upload_duration = (time.time() - seg_upload_start) * 1000
                agent_file_uri = segment_uploaded.uri
                agent_mime_type = getattr(segment_uploaded, "mime_type", None) or "text/plain"

                logger.info(
                    f"[Process] Segmento textual parte {part_id} subido en {int(seg_upload_duration)}ms",
                    extra={
                        "segment_uri": agent_file_uri,
                        "seg_upload_duration_ms": int(seg_upload_duration),
                        "bloque_inicio": bloque_inicio,
                        "bloque_fin": bloque_fin,
                    }
                )

                agent_prompt = _build_text_agent_prompt(table_of_contents, identificacion, part_id, num_partes)

            # Ejecutar los tres agentes en paralelo
            agents_start = time.time()
            results = await asyncio.gather(
                asyncio.to_thread(run_explainer, api_key, agent_file_uri, agent_prompt, model_name, agent_mime_type),
                asyncio.to_thread(run_recorrido, api_key, agent_file_uri, agent_prompt, model_name, agent_mime_type),
                asyncio.to_thread(run_resources, api_key, agent_file_uri, agent_prompt, model_name, agent_mime_type),
                return_exceptions=True,
            )
            agents_duration = (time.time() - agents_start) * 1000

            explainer_data, usage_e = results[0] if not isinstance(results[0], Exception) else (results[0], None)
            recorrido_data, usage_rec = results[1] if not isinstance(results[1], Exception) else (results[1], None)
            resources_data, usage_res = results[2] if not isinstance(results[2], Exception) else (results[2], None)

            # Actualizar uso de tokens
            for u, phase in [(usage_e, "explainer"), (usage_rec, "recorrido"), (usage_res, "resources")]:
                if u:
                    _update_usage(u, phase=f"part_{part_id}_{phase}")
            await send_event(project_id, {"type": "usage_update", "usage": cumulative_usage})

            # Procesar resultados de cada agente
            for result, agent_name in [
                (explainer_data, "explainer"),
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
                f"(agentes: {int(agents_duration)}ms) — iniciando formatter en background",
                extra={
                    "part_id": part_id,
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
                    explainer_data,
                    partes_contenido,
                )
            )
            formatter_tasks.append(formatter_task)

        # Esperar a que todos los formatters terminen antes de marcar el proyecto como completado.
        # Los formatter_tasks ya se están ejecutando en paralelo con los agentes de secciones
        # posteriores; aquí solo esperamos a que los últimos en terminar concluyan.
        if formatter_tasks:
            logger.info(
                f"[Process] Esperando a {len(formatter_tasks)} formatter task(s) pendientes…"
            )
            await asyncio.gather(*formatter_tasks, return_exceptions=True)

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
                "Intenta con un modelo diferente (ej: cambia de Pro a Flash) o espera unos minutos."
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
                "Intenta con un documento más pequeño o un modelo diferente."
            )
        elif exc.status_code == 400:
            error_msg = f"Error en la petición a Gemini API (400): {exc.message}"
        elif exc.status_code == 403:
            error_msg = (
                "Error de permisos en Gemini API (403). "
                "Verifica que tu API key sea válida y tenga acceso al modelo seleccionado."
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
        # Clean up all temporary files created during processing.
        for temp_path in dict.fromkeys(temp_paths):
            if temp_path and os.path.isfile(temp_path):
                try:
                    os.unlink(temp_path)
                    logger.debug(f"[Process] Archivo temporal eliminado: {temp_path}")
                except OSError as e:
                    logger.warning(f"[Process] No se pudo eliminar archivo temporal {temp_path}: {e}")
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

    api_key = get_user_api_key(user_id)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="No hay API key de Gemini configurada. Configúrala en Ajustes.",
        )

    partes_contenido: dict = dict(project.get("partes_contenido") or {})

    async def _fmt_part(pid: str, part_data: dict) -> tuple[str, dict]:
        explainer = part_data.get("explainer")
        if (
            explainer
            and isinstance(explainer, dict)
            and "error" not in explainer
        ):
            formatted = await format_explainer_content(api_key, explainer)
            return pid, {**part_data, "explainer": formatted, "formatter_version": 1}
        # No explainer or explainer errored — just mark version so we skip next time.
        return pid, {**part_data, "formatter_version": 1}

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
    for r in results:
        if isinstance(r, Exception):
            logger.warning(
                f"[Reformat] Error en una parte: {r}",
                extra={"error": str(r)[:300]},
            )
            continue
        pid, updated_part = r
        partes_contenido[pid] = updated_part
        reformatted += 1

    if reformatted > 0:
        update_project(project_id, user_id, {"partes_contenido": partes_contenido})

    elapsed_ms = int((time.time() - reformat_start) * 1000)
    logger.info(
        f"[Reformat] Proyecto {project_id}: {reformatted}/{len(tasks)} partes formateadas "
        f"en {elapsed_ms}ms",
        extra={
            "project_id": project_id,
            "reformatted": reformatted,
            "total": len(tasks),
            "elapsed_ms": elapsed_ms,
        },
    )
    return {"ok": True, "reformatted": reformatted}


@app.post("/api/projects/{project_id}/process")
async def api_process_project(
    user_id: Annotated[str, Depends(get_current_user_id)],
    project_id: str,
    background_tasks: BackgroundTasks,
    model: str = Query("gemini-3-flash-preview"),
):
    """Start processing a project using the user's own API key (BYOK)."""
    logger.info(
        f"[API] Solicitud de procesamiento recibida",
        extra={
            "project_id": project_id,
            "user_id": user_id[:8] + "..." if len(user_id) > 8 else user_id,
            "endpoint": "POST /api/projects/{project_id}/process",
        }
    )

    project = get_project(project_id, user_id)
    if not project:
        logger.warning(f"[API] Proyecto no encontrado: {project_id}")
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    if project["status"] not in ("pending", "error"):
        logger.warning(
            f"[API] Proyecto ya está en estado '{project['status']}'",
            extra={"project_id": project_id, "current_status": project["status"]}
        )
        raise HTTPException(status_code=400, detail=f"El proyecto ya está en estado '{project['status']}'")

    if not has_user_api_key(user_id):
        logger.warning(f"[API] Usuario sin API key configurada: {user_id[:8]}...")
        raise HTTPException(status_code=400, detail="No hay API key de Gemini configurada. Configúrala en Ajustes.")

    if model not in ALLOWED_MODELS:
        raise HTTPException(status_code=400, detail=f"Modelo no válido. Opciones: {', '.join(sorted(ALLOWED_MODELS))}")

    logger.info(
        f"[API] Iniciando procesamiento en background",
        extra={
            "project_id": project_id,
            "project_name": project.get("name", "unnamed"),
            "source_type": project.get("source_type", "pdf"),
            "model": model,
        }
    )
    background_tasks.add_task(_process_project, project_id, user_id, model)
    return {"ok": True, "status": "started"}


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


if os.environ.get("ENVIRONMENT") != "production":
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
else:
    @app.get("/")
    async def root():
        return FileResponse("frontend/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
