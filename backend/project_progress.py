"""Project progress handlers shared by API routes and unit tests."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend.supabase_data import get_project, update_subsection_progress


def handle_update_subsection_progress(
    user_id: str,
    project_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Validate and update subsection reading progress."""
    subsection_id = body.get("subsection_id")
    part_id = body.get("part_id")
    if not subsection_id or part_id is None:
        raise HTTPException(status_code=400, detail="subsection_id y part_id requeridos")
    try:
        part_id = int(part_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="part_id debe ser un número")

    completed = body.get("completed")
    if completed is not None and not isinstance(completed, bool):
        raise HTTPException(status_code=400, detail="completed debe ser boolean")
    is_last_read = body.get("is_last_read", False)
    if not isinstance(is_last_read, bool):
        is_last_read = False

    project = get_project(project_id, user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    partes = project.get("segmentation") or {}
    partes_list = partes.get("partes") or []
    if not any(p.get("numero") == part_id for p in partes_list):
        raise HTTPException(status_code=400, detail="Sección no encontrada")

    if not subsection_id.startswith(f"subsec-{part_id}-"):
        raise HTTPException(status_code=400, detail="subsection_id no pertenece a la sección")

    updated = update_subsection_progress(
        project_id,
        user_id,
        subsection_id,
        part_id,
        completed=completed,
        is_last_read=is_last_read,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return updated
