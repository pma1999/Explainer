"""Persistencia local sin usuarios usando archivos JSON."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path(os.environ.get("EXPLAINER_DATA_DIR", "data"))
PROJECTS_DIR = DATA_DIR / "projects"
SETTINGS_PATH = DATA_DIR / "settings.json"


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def _project_json_path(project_id: str) -> Path:
    return _project_dir(project_id) / "project.json"


def init_local_data() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


# ===== Settings =====

def _read_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {}
    return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))


def _write_settings(payload: dict[str, Any]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def get_encrypted_api_key() -> Optional[str]:
    return _read_settings().get("gemini_api_key_encrypted")


def set_encrypted_api_key(encrypted_api_key: Optional[str]) -> None:
    data = _read_settings()
    data["gemini_api_key_encrypted"] = encrypted_api_key
    data["updated_at"] = _now_iso()
    _write_settings(data)


# ===== Projects =====

def create_project(name: str, description: str, pdf_filename: str) -> dict[str, Any]:
    project_id = str(uuid.uuid4())
    project = {
        "id": project_id,
        "name": name,
        "description": description,
        "pdf_filename": pdf_filename,
        "file_uri": None,
        "status": "pending",
        "segmentation": None,
        "partes_contenido": {},
        "usage": {},
        "error_message": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    persist_project(project)
    return project


def get_project(project_id: str) -> Optional[dict[str, Any]]:
    path = _project_json_path(project_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def persist_project(project: dict[str, Any]) -> None:
    project["updated_at"] = _now_iso()
    path = _project_json_path(project["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")


def update_project(project_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    project = get_project(project_id)
    if not project:
        return None
    project.update(updates)
    persist_project(project)
    return project


def list_projects() -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    if not PROJECTS_DIR.exists():
        return projects

    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        pj = project_dir / "project.json"
        if not pj.exists():
            continue
        try:
            projects.append(json.loads(pj.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue

    return sorted(projects, key=lambda p: p.get("created_at", ""), reverse=True)


def delete_project(project_id: str) -> bool:
    project_dir = _project_dir(project_id)
    if not project_dir.exists():
        return False
    for child in project_dir.glob("**/*"):
        if child.is_file():
            child.unlink(missing_ok=True)
    for child in sorted(project_dir.glob("**/*"), reverse=True):
        if child.is_dir():
            child.rmdir()
    project_dir.rmdir()
    return True


def export_projects_payload() -> dict[str, Any]:
    return {
        "version": 1,
        "exported_at": _now_iso(),
        "projects": list_projects(),
    }


def import_projects_payload(payload: dict[str, Any]) -> dict[str, int]:
    projects = payload.get("projects")
    if not isinstance(projects, list):
        raise ValueError("Formato inválido: falta lista de proyectos")

    imported = 0
    skipped = 0

    for project in projects:
        if not isinstance(project, dict):
            skipped += 1
            continue

        project_id = project.get("id") or str(uuid.uuid4())
        if get_project(project_id):
            project_id = str(uuid.uuid4())

        required = ["name", "description", "pdf_filename", "status"]
        if any(not project.get(k) for k in required):
            skipped += 1
            continue

        normalized = {
            "id": project_id,
            "name": project["name"],
            "description": project["description"],
            "pdf_filename": project["pdf_filename"],
            "file_uri": project.get("file_uri"),
            "status": project.get("status", "completed"),
            "segmentation": project.get("segmentation"),
            "partes_contenido": project.get("partes_contenido") or {},
            "usage": project.get("usage") or {},
            "error_message": project.get("error_message"),
            "created_at": project.get("created_at") or _now_iso(),
            "updated_at": project.get("updated_at") or _now_iso(),
        }
        persist_project(normalized)
        imported += 1

    return {"imported": imported, "skipped": skipped}
