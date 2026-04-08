"""Explainer API con autenticación Supabase y persistencia en Postgres + Storage."""

import asyncio
import json
import math
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, AsyncGenerator, Literal
from urllib.parse import urlparse

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
    PROVIDER_GEMINI,
    PROVIDER_OPENROUTER,
)
from backend.crypto import mask_api_key
from backend.sse_manager import sse_manager, send_event
from backend.rate_limit import api_key_rate_limit, project_create_rate_limit
from backend.pricing import calculate_cost
from backend.gemini_model_routing import MODEL_AGENTS, MODEL_CLASSIFIER, MODEL_EXPLAINER, MODEL_SEGMENTADOR

from backend.gemini_client import upload_file_with_retry, GeminiError, GeminiRateLimitError
from backend.agents.segmentador import DEFAULT_DESCRIPTION, run_segmentador
from backend.segmentation_tema_coverage import (
    MAX_SEGMENTATION_COVERAGE_ATTEMPTS,
    SEGMENTATION_TEMA_COVERAGE_USER_MESSAGE,
    build_tema_coverage_retry_suffix,
    validate_tema_partition,
)
from backend.agents.page_classifier import run_page_classifier
from backend.segmentation_page_coverage import (
    MAX_PAGE_COVERAGE_ATTEMPTS,
    SEGMENTATION_PAGE_COVERAGE_USER_MESSAGE,
    build_page_coverage_retry_suffix,
    validate_page_coverage,
)
from pypdf import PdfReader
from backend.agents.explainer import run_explainer, run_subpart_explainer
from backend.agents.explainer_openrouter import (
    run_explainer_or,
    run_subpart_explainer_or,
    OPENROUTER_MODEL_AGENTS as OPENROUTER_EXPLAINER_MODEL,
    OPENROUTER_PDF_PARSER_ENGINE,
    OPENROUTER_PDF_PRIMING_MODEL,
)
from backend.agents.recorrido import run_recorrido
from backend.agents.resources import run_resources
from backend.agents.formatter import format_explainer_content
from backend.middleware import SecurityHeadersMiddleware, RequestLoggingMiddleware
from backend.openrouter_client import OpenRouterPdfParseCacheEntry, get_or_prime_pdf_parse_cache
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

# Max concurrent parts in the agent phase (prep + explainer/recorrido/resources); formatters run outside this limit.
MAX_CONCURRENT_PARTS = 5

ExplainerProvider = Literal["gemini", "openrouter"]

EXPLAINER_PROVIDER_GEMINI: ExplainerProvider = "gemini"
EXPLAINER_PROVIDER_OPENROUTER: ExplainerProvider = "openrouter"


class ProcessProjectRequest(BaseModel):
    explainer_provider: ExplainerProvider = EXPLAINER_PROVIDER_GEMINI


def _resolve_explainer_model(explainer_provider: ExplainerProvider) -> str:
    if explainer_provider == EXPLAINER_PROVIDER_OPENROUTER:
        return OPENROUTER_EXPLAINER_MODEL
    return MODEL_AGENTS


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


def _validate_openrouter_api_key(api_key: str) -> str:
    """Validate and normalize OpenRouter API key. Raises HTTPException on invalid input."""
    key = (api_key or "").strip()
    if not key.startswith("sk-or-") or len(key) < 20 or len(key) > 200:
        raise HTTPException(status_code=400, detail="API key de OpenRouter inválida (debe empezar por sk-or-)")
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


# ---- Status (all providers) ----

@app.get("/api/settings/api-key/status")
async def api_api_key_status(user_id: Annotated[str, Depends(get_current_user_id)]):
    """Get API key status for all providers."""
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


def _prepare_openrouter_pdf_context(
    *,
    numbered_pdf_path: str,
    content_page_set: frozenset[int],
    api_key: str,
    engine: str,
) -> "OpenRouterPreparedPdfContext":
    """Prime the incremental OCR cache over the numbered source PDF.

    The cache is keyed by the numbered source document itself, not by a
    reconstructed per-run subset PDF. This allows future executions to reuse
    already processed pages even if the classifier adds or removes pages.
    """
    cache_entry = get_or_prime_pdf_parse_cache(
        source_path=numbered_pdf_path,
        api_key=api_key,
        model=OPENROUTER_PDF_PRIMING_MODEL,
        engine=engine,
        filename="document.pdf",
        expected_page_numbers=tuple(sorted(content_page_set)),
    )
    return OpenRouterPreparedPdfContext(
        source_pdf_path=numbered_pdf_path,
        cache_entry=cache_entry,
    )


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
    temas_cubiertos: tuple[str, ...]
    intent_usuario: str | None
    continuidad_previa: str | None
    vision_global_division: str | None


@dataclass(frozen=True, slots=True)
class OpenRouterPreparedPdfContext:
    source_pdf_path: str
    cache_entry: OpenRouterPdfParseCacheEntry


def _normalized_temas_cubiertos(parte: dict) -> tuple[str, ...]:
    raw = parte.get("temas_cubiertos")
    if not isinstance(raw, list):
        return ()
    out: list[str] = []
    for item in raw:
        s = str(item).strip()
        if s:
            out.append(s)
    return tuple(out)


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
        temas_cubiertos=_normalized_temas_cubiertos(parte),
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
    temas = _normalized_temas_cubiertos(prev)
    if temas:
        lines.append(
            "Temas que el segmentador cerró en ese módulo (para enlazar ideas y prerequisitos; no reexpliques ese bloque aquí):"
        )
        for i, tema in enumerate(temas, start=1):
            lines.append(f"  {i}. {tema}")
    return "\n".join(lines) if lines else ""


def _find_parte_by_numero(partes: list[dict], numero: int) -> dict | None:
    for p in partes:
        if p.get("numero") == numero:
            return p
    return None


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
        "usa este bloque como contrato de cobertura y hilo conductor."
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

    blocks.append("")
    blocks.append(
        "CONTRATO DE COBERTURA — cada ítem debe quedar desarrollado en el cuerpo de la explicación "
        "(no basta mencionarlo en listas ni en la introducción):"
    )
    if ctx.temas_cubiertos:
        for i, tema in enumerate(ctx.temas_cubiertos, start=1):
            blocks.append(f"  {i}. {tema}")
    else:
        blocks.append(
            "  (El segmentador no devolvió lista explícita de temas_cubiertos; "
            "deriva el inventario exhaustivo del texto adjunto y de la identificación.)"
        )

    return "\n".join(blocks)


def _pdf_scope_instructions(
    *,
    mode: Literal["subpdf_buffered", "full_document"],
    part_id: int,
    num_partes: int,
    nucleo_inicio: int | None,
    nucleo_fin: int | None,
) -> str:
    if mode == "subpdf_buffered":
        if nucleo_inicio is not None and nucleo_fin is not None:
            return (
                "ALCANCE DEL PDF ADJUNTO (LECTURA)\n"
                "El archivo recorta el documento original e incluye el NÚCLEO de esta parte "
                f"(páginas {nucleo_inicio}–{nucleo_fin}, según las marcas «— Página X / N —» de la segmentación) "
                "más hasta una página de contexto a cada lado (buffer), para no perder párrafos cortados entre módulos.\n\n"
                "- Páginas NÚCLEO: son el objetivo principal de estudio de esta parte. "
                "Todo contenido examinable del módulo debe basarse principalmente en este intervalo.\n"
                "- Páginas solo de CONTEXTO (buffer): úsalas solo para recuperar enunciados partidos en el corte, "
                "coherencia entre páginas colindantes o referencias inmediatas. "
                "No las desarrolles como bloques didácticos independientes, no les asignes peso similar al núcleo "
                "y no inventes exigencias de estudio basadas únicamente en el buffer.\n\n"
                f"Parte {part_id}/{num_partes}: desarrolla exclusivamente este módulo según el contrato de cobertura; "
                "el temario de otras partes no es objeto de este procesamiento."
            )
        return (
            "ALCANCE DEL PDF ADJUNTO (LECTURA)\n"
            "El archivo es un recorte local del documento con hasta una página de contexto a cada lado del tramo "
            "principal de esta parte (buffer), para no perder párrafos cortados entre módulos.\n\n"
            "- NÚCLEO: delimita el bloque principal usando la identificación de la parte y el contrato de cobertura; "
            "ahí reside el objetivo de estudio.\n"
            "- CONTEXTO (buffer): solo continuidad en los bordes; no lo desarrolles como temario independiente "
            "ni bases de estudio aisladas.\n\n"
            f"Parte {part_id}/{num_partes}: desarrolla exclusivamente este módulo; el resto del documento completo "
            "no es objeto de este procesamiento."
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
        f"Desarrolla exclusivamente la Parte {part_id}/{num_partes} según el contrato de cobertura y la identificación. "
        "No sustituyas el material de otras partes por contenido de este módulo. "
        "Si necesitas enlaces mínimos con el resto del temario, limítalos al campo conexiones_contextuales o a menciones breves."
    )


def _text_scope_instructions(part_id: int, num_partes: int, bloque_inicio: int, bloque_fin: int) -> str:
    return (
        "ALCANCE DEL TEXTO ADJUNTO\n"
        f"El archivo incluye exactamente los bloques {bloque_inicio}–{bloque_fin} de la segmentación "
        "(sin páginas de buffer: el corte es preciso). "
        f"Desarrolla exclusivamente la Parte {part_id}/{num_partes}; "
        "la tabla de contenidos aporta panorama global, pero no añadas temario fuera de los bloques adjuntos."
    )


def _youtube_scope_instructions(part_id: int, num_partes: int) -> str:
    return (
        "ALCANCE DE LA FUENTE ADJUNTA\n"
        f"Procesa únicamente la Parte {part_id}/{num_partes} según el contrato de cobertura y la identificación. "
        "La tabla de contenidos sitúa el módulo dentro del conjunto del material."
    )


def _build_pdf_agent_prompt(
    table_of_contents: str,
    identificacion: str,
    part_id: int,
    num_partes: int,
    handoff: PartHandoffContext,
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
    scope = _pdf_scope_instructions(
        mode=pdf_scope_mode,
        part_id=part_id,
        num_partes=num_partes,
        nucleo_inicio=nucleo_inicio,
        nucleo_fin=nucleo_fin,
    )
    return (
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
    *,
    bloque_inicio: int,
    bloque_fin: int,
) -> str:
    toc_with_marker = table_of_contents.replace(
        f"  Parte {part_id}/{num_partes}:",
        f"  ▶ Parte {part_id}/{num_partes} [PARTE ACTUAL]:",
    )
    handoff_body = _format_handoff_section(handoff, part_id=part_id, num_partes=num_partes)
    scope = _text_scope_instructions(part_id, num_partes, bloque_inicio, bloque_fin)
    return (
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
) -> str:
    toc_with_marker = table_of_contents.replace(
        f"  Parte {part_id}/{num_partes}:",
        f"  ▶ Parte {part_id}/{num_partes} [PARTE ACTUAL]:",
    )
    handoff_body = _format_handoff_section(handoff, part_id=part_id, num_partes=num_partes)
    scope = _youtube_scope_instructions(part_id, num_partes)
    return (
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
    """Build the subpart-specific scope block for the explainer prompt."""
    sp_num = subparte.get("numero_subparte", 1)
    total_sp = len(all_subpartes)
    sp_titulo = subparte.get("titulo", f"Subparte {sp_num}")
    sp_contenido = subparte.get("contenido", "")
    sp_temas = subparte.get("temas_cubiertos", [])

    lines: list[str] = []
    lines.append("ALCANCE DE LA SUBPARTE (EXPLAINER)")
    lines.append(
        f"Estás explicando la SUBPARTE {sp_num}/{total_sp} de la Parte {part_id}/{num_partes}."
    )
    lines.append(
        "Genera SOLO el campo «desarrollo» (secciones y subsecciones con explicaciones exhaustivas). "
        "NO generes introduccion, conclusion ni conexiones_contextuales — ya han sido redactados "
        "por el segmentador con visión global del documento completo."
    )
    lines.append("")
    lines.append(f"Título de esta subparte: «{sp_titulo}»")
    if sp_contenido:
        lines.append(f"Alcance: {sp_contenido}")
    if sp_temas:
        lines.append("Temas a desarrollar en esta subparte:")
        for i, tema in enumerate(sp_temas, 1):
            lines.append(f"  {i}. {tema}")

    # Context about sibling subparts for continuity
    if total_sp > 1:
        lines.append("")
        lines.append("Contexto de otras subpartes de esta misma parte (NO las expliques, solo para continuidad):")
        for sp in all_subpartes:
            sp_n = sp.get("numero_subparte", 0)
            if sp_n != sp_num:
                label = "anterior" if sp_n < sp_num else "siguiente"
                lines.append(f"  - Subparte {sp_n} ({label}): {sp.get('titulo', '?')} — {sp.get('contenido', '')[:120]}")

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
    scope = _pdf_scope_instructions(
        mode=pdf_scope_mode,
        part_id=part_id,
        num_partes=num_partes,
        nucleo_inicio=sp_pi,
        nucleo_fin=sp_pf,
    )

    subpart_ctx = _build_subpart_context(subparte, all_subpartes, part_id, num_partes)
    sp_identificacion = subparte.get("identificacion", parte.get("identificacion", ""))

    return (
        f"{toc_with_marker}\n\n"
        f"---\n\n"
        f"{handoff_body}\n\n"
        f"---\n\n"
        f"{scope}\n\n"
        f"---\n\n"
        f"{subpart_ctx}\n\n"
        f"---\n\n"
        f"IDENTIFICACIÓN PRECISA DE LA SUBPARTE (texto del segmentador):\n{sp_identificacion}"
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
    scope = _text_scope_instructions(part_id, num_partes, int(sp_bi), int(sp_bf))

    subpart_ctx = _build_subpart_context(subparte, all_subpartes, part_id, num_partes)
    sp_identificacion = subparte.get("identificacion", parte.get("identificacion", ""))

    return (
        f"{toc_with_marker}\n\n"
        f"---\n\n"
        f"{handoff_body}\n\n"
        f"---\n\n"
        f"{scope}\n\n"
        f"---\n\n"
        f"{subpart_ctx}\n\n"
        f"---\n\n"
        f"IDENTIFICACIÓN PRECISA DE LA SUBPARTE (texto del segmentador):\n{sp_identificacion}"
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
    scope = _youtube_scope_instructions(part_id, num_partes)

    subpart_ctx = _build_subpart_context(subparte, all_subpartes, part_id, num_partes)
    sp_identificacion = subparte.get("identificacion", parte.get("identificacion", ""))

    return (
        f"{toc_with_marker}\n\n"
        f"---\n\n"
        f"{handoff_body}\n\n"
        f"---\n\n"
        f"{scope}\n\n"
        f"---\n\n"
        f"{subpart_ctx}\n\n"
        f"---\n\n"
        f"IDENTIFICACIÓN PRECISA DE LA SUBPARTE (texto del segmentador):\n{sp_identificacion}"
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
    fmt_usage: dict = {}
    try:
        is_markdown_format = isinstance(explainer_data, dict) and explainer_data.get("_format") == "markdown"
        if not isinstance(explainer_data, Exception) and isinstance(explainer_data, dict) and not is_markdown_format:
            formatted, fmt_usage = await format_explainer_content(api_key, explainer_data)
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
) -> None:
    process_start_time = time.time()
    pdf_temp_path = None
    numbered_pdf_path = None
    segment_pdf_paths: list[str] = []
    pdf_total_pages: int = 0
    content_page_set: frozenset[int] = frozenset()
    openrouter_pdf_prepare_task: asyncio.Task | None = None
    openrouter_pdf_context: OpenRouterPreparedPdfContext | None = None
    temp_paths: list[str] = []
    web_blocks = []
    source_mime_type = "application/pdf"
    source_kind = "pdf"
    source_title = ""
    resolved_source_url = ""
    source_metadata: dict[str, object] = {}
    use_openrouter_explainer = explainer_provider == EXPLAINER_PROVIDER_OPENROUTER
    explainer_model = _resolve_explainer_model(explainer_provider)

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

        if use_openrouter_explainer and source_type == "youtube":
            error_msg = (
                "OpenRouter todavía no está disponible para proyectos de YouTube. "
                "Usa Gemini para esta fuente."
            )
            logger.warning(
                "[Process] Selección OpenRouter no soportada para YouTube",
                extra={"project_id": project_id, "source_type": source_type},
            )
            await send_event(project_id, {"type": "error", "message": error_msg})
            update_project(project_id, user_id, {"status": "error", "error_message": error_msg})
            return

        # Get user's API keys (BYOK) from Supabase
        api_key = get_user_api_key(user_id, provider=PROVIDER_GEMINI)
        if not api_key:
            logger.error(f"[Process] API key Gemini no configurada para user: {user_id[:8]}...")
            await send_event(project_id, {"type": "error", "message": "No hay API key de Gemini configurada. Configúrala en Ajustes."})
            update_project(project_id, user_id, {"status": "error", "error_message": "API key no configurada"})
            return

        openrouter_api_key = ""
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
                            "Guárdala en Ajustes para usar MiniMax en el explainer."
                        ),
                    },
                )
                update_project(project_id, user_id, {"status": "error", "error_message": "API key OpenRouter no configurada"})
                return

        logger.info(f"[Process] Usando API key: {mask_api_key(api_key)}")

        from google import genai
        client = genai.Client(api_key=api_key)
        logger.info(
            "[Process] Enrutamiento de modelos: segmentador=%s, gemini_agents=%s, explainer_provider=%s, explainer_model=%s",
            MODEL_SEGMENTADOR,
            MODEL_AGENTS,
            explainer_provider,
            explainer_model,
        )

        cumulative_usage = {
            "segmentation_model": MODEL_SEGMENTADOR,
            "agents_model": MODEL_AGENTS,
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
        update_project(project_id, user_id, {"usage": cumulative_usage})

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
            update_project(project_id, user_id, {"usage": cumulative_usage})

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
                    MODEL_AGENTS,
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
                _update_usage(extraction_usage, phase="web_extraction", cost_model=MODEL_AGENTS)
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
            pdf_total_pages = len(PdfReader(numbered_pdf_path).pages)

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

        # Clasificador de páginas (solo para PDF): identifica qué páginas son contenido vs. accesorias
        if source_type == "pdf" and numbered_pdf_path and file_uri and pdf_total_pages > 0:
            try:
                content_page_set, clf_usage = await asyncio.to_thread(
                    run_page_classifier,
                    api_key,
                    file_uri,
                    pdf_total_pages,
                    MODEL_CLASSIFIER,
                )
                _update_usage(clf_usage, phase="page_classifier", cost_model=MODEL_CLASSIFIER)
                await send_event(project_id, {"type": "usage_update", "usage": cumulative_usage})
                clf_cost = calculate_cost(MODEL_CLASSIFIER, clf_usage)
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
                content_page_set = frozenset(range(1, pdf_total_pages + 1))
                logger.warning(
                    "[Process] Clasificador de páginas falló, asumiendo todas como contenido: %s",
                    clf_err,
                    extra={"error_type": type(clf_err).__name__},
                )

            if use_openrouter_explainer and openrouter_api_key and content_page_set:
                logger.info(
                    "[Process] Preparando OCR canónico de OpenRouter sobre páginas con contenido",
                    extra={
                        "content_pages_count": len(content_page_set),
                        "openrouter_model": explainer_model,
                        "openrouter_pdf_priming_model": OPENROUTER_PDF_PRIMING_MODEL,
                    },
                )
                openrouter_pdf_prepare_task = asyncio.create_task(
                    asyncio.to_thread(
                        _prepare_openrouter_pdf_context,
                        numbered_pdf_path=numbered_pdf_path,
                        content_page_set=content_page_set,
                        api_key=openrouter_api_key,
                        engine=OPENROUTER_PDF_PARSER_ENGINE,
                    )
                )

        # Fase de segmentación (con validación MECE de temas + cobertura de páginas y reintentos)
        logger.info("[Process] Iniciando segmentación del documento")
        seg_start = time.time()
        segmentation: dict | None = None
        tema_report = None
        page_report = None
        is_pdf_seg = source_type == "pdf"
        content_pages_prefix = (
            _build_content_pages_prefix(content_page_set, pdf_total_pages)
            if is_pdf_seg and content_page_set
            else ""
        )
        MAX_COMBINED_ATTEMPTS = max(MAX_SEGMENTATION_COVERAGE_ATTEMPTS, MAX_PAGE_COVERAGE_ATTEMPTS)

        for seg_attempt in range(MAX_COMBINED_ATTEMPTS):
            if seg_attempt == 0:
                seg_description = content_pages_prefix + (project["description"].strip() or DEFAULT_DESCRIPTION)
            else:
                assert segmentation is not None
                correction_parts = []
                if tema_report is not None and not tema_report.is_valid:
                    correction_parts.append(
                        build_tema_coverage_retry_suffix(
                            attempt=seg_attempt,
                            segmentation=segmentation,
                            report=tema_report,
                        )
                    )
                if page_report is not None and not page_report.is_valid:
                    correction_parts.append(
                        build_page_coverage_retry_suffix(
                            attempt=seg_attempt,
                            segmentation=segmentation,
                            report=page_report,
                            content_page_set=content_page_set,
                        )
                    )
                correction_suffix = "\n\n".join(correction_parts)
                base_desc = project["description"].strip() or DEFAULT_DESCRIPTION
                seg_description = content_pages_prefix + base_desc + "\n\n" + correction_suffix

            segmentation, usage_meta = await asyncio.to_thread(
                run_segmentador,
                api_key,
                file_uri,
                seg_description,
                MODEL_SEGMENTADOR,
                source_mime_type,
                source_kind,
            )
            phase = "segmentation" if seg_attempt == 0 else f"segmentation_retry_{seg_attempt}"
            _update_usage(usage_meta, phase=phase, cost_model=MODEL_SEGMENTADOR)
            await send_event(project_id, {"type": "usage_update", "usage": cumulative_usage})

            tema_report = validate_tema_partition(segmentation)
            page_report = (
                validate_page_coverage(segmentation, content_page_set)
                if is_pdf_seg
                else None
            )

            both_valid = tema_report.is_valid and (page_report is None or page_report.is_valid)

            if both_valid:
                if tema_report.empty_temas_inventory:
                    logger.warning(
                        "[Process] Segmentación sin temas_identificados; se omite validación MECE de temas",
                        extra={"project_id": project_id, "seg_attempt": seg_attempt},
                    )
                if seg_attempt > 0:
                    logger.info(
                        "[Process] Segmentación corregida tras reintento (temas + páginas)",
                        extra={"project_id": project_id, "seg_attempt": seg_attempt},
                    )
                break

            logger.warning(
                "[Process] Validación fallida; se reintentará el segmentador si quedan intentos",
                extra={
                    "project_id": project_id,
                    "seg_attempt": seg_attempt,
                    "tema_valid": tema_report.is_valid,
                    "page_valid": page_report.is_valid if page_report else True,
                    "tema_missing": len(tema_report.missing),
                    "tema_duplicates": len(tema_report.duplicates),
                    "page_part_errors": len(page_report.part_errors) if page_report else 0,
                    "page_subpart_errors": len(page_report.subpart_errors) if page_report else 0,
                },
            )
        else:
            assert segmentation is not None
            error_bits = []
            if tema_report and not tema_report.is_valid:
                if tema_report.missing:
                    error_bits.append(f"{len(tema_report.missing)} tema(s) sin asignar")
                if tema_report.duplicates:
                    error_bits.append(f"{len(tema_report.duplicates)} tema(s) duplicados")
            if page_report and not page_report.is_valid:
                if page_report.part_errors:
                    error_bits.append(f"{len(page_report.part_errors)} error(es) de rango en partes")
                if page_report.subpart_errors:
                    error_bits.append(f"{len(page_report.subpart_errors)} error(es) de rango en subpartes")
            detail = "; ".join(error_bits) if error_bits else "inconsistencias en segmentación"
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
                    "error_message": SEGMENTATION_TEMA_COVERAGE_USER_MESSAGE,
                },
            )
            await send_event(
                project_id,
                {"type": "error", "message": SEGMENTATION_TEMA_COVERAGE_USER_MESSAGE},
            )
            return

        seg_duration = (time.time() - seg_start) * 1000

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

        if openrouter_pdf_prepare_task is not None:
            try:
                openrouter_pdf_context = await openrouter_pdf_prepare_task
                logger.info(
                    "[Process] OCR canónico OpenRouter preparado",
                    extra={
                        "source_pdf_path": openrouter_pdf_context.source_pdf_path,
                        "cache_path": openrouter_pdf_context.cache_entry.cache_path,
                        "cache_hit": openrouter_pdf_context.cache_entry.cache_hit,
                        "requested_pages_count": len(openrouter_pdf_context.cache_entry.expected_page_numbers),
                        "cached_pages_count": len(openrouter_pdf_context.cache_entry.cached_page_numbers),
                    },
                )
            except Exception as exc:
                openrouter_pdf_context = None
                logger.warning(
                    "[Process] No se pudo preparar el OCR canónico OpenRouter; se usará el flujo local por parte: %s",
                    exc,
                    extra={"error_type": type(exc).__name__},
                )

        partes_segmentadas: list[dict] = segmentation["partes"]
        user_intent = _strip_str(project.get("description"))
        consideraciones = _strip_str(segmentation.get("consideraciones_estudiante"))

        # Procesar cada parte
        logger.info(f"[Process] Comenzando procesamiento de {num_partes} partes")
        formatter_tasks: list[asyncio.Task] = []

        for parte in partes_segmentadas:
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
            openrouter_page_scopes: list[tuple[int, ...]] = []

            nucleo_pi = _optional_int(parte, "pagina_inicio")
            nucleo_pf = _optional_int(parte, "pagina_fin")

            if is_pdf_source and numbered_pdf_path:
                pagina_inicio = parte.get("pagina_inicio")
                pagina_fin = parte.get("pagina_fin")
                subpdf_buffered_ok = False

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
                        subpdf_buffered_ok = True

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

                pdf_scope_mode: Literal["subpdf_buffered", "full_document"] = (
                    "subpdf_buffered" if subpdf_buffered_ok else "full_document"
                )
                # Build part-level prompt (for recorrido and resources)
                agent_prompt = _build_pdf_agent_prompt(
                    table_of_contents,
                    identificacion,
                    part_id,
                    num_partes,
                    handoff,
                    pdf_scope_mode=pdf_scope_mode,
                    nucleo_inicio=nucleo_pi,
                    nucleo_fin=nucleo_pf,
                )

                # Build subpart-level prompts (for explainer)
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
                    subpart_prompts = [agent_prompt]  # fallback: whole part as single subpart
                    openrouter_page_scopes = [
                        _select_openrouter_pdf_pages(
                            content_page_set,
                            start_page=nucleo_pi,
                            end_page=nucleo_pf,
                            buffer=1,
                        )
                    ]

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

                # Build part-level prompt (for recorrido and resources)
                agent_prompt = _build_text_agent_prompt(
                    table_of_contents,
                    identificacion,
                    part_id,
                    num_partes,
                    handoff,
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

            num_subparts = len(subpart_prompts)
            use_subpart_explainer = bool(parte.get("subpartes"))

            logger.info(
                f"[Process] Parte {part_id}: {num_subparts} subparte(s) — ejecutando agentes en paralelo",
                extra={"part_id": part_id, "num_subparts": num_subparts}
            )

            # Execute all subpart explainers + recorrido + resources in parallel
            agents_start = time.time()
            use_or_canonical = use_openrouter_explainer and is_pdf_source and openrouter_pdf_context is not None
            use_or_direct = use_openrouter_explainer and not use_or_canonical and segment_temp_path is not None
            use_or = use_or_canonical or use_or_direct
            if use_or:
                explainer_fn_or = run_subpart_explainer_or if use_subpart_explainer else run_explainer_or
                if use_or_canonical:
                    if len(openrouter_page_scopes) != len(subpart_prompts):
                        raise RuntimeError(
                            "Las páginas OpenRouter no coinciden con el número de subprompts generados."
                        )
                    explainer_calls = [
                        asyncio.to_thread(
                            explainer_fn_or,
                            openrouter_pdf_context.source_pdf_path,
                            sp_prompt,
                            explainer_model,
                            "application/pdf",
                            openrouter_api_key,
                            openrouter_pdf_context.cache_entry,
                            page_scope,
                        )
                        for sp_prompt, page_scope in zip(subpart_prompts, openrouter_page_scopes)
                    ]
                else:
                    explainer_calls = [
                        asyncio.to_thread(
                            explainer_fn_or,
                            segment_temp_path,
                            sp_prompt,
                            explainer_model,
                            agent_mime_type,
                            openrouter_api_key,
                        )
                        for sp_prompt in subpart_prompts
                    ]
            else:
                explainer_fn = run_subpart_explainer if use_subpart_explainer else run_explainer
                explainer_calls = [
                    asyncio.to_thread(explainer_fn, api_key, agent_file_uri, sp_prompt, MODEL_AGENTS, agent_mime_type)
                    for sp_prompt in subpart_prompts
                ]
            results = await asyncio.gather(
                *explainer_calls,
                asyncio.to_thread(run_recorrido, api_key, agent_file_uri, agent_prompt, MODEL_AGENTS, agent_mime_type),
                asyncio.to_thread(run_resources, api_key, agent_file_uri, agent_prompt, MODEL_AGENTS, agent_mime_type),
                return_exceptions=True,
            )
            agents_duration = (time.time() - agents_start) * 1000

            # Split results: first N are subpart explainers, then recorrido, then resources
            subpart_results = results[:num_subparts]
            recorrido_result = results[num_subparts]
            resources_result = results[num_subparts + 1]

            # Process subpart explainer results
            subpart_desarrollos: list[list[dict]] = []
            for i, sp_result in enumerate(subpart_results):
                if isinstance(sp_result, Exception):
                    logger.error(
                        f"[Process] Error en explainer subparte {i+1}/{num_subparts} de parte {part_id}: {str(sp_result)}",
                        extra={"part_id": part_id, "subpart": i+1, "error_type": type(sp_result).__name__}
                    )
                else:
                    sp_data, sp_usage = sp_result
                    if sp_usage:
                        _update_usage(sp_usage, phase=f"part_{part_id}_explainer_sp{i+1}", cost_model=explainer_model)
                    subpart_desarrollos.append(sp_data.get("desarrollo") or [])

            # Assemble: intro/conclusion/conexiones from segmentador + subpart results
            if use_subpart_explainer:
                assembled_explainer = _assemble_part_explainer(parte, subpart_desarrollos)
            else:
                # Fallback: no subparts — use the full explainer output as-is.
                # Both Gemini and OpenRouter now return the same structured shape.
                if subpart_results and not isinstance(subpart_results[0], Exception):
                    assembled_explainer = subpart_results[0][0]
                else:
                    assembled_explainer = {"error": "All explainer calls failed"}

            # Process recorrido and resources results
            recorrido_data, usage_rec = recorrido_result if not isinstance(recorrido_result, Exception) else (recorrido_result, None)
            resources_data, usage_res = resources_result if not isinstance(resources_result, Exception) else (resources_result, None)

            if usage_rec:
                _update_usage(usage_rec, phase=f"part_{part_id}_recorrido", cost_model=MODEL_AGENTS)
            if usage_res:
                _update_usage(usage_res, phase=f"part_{part_id}_resources", cost_model=MODEL_AGENTS)
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
        if openrouter_pdf_prepare_task is not None:
            try:
                if not openrouter_pdf_prepare_task.done():
                    openrouter_pdf_prepare_task.cancel()
                    try:
                        await openrouter_pdf_prepare_task
                    except asyncio.CancelledError:
                        pass
                elif openrouter_pdf_context is None:
                    prepared_context = openrouter_pdf_prepare_task.result()
            except Exception as exc:
                logger.debug(
                    "[Process] Cierre del task OCR canónico OpenRouter sin contexto reutilizable",
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
            formatted, fmt_usage = await format_explainer_content(api_key, explainer)
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
    explainer_model = _resolve_explainer_model(explainer_provider)
    logger.info(
        f"[API] Solicitud de procesamiento recibida",
        extra={
            "project_id": project_id,
            "user_id": user_id[:8] + "..." if len(user_id) > 8 else user_id,
            "endpoint": "POST /api/projects/{project_id}/process",
            "explainer_provider": explainer_provider,
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

    if not has_user_api_key(user_id, provider=PROVIDER_GEMINI):
        logger.warning(f"[API] Usuario sin API key configurada: {user_id[:8]}...")
        raise HTTPException(status_code=400, detail="No hay API key de Gemini configurada. Configúrala en Ajustes.")

    if explainer_provider == EXPLAINER_PROVIDER_OPENROUTER:
        if project.get("source_type") == "youtube":
            raise HTTPException(
                status_code=400,
                detail="OpenRouter todavía no está disponible para proyectos de YouTube. Usa Gemini para esta fuente.",
            )
        if not has_user_api_key(user_id, provider=PROVIDER_OPENROUTER):
            logger.warning(f"[API] Usuario sin API key OpenRouter configurada: {user_id[:8]}...")
            raise HTTPException(
                status_code=400,
                detail="No hay API key de OpenRouter configurada. Guárdala en Ajustes para usar MiniMax en el explainer.",
            )

    logger.info(
        f"[API] Iniciando procesamiento en background",
        extra={
            "project_id": project_id,
            "project_name": project.get("name", "unnamed"),
            "source_type": project.get("source_type", "pdf"),
            "segmentation_model": MODEL_SEGMENTADOR,
            "agents_model": MODEL_AGENTS,
            "explainer_provider": explainer_provider,
            "explainer_model": explainer_model,
        }
    )
    background_tasks.add_task(_process_project, project_id, user_id, explainer_provider)
    return {"ok": True, "status": "started", "explainer_provider": explainer_provider}


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
