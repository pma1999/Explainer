"""Project persistence and PDF storage via Supabase (Postgres + Storage)."""

from __future__ import annotations

import logging
import os
import re
import secrets
import tempfile
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from supabase import create_client, Client

from backend.crypto import encrypt_user_api_key, decrypt_user_api_key

try:
    from postgrest.types import ReturnMethod
except Exception:  # pragma: no cover - defensive for older supabase installs
    ReturnMethod = None

logger = logging.getLogger("backend.supabase_data")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
BUCKET_ID = "project-pdfs"
SOURCE_OBJECT_STATUS_NONE = "none"
SOURCE_OBJECT_STATUS_STORED = "stored"
SOURCE_OBJECT_STATUS_DELETED = "deleted"


def _client() -> Client:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_storage_filename(filename: str) -> str:
    """Convert filename to a Supabase-safe storage key (ASCII, no spaces/special chars)."""
    normalized = unicodedata.normalize("NFKD", filename)
    ascii_str = normalized.encode("ascii", "ignore").decode("ascii")
    safe = re.sub(r"[^a-zA-Z0-9._\-]", "_", ascii_str)
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe or "document.pdf"


def _project_storage_path(user_id: str, project_id: str, pdf_filename: str) -> str:
    return f"{user_id}/{project_id}/{_sanitize_storage_filename(pdf_filename)}"


def _looks_like_storage_not_found(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        needle in message
        for needle in (
            "not found",
            "object not found",
            "no such",
            "404",
            "does not exist",
        )
    )


def _resolve_source_object_status(row: dict[str, Any]) -> str:
    raw = row.get("source_object_status")
    if raw in {
        SOURCE_OBJECT_STATUS_NONE,
        SOURCE_OBJECT_STATUS_STORED,
        SOURCE_OBJECT_STATUS_DELETED,
    }:
        return raw
    if row.get("source_type", "pdf") == "pdf" and row.get("source_object_path"):
        return SOURCE_OBJECT_STATUS_STORED
    return SOURCE_OBJECT_STATUS_NONE


def _row_to_project(row: dict[str, Any], include_internal: bool = False) -> dict[str, Any]:
    """Convert DB row to API-shaped project dict (id str, dates ISO)."""
    result = {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "pdf_filename": row["pdf_filename"],
        "source_type": row.get("source_type", "pdf"),
        "source_url": row.get("source_url"),
        "source_metadata": row.get("source_metadata") or {},
        "file_uri": row.get("file_uri"),
        "status": row["status"],
        "segmentation": row.get("segmentation"),
        "partes_contenido": row.get("partes_contenido") or {},
        "usage": row.get("usage") or {},
        "reading_progress": row.get("reading_progress") or {},
        "error_message": row.get("error_message"),
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
        "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
    }
    if "share_token" in row:
        result["share_token"] = row.get("share_token")
    if include_internal:
        result["user_id"] = str(row["user_id"]) if row.get("user_id") is not None else None
        result["source_text"] = row.get("source_text")
        result["source_object_path"] = row.get("source_object_path")
        result["source_object_status"] = _resolve_source_object_status(row)
        result["source_object_deleted_at"] = _format_datetime_value(
            row.get("source_object_deleted_at")
        )
    return result


# Columns for GET /api/projects list — omits heavy JSON blobs (OOM on small instances).
PROJECT_LIST_SUMMARY_SELECT = (
    "id,name,description,pdf_filename,source_type,source_url,source_metadata,"
    "file_uri,status,segmentation,usage,reading_progress,error_message,"
    "share_token,created_at,updated_at"
)
PROJECT_PROGRESS_SELECT = "id,segmentation,reading_progress,updated_at"


def _row_to_list_summary(row: dict[str, Any]) -> dict[str, Any]:
    """API list item: same shape as project minus heavy fields; marks list_summary."""
    result: dict[str, Any] = {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "pdf_filename": row["pdf_filename"],
        "source_type": row.get("source_type", "pdf"),
        "source_url": row.get("source_url"),
        "source_metadata": row.get("source_metadata") or {},
        "file_uri": row.get("file_uri"),
        "status": row["status"],
        "segmentation": row.get("segmentation"),
        "usage": row.get("usage") or {},
        "reading_progress": row.get("reading_progress") or {},
        "error_message": row.get("error_message"),
        "created_at": row["created_at"].isoformat()
        if hasattr(row["created_at"], "isoformat")
        else str(row["created_at"]),
        "updated_at": row["updated_at"].isoformat()
        if hasattr(row["updated_at"], "isoformat")
        else str(row["updated_at"]),
        "list_summary": True,
    }
    if "share_token" in row:
        result["share_token"] = row.get("share_token")
    return result


def list_projects_summary(user_id: str) -> list[dict[str, Any]]:
    """List projects for user (newest first) without partes_contenido or source_text."""
    client = _client()
    r = (
        client.table("projects")
        .select(PROJECT_LIST_SUMMARY_SELECT)
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .execute()
    )
    rows = (r.data or []) if r else []
    return [_row_to_list_summary(row) for row in rows]


def _format_datetime_value(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _row_to_progress_context(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "segmentation": row.get("segmentation") or {},
        "reading_progress": row.get("reading_progress") or {},
        "updated_at": _format_datetime_value(row.get("updated_at")),
    }


def get_project_progress_context(project_id: str, user_id: str) -> Optional[dict[str, Any]]:
    """Load only the fields needed to validate and update reading progress."""
    client = _client()
    r = (
        client.table("projects")
        .select(PROJECT_PROGRESS_SELECT)
        .eq("id", project_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if r is None:
        logger.warning(
            "Supabase progress select returned None from execute() (project_id=%s)",
            project_id,
        )
        return None
    if not r.data:
        return None
    return _row_to_progress_context(r.data)


def _progress_response(reading_progress: dict[str, Any], updated_at: str | None) -> dict[str, Any]:
    return {
        "reading_progress": reading_progress or {},
        "updated_at": updated_at,
    }


def _update_reading_progress_minimal(
    project_id: str,
    user_id: str,
    reading_progress: dict[str, Any],
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """Persist reading_progress without asking PostgREST to return the full row."""
    updated_at = updated_at or _now_iso()
    payload = {
        "reading_progress": reading_progress,
        "updated_at": updated_at,
    }
    table = _client().table("projects")
    if ReturnMethod is not None:
        try:
            request = table.update(payload, returning=ReturnMethod.minimal)
        except TypeError:  # pragma: no cover - compatibility with old clients
            request = table.update(payload)
    else:  # pragma: no cover
        request = table.update(payload)
    request.eq("id", project_id).eq("user_id", user_id).execute()
    return _progress_response(reading_progress, updated_at)


def _coerce_rpc_status(data: Any) -> str:
    if isinstance(data, str):
        return data
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            for value in first.values():
                if isinstance(value, str):
                    return value
    if data is None:
        return "error"
    return str(data)


def _progress_rpc_status(function_name: str, params: dict[str, Any]) -> str:
    response = _client().rpc(function_name, params).execute()
    return _coerce_rpc_status(getattr(response, "data", None) if response else None)


def apply_subsection_progress_rpc(
    project_id: str,
    user_id: str,
    part_id: int,
    *,
    tab: str = "explicacion",
    completed_subsection_ids: list[str] | None = None,
    uncompleted_subsection_ids: list[str] | None = None,
    last_subsection_id: str | None = None,
) -> str:
    """Apply subsection progress inside Postgres and return a compact status."""
    return _progress_rpc_status(
        "apply_project_subsection_progress",
        {
            "p_project_id": project_id,
            "p_user_id": user_id,
            "p_part_id": part_id,
            "p_tab": tab or "explicacion",
            "p_completed_subsection_ids": completed_subsection_ids or [],
            "p_uncompleted_subsection_ids": uncompleted_subsection_ids or [],
            "p_last_subsection_id": last_subsection_id,
        },
    )


def apply_section_progress_rpc(
    project_id: str,
    user_id: str,
    part_id: int,
    *,
    completed: bool = True,
) -> str:
    """Apply section progress inside Postgres and return a compact status."""
    return _progress_rpc_status(
        "apply_project_section_progress",
        {
            "p_project_id": project_id,
            "p_user_id": user_id,
            "p_part_id": part_id,
            "p_completed": completed,
        },
    )


def _dedupe_preserve_order(values: list[Any]) -> list[Any]:
    out: list[Any] = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _subsection_progress_update(
    project_id: str,
    user_id: str,
    project: dict[str, Any],
    *,
    part_id: int,
    tab: str = "explicacion",
    completed_subsection_ids: list[str] | None = None,
    uncompleted_subsection_ids: list[str] | None = None,
    last_subsection_id: str | None = None,
) -> dict[str, Any]:
    progress: dict[str, Any] = dict(project.get("reading_progress") or {})
    completed = _dedupe_preserve_order(list(progress.get("completed_subsections") or []))
    changed = False

    if completed_subsection_ids:
        for subsection_id in completed_subsection_ids:
            if subsection_id not in completed:
                completed.append(subsection_id)
                changed = True

    if uncompleted_subsection_ids:
        remove_set = set(uncompleted_subsection_ids)
        next_completed = [subsection_id for subsection_id in completed if subsection_id not in remove_set]
        if next_completed != completed:
            completed = next_completed
            changed = True

    if changed or "completed_subsections" in progress:
        progress["completed_subsections"] = completed

    if last_subsection_id:
        next_last = {
            "part_id": part_id,
            "subsection_id": last_subsection_id,
            "tab": tab or "explicacion",
        }
        if progress.get("last_subsection") != next_last:
            progress["last_subsection"] = next_last
            changed = True

    if not changed:
        return _progress_response(progress, project.get("updated_at"))

    updated_at = _now_iso()
    if last_subsection_id:
        progress["last_read_at"] = updated_at
    return _update_reading_progress_minimal(project_id, user_id, progress, updated_at=updated_at)


def create_project(
    user_id: str,
    name: str,
    description: str,
    pdf_filename: str,
    pdf_content: bytes | None = None,
    source_type: str = "pdf",
    source_url: str | None = None,
    source_text: str | None = None,
    source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert project and optionally upload PDF to Storage. Returns project dict.

    Args:
        user_id: UUID of the user
        name: Project name
        description: Project description
        pdf_filename: Filename (for PDFs) or display name (for YouTube)
        pdf_content: PDF file bytes (only for source_type='pdf')
        source_type: 'pdf', 'youtube' or 'web'
        source_url: Source URL for URL-based source types
        source_text: Extracted source text cached for non-PDF sources
        source_metadata: Extra metadata for the source extraction pipeline
    """
    client = _client()
    project_id = str(uuid.uuid4())
    now = _now_iso()
    row = {
        "id": project_id,
        "user_id": user_id,
        "name": name,
        "description": description,
        "pdf_filename": pdf_filename,
        "source_type": source_type,
        "source_url": source_url,
        "source_text": source_text,
        "source_metadata": source_metadata or {},
        "file_uri": None,
        "status": "pending",
        "segmentation": None,
        "partes_contenido": {},
        "usage": {},
        "reading_progress": {},
        "error_message": None,
        "source_object_path": None,
        "source_object_status": SOURCE_OBJECT_STATUS_NONE,
        "source_object_deleted_at": None,
        "created_at": now,
        "updated_at": now,
    }
    storage_path = None
    if source_type == "pdf" and pdf_content:
        storage_path = _project_storage_path(user_id, project_id, pdf_filename)
        row["source_object_path"] = storage_path
    client.table("projects").insert(row).execute()

    # Only upload to storage for PDF source type
    if source_type == "pdf" and pdf_content:
        try:
            client.storage.from_(BUCKET_ID).upload(
                path=storage_path,
                file=pdf_content,
                file_options={"content-type": "application/pdf", "upsert": "false"},
            )
            client.table("projects").update(
                {
                    "source_object_status": SOURCE_OBJECT_STATUS_STORED,
                    "source_object_deleted_at": None,
                    "updated_at": _now_iso(),
                }
            ).eq("id", project_id).eq("user_id", user_id).execute()
            row["source_object_status"] = SOURCE_OBJECT_STATUS_STORED
        except Exception:
            if storage_path:
                try:
                    client.storage.from_(BUCKET_ID).remove([storage_path])
                except Exception as cleanup_exc:
                    if not _looks_like_storage_not_found(cleanup_exc):
                        logger.warning(
                            "No se pudo limpiar el PDF tras fallo de upload (project_id=%s): %s",
                            project_id,
                            cleanup_exc,
                        )
            client.table("projects").delete().eq("id", project_id).eq("user_id", user_id).execute()
            raise

    return _row_to_project(row)


def get_project(project_id: str, user_id: str, include_internal: bool = False) -> Optional[dict[str, Any]]:
    """Load project by id and user_id. Returns None if not found."""
    client = _client()
    r = client.table("projects").select("*").eq("id", project_id).eq("user_id", user_id).maybe_single().execute()
    if r is None:
        logger.warning(
            "Supabase projects select returned None from execute() (project_id=%s)",
            project_id,
        )
        return None
    if not r.data:
        return None
    return _row_to_project(r.data, include_internal=include_internal)


def list_projects(user_id: str) -> list[dict[str, Any]]:
    """List projects for user, newest first."""
    client = _client()
    r = client.table("projects").select("*").eq("user_id", user_id).order("updated_at", desc=True).execute()
    rows = (r.data or []) if r else []
    return [_row_to_project(row) for row in rows]


def update_project(project_id: str, user_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Update project; only fields in updates are changed. Returns updated project or None."""
    project = get_project(project_id, user_id)
    if not project:
        return None
    allowed = {
        "name",
        "description",
        "pdf_filename",
        "source_type",
        "source_url",
        "source_text",
        "source_metadata",
        "file_uri",
        "status",
        "segmentation",
        "partes_contenido",
        "usage",
        "reading_progress",
        "error_message",
        "share_token",
        "source_object_path",
        "source_object_status",
        "source_object_deleted_at",
    }
    payload = {k: v for k, v in updates.items() if k in allowed}
    payload["updated_at"] = _now_iso()
    client = _client()
    client.table("projects").update(payload).eq("id", project_id).eq("user_id", user_id).execute()
    return get_project(project_id, user_id)


def update_reading_progress(
    project_id: str,
    user_id: str,
    part_id: int,
) -> Optional[dict[str, Any]]:
    """Mark a section as read. Adds part_id to completed_parts, deduplicated and sorted.
    Returns updated project or None if not found."""
    return set_section_read_status(project_id, user_id, part_id, completed=True)


def update_subsection_progress(
    project_id: str,
    user_id: str,
    subsection_id: str,
    part_id: int,
    completed: Optional[bool] = None,
    is_last_read: bool = False,
    tab: str = "explicacion",
    project: dict[str, Any] | None = None,
) -> Optional[dict[str, Any]]:
    """Update subsection progress inside reading_progress JSONB.
    completed=True adds to completed_subsections; is_last_read=True updates last_subsection."""
    project = project or get_project_progress_context(project_id, user_id)
    if not project:
        return None
    completed_ids = [subsection_id] if completed is True else None
    uncompleted_ids = [subsection_id] if completed is False else None
    last_subsection_id = subsection_id if is_last_read else None
    return _subsection_progress_update(
        project_id,
        user_id,
        project,
        part_id=part_id,
        tab=tab,
        completed_subsection_ids=completed_ids,
        uncompleted_subsection_ids=uncompleted_ids,
        last_subsection_id=last_subsection_id,
    )


def update_subsection_progress_batch(
    project_id: str,
    user_id: str,
    part_id: int,
    *,
    tab: str = "explicacion",
    completed_subsection_ids: list[str] | None = None,
    last_subsection_id: str | None = None,
    project: dict[str, Any] | None = None,
) -> Optional[dict[str, Any]]:
    """Apply a compact batch of subsection progress changes."""
    project = project or get_project_progress_context(project_id, user_id)
    if not project:
        return None
    return _subsection_progress_update(
        project_id,
        user_id,
        project,
        part_id=part_id,
        tab=tab,
        completed_subsection_ids=completed_subsection_ids,
        last_subsection_id=last_subsection_id,
    )


def set_section_read_status(
    project_id: str,
    user_id: str,
    part_id: int,
    completed: bool,
    project: dict[str, Any] | None = None,
) -> Optional[dict[str, Any]]:
    """Set section read status. completed=True adds to completed_parts, completed=False removes.
    Returns updated project or None if not found."""
    project = project or get_project_progress_context(project_id, user_id)
    if not project:
        return None
    progress = dict(project.get("reading_progress") or {})
    completed_list = list(progress.get("completed_parts") or [])

    if completed:
        if part_id in completed_list:
            return _progress_response(progress, project.get("updated_at"))
        completed_list.append(part_id)
        completed_list.sort()
    else:
        if part_id not in completed_list:
            return _progress_response(progress, project.get("updated_at"))
        completed_list = [p for p in completed_list if p != part_id]

    new_progress = {
        **progress,
        "completed_parts": completed_list,
        "last_read_at": _now_iso(),
    }
    return _update_reading_progress_minimal(
        project_id,
        user_id,
        new_progress,
        updated_at=new_progress["last_read_at"],
    )


def delete_project(project_id: str, user_id: str) -> bool:
    """Delete project row and its PDF from Storage (if PDF type). Returns True if deleted."""
    project = get_project(project_id, user_id, include_internal=True)
    if not project:
        return False

    if project.get("source_type") == "pdf":
        delete_project_source_object(project_id, user_id, project=project)

    _client().table("projects").delete().eq("id", project_id).eq("user_id", user_id).execute()
    return True


# ========== Project Sharing ==========


def _sanitize_project_for_shared(project: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive data and trim segmentation/partes_contenido for public sharing."""
    # Strip sensitive fields
    out = {
        "id": project["id"],
        "name": project["name"],
        "description": project["description"],
        "status": project["status"],
        "created_at": project["created_at"],
        "updated_at": project["updated_at"],
    }

    # Segmentation: numero, titulo, contenido for navigation and part header
    seg = project.get("segmentation") or {}
    partes_raw = seg.get("partes") or []
    out["segmentation"] = {
        "partes": [
            {"numero": p["numero"], "titulo": p.get("titulo", ""), "contenido": p.get("contenido", "")}
            for p in partes_raw
        ],
    }

    # Partes contenido: only completed parts, only explainer/recorrido/resources
    contenido_raw = project.get("partes_contenido") or {}
    out["partes_contenido"] = {}
    for part_key, part_data in contenido_raw.items():
        if not isinstance(part_data, dict):
            continue
        if part_data.get("status") != "completed":
            continue
        out["partes_contenido"][part_key] = {
            "explainer": part_data.get("explainer"),
            "recorrido": part_data.get("recorrido"),
            "resources": part_data.get("resources"),
        }

    return out


def get_project_by_share_token(share_token: str) -> Optional[dict[str, Any]]:
    """Load project by share_token for public viewing. Returns sanitized project or None."""
    if not share_token or not share_token.strip():
        return None
    client = _client()
    r = (
        client.table("projects")
        .select("*")
        .eq("share_token", share_token.strip())
        .maybe_single()
        .execute()
    )
    if not r or not r.data:
        return None
    project = _row_to_project(r.data)
    if project.get("status") != "completed":
        return None
    return _sanitize_project_for_shared(project)


def create_share_token(project_id: str, user_id: str) -> Optional[str]:
    """Create share token for project. Verifies ownership. Returns token or None."""
    project = get_project(project_id, user_id)
    if not project:
        return None
    if project.get("status") != "completed":
        return None
    if project.get("share_token"):
        return project["share_token"]
    token = secrets.token_urlsafe(24)
    update_project(project_id, user_id, {"share_token": token})
    return token


def revoke_share_token(project_id: str, user_id: str) -> bool:
    """Revoke share token. Verifies ownership. Returns True if revoked."""
    project = get_project(project_id, user_id)
    if not project:
        return False
    update_project(project_id, user_id, {"share_token": None})
    return True


def export_projects_payload(user_id: str) -> dict[str, Any]:
    """Export format compatible with frontend/import."""
    projects = list_projects(user_id)
    return {
        "version": 1,
        "exported_at": _now_iso(),
        "projects": projects,
    }


def import_projects_payload(user_id: str, payload: dict[str, Any]) -> dict[str, int]:
    """Import projects from export payload; assigns user_id. No PDFs (metadata only)."""
    projects = payload.get("projects")
    if not isinstance(projects, list):
        raise ValueError("Formato inválido: falta lista de proyectos")
    client = _client()
    imported = 0
    skipped = 0
    for project in projects:
        if not isinstance(project, dict):
            skipped += 1
            continue
        required = ["name", "pdf_filename", "status"]
        if any(not project.get(k) for k in required):
            skipped += 1
            continue
        project_id = str(uuid.uuid4())
        created = _now_iso()
        row = {
            "id": project_id,
            "user_id": user_id,
            "name": project["name"],
            "description": project["description"],
            "pdf_filename": project["pdf_filename"],
            "source_type": project.get("source_type", "pdf"),
            "source_url": project.get("source_url"),
            "source_metadata": project.get("source_metadata") or {},
            "file_uri": project.get("file_uri"),
            "status": project.get("status", "completed"),
            "segmentation": project.get("segmentation"),
            "partes_contenido": project.get("partes_contenido") or {},
            "usage": project.get("usage") or {},
            "reading_progress": project.get("reading_progress") or {},
            "error_message": project.get("error_message"),
            "source_object_path": None,
            "source_object_status": SOURCE_OBJECT_STATUS_NONE,
            "source_object_deleted_at": None,
            "created_at": project.get("created_at") or created,
            "updated_at": project.get("updated_at") or created,
        }
        try:
            client.table("projects").insert(row).execute()
            imported += 1
        except Exception:
            skipped += 1
    return {"imported": imported, "skipped": skipped}


def download_pdf_to_temp(project_id: str, user_id: str) -> Optional[str]:
    """Download project PDF from Storage to a temp file. Returns temp file path or None. Caller must unlink.

    Returns None for YouTube projects (no PDF to download).
    """
    project = get_project(project_id, user_id, include_internal=True)
    if not project:
        return None

    # Only PDF projects are backed by Storage uploads.
    if project.get("source_type") != "pdf":
        return None

    if project.get("source_object_status") == SOURCE_OBJECT_STATUS_DELETED:
        logger.info(
            "Se intentó descargar un PDF ya eliminado (project_id=%s, user_id=%s...)",
            project_id,
            user_id[:8],
        )
        return None

    storage_path = project.get("source_object_path")
    if not storage_path and project.get("source_object_status") == SOURCE_OBJECT_STATUS_STORED:
        storage_path = _project_storage_path(user_id, project_id, project["pdf_filename"])
    if not storage_path:
        return None

    try:
        data = _client().storage.from_(BUCKET_ID).download(storage_path)
    except Exception:
        return None
    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return path


def delete_project_source_object(
    project_id: str,
    user_id: str,
    *,
    project: dict[str, Any] | None = None,
) -> bool:
    """Delete the stored PDF object for a project and mark it deleted.

    The operation is idempotent: if the object is already gone, the DB row is still
    marked as deleted so startup reconciliation can converge.
    """
    project = project or get_project(project_id, user_id, include_internal=True)
    if not project or project.get("source_type") != "pdf":
        return False

    if project.get("source_object_status") == SOURCE_OBJECT_STATUS_DELETED:
        return False

    storage_path = project.get("source_object_path")
    if not storage_path and project.get("source_object_status") == SOURCE_OBJECT_STATUS_STORED:
        storage_path = _project_storage_path(user_id, project_id, project["pdf_filename"])

    if storage_path:
        try:
            _client().storage.from_(BUCKET_ID).remove([storage_path])
        except Exception as exc:
            if not _looks_like_storage_not_found(exc):
                raise

    deleted_at = _now_iso()
    _client().table("projects").update(
        {
            "source_object_status": SOURCE_OBJECT_STATUS_DELETED,
            "source_object_deleted_at": deleted_at,
            "updated_at": deleted_at,
        }
    ).eq("id", project_id).eq("user_id", user_id).execute()
    return True


def list_projects_with_stored_source_objects() -> list[dict[str, Any]]:
    """Return PDF projects whose source object still exists in Supabase storage."""
    client = _client()
    result = (
        client.table("projects")
        .select("*")
        .eq("source_type", "pdf")
        .eq("source_object_status", SOURCE_OBJECT_STATUS_STORED)
        .execute()
    )
    rows = (result.data or []) if result else []
    return [_row_to_project(row, include_internal=True) for row in rows]


# ========== User API Keys (BYOK) ==========

PROVIDER_GEMINI = "google_gemini"
PROVIDER_OPENROUTER = "openrouter"
PROVIDER_MISTRAL = "mistral"


def has_user_api_key(user_id: str, provider: str = PROVIDER_GEMINI) -> bool:
    """Check if user has an API key configured for the given provider."""
    client = _client()
    try:
        r = (
            client.table("user_api_keys")
            .select("user_id")
            .eq("user_id", user_id)
            .eq("provider", provider)
            .maybe_single()
            .execute()
        )
        result = bool(r and r.data)
        logger.debug("[has_user_api_key] user=%s... provider=%s result=%s", user_id[:8], provider, result)
        return result
    except Exception as e:
        logger.error(f"[has_user_api_key] Error for user {user_id[:8]}... provider={provider}: {type(e).__name__}: {e}")
        return False


def get_user_api_key(user_id: str, provider: str = PROVIDER_GEMINI) -> Optional[str]:
    """
    Get and decrypt the user's API key for the given provider.

    Args:
        user_id: UUID of the user
        provider: API provider identifier (default: google_gemini)

    Returns:
        Decrypted API key or None if not found
    """
    client = _client()
    try:
        r = (
            client.table("user_api_keys")
            .select("encrypted_api_key")
            .eq("user_id", user_id)
            .eq("provider", provider)
            .maybe_single()
            .execute()
        )
        if not r or not r.data:
            return None
        encrypted_key = r.data["encrypted_api_key"]
        return decrypt_user_api_key(encrypted_key, user_id)
    except Exception:
        return None


def set_user_api_key(user_id: str, api_key: str, provider: str = PROVIDER_GEMINI) -> None:
    """
    Encrypt and save the user's API key (BYOK).

    Args:
        user_id: UUID of the user
        api_key: API key in plain text (will be encrypted before storage)
        provider: API provider identifier (composite PK with user_id)
    """
    client = _client()
    encrypted_key = encrypt_user_api_key(api_key, user_id)

    row = {
        "user_id": user_id,
        "encrypted_api_key": encrypted_key,
        "provider": provider,
    }

    # Atomic upsert: insert if not exists, update if exists — PK is (user_id, provider)
    client.table("user_api_keys").upsert(row, on_conflict="user_id,provider").execute()


def delete_user_api_key(user_id: str, provider: str = PROVIDER_GEMINI) -> bool:
    """
    Delete the user's API key for the given provider.

    Args:
        user_id: UUID of the user
        provider: API provider identifier (default: google_gemini)

    Returns:
        True if deleted, False if not found
    """
    client = _client()
    try:
        existing = (
            client.table("user_api_keys")
            .select("user_id")
            .eq("user_id", user_id)
            .eq("provider", provider)
            .maybe_single()
            .execute()
        )
        if not existing or not existing.data:
            return False
        client.table("user_api_keys").delete().eq("user_id", user_id).eq("provider", provider).execute()
        return True
    except Exception:
        return False


def get_user_api_key_status(user_id: str) -> dict[str, Any]:
    """
    Get API key status for all providers (safe for returning to frontend).

    Returns status without exposing any sensitive data.
    Backwards-compatible: always includes has_api_key / provider / updated_at for Gemini.
    Adds has_openrouter_key / openrouter_updated_at for OpenRouter.
    Adds has_mistral_key / mistral_updated_at for Mistral.
    """
    client = _client()
    gemini_data: dict = {}
    openrouter_data: dict = {}
    mistral_data: dict = {}

    try:
        rows = (
            client.table("user_api_keys")
            .select("provider, updated_at")
            .eq("user_id", user_id)
            .execute()
        )
        if rows and rows.data:
            for row in rows.data:
                if row.get("provider") == PROVIDER_GEMINI:
                    gemini_data = row
                elif row.get("provider") == PROVIDER_OPENROUTER:
                    openrouter_data = row
                elif row.get("provider") == PROVIDER_MISTRAL:
                    mistral_data = row
    except Exception as e:
        logger.error(f"[API Key Status] Error for user {user_id[:8]}...: {type(e).__name__}: {e}")

    return {
        # Gemini (backwards-compatible fields)
        "has_api_key": bool(gemini_data),
        "provider": gemini_data.get("provider") or None,
        "updated_at": gemini_data.get("updated_at") or None,
        # OpenRouter (new fields)
        "has_openrouter_key": bool(openrouter_data),
        "openrouter_updated_at": openrouter_data.get("updated_at") or None,
        # Mistral (new fields)
        "has_mistral_key": bool(mistral_data),
        "mistral_updated_at": mistral_data.get("updated_at") or None,
    }
