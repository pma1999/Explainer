"""Project persistence and PDF storage via Supabase (Postgres + Storage)."""

from __future__ import annotations

import logging
import os
import secrets
import tempfile
import uuid
from datetime import datetime
from typing import Any, Optional

from supabase import create_client, Client

from backend.crypto import encrypt_user_api_key, decrypt_user_api_key

logger = logging.getLogger("backend.supabase_data")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
BUCKET_ID = "project-pdfs"


def _client() -> Client:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _row_to_project(row: dict[str, Any]) -> dict[str, Any]:
    """Convert DB row to API-shaped project dict (id str, dates ISO)."""
    result = {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "pdf_filename": row["pdf_filename"],
        "source_type": row.get("source_type", "pdf"),
        "source_url": row.get("source_url"),
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
    return result


def create_project(
    user_id: str,
    name: str,
    description: str,
    pdf_filename: str,
    pdf_content: bytes | None = None,
    source_type: str = "pdf",
    source_url: str | None = None,
) -> dict[str, Any]:
    """Insert project and optionally upload PDF to Storage. Returns project dict.

    Args:
        user_id: UUID of the user
        name: Project name
        description: Project description
        pdf_filename: Filename (for PDFs) or display name (for YouTube)
        pdf_content: PDF file bytes (only for source_type='pdf')
        source_type: 'pdf' or 'youtube'
        source_url: YouTube URL (only for source_type='youtube')
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
        "file_uri": None,
        "status": "pending",
        "segmentation": None,
        "partes_contenido": {},
        "usage": {},
        "reading_progress": {},
        "error_message": None,
        "created_at": now,
        "updated_at": now,
    }
    client.table("projects").insert(row).execute()

    # Only upload to storage for PDF source type
    if source_type == "pdf" and pdf_content:
        storage_path = f"{user_id}/{project_id}/{pdf_filename}"
        client.storage.from_(BUCKET_ID).upload(path=storage_path, file=pdf_content, file_options={"content-type": "application/pdf", "upsert": "false"})

    return _row_to_project(row)


def get_project(project_id: str, user_id: str) -> Optional[dict[str, Any]]:
    """Load project by id and user_id. Returns None if not found."""
    client = _client()
    r = client.table("projects").select("*").eq("id", project_id).eq("user_id", user_id).maybe_single().execute()
    if not r.data:
        return None
    return _row_to_project(r.data)


def list_projects(user_id: str) -> list[dict[str, Any]]:
    """List projects for user, newest first."""
    client = _client()
    r = client.table("projects").select("*").eq("user_id", user_id).order("updated_at", desc=True).execute()
    return [_row_to_project(row) for row in (r.data or [])]


def update_project(project_id: str, user_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Update project; only fields in updates are changed. Returns updated project or None."""
    project = get_project(project_id, user_id)
    if not project:
        return None
    allowed = {"name", "description", "pdf_filename", "source_type", "source_url", "file_uri", "status", "segmentation", "partes_contenido", "usage", "reading_progress", "error_message", "share_token"}
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


def set_section_read_status(
    project_id: str,
    user_id: str,
    part_id: int,
    completed: bool,
) -> Optional[dict[str, Any]]:
    """Set section read status. completed=True adds to completed_parts, completed=False removes.
    Returns updated project or None if not found."""
    project = get_project(project_id, user_id)
    if not project:
        return None
    progress = project.get("reading_progress") or {}
    completed_list = list(progress.get("completed_parts") or [])

    if completed:
        if part_id in completed_list:
            return project
        completed_list.append(part_id)
        completed_list.sort()
    else:
        completed_list = [p for p in completed_list if p != part_id]

    new_progress = {
        "completed_parts": completed_list,
        "last_read_at": _now_iso(),
    }
    return update_project(project_id, user_id, {"reading_progress": new_progress})


def delete_project(project_id: str, user_id: str) -> bool:
    """Delete project row and its PDF from Storage (if PDF type). Returns True if deleted."""
    project = get_project(project_id, user_id)
    if not project:
        return False

    # Only delete from storage for PDF projects
    if project.get("source_type") == "pdf":
        storage_path = f"{user_id}/{project_id}/{project['pdf_filename']}"
        try:
            _client().storage.from_(BUCKET_ID).remove([storage_path])
        except Exception:
            pass

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
    if not r.data:
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
            "file_uri": project.get("file_uri"),
            "status": project.get("status", "completed"),
            "segmentation": project.get("segmentation"),
            "partes_contenido": project.get("partes_contenido") or {},
            "usage": project.get("usage") or {},
            "reading_progress": project.get("reading_progress") or {},
            "error_message": project.get("error_message"),
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
    project = get_project(project_id, user_id)
    if not project:
        return None

    # YouTube projects don't have a PDF to download
    if project.get("source_type") == "youtube":
        return None

    storage_path = f"{user_id}/{project_id}/{project['pdf_filename']}"
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


# ========== User API Keys (BYOK) ==========

def has_user_api_key(user_id: str) -> bool:
    """Check if user has an API key configured."""
    client = _client()
    try:
        r = client.table("user_api_keys").select("user_id").eq("user_id", user_id).maybe_single().execute()
        result = bool(r and r.data)
        logger.debug("[has_user_api_key] user=%s... result=%s", user_id[:8], result)
        return result
    except Exception as e:
        logger.error(f"[has_user_api_key] Error for user {user_id[:8]}...: {type(e).__name__}: {e}")
        return False


def get_user_api_key(user_id: str) -> Optional[str]:
    """
    Get and decrypt the user's API key.

    Args:
        user_id: UUID of the user

    Returns:
        Decrypted API key or None if not found
    """
    client = _client()
    try:
        r = client.table("user_api_keys").select("encrypted_api_key").eq("user_id", user_id).maybe_single().execute()
        if not r or not r.data:
            return None

        encrypted_key = r.data["encrypted_api_key"]
        return decrypt_user_api_key(encrypted_key, user_id)
    except Exception:
        return None


def set_user_api_key(user_id: str, api_key: str, provider: str = "google_gemini") -> None:
    """
    Encrypt and save the user's API key (BYOK).

    Args:
        user_id: UUID of the user
        api_key: API key in plain text (will be encrypted before storage)
        provider: API provider identifier
    """
    client = _client()
    encrypted_key = encrypt_user_api_key(api_key, user_id)

    row = {
        "user_id": user_id,
        "encrypted_api_key": encrypted_key,
        "provider": provider,
    }

    # Atomic upsert: insert if not exists, update if exists (user_id is PK)
    client.table("user_api_keys").upsert(row, on_conflict="user_id").execute()


def delete_user_api_key(user_id: str) -> bool:
    """
    Delete the user's API key.

    Args:
        user_id: UUID of the user

    Returns:
        True if deleted, False if not found
    """
    client = _client()
    try:
        existing = client.table("user_api_keys").select("user_id").eq("user_id", user_id).maybe_single().execute()
        if not existing or not existing.data:
            return False

        client.table("user_api_keys").delete().eq("user_id", user_id).execute()
        return True
    except Exception:
        return False


def get_user_api_key_status(user_id: str) -> dict[str, Any]:
    """
    Get API key status for a user (safe for returning to frontend).

    Returns info about API key without exposing any sensitive data.

    Args:
        user_id: UUID of the user

    Returns:
        Dict with has_api_key (bool), provider (str or None), updated_at (str or None)
    """
    client = _client()
    try:
        r = client.table("user_api_keys").select("provider, updated_at").eq("user_id", user_id).maybe_single().execute()

        if r and r.data:
            return {
                "has_api_key": True,
                "provider": r.data.get("provider"),
                "updated_at": r.data.get("updated_at"),
            }
        logger.warning(f"[API Key Status] No data found for user {user_id[:8]}... r={r}")
    except Exception as e:
        logger.error(f"[API Key Status] Error for user {user_id[:8]}...: {type(e).__name__}: {e}")

    return {
        "has_api_key": False,
        "provider": None,
        "updated_at": None,
    }
