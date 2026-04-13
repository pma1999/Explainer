"""Audit whether a subpart explainer stayed inside its allowed scope."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types

from backend.gemini_client import gemini_retry, generate_content_with_retry


MAX_SUBPART_SCOPE_AUDIT_ATTEMPTS = 2


@dataclass(frozen=True, slots=True)
class SubpartScopeAuditReport:
    is_valid: bool
    invades_previous: tuple[str, ...]
    invades_next: tuple[str, ...]
    missing_current: tuple[str, ...]
    rationale: str


def flatten_desarrollo_text(payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    for section in payload.get("desarrollo") or []:
        chunks.append(str(section.get("titulo_seccion") or ""))
        chunks.append(str(section.get("explicacion_introductoria") or ""))
        for sub in section.get("subsecciones") or []:
            chunks.append(str(sub.get("titulo_subseccion") or ""))
            chunks.append(str(sub.get("explicacion_detallada") or ""))
    return "\n".join(chunk for chunk in chunks if chunk)


def build_subpart_scope_retry_suffix(report: SubpartScopeAuditReport) -> str:
    lines = [
        "<correccion_alcance_subparte>",
        "SOLO corrige el alcance de esta subparte. Mantén la calidad didáctica, pero elimina invasiones de subpartes vecinas.",
    ]
    if report.invades_previous:
        lines.append("NO desarrolles contenido de la subparte anterior:")
        for item in report.invades_previous:
            lines.append(f"- {item}")
    if report.invades_next:
        lines.append("NO desarrolles contenido de la subparte siguiente:")
        for item in report.invades_next:
            lines.append(f"- {item}")
    if report.missing_current:
        lines.append("SÍ debes desarrollar el contenido propio que falta:")
        for item in report.missing_current:
            lines.append(f"- {item}")
    lines.append(f"Motivo: {report.rationale}")
    lines.append("</correccion_alcance_subparte>")
    return "\n".join(lines)


RESPONSE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    required=["is_valid", "invades_previous", "invades_next", "missing_current", "rationale"],
    properties={
        "is_valid": types.Schema(type=types.Type.BOOLEAN),
        "invades_previous": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
        "invades_next": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
        "missing_current": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
        "rationale": types.Schema(type=types.Type.STRING),
    },
)


@gemini_retry(max_retries=3)
def run_subpart_scope_auditor(
    *,
    api_key: str,
    current_subpart_summary: str,
    previous_subpart_summary: str,
    next_subpart_summary: str,
    desarrollo_payload: dict[str, Any],
    model: str,
) -> tuple[SubpartScopeAuditReport, Any]:
    client = genai.Client(api_key=api_key)
    desarrollo_text = flatten_desarrollo_text(desarrollo_payload)
    prompt = f"""Evalúa si esta salida del explainer respeta el alcance de la subparte actual.

SUBPARTE ACTUAL:
{current_subpart_summary}

SUBPARTE ANTERIOR:
{previous_subpart_summary}

SUBPARTE SIGUIENTE:
{next_subpart_summary}

SALIDA GENERADA:
{desarrollo_text}
"""
    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        ),
    ]
    response = generate_content_with_retry(
        client=client,
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            thinking_config=types.ThinkingConfig(thinking_level="LOW"),
        ),
        max_retries=5,
        operation_context={"agent": "subpart_scope_auditor"},
    )
    data = json.loads(response.text)
    report = SubpartScopeAuditReport(
        is_valid=bool(data["is_valid"]),
        invades_previous=tuple(data["invades_previous"]),
        invades_next=tuple(data["invades_next"]),
        missing_current=tuple(data["missing_current"]),
        rationale=str(data["rationale"]),
    )
    return report, response.usage_metadata
