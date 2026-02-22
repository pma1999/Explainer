"""Project persistence and PDF storage via Supabase (Postgres + Storage)."""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime
from typing import Any, Optional

from supabase import create_client, Client

from backend.crypto import encrypt_user_api_key, decrypt_user_api_key

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
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "pdf_filename": row["pdf_filename"],
        "file_uri": row.get("file_uri"),
        "status": row["status"],
        "segmentation": row.get("segmentation"),
        "partes_contenido": row.get("partes_contenido") or {},
        "usage": row.get("usage") or {},
        "error_message": row.get("error_message"),
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
        "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
    }


def create_project(
    user_id: str,
    name: str,
    description: str,
    pdf_filename: str,
    pdf_content: bytes,
) -> dict[str, Any]:
    """Insert project and upload PDF to Storage. Returns project dict."""
    client = _client()
    project_id = str(uuid.uuid4())
    now = _now_iso()
    row = {
        "id": project_id,
        "user_id": user_id,
        "name": name,
        "description": description,
        "pdf_filename": pdf_filename,
        "file_uri": None,
        "status": "pending",
        "segmentation": None,
        "partes_contenido": {},
        "usage": {},
        "error_message": None,
        "created_at": now,
        "updated_at": now,
    }
    client.table("projects").insert(row).execute()

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
    allowed = {"name", "description", "pdf_filename", "file_uri", "status", "segmentation", "partes_contenido", "usage", "error_message"}
    payload = {k: v for k, v in updates.items() if k in allowed}
    payload["updated_at"] = _now_iso()
    client = _client()
    client.table("projects").update(payload).eq("id", project_id).eq("user_id", user_id).execute()
    return get_project(project_id, user_id)


def delete_project(project_id: str, user_id: str) -> bool:
    """Delete project row and its PDF from Storage. Returns True if deleted."""
    project = get_project(project_id, user_id)
    if not project:
        return False
    storage_path = f"{user_id}/{project_id}/{project['pdf_filename']}"
    try:
        _client().storage.from_(BUCKET_ID).remove([storage_path])
    except Exception:
        pass
    _client().table("projects").delete().eq("id", project_id).eq("user_id", user_id).execute()
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
        required = ["name", "description", "pdf_filename", "status"]
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
            "file_uri": project.get("file_uri"),
            "status": project.get("status", "completed"),
            "segmentation": project.get("segmentation"),
            "partes_contenido": project.get("partes_contenido") or {},
            "usage": project.get("usage") or {},
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
    """Download project PDF from Storage to a temp file. Returns temp file path or None. Caller must unlink."""
    project = get_project(project_id, user_id)
    if not project:
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
    r = client.table("user_api_keys").select("user_id").eq("user_id", user_id).maybe_single().execute()
    return bool(r.data)


def get_user_api_key(user_id: str) -> Optional[str]:
    """
    Get and decrypt the user's API key.

    Args:
        user_id: UUID of the user

    Returns:
        Decrypted API key or None if not found
    """
    client = _client()
    r = client.table("user_api_keys").select("encrypted_api_key").eq("user_id", user_id).maybe_single().execute()
    if not r.data:
        return None

    encrypted_key = r.data["encrypted_api_key"]
    return decrypt_user_api_key(encrypted_key, user_id)


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

    # Upsert: insert if not exists, update if exists
    row = {
        "user_id": user_id,
        "encrypted_api_key": encrypted_key,
        "provider": provider,
    }

    # Try update first
    existing = client.table("user_api_keys").select("user_id").eq("user_id", user_id).maybe_single().execute()
    if existing.data:
        client.table("user_api_keys").update(row).eq("user_id", user_id).execute()
    else:
        client.table("user_api_keys").insert(row).execute()


def delete_user_api_key(user_id: str) -> bool:
    """
    Delete the user's API key.

    Args:
        user_id: UUID of the user

    Returns:
        True if deleted, False if not found
    """
    client = _client()
    existing = client.table("user_api_keys").select("user_id").eq("user_id", user_id).maybe_single().execute()
    if not existing.data:
        return False

    client.table("user_api_keys").delete().eq("user_id", user_id).execute()
    return True


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
    r = client.table("user_api_keys").select("provider, updated_at").eq("user_id", user_id).maybe_single().execute()

    if r.data:
        return {
            "has_api_key": True,
            "provider": r.data.get("provider"),
            "updated_at": r.data.get("updated_at"),
        }

    return {
        "has_api_key": False,
        "provider": None,
        "updated_at": None,
    }
