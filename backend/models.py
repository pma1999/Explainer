from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    candidates_tokens: int = 0
    thoughts_tokens: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0


class ProjectSummary(BaseModel):
    id: str
    name: str
    description: str
    created_at: str
    status: str
    pdf_filename: str
    num_partes: int = 0
    total_cost: float = 0.0


class Project(BaseModel):
    id: str
    name: str
    description: str
    created_at: str
    status: str
    pdf_filename: str
    file_uri: Optional[str] = None
    segmentation: Optional[dict[str, Any]] = None
    partes_contenido: dict[str, Any] = {}
    usage: UsageInfo = UsageInfo()
    error_message: Optional[str] = None
