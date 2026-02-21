"""Simple JSON-file-based persistence for projects."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path("data/projects")


def _project_path(project_id: str) -> Path:
    return DATA_DIR / project_id / "project.json"


def create_project(project_id: str, data: dict[str, Any]) -> None:
    path = _project_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_project(project_id: str) -> Optional[dict[str, Any]]:
    path = _project_path(project_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def update_project(project_id: str, updates: dict[str, Any]) -> None:
    project = get_project(project_id)
    if project is None:
        return
    project.update(updates)
    path = _project_path(project_id)
    path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_project(project_id: str) -> None:
    # Directory deletion is handled by the caller; just a no-op here
    pass


def list_projects() -> list[dict[str, Any]]:
    if not DATA_DIR.exists():
        return []
    projects = []
    for project_dir in sorted(DATA_DIR.iterdir(), reverse=True):
        project_file = project_dir / "project.json"
        if project_file.exists():
            data = json.loads(project_file.read_text(encoding="utf-8"))
            # Lightweight summary
            num_partes = 0
            if data.get("segmentation") and data["segmentation"].get("partes"):
                num_partes = len(data["segmentation"]["partes"])
            total_cost = 0.0
            if data.get("usage"):
                total_cost = data["usage"].get("total_cost", 0.0)

            projects.append({
                "id": data["id"],
                "name": data["name"],
                "description": data["description"],
                "created_at": data["created_at"],
                "status": data["status"],
                "pdf_filename": data["pdf_filename"],
                "num_partes": num_partes,
                "total_cost": total_cost,
            })
    return projects
