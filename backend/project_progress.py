"""Project progress handlers shared by API routes and unit tests."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend.supabase_data import (
    get_project_progress_context,
    update_subsection_progress,
    update_subsection_progress_batch,
)


def _coerce_part_id(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="part_id debe ser un número") from None


def _validate_project_part(project: dict[str, Any], part_id: int) -> None:
    partes = project.get("segmentation") or {}
    partes_list = partes.get("partes") or []
    if not any(p.get("numero") == part_id for p in partes_list):
        raise HTTPException(status_code=400, detail="Sección no encontrada")


def _validate_subsection_id(subsection_id: str, part_id: int) -> None:
    if not isinstance(subsection_id, str) or not subsection_id:
        raise HTTPException(status_code=400, detail="subsection_id y part_id requeridos")
    if not subsection_id.startswith(f"subsec-{part_id}-"):
        raise HTTPException(status_code=400, detail="subsection_id no pertenece a la sección")


def _normalize_completed_subsection_ids(value: Any, part_id: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail="completed_subsection_ids debe ser una lista")

    out: list[str] = []
    seen = set()
    for item in value:
        _validate_subsection_id(item, part_id)
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def handle_update_subsection_progress(
    user_id: str,
    project_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Validate and update subsection reading progress."""
    subsection_id = body.get("subsection_id")
    part_id = body.get("part_id")
    last_subsection_id = body.get("last_subsection_id")
    has_batch_payload = "last_subsection_id" in body or "completed_subsection_ids" in body

    if part_id is None or (not subsection_id and not has_batch_payload):
        raise HTTPException(status_code=400, detail="subsection_id y part_id requeridos")
    part_id = _coerce_part_id(part_id)

    completed = body.get("completed")
    if completed is not None and not isinstance(completed, bool):
        raise HTTPException(status_code=400, detail="completed debe ser boolean")
    is_last_read = body.get("is_last_read", False)
    if not isinstance(is_last_read, bool):
        is_last_read = False

    project = get_project_progress_context(project_id, user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    _validate_project_part(project, part_id)

    tab = body.get("tab")
    if not isinstance(tab, str) or not tab:
        tab = "explicacion"

    if has_batch_payload:
        if last_subsection_id is not None:
            _validate_subsection_id(last_subsection_id, part_id)
        completed_subsection_ids = _normalize_completed_subsection_ids(
            body.get("completed_subsection_ids"),
            part_id,
        )
        updated = update_subsection_progress_batch(
            project_id,
            user_id,
            part_id,
            tab=tab,
            completed_subsection_ids=completed_subsection_ids,
            last_subsection_id=last_subsection_id,
            project=project,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Proyecto no encontrado")
        return updated

    _validate_subsection_id(subsection_id, part_id)
    updated = update_subsection_progress(
        project_id,
        user_id,
        subsection_id,
        part_id,
        completed=completed,
        is_last_read=is_last_read,
        tab=tab,
        project=project,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return updated
