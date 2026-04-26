"""Project progress handlers shared by API routes and unit tests."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from backend.supabase_data import (
    apply_section_progress_rpc,
    apply_subsection_progress_rpc,
)

logger = logging.getLogger("backend.project_progress")

_SUCCESS_STATUSES = {"ok", "noop"}


def _coerce_part_id(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="part_id debe ser un número") from None


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


def _status_response(status: str) -> dict[str, bool]:
    if status in _SUCCESS_STATUSES:
        return {"ok": True}
    if status == "not_found":
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    if status == "part_not_found":
        raise HTTPException(status_code=400, detail="Sección no encontrada")
    if status == "content_not_ready":
        raise HTTPException(status_code=400, detail="El contenido de esta sección aún no está listo")
    if status == "invalid_subsection":
        raise HTTPException(status_code=400, detail="subsection_id no pertenece a la sección")

    logger.error("Unexpected project progress RPC status: %s", status)
    raise HTTPException(status_code=500, detail="No se pudo actualizar el progreso")


def handle_update_section_progress(
    user_id: str,
    project_id: str,
    body: dict[str, Any],
) -> dict[str, bool]:
    """Validate and update section reading progress via a compact RPC."""
    part_id = body.get("part_id")
    if part_id is None:
        raise HTTPException(status_code=400, detail="part_id requerido")
    part_id = _coerce_part_id(part_id)

    completed = body.get("completed", True)
    if not isinstance(completed, bool):
        completed = True

    status = apply_section_progress_rpc(
        project_id,
        user_id,
        part_id,
        completed=completed,
    )
    return _status_response(status)


def handle_update_subsection_progress(
    user_id: str,
    project_id: str,
    body: dict[str, Any],
) -> dict[str, bool]:
    """Validate and update subsection reading progress via a compact RPC."""
    subsection_id = body.get("subsection_id")
    part_id = body.get("part_id")
    last_subsection_id = body.get("last_subsection_id")
    has_batch_payload = (
        "last_subsection_id" in body
        or "completed_subsection_ids" in body
        or "uncompleted_subsection_ids" in body
    )

    if part_id is None or (not subsection_id and not has_batch_payload):
        raise HTTPException(status_code=400, detail="subsection_id y part_id requeridos")
    part_id = _coerce_part_id(part_id)

    completed = body.get("completed")
    if completed is not None and not isinstance(completed, bool):
        raise HTTPException(status_code=400, detail="completed debe ser boolean")
    is_last_read = body.get("is_last_read", False)
    if not isinstance(is_last_read, bool):
        is_last_read = False

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
        uncompleted_subsection_ids = _normalize_completed_subsection_ids(
            body.get("uncompleted_subsection_ids"),
            part_id,
        )
        status = apply_subsection_progress_rpc(
            project_id,
            user_id,
            part_id,
            tab=tab,
            completed_subsection_ids=completed_subsection_ids,
            uncompleted_subsection_ids=uncompleted_subsection_ids,
            last_subsection_id=last_subsection_id,
        )
        return _status_response(status)

    _validate_subsection_id(subsection_id, part_id)
    completed_subsection_ids = [subsection_id] if completed is True else []
    uncompleted_subsection_ids = [subsection_id] if completed is False else []
    last_subsection_id = subsection_id if is_last_read else None

    status = apply_subsection_progress_rpc(
        project_id,
        user_id,
        part_id,
        tab=tab,
        completed_subsection_ids=completed_subsection_ids,
        uncompleted_subsection_ids=uncompleted_subsection_ids,
        last_subsection_id=last_subsection_id,
    )
    return _status_response(status)
