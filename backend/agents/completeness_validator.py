"""Validador de explicaciones: truncamiento y alcance del explainer.

El revisor usa el mismo proveedor que el flujo explainer activo: Gemini para el
flujo Gemini y OpenRouter para el flujo OpenRouter. Evalua solo dos cosas:

- Si la explicacion quedo truncada.
- Si desarrolla contenido sustantivo fuera de la parte/subparte asignada.

La politica es conservadora: las menciones puente breves y los casos ambiguos
se aceptan; solo una invasion sustantiva y clara provoca reintento o error.
"""
from __future__ import annotations

import inspect
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal

from google import genai
from google.genai import types

from backend.gemini_client import generate_content_with_retry
from backend.logging_config import get_logger
from backend.openrouter_client import call_openrouter_chat
from backend.openrouter_model_routing import (
    OPENROUTER_MODEL_AUXILIARY,
    deepseek_provider_preferences,
)

logger = get_logger("backend.agents.completeness_validator")

# Modelo Gemini usado por el validador cuando el flujo explainer es Gemini.
COMPLETENESS_VALIDATOR_MODEL = "gemini-3.1-flash-lite-preview"
# Modelo OpenRouter usado por el validador cuando el flujo explainer es OpenRouter.
OPENROUTER_COMPLETENESS_VALIDATOR_MODEL = OPENROUTER_MODEL_AUXILIARY

# Numero maximo de reintentos de validacion (sin contar el intento inicial).
MAX_COMPLETENESS_RETRIES = 2
MAX_EXPLAINER_VALIDATION_RETRIES = MAX_COMPLETENESS_RETRIES

ScopeStatus = Literal["ok", "minor_context_only", "violation", "unknown"]
SourceEvidenceKind = Literal["ocr_text", "gemini_file"]


@dataclass(frozen=True, slots=True)
class ExplainerScopeItem:
    """A segmentador-defined scope item used by the reviewer as ground truth."""

    kind: str
    title: str
    number: str = ""
    content: str = ""
    identification: str = ""
    anchors: tuple[str, ...] = ()
    page_start: int | None = None
    page_end: int | None = None
    block_start: int | None = None
    block_end: int | None = None


@dataclass(frozen=True, slots=True)
class ExplainerSourceEvidence:
    """Source material already available to the explainer, reused by the reviewer."""

    kind: SourceEvidenceKind
    label: str = ""
    text: str = ""
    file_uri: str = ""
    mime_type: str = ""
    pages: tuple[int, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class ExplainerValidationContext:
    """Scope contract for validating one explainer generation."""

    scope_kind: Literal["part", "subpart"]
    current: ExplainerScopeItem
    parent: ExplainerScopeItem | None = None
    previous_neighbor: ExplainerScopeItem | None = None
    next_neighbor: ExplainerScopeItem | None = None
    source_evidence: ExplainerSourceEvidence | None = None


@dataclass(frozen=True, slots=True)
class ExplainerValidationReport:
    """Structured reviewer result."""

    is_complete: bool
    scope_status: ScopeStatus
    reason: str
    offending_fragments: tuple[str, ...] = ()
    retry_instructions: str = ""

    @property
    def is_scope_valid(self) -> bool:
        return self.scope_status in {"ok", "minor_context_only", "unknown"}

    @property
    def is_valid(self) -> bool:
        return self.is_complete and self.is_scope_valid


class ExplainerValidationError(RuntimeError):
    """Raised when a confirmed explainer validation failure survives retries."""

    def __init__(self, *, label: str, report: ExplainerValidationReport) -> None:
        self.label = label
        self.report = report
        super().__init__(
            f"{label}: validacion de explainer fallida "
            f"(complete={report.is_complete}, scope={report.scope_status}): {report.reason}"
        )


# Sufijo mantenido por compatibilidad para importadores antiguos. Los reintentos
# nuevos deben usar build_explainer_retry_system_suffix(...).
INCOMPLETE_RETRY_SYSTEM_SUFFIX = """

<aviso_regeneracion_por_truncamiento>
La explicacion anterior quedo truncada. Genera una explicacion nueva y completa,
con cierre natural en cada seccion y una ultima oracion terminada correctamente.
</aviso_regeneracion_por_truncamiento>"""


_VALIDATOR_SYSTEM_PROMPT = """Eres un revisor conservador de explicaciones academicas.

Tu unica tarea es validar dos cosas y solo dos:
1. Completitud: si la explicacion esta completa o fue truncada/cortada abruptamente.
2. Alcance: si la explicacion desarrolla contenido sustantivo fuera de la parte o subparte asignada por el segmentador.

Politica de alcance:
- El contrato del segmentador y la fuente real permitida son la fuente de verdad: titulo, contenido, identificacion, anclas, limites, vecinos y PDF/OCR adjunto cuando exista.
- La fuente real permitida manda sobre los resumenes tematicos del segmentador. Los titulos/contenidos de vecinos son ayudas para detectar invasiones, no una lista exhaustiva para excluir contenido que aparece dentro del nucleo permitido.
- Si un tema, nombre, fecha, ejemplo o bloque aparece en el OCR/PDF permitido o dentro de las paginas/anclas actuales, NO marques violation aunque se parezca al titulo o resumen de un vecino.
- Marca scope_status="violation" solo si hay desarrollo sustantivo y claro de anclas, encabezados o contenido de vecinos prohibidos Y no esta respaldado por la fuente real permitida.
- Acepta menciones puente breves, recordatorios contextuales o conexiones necesarias si no se convierten en desarrollo didactico del vecino.
- Si la fuente real no esta disponible, no puedes localizar el fragmento, o hay duda razonable, usa scope_status="minor_context_only" u "unknown", no "violation".
- Los offending_fragments deben ser fragmentos concretos de la explicacion generada y la reason debe explicar por que estan fuera de la fuente/alcance permitido.
- No evalues estilo, profundidad didactica, elegancia, formato ni cobertura fina de conceptos.

Politica de completitud:
- is_complete=false solo si hay senales claras de truncamiento: ultima oracion sin cierre, corte a mitad de idea, lista inconclusa, seccion cortada o final que exige continuacion.
- is_complete=true si el final tiene cierre natural aunque la explicacion sea mejorable.

Devuelve un unico objeto JSON con:
{
  "is_complete": boolean,
  "scope_status": "ok" | "minor_context_only" | "violation" | "unknown",
  "reason": "razon breve y concreta",
  "offending_fragments": ["fragmentos concretos si hay violacion o truncamiento"],
  "retry_instructions": "instrucciones concretas para regenerar, vacio si no hace falta"
}"""

_OPENROUTER_VALIDATOR_JSON_RETRY_INSTRUCTION = """Devuelve exclusivamente un único objeto JSON raíz válido, sin Markdown ni texto externo, con exactamente esta forma:
{
  "is_complete": boolean,
  "scope_status": "ok" | "minor_context_only" | "violation" | "unknown",
  "reason": string,
  "offending_fragments": string[],
  "retry_instructions": string
}
Todas las claves son obligatorias. `offending_fragments` debe ser [] si no hay fragmentos problemáticos. `retry_instructions` debe ser "" si la explicación es aceptable."""

_OPENROUTER_VALIDATOR_SYSTEM_PROMPT = f"""{_VALIDATOR_SYSTEM_PROMPT}

<openrouter_json_mode_contract>
Para OpenRouter JSON mode, cumple explícitamente este contrato adicional:
{_OPENROUTER_VALIDATOR_JSON_RETRY_INSTRUCTION}
</openrouter_json_mode_contract>"""

_VALIDATOR_SCHEMA = genai.types.Schema(
    type=genai.types.Type.OBJECT,
    required=[
        "is_complete",
        "scope_status",
        "reason",
        "offending_fragments",
        "retry_instructions",
    ],
    properties={
        "is_complete": genai.types.Schema(
            type=genai.types.Type.BOOLEAN,
            description="True si la explicacion esta completa; False si esta truncada.",
        ),
        "scope_status": genai.types.Schema(
            type=genai.types.Type.STRING,
            enum=["ok", "minor_context_only", "violation", "unknown"],
            description=(
                "ok si respeta alcance; minor_context_only si solo hay puente breve; "
                "violation si desarrolla contenido vecino de forma sustantiva; unknown si no puede decidir."
            ),
        ),
        "reason": genai.types.Schema(
            type=genai.types.Type.STRING,
            description="Justificacion breve, especifica y conservadora.",
        ),
        "offending_fragments": genai.types.Schema(
            type=genai.types.Type.ARRAY,
            items=genai.types.Schema(type=genai.types.Type.STRING),
            description="Fragmentos concretos que evidencian truncamiento o invasion de alcance.",
        ),
        "retry_instructions": genai.types.Schema(
            type=genai.types.Type.STRING,
            description="Instrucciones concretas para regenerar; cadena vacia si la salida es aceptable.",
        ),
    },
)


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _serialize_for_validation(explanation: dict) -> str:
    """Serialize all explainer text, including desarrollo titles and bodies."""
    parts: list[str] = []

    intro = explanation.get("introduccion")
    if isinstance(intro, str) and intro.strip():
        parts.append(f"INTRODUCCION:\n{intro.strip()}")

    for index, section in enumerate(explanation.get("desarrollo") or [], start=1):
        if not isinstance(section, dict):
            continue
        title = section.get("titulo_seccion")
        if isinstance(title, str) and title.strip():
            parts.append(f"SECCION {index}: {title.strip()}")
        section_intro = section.get("explicacion_introductoria")
        if isinstance(section_intro, str) and section_intro.strip():
            parts.append(section_intro.strip())
        for sub_index, subsection in enumerate(section.get("subsecciones") or [], start=1):
            if not isinstance(subsection, dict):
                continue
            sub_title = subsection.get("titulo_subseccion")
            if isinstance(sub_title, str) and sub_title.strip():
                parts.append(f"SUBSECCION {index}.{sub_index}: {sub_title.strip()}")
            body = subsection.get("explicacion_detallada")
            if isinstance(body, str) and body.strip():
                parts.append(body.strip())

    conclusion = explanation.get("conclusion")
    if isinstance(conclusion, str) and conclusion.strip():
        parts.append(f"CONCLUSION:\n{conclusion.strip()}")

    return "\n\n".join(parts)


def _format_scope_item(item: ExplainerScopeItem | None, *, label: str) -> str:
    if item is None:
        return f"{label}: (no disponible)"

    lines = [f"{label}:"]
    kind = item.kind.strip() or "item"
    number = f" {item.number}" if item.number else ""
    lines.append(f"- Tipo: {kind}{number}")
    lines.append(f"- Titulo: {item.title or '(sin titulo)'}")
    if item.content:
        lines.append(f"- Contenido asignado: {item.content}")
    if item.identification:
        lines.append(f"- Identificacion del segmentador: {item.identification}")
    if item.anchors:
        lines.append("- Anclas/limites:")
        for anchor in item.anchors:
            lines.append(f"  - {anchor}")
    if item.page_start is not None or item.page_end is not None:
        lines.append(f"- Paginas: {item.page_start or '?'}-{item.page_end or '?'}")
    if item.block_start is not None or item.block_end is not None:
        lines.append(f"- Bloques: {item.block_start or '?'}-{item.block_end or '?'}")
    return "\n".join(lines)


def _format_source_evidence(
    source_evidence: ExplainerSourceEvidence | None,
    *,
    include_text: bool,
) -> str:
    if source_evidence is None:
        return (
            "FUENTE REAL PERMITIDA PARA VALIDAR ALCANCE:\n"
            "(No disponible. Se debe validar de forma conservadora y no marcar violation si hay duda.)"
        )

    lines = ["FUENTE REAL PERMITIDA PARA VALIDAR ALCANCE:"]
    if source_evidence.label:
        lines.append(f"- Origen: {source_evidence.label}")
    lines.append(f"- Modo: {source_evidence.kind}")
    if source_evidence.pages:
        pages = ", ".join(str(page) for page in source_evidence.pages)
        lines.append(f"- Paginas fuente: {pages}")
    if source_evidence.mime_type:
        lines.append(f"- MIME: {source_evidence.mime_type}")
    if source_evidence.file_uri:
        lines.append("- Archivo adjunto: disponible por Files API de Gemini en esta misma llamada.")
    if source_evidence.note:
        lines.append(f"- Nota: {source_evidence.note}")

    if include_text and source_evidence.kind == "ocr_text":
        text = source_evidence.text.strip()
        if text:
            lines.extend(
                [
                    "",
                    "TEXTO OCR PERMITIDO:",
                    text,
                    "FIN DEL TEXTO OCR PERMITIDO.",
                ]
            )
        else:
            lines.append("- Texto OCR: vacio; valida de forma conservadora.")

    if include_text and source_evidence.kind == "gemini_file":
        lines.append(
            "- El PDF permitido esta adjunto como primer part de esta llamada. "
            "Inspeccionalo usando las paginas/anclas del contrato actual."
        )

    return "\n".join(lines)


def format_validation_context(
    validation_context: ExplainerValidationContext | None,
    *,
    include_source_text: bool = False,
) -> str:
    """Render the segmentador scope contract for the reviewer and retries."""
    if validation_context is None:
        return (
            "CONTRATO DE ALCANCE DEL SEGMENTADOR:\n"
            "(No se proporciono contexto estructurado; valida solo truncamiento y acepta alcance por defecto.)"
        )

    lines = [
        "CONTRATO DE ALCANCE DEL SEGMENTADOR",
        f"Unidad evaluada: {validation_context.scope_kind}",
        "",
        _format_scope_item(validation_context.current, label="ALCANCE PERMITIDO ACTUAL"),
    ]
    if validation_context.parent is not None:
        lines.extend(["", _format_scope_item(validation_context.parent, label="PARTE PADRE / CONTEXTO SUPERIOR")])
    lines.extend(
        [
            "",
            "VECINOS FUERA DEL ALCANCE PERMITIDO",
            "Estos vecinos solo pueden aparecer como menciones puente breves; no deben desarrollarse como contenido propio.",
            _format_scope_item(validation_context.previous_neighbor, label="Vecino anterior"),
            "",
            _format_scope_item(validation_context.next_neighbor, label="Vecino siguiente"),
        ]
    )
    if validation_context.source_evidence is not None:
        lines.extend(
            [
                "",
                _format_source_evidence(
                    validation_context.source_evidence,
                    include_text=include_source_text,
                ),
            ]
        )
    return "\n".join(lines)


def _build_validator_contents(
    *,
    user_message: str,
    validation_context: ExplainerValidationContext | None,
) -> list[types.Content]:
    parts: list[types.Part] = []
    source_evidence = validation_context.source_evidence if validation_context else None
    if (
        source_evidence is not None
        and source_evidence.kind == "gemini_file"
        and source_evidence.file_uri
    ):
        parts.append(
            types.Part.from_uri(
                file_uri=source_evidence.file_uri,
                mime_type=source_evidence.mime_type or "application/pdf",
            )
        )
    parts.append(types.Part.from_text(text=user_message))
    return [types.Content(role="user", parts=parts)]


def _normalize_scope_status(raw: Any) -> ScopeStatus:
    status = str(raw or "").strip()
    if status in {"ok", "minor_context_only", "violation", "unknown"}:
        return status  # type: ignore[return-value]
    return "unknown"


def _parse_validation_report(raw: dict[str, Any]) -> ExplainerValidationReport:
    return ExplainerValidationReport(
        is_complete=bool(raw.get("is_complete", True)),
        scope_status=_normalize_scope_status(raw.get("scope_status")),
        reason=str(raw.get("reason") or "").strip(),
        offending_fragments=_tuple_of_strings(raw.get("offending_fragments")),
        retry_instructions=str(raw.get("retry_instructions") or "").strip(),
    )


def _accepted_report(reason: str) -> ExplainerValidationReport:
    return ExplainerValidationReport(
        is_complete=True,
        scope_status="unknown",
        reason=reason,
        offending_fragments=(),
        retry_instructions="",
    )


def _build_validator_user_message(
    explanation: dict,
    validation_context: ExplainerValidationContext | None,
) -> str | None:
    text = _serialize_for_validation(explanation)
    if not text.strip():
        return None

    scope_contract = format_validation_context(validation_context, include_source_text=True)
    return (
        "Evalua la siguiente explicacion academica usando el contrato de alcance y la fuente real permitida.\n"
        "Recuerda: si un contenido aparece en la fuente permitida o dentro de las paginas/anclas actuales, no es invasion de alcance.\n\n"
        f"{scope_contract}\n\n"
        "---\n\n"
        "EXPLICACION GENERADA A VALIDAR:\n"
        f"{text}"
    )


def check_explainer_validation(
    explanation: dict,
    gemini_api_key: str,
    validation_context: ExplainerValidationContext | None = None,
) -> tuple[ExplainerValidationReport, Any]:
    """Validate an explainer output with Gemini.

    Returns:
        (report, usage_metadata). If the reviewer fails, returns an accepted
        fail-open report with usage None.
    """
    start = time.time()
    try:
        user_message = _build_validator_user_message(explanation, validation_context)
        if user_message is None:
            return _accepted_report("Explicacion vacia; se acepta por defecto."), None

        client = genai.Client(api_key=gemini_api_key)
        contents = _build_validator_contents(
            user_message=user_message,
            validation_context=validation_context,
        )
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_VALIDATOR_SCHEMA,
            system_instruction=[types.Part.from_text(text=_VALIDATOR_SYSTEM_PROMPT)],
        )

        response = generate_content_with_retry(
            client=client,
            model=COMPLETENESS_VALIDATOR_MODEL,
            contents=contents,
            config=config,
            max_retries=2,
            operation_context={"agent": "explainer_validator"},
        )

        report = _parse_validation_report(json.loads(response.text or "{}"))
        elapsed_ms = int((time.time() - start) * 1000)
        logger.info(
            "Explainer validado: complete=%s scope=%s — %s (%dms)",
            report.is_complete,
            report.scope_status,
            report.reason[:150],
            elapsed_ms,
            extra={
                "is_complete": report.is_complete,
                "scope_status": report.scope_status,
                "reason": report.reason[:200],
                "elapsed_ms": elapsed_ms,
                "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0) if response.usage_metadata else 0,
                "candidates_tokens": getattr(response.usage_metadata, "candidates_token_count", 0) if response.usage_metadata else 0,
            },
        )
        return report, response.usage_metadata

    except Exception as exc:
        elapsed_ms = int((time.time() - start) * 1000)
        logger.warning(
            "Error en validador de explainer (%dms) — se acepta fail-open. Error: %s",
            elapsed_ms,
            str(exc)[:200],
            extra={"error_type": type(exc).__name__, "elapsed_ms": elapsed_ms},
        )
        return _accepted_report(f"Error en validador ({type(exc).__name__}); resultado aceptado."), None


def check_explainer_validation_or(
    explanation: dict,
    openrouter_api_key: str,
    validation_context: ExplainerValidationContext | None = None,
    model: str = OPENROUTER_COMPLETENESS_VALIDATOR_MODEL,
) -> tuple[ExplainerValidationReport, Any]:
    """Validate an explainer output with OpenRouter.

    Returns:
        (report, usage). If the reviewer fails, returns an accepted fail-open
        report with usage None, matching the Gemini validator policy.
    """
    start = time.time()
    try:
        user_message = _build_validator_user_message(explanation, validation_context)
        if user_message is None:
            return _accepted_report("Explicacion vacia; se acepta por defecto."), None

        content, usage = call_openrouter_chat(
            messages=[{"role": "user", "content": user_message}],
            model=model,
            system_prompt=_OPENROUTER_VALIDATOR_SYSTEM_PROMPT,
            api_key=openrouter_api_key,
            response_format="json_object",
            enable_response_healing=True,
            provider=deepseek_provider_preferences(),
            json_retry_instruction=_OPENROUTER_VALIDATOR_JSON_RETRY_INSTRUCTION,
        )
        if not isinstance(content, dict):
            raise TypeError("El validador OpenRouter no devolvio un objeto JSON.")

        report = _parse_validation_report(content)
        elapsed_ms = int((time.time() - start) * 1000)
        logger.info(
            "Explainer validado con OpenRouter: complete=%s scope=%s — %s (%dms)",
            report.is_complete,
            report.scope_status,
            report.reason[:150],
            elapsed_ms,
            extra={
                "is_complete": report.is_complete,
                "scope_status": report.scope_status,
                "reason": report.reason[:200],
                "elapsed_ms": elapsed_ms,
                "prompt_tokens": getattr(usage, "prompt_token_count", 0) if usage else 0,
                "candidates_tokens": getattr(usage, "candidates_token_count", 0) if usage else 0,
                "model": model,
            },
        )
        return report, usage

    except Exception as exc:
        elapsed_ms = int((time.time() - start) * 1000)
        logger.warning(
            "Error en validador OpenRouter de explainer (%dms) — se acepta fail-open. Error: %s",
            elapsed_ms,
            str(exc)[:200],
            extra={"error_type": type(exc).__name__, "elapsed_ms": elapsed_ms},
        )
        return _accepted_report(f"Error en validador OpenRouter ({type(exc).__name__}); resultado aceptado."), None


def check_explanation_completeness(
    explanation: dict,
    gemini_api_key: str,
) -> tuple[bool, str, Any]:
    """Backward-compatible completeness API."""
    report, usage = check_explainer_validation(
        explanation,
        gemini_api_key=gemini_api_key,
        validation_context=None,
    )
    return report.is_valid, report.reason, usage


def format_explainer_retry_context(
    previous_result: dict,
    validation_report: ExplainerValidationReport,
    *,
    validation_context: ExplainerValidationContext | None = None,
) -> str:
    """Format the previous invalid output and the precise retry contract."""
    try:
        serialized = json.dumps(previous_result, ensure_ascii=False, indent=2)
    except Exception:
        serialized = str(previous_result)

    failure_labels: list[str] = []
    if not validation_report.is_complete:
        failure_labels.append("truncamiento")
    if validation_report.scope_status == "violation":
        failure_labels.append("invasion sustantiva de alcance")
    if not failure_labels:
        failure_labels.append("validacion no aceptada")

    lines = [
        "<explicacion_anterior_no_valida>",
        "La explicacion anterior debe regenerarse completa; no parches el JSON parcialmente.",
        f"Fallo(s) detectado(s): {', '.join(failure_labels)}.",
        f"Razon del revisor: {validation_report.reason}",
    ]
    if validation_report.offending_fragments:
        lines.append("Fragmentos problematicos:")
        for fragment in validation_report.offending_fragments:
            lines.append(f"- {fragment}")
    if validation_report.retry_instructions:
        lines.append("Instrucciones concretas del revisor:")
        lines.append(validation_report.retry_instructions)
    if not validation_report.is_complete:
        lines.append(
            "Para corregir truncamiento: cierra todas las secciones de forma natural y termina con una oracion completa."
        )
    if validation_report.scope_status == "violation":
        lines.append(
            "Para corregir alcance: retira solo el desarrollo sustantivo fuera de alcance, conserva el contenido valido del alcance permitido y usa los vecinos solo como puente breve si es imprescindible."
        )
    lines.extend(
        [
            "",
            format_validation_context(validation_context),
            "",
            "Explicacion anterior:",
            serialized,
            "</explicacion_anterior_no_valida>",
        ]
    )
    return "\n".join(lines)


def format_incomplete_context(previous_result: dict) -> str:
    """Backward-compatible retry context for truncation-only callers."""
    return format_explainer_retry_context(
        previous_result,
        ExplainerValidationReport(
            is_complete=False,
            scope_status="ok",
            reason="La explicacion quedo truncada.",
            offending_fragments=(),
            retry_instructions="Regenera una explicacion completa con cierre natural.",
        ),
        validation_context=None,
    )


def build_explainer_retry_system_suffix(
    validation_report: ExplainerValidationReport,
    *,
    validation_context: ExplainerValidationContext | None = None,
) -> str:
    """Build a dynamic system suffix for a full regeneration attempt."""
    lines = [
        "",
        "<aviso_regeneracion_por_validacion_explainer>",
        "La generacion anterior no fue aceptada por el revisor. Regenera la explicacion completa desde cero, manteniendo el mismo contrato JSON.",
    ]
    if not validation_report.is_complete:
        lines.append(
            "- Problema de completitud: evita cortes abruptos, cierra cada seccion y termina con puntuacion final."
        )
    if validation_report.scope_status == "violation":
        lines.append(
            "- Problema de alcance: elimina el desarrollo sustantivo de partes/subpartes vecinas y conserva el desarrollo propio permitido."
        )
        lines.append("Alcance permitido exacto para esta regeneracion:")
        lines.append(format_validation_context(validation_context))
    if validation_report.reason:
        lines.append(f"Razon concreta del revisor: {validation_report.reason}")
    if validation_report.retry_instructions:
        lines.append(f"Instrucciones concretas: {validation_report.retry_instructions}")
    lines.append("</aviso_regeneracion_por_validacion_explainer>")
    return "\n".join(lines)


def _retry_accepts_report(retry_call: Callable[..., tuple[dict, Any]]) -> bool:
    try:
        signature = inspect.signature(retry_call)
    except (TypeError, ValueError):
        return True
    positional = 0
    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            return True
        if parameter.kind in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }:
            positional += 1
    return positional >= 2


def _call_retry(
    retry_call: Callable[..., tuple[dict, Any]],
    previous_result: dict,
    validation_report: ExplainerValidationReport,
) -> tuple[dict, Any]:
    if _retry_accepts_report(retry_call):
        return retry_call(previous_result, validation_report)
    return retry_call(previous_result)


def _run_with_explainer_validation_core(
    *,
    initial_call: Callable[[], tuple[dict, Any]],
    retry_call: Callable[..., tuple[dict, Any]],
    check_validation: Callable[[dict], tuple[ExplainerValidationReport, Any]],
    label: str,
) -> tuple[dict, Any, list[Any]]:
    """Run an explainer call with provider-specific validation and regeneration."""
    result, usage = initial_call()
    validator_usages: list[Any] = []
    last_report: ExplainerValidationReport | None = None

    for attempt in range(MAX_EXPLAINER_VALIDATION_RETRIES + 1):
        report, val_usage = check_validation(result)
        last_report = report
        if val_usage is not None:
            validator_usages.append(val_usage)

        if report.is_valid:
            if attempt > 0:
                logger.info(
                    "%s: validacion confirmada tras %d reintento(s).",
                    label,
                    attempt,
                    extra={"label": label, "successful_attempt": attempt},
                )
            return result, usage, validator_usages

        logger.warning(
            "%s: explainer no valido (evaluacion %d/%d) — complete=%s scope=%s — %s",
            label,
            attempt + 1,
            MAX_EXPLAINER_VALIDATION_RETRIES + 1,
            report.is_complete,
            report.scope_status,
            report.reason[:150],
            extra={
                "label": label,
                "validation_attempt": attempt + 1,
                "max_validations": MAX_EXPLAINER_VALIDATION_RETRIES + 1,
                "is_complete": report.is_complete,
                "scope_status": report.scope_status,
                "reason": report.reason[:200],
            },
        )

        if attempt >= MAX_EXPLAINER_VALIDATION_RETRIES:
            break

        result, usage = _call_retry(retry_call, result, report)

    assert last_report is not None
    logger.error(
        "%s: validacion de explainer agotada — abortando salida conocida como invalida.",
        label,
        extra={
            "label": label,
            "is_complete": last_report.is_complete,
            "scope_status": last_report.scope_status,
            "reason": last_report.reason[:300],
        },
    )
    raise ExplainerValidationError(label=label, report=last_report)


def run_with_explainer_validation(
    *,
    initial_call: Callable[[], tuple[dict, Any]],
    retry_call: Callable[..., tuple[dict, Any]],
    gemini_api_key: str,
    label: str,
    validation_context: ExplainerValidationContext | None = None,
) -> tuple[dict, Any, list[Any]]:
    """Run an explainer call, validate it with Gemini, and regenerate on confirmed failures."""
    return _run_with_explainer_validation_core(
        initial_call=initial_call,
        retry_call=retry_call,
        check_validation=lambda result: check_explainer_validation(
            result,
            gemini_api_key=gemini_api_key,
            validation_context=validation_context,
        ),
        label=label,
    )


def run_with_openrouter_explainer_validation(
    *,
    initial_call: Callable[[], tuple[dict, Any]],
    retry_call: Callable[..., tuple[dict, Any]],
    openrouter_api_key: str,
    label: str,
    validation_context: ExplainerValidationContext | None = None,
) -> tuple[dict, Any, list[Any]]:
    """Run an explainer call, validate it with OpenRouter, and regenerate on confirmed failures."""
    return _run_with_explainer_validation_core(
        initial_call=initial_call,
        retry_call=retry_call,
        check_validation=lambda result: check_explainer_validation_or(
            result,
            openrouter_api_key=openrouter_api_key,
            validation_context=validation_context,
        ),
        label=label,
    )


def run_with_completeness_validation(
    *,
    initial_call: Callable[[], tuple[dict, Any]],
    retry_call: Callable[..., tuple[dict, Any]],
    gemini_api_key: str,
    label: str,
    validation_context: ExplainerValidationContext | None = None,
) -> tuple[dict, Any, list[Any]]:
    """Backward-compatible wrapper name for the explainer validator."""
    return run_with_explainer_validation(
        initial_call=initial_call,
        retry_call=retry_call,
        gemini_api_key=gemini_api_key,
        label=label,
        validation_context=validation_context,
    )
