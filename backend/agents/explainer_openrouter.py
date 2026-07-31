"""Agente Explainer — implementación OpenRouter con JSON mode."""
from __future__ import annotations

import base64
import os
import tempfile
import time
from typing import Any, Callable, Literal

from pypdf import PdfReader

from backend.logging_config import get_logger
from backend.openrouter_client import (
    OpenRouterError,
    OpenRouterJsonSchemaResponseFormat,
    OpenRouterPdfParseCacheEntry,
    OpenRouterUsage,
    call_openrouter_chat,
    get_or_prime_pdf_parse_cache,
)
from backend.openrouter_model_routing import max_reasoning_preferences
from backend.pdf_ocr_cache import PdfOcrCacheEntry, PdfOcrError, render_pdf_pages_with_xml_tags
from backend.agents.explainer_prompts import (
    build_explainer_system_instruction,
    build_subpart_explainer_system_instruction,
)
from backend.agents.completeness_validator import (
    ExplainerValidationContext,
    ExplainerValidationReport,
    build_explainer_retry_system_suffix,
    format_explainer_retry_context,
    run_with_openrouter_explainer_validation,
)

logger = get_logger("backend.agents.explainer_openrouter")

OPENROUTER_MODEL_AGENTS = "xiaomi/mimo-v2.5-pro"
OPENROUTER_PDF_PARSER_ENGINE = "mistral-ocr"
OPENROUTER_PDF_PRIMING_MODEL = "x-ai/grok-4.1-fast"
OPENROUTER_PDF_PRIMING_FALLBACK_MODEL = "google/gemini-3.1-flash-lite-preview"
# OpenRouter API: sampling temperature (0–2).
OPENROUTER_EXPLAINER_TEMPERATURE = 0.7
OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES = 2
OPENROUTER_STRUCTURED_OUTPUT_MODELS = frozenset(
    {
        "openai/gpt-5.4-nano",
        "qwen/qwen3.6-plus",
    }
)
_OPENROUTER_PROVIDER_OVERRIDES = {
    "deepseek/deepseek-v4-flash-0731": {"order": ["deepseek"], "allow_fallbacks": False},
}

# PDF parsing plugin (used only in the fallback path for direct file sends)
_PDF_PLUGIN = [{"id": "file-parser", "pdf": {"engine": OPENROUTER_PDF_PARSER_ENGINE}}]

# ---------------------------------------------------------------------------
# Shared prompt base + OpenRouter JSON output contract
# ---------------------------------------------------------------------------

_FULL_JSON_OUTPUT_CONTRACT = """

<json_output_contract>
Además de TODAS las instrucciones anteriores, para esta ejecución OpenRouter debes cumplir exactamente este contrato de salida:

- Devuelve EXCLUSIVAMENTE un único objeto JSON válido. No escribas nada antes ni después del objeto. No uses bloques ```json.
- Si la API te proporciona un JSON Schema, debes obedecerlo exactamente. Si no lo hace, igualmente debes producir un JSON que respete esta forma.

Forma exacta del objeto:
{
  "introduccion": "string",
  "desarrollo": [
    {
      "titulo_seccion": "string",
      "explicacion_introductoria": "string",
      "subsecciones": [
        {
          "titulo_subseccion": "string",
          "explicacion_detallada": "string"
        }
      ]
    }
  ],
  "conclusion": "string",
  "conexiones_contextuales": [
    {
      "seccion_temario_relacionada": "string",
      "descripcion_conexion": "string"
    }
  ]
}

Reglas JSON obligatorias:
- Todas esas claves deben existir SIEMPRE.
- `conexiones_contextuales` debe ser `[]` cuando no aplique.
- No añadas claves extra.
- Cada valor debe respetar exactamente su tipo.
- Escapa correctamente comillas, saltos de línea y caracteres especiales para que el JSON sea parseable.
- `titulo_seccion` y `titulo_subseccion` son títulos breves; no los repitas dentro del cuerpo.
- `introduccion` y `conclusion` contienen solo sus párrafos; no incluyas los rótulos literales "Introducción" o "Conclusión".
- `explicacion_introductoria` y `explicacion_detallada` contienen solo el cuerpo explicativo de ese bloque, sin encabezados duplicados ni metacomentarios.
</json_output_contract>"""

_SUBPART_JSON_OUTPUT_CONTRACT = """

<json_output_contract>
Además de TODAS las instrucciones anteriores, para esta ejecución OpenRouter debes cumplir exactamente este contrato de salida:

- Devuelve EXCLUSIVAMENTE un único objeto JSON válido. No escribas nada antes ni después del objeto. No uses bloques ```json.
- Si la API te proporciona un JSON Schema, debes obedecerlo exactamente. Si no lo hace, igualmente debes producir un JSON que respete esta forma.

Forma exacta del objeto:
{
  "desarrollo": [
    {
      "titulo_seccion": "string",
      "explicacion_introductoria": "string",
      "subsecciones": [
        {
          "titulo_subseccion": "string",
          "explicacion_detallada": "string"
        }
      ]
    }
  ]
}

Reglas JSON obligatorias:
- Devuelve SOLO la clave `desarrollo`.
- No añadas introducción, conclusión ni conexiones contextuales.
- No añadas claves extra.
- Cada `titulo_*` debe ser breve y no repetirse dentro del cuerpo.
- Cada `explicacion_*` contiene solo el cuerpo explicativo, sin encabezados duplicados ni metacomentarios.
- Escapa correctamente comillas, saltos de línea y caracteres especiales para que el JSON sea parseable.
</json_output_contract>"""


def _append_json_output_contract(base_prompt: str, contract: str) -> str:
    return f"{base_prompt}{contract}"


def build_openrouter_explainer_system_prompt(target_language: str = "es-ES") -> str:
    return _append_json_output_contract(
        build_explainer_system_instruction(target_language),
        _FULL_JSON_OUTPUT_CONTRACT,
    )


def build_openrouter_subpart_explainer_system_prompt(target_language: str = "es-ES") -> str:
    return _append_json_output_contract(
        build_subpart_explainer_system_instruction(target_language),
        _SUBPART_JSON_OUTPUT_CONTRACT,
    )


OR_EXPLAINER_SYSTEM_PROMPT = build_openrouter_explainer_system_prompt("es-ES")
OR_SUBPART_EXPLAINER_SYSTEM_PROMPT = build_openrouter_subpart_explainer_system_prompt("es-ES")


def prime_pdf_parse_cache_with_fallback(
    *,
    source_path: str,
    api_key: str,
    engine: str,
    filename: str,
    expected_page_numbers: tuple[int, ...] | None = None,
) -> tuple[OpenRouterPdfParseCacheEntry, str]:
    priming_models = (
        OPENROUTER_PDF_PRIMING_MODEL,
        OPENROUTER_PDF_PRIMING_FALLBACK_MODEL,
    )

    for index, priming_model in enumerate(priming_models):
        try:
            cache_entry = get_or_prime_pdf_parse_cache(
                source_path=source_path,
                api_key=api_key,
                model=priming_model,
                engine=engine,
                filename=filename,
                expected_page_numbers=expected_page_numbers,
            )
            return cache_entry, priming_model
        except OpenRouterError:
            if index == len(priming_models) - 1:
                raise
            logger.warning(
                "OpenRouter PDF priming failed with primary model; retrying fallback model",
                extra={
                    "source_path": source_path,
                    "failed_priming_model": priming_model,
                    "fallback_priming_model": OPENROUTER_PDF_PRIMING_FALLBACK_MODEL,
                    "pdf_parser_engine": engine,
                },
            )


_SUBSECTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Single didactic subsection of the explanation.",
    "properties": {
        "titulo_subseccion": {
            "type": "string",
            "description": "Brief subsection title in Spanish.",
        },
        "explicacion_detallada": {
            "type": "string",
            "description": "Detailed explanation body for the subsection.",
        },
    },
    "required": ["titulo_subseccion", "explicacion_detallada"],
    "additionalProperties": False,
}

_SECTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Single top-level section of the explanation.",
    "properties": {
        "titulo_seccion": {
            "type": "string",
            "description": "Brief section title in Spanish.",
        },
        "explicacion_introductoria": {
            "type": "string",
            "description": "Introductory explanation for the section.",
        },
        "subsecciones": {
            "type": "array",
            "description": "Didactic subsections that fully develop the section.",
            "items": _SUBSECTION_JSON_SCHEMA,
            "minItems": 1,
        },
    },
    "required": ["titulo_seccion", "explicacion_introductoria", "subsecciones"],
    "additionalProperties": False,
}

_CONNECTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Cross-reference to another syllabus section when relevant.",
    "properties": {
        "seccion_temario_relacionada": {
            "type": "string",
            "description": "Related syllabus section title.",
        },
        "descripcion_conexion": {
            "type": "string",
            "description": "Why this connection matters for understanding.",
        },
    },
    "required": ["seccion_temario_relacionada", "descripcion_conexion"],
    "additionalProperties": False,
}

OR_EXPLAINER_JSON_SCHEMA = OpenRouterJsonSchemaResponseFormat(
    name="full_explainer",
    strict=True,
    schema={
        "type": "object",
        "description": "Complete explainer output for a syllabus part.",
        "properties": {
            "introduccion": {
                "type": "string",
                "description": "Introductory text for the part.",
            },
            "desarrollo": {
                "type": "array",
                "description": "Full didactic development of the content.",
                "items": _SECTION_JSON_SCHEMA,
                "minItems": 1,
            },
            "conclusion": {
                "type": "string",
                "description": "Closing summary for the part.",
            },
            "conexiones_contextuales": {
                "type": "array",
                "description": "Optional contextual links to other syllabus sections.",
                "items": _CONNECTION_JSON_SCHEMA,
            },
        },
        "required": ["introduccion", "desarrollo", "conclusion", "conexiones_contextuales"],
        "additionalProperties": False,
    },
)

OR_SUBPART_EXPLAINER_JSON_SCHEMA = OpenRouterJsonSchemaResponseFormat(
    name="subpart_explainer",
    strict=True,
    schema={
        "type": "object",
        "description": "Explainer output for a single segmented subpart.",
        "properties": {
            "desarrollo": {
                "type": "array",
                "description": "Didactic development for the assigned subpart.",
                "items": _SECTION_JSON_SCHEMA,
                "minItems": 1,
            },
        },
        "required": ["desarrollo"],
        "additionalProperties": False,
    },
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_openrouter_model_name(model: str) -> str:
    return (model or "").strip().lower()


def _supports_openrouter_structured_outputs(model: str) -> bool:
    return _normalize_openrouter_model_name(model) in OPENROUTER_STRUCTURED_OUTPUT_MODELS


def _resolve_openrouter_response_format(
    *,
    model: str,
    json_schema: OpenRouterJsonSchemaResponseFormat,
) -> Literal["json_object"] | OpenRouterJsonSchemaResponseFormat:
    if _supports_openrouter_structured_outputs(model):
        return json_schema
    return "json_object"


def _require_object(value: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OpenRouterError(f"Campo inválido en {path}: se esperaba un objeto JSON.")
    return value


def _require_string(value: Any, *, path: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise OpenRouterError(f"Campo inválido en {path}: se esperaba una cadena.")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise OpenRouterError(f"Campo inválido en {path}: la cadena no puede estar vacía.")
    return normalized


def _validate_subsections(raw: Any, *, path: str) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not raw:
        raise OpenRouterError(f"Campo inválido en {path}: se esperaba una lista no vacía.")
    validated: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        subsection = _require_object(item, path=f"{path}[{index}]")
        validated.append(
            {
                "titulo_subseccion": _require_string(
                    subsection.get("titulo_subseccion"),
                    path=f"{path}[{index}].titulo_subseccion",
                ),
                "explicacion_detallada": _require_string(
                    subsection.get("explicacion_detallada"),
                    path=f"{path}[{index}].explicacion_detallada",
                ),
            }
        )
    return validated


def _validate_desarrollo(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise OpenRouterError("Campo inválido en desarrollo: se esperaba una lista no vacía.")
    validated: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        section = _require_object(item, path=f"desarrollo[{index}]")
        validated.append(
            {
                "titulo_seccion": _require_string(
                    section.get("titulo_seccion"),
                    path=f"desarrollo[{index}].titulo_seccion",
                ),
                "explicacion_introductoria": _require_string(
                    section.get("explicacion_introductoria"),
                    path=f"desarrollo[{index}].explicacion_introductoria",
                ),
                "subsecciones": _validate_subsections(
                    section.get("subsecciones"),
                    path=f"desarrollo[{index}].subsecciones",
                ),
            }
        )
    return validated


def _validate_conexiones(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise OpenRouterError(
            "Campo inválido en conexiones_contextuales: se esperaba una lista o []."
        )
    validated: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        connection = _require_object(item, path=f"conexiones_contextuales[{index}]")
        validated.append(
            {
                "seccion_temario_relacionada": _require_string(
                    connection.get("seccion_temario_relacionada"),
                    path=f"conexiones_contextuales[{index}].seccion_temario_relacionada",
                ),
                "descripcion_conexion": _require_string(
                    connection.get("descripcion_conexion"),
                    path=f"conexiones_contextuales[{index}].descripcion_conexion",
                ),
            }
        )
    return validated


def _validate_full_explainer_payload(payload: Any) -> dict[str, Any]:
    data = _require_object(payload, path="root")
    return {
        "introduccion": _require_string(data.get("introduccion"), path="introduccion"),
        "desarrollo": _validate_desarrollo(data.get("desarrollo")),
        "conclusion": _require_string(data.get("conclusion"), path="conclusion"),
        "conexiones_contextuales": _validate_conexiones(data.get("conexiones_contextuales")),
    }


def _validate_subpart_explainer_payload(payload: Any) -> dict[str, Any]:
    data = _require_object(payload, path="root")
    return {"desarrollo": _validate_desarrollo(data.get("desarrollo"))}


def _count_desarrollo_subsections(desarrollo: list[dict[str, Any]]) -> int:
    return sum(len(section.get("subsecciones") or []) for section in desarrollo)


def _count_payload_chars(payload: dict[str, Any]) -> int:
    total = 0
    for key in ("introduccion", "conclusion"):
        value = payload.get(key)
        if isinstance(value, str):
            total += len(value)

    for section in payload.get("desarrollo") or []:
        total += len(section.get("titulo_seccion", ""))
        total += len(section.get("explicacion_introductoria", ""))
        for subsection in section.get("subsecciones") or []:
            total += len(subsection.get("titulo_subseccion", ""))
            total += len(subsection.get("explicacion_detallada", ""))

    for connection in payload.get("conexiones_contextuales") or []:
        total += len(connection.get("seccion_temario_relacionada", ""))
        total += len(connection.get("descripcion_conexion", ""))

    return total


def _is_pdf_parse_failure(exc: OpenRouterError) -> bool:
    message = str(exc)
    return "Failed to parse document.pdf" in message or "Failed to parse" in message


def _is_retryable_payload_validation_error(exc: OpenRouterError) -> bool:
    message = str(exc)
    return message.startswith("Campo inválido en ")


def _call_openrouter_with_validation_retries(
    *,
    call_operation: Callable[[], tuple[dict[str, Any], OpenRouterUsage]],
    validate_payload: Callable[[Any], dict[str, Any]],
    operation_label: str,
) -> tuple[dict[str, Any], OpenRouterUsage]:
    total_attempts = OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES + 1
    for attempt in range(1, total_attempts + 1):
        raw, usage = call_operation()
        try:
            return validate_payload(raw), usage
        except OpenRouterError as exc:
            if attempt >= total_attempts or not _is_retryable_payload_validation_error(exc):
                raise
            logger.warning(
                "%s devolvió JSON estructurado inválido (%s). Reintentando %s/%s",
                operation_label,
                str(exc),
                attempt,
                OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES,
                extra={
                    "operation_label": operation_label,
                    "validation_attempt": attempt,
                    "validation_max_retries": OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES,
                    "error_message": str(exc),
                },
            )
    raise OpenRouterError(
        f"{operation_label} agotó reintentos por payload inválido sin devolver JSON válido."
    )


def _extract_pdf_text_to_temp(source_path: str) -> str:
    reader = PdfReader(source_path)
    chunks: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        chunks.append(f"=== PAGE {index} ===\n{text}")

    if not chunks:
        raise OpenRouterError(
            "OpenRouter fallback failed: no se pudo extraer texto util del PDF local."
        )

    fd, temp_path = tempfile.mkstemp(suffix="_openrouter_pdf_fallback.txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n\n".join(chunks))
    return temp_path


def _build_inline_text_messages(ocr_text: str, identificacion: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"{ocr_text}\n\n{identificacion}",
                }
            ],
        }
    ]


def _call_openrouter_json_with_pdf_fallback(
    *,
    source_path: str,
    identificacion: str,
    mime_type: str,
    model: str,
    system_prompt: str,
    response_format: Literal["json_object"] | OpenRouterJsonSchemaResponseFormat,
    api_key: str,
    pdf_cache_entry: "PdfOcrCacheEntry | None" = None,
    page_numbers: tuple[int, ...] | None = None,
    provider_routing: dict | None = None,
) -> tuple[dict[str, Any], OpenRouterUsage]:
    if provider_routing is not None:
        provider = provider_routing
    else:
        provider = _OPENROUTER_PROVIDER_OVERRIDES.get(model)
    try:
        if mime_type == "application/pdf" and pdf_cache_entry is not None:
            requested_pages = page_numbers or pdf_cache_entry.cached_page_numbers
            ocr_text = render_pdf_pages_with_xml_tags(
                cache_entry=pdf_cache_entry,
                page_numbers=requested_pages,
            )
            inline_messages = _build_inline_text_messages(ocr_text, identificacion)
            return call_openrouter_chat(
                messages=inline_messages,
                model=model,
                system_prompt=system_prompt,
                api_key=api_key,
                response_format=response_format,
                plugins=None,
                enable_response_healing=True,
                reasoning=max_reasoning_preferences(model),
                temperature=OPENROUTER_EXPLAINER_TEMPERATURE,
                provider=provider,
            )
    except PdfOcrError:
        logger.warning("La caché OCR de Mistral no pudo renderizar el subconjunto solicitado.")

    if mime_type == "application/pdf":
        fallback_text_path = _extract_pdf_text_to_temp(source_path)
        try:
            fallback_content, fallback_plugins = _build_content(
                fallback_text_path,
                identificacion,
                "text/plain",
            )
            return call_openrouter_chat(
                messages=[{"role": "user", "content": fallback_content}],
                model=model,
                system_prompt=system_prompt,
                api_key=api_key,
                response_format=response_format,
                plugins=fallback_plugins,
                enable_response_healing=True,
                reasoning=max_reasoning_preferences(model),
                temperature=OPENROUTER_EXPLAINER_TEMPERATURE,
                provider=provider,
            )
        finally:
            try:
                os.unlink(fallback_text_path)
            except OSError:
                logger.warning("No se pudo borrar el fallback textual temporal: %s", fallback_text_path)

    # Non-PDF path (text/plain, web, etc.)
    content, plugins = _build_content(source_path, identificacion, mime_type)
    messages = [{"role": "user", "content": content}]
    return call_openrouter_chat(
        messages=messages,
        model=model,
        system_prompt=system_prompt,
        api_key=api_key,
        response_format=response_format,
        plugins=plugins,
        enable_response_healing=True,
        reasoning=max_reasoning_preferences(model),
        temperature=OPENROUTER_EXPLAINER_TEMPERATURE,
        provider=provider,
    )

def _build_content(source_path: str, identificacion: str, mime_type: str) -> tuple[list[dict], list[dict] | None]:
    """
    Construye el array de content y la lista de plugins para OpenRouter.

    - PDF: base64 + file-parser plugin
    - Texto/web: texto inline
    """
    if mime_type == "application/pdf":
        with open(source_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")

        content = [
            {"type": "text", "text": identificacion},
            {
                "type": "file",
                "file": {
                    "filename": "document.pdf",
                    "file_data": f"data:application/pdf;base64,{b64}",
                },
            },
        ]
        return content, _PDF_PLUGIN

    # Texto plano (web/texto)
    with open(source_path, "r", encoding="utf-8", errors="replace") as f:
        text_content = f.read()

    content = [{"type": "text", "text": f"{text_content}\n\n{identificacion}"}]
    return content, None


# ---------------------------------------------------------------------------
# Funciones públicas
# ---------------------------------------------------------------------------

def run_explainer_or(
    source_path: str,
    identificacion: str,
    model: str = OPENROUTER_MODEL_AGENTS,
    mime_type: str = "application/pdf",
    api_key: str = "",
    pdf_cache_entry: "PdfOcrCacheEntry | None" = None,
    page_numbers: tuple[int, ...] | None = None,
    target_language: str = "es-ES",
    *,
    provider_routing: dict | None = None,
) -> tuple[dict[str, Any], OpenRouterUsage]:
    """Explainer completo vía OpenRouter. Retorna (structured_result, usage)."""
    start = time.time()
    logger.info(
        "Iniciando agente explainer (openrouter)",
        extra={
            "source_path": source_path,
            "identificacion_length": len(identificacion),
            "identificacion_preview": identificacion[:150] + "..." if len(identificacion) > 150 else identificacion,
            "mime_type": mime_type,
            "model": model,
        },
    )
    response_format = _resolve_openrouter_response_format(
        model=model,
        json_schema=OR_EXPLAINER_JSON_SCHEMA,
    )

    result, usage = _call_openrouter_with_validation_retries(
        call_operation=lambda: _call_openrouter_json_with_pdf_fallback(
            source_path=source_path,
            identificacion=identificacion,
            mime_type=mime_type,
            model=model,
            system_prompt=build_openrouter_explainer_system_prompt(target_language),
            response_format=response_format,
            api_key=api_key,
            pdf_cache_entry=pdf_cache_entry,
            page_numbers=page_numbers,
            provider_routing=provider_routing,
        ),
        validate_payload=_validate_full_explainer_payload,
        operation_label="Explainer OpenRouter",
    )
    desarrollo = result.get("desarrollo") or []
    total_chars = _count_payload_chars(result)
    total_subsections = _count_desarrollo_subsections(desarrollo)

    total_ms = int((time.time() - start) * 1000)
    logger.info(
        "Explainer (openrouter) completado: %s secciones, %s subsecciones, %s chars en %sms",
        len(desarrollo),
        total_subsections,
        total_chars,
        total_ms,
        extra={
            "num_sections": len(desarrollo),
            "num_subsections": total_subsections,
            "content_length": total_chars,
            "total_duration_ms": total_ms,
            "prompt_tokens": usage.prompt_token_count,
            "completion_tokens": usage.candidates_token_count,
        },
    )

    return result, usage


def run_subpart_explainer_or(
    source_path: str,
    identificacion: str,
    model: str = OPENROUTER_MODEL_AGENTS,
    mime_type: str = "application/pdf",
    api_key: str = "",
    pdf_cache_entry: "PdfOcrCacheEntry | None" = None,
    page_numbers: tuple[int, ...] | None = None,
    target_language: str = "es-ES",
    *,
    provider_routing: dict | None = None,
) -> tuple[dict[str, Any], OpenRouterUsage]:
    """Explainer de subparte vía OpenRouter — retorna solo `desarrollo` estructurado."""
    start = time.time()
    logger.info(
        "Iniciando agente explainer subparte (openrouter)",
        extra={
            "source_path": source_path,
            "identificacion_length": len(identificacion),
            "identificacion_preview": identificacion[:150] + "..." if len(identificacion) > 150 else identificacion,
            "mime_type": mime_type,
            "model": model,
        },
    )
    response_format = _resolve_openrouter_response_format(
        model=model,
        json_schema=OR_SUBPART_EXPLAINER_JSON_SCHEMA,
    )

    result, usage = _call_openrouter_with_validation_retries(
        call_operation=lambda: _call_openrouter_json_with_pdf_fallback(
            source_path=source_path,
            identificacion=identificacion,
            mime_type=mime_type,
            model=model,
            system_prompt=build_openrouter_subpart_explainer_system_prompt(target_language),
            response_format=response_format,
            api_key=api_key,
            pdf_cache_entry=pdf_cache_entry,
            page_numbers=page_numbers,
            provider_routing=provider_routing,
        ),
        validate_payload=_validate_subpart_explainer_payload,
        operation_label="Explainer subparte OpenRouter",
    )
    desarrollo = result.get("desarrollo") or []
    total_chars = _count_payload_chars(result)
    total_subsections = _count_desarrollo_subsections(desarrollo)

    total_ms = int((time.time() - start) * 1000)
    logger.info(
        "Subpart explainer (openrouter) completado: %s secciones, %s subsecciones, %s chars en %sms",
        len(desarrollo),
        total_subsections,
        total_chars,
        total_ms,
        extra={
            "num_sections": len(desarrollo),
            "num_subsections": total_subsections,
            "content_length": total_chars,
            "total_duration_ms": total_ms,
            "prompt_tokens": usage.prompt_token_count,
            "completion_tokens": usage.candidates_token_count,
        },
    )

    return result, usage


# ---------------------------------------------------------------------------
# Retry helpers — reutilizan _call_openrouter_json_with_pdf_fallback con el
# system prompt y el identificacion extendidos para indicar el truncamiento.
# ---------------------------------------------------------------------------

def _run_explainer_or_for_retry(
    source_path: str,
    identificacion: str,
    previous_result: dict[str, Any],
    validation_report: ExplainerValidationReport,
    model: str,
    mime_type: str,
    api_key: str,
    pdf_cache_entry: "PdfOcrCacheEntry | None",
    page_numbers: tuple[int, ...] | None,
    validation_context: ExplainerValidationContext | None,
    target_language: str = "es-ES",
    *,
    provider_routing: dict | None = None,
) -> tuple[dict[str, Any], OpenRouterUsage]:
    """Reintento de run_explainer_or con contexto de validación de la salida anterior."""
    logger.info(
        "Reintentando explainer (openrouter) por validación fallida",
        extra={
            "source_path": source_path,
            "model": model,
            "is_complete": validation_report.is_complete,
            "scope_status": validation_report.scope_status,
        },
    )
    retry_ctx = format_explainer_retry_context(
        previous_result,
        validation_report,
        validation_context=validation_context,
    )
    extended_identificacion = f"{identificacion}\n\n{retry_ctx}"
    extended_system = (
        f"{build_openrouter_explainer_system_prompt(target_language)}"
        f"{build_explainer_retry_system_suffix(validation_report, validation_context=validation_context)}"
    )

    response_format = _resolve_openrouter_response_format(
        model=model, json_schema=OR_EXPLAINER_JSON_SCHEMA
    )
    raw, usage = _call_openrouter_json_with_pdf_fallback(
        source_path=source_path,
        identificacion=extended_identificacion,
        mime_type=mime_type,
        model=model,
        system_prompt=extended_system,
        response_format=response_format,
        api_key=api_key,
        pdf_cache_entry=pdf_cache_entry,
        page_numbers=page_numbers,
        provider_routing=provider_routing,
    )
    result = _validate_full_explainer_payload(raw)
    logger.info(
        "Reintento explainer (openrouter) completado: %d secciones",
        len(result.get("desarrollo", [])),
    )
    return result, usage


def _run_subpart_explainer_or_for_retry(
    source_path: str,
    identificacion: str,
    previous_result: dict[str, Any],
    validation_report: ExplainerValidationReport,
    model: str,
    mime_type: str,
    api_key: str,
    pdf_cache_entry: "PdfOcrCacheEntry | None",
    page_numbers: tuple[int, ...] | None,
    validation_context: ExplainerValidationContext | None,
    target_language: str = "es-ES",
    *,
    provider_routing: dict | None = None,
) -> tuple[dict[str, Any], OpenRouterUsage]:
    """Reintento de run_subpart_explainer_or con contexto de validación de la salida anterior."""
    logger.info(
        "Reintentando subpart explainer (openrouter) por validación fallida",
        extra={
            "source_path": source_path,
            "model": model,
            "is_complete": validation_report.is_complete,
            "scope_status": validation_report.scope_status,
        },
    )
    retry_ctx = format_explainer_retry_context(
        previous_result,
        validation_report,
        validation_context=validation_context,
    )
    extended_identificacion = f"{identificacion}\n\n{retry_ctx}"
    extended_system = (
        f"{build_openrouter_subpart_explainer_system_prompt(target_language)}"
        f"{build_explainer_retry_system_suffix(validation_report, validation_context=validation_context)}"
    )

    response_format = _resolve_openrouter_response_format(
        model=model, json_schema=OR_SUBPART_EXPLAINER_JSON_SCHEMA
    )
    raw, usage = _call_openrouter_json_with_pdf_fallback(
        source_path=source_path,
        identificacion=extended_identificacion,
        mime_type=mime_type,
        model=model,
        system_prompt=extended_system,
        response_format=response_format,
        api_key=api_key,
        pdf_cache_entry=pdf_cache_entry,
        page_numbers=page_numbers,
        provider_routing=provider_routing,
    )
    result = _validate_subpart_explainer_payload(raw)
    logger.info(
        "Reintento subpart explainer (openrouter) completado: %d secciones",
        len(result.get("desarrollo", [])),
    )
    return result, usage


# ---------------------------------------------------------------------------
# Funciones públicas con validación de completitud integrada.
# El validador usa OpenRouter con la misma clave salvo que se indique otra.
# Devuelven (result, usage, list[validator_usages]) en lugar del 2-tuple original.
# ---------------------------------------------------------------------------

def run_explainer_or_validated(
    source_path: str,
    identificacion: str,
    model: str = OPENROUTER_MODEL_AGENTS,
    mime_type: str = "application/pdf",
    api_key: str = "",
    validator_api_key: str = "",
    pdf_cache_entry: "PdfOcrCacheEntry | None" = None,
    page_numbers: tuple[int, ...] | None = None,
    validation_context: ExplainerValidationContext | None = None,
    target_language: str = "es-ES",
    *,
    provider_routing: dict | None = None,
) -> tuple[dict[str, Any], OpenRouterUsage, list[Any]]:
    """run_explainer_or con validación de completitud y reintento automático.

    Args:
        api_key:            Clave de OpenRouter para el explainer.
        validator_api_key:  Clave de OpenRouter para el validador. Si está vacía,
                            se reutiliza api_key.

    Returns:
        (result, usage, validator_usages_list)
    """
    return run_with_openrouter_explainer_validation(
        initial_call=lambda: run_explainer_or(
            source_path, identificacion, model, mime_type, api_key, pdf_cache_entry, page_numbers, target_language,
            provider_routing=provider_routing,
        ),
        retry_call=lambda prev, report: _run_explainer_or_for_retry(
            source_path,
            identificacion,
            prev,
            report,
            model,
            mime_type,
            api_key,
            pdf_cache_entry,
            page_numbers,
            validation_context,
            target_language,
            provider_routing=provider_routing,
        ),
        openrouter_api_key=validator_api_key or api_key,
        label=f"Explainer OpenRouter [{model}]",
        validation_context=validation_context,
    )


def run_subpart_explainer_or_validated(
    source_path: str,
    identificacion: str,
    model: str = OPENROUTER_MODEL_AGENTS,
    mime_type: str = "application/pdf",
    api_key: str = "",
    validator_api_key: str = "",
    pdf_cache_entry: "PdfOcrCacheEntry | None" = None,
    page_numbers: tuple[int, ...] | None = None,
    validation_context: ExplainerValidationContext | None = None,
    target_language: str = "es-ES",
    *,
    provider_routing: dict | None = None,
) -> tuple[dict[str, Any], OpenRouterUsage, list[Any]]:
    """run_subpart_explainer_or con validación de completitud y reintento automático.

    Args:
        api_key:            Clave de OpenRouter para el explainer.
        validator_api_key:  Clave de OpenRouter para el validador. Si está vacía,
                            se reutiliza api_key.

    Returns:
        (result, usage, validator_usages_list)
    """
    return run_with_openrouter_explainer_validation(
        initial_call=lambda: run_subpart_explainer_or(
            source_path, identificacion, model, mime_type, api_key, pdf_cache_entry, page_numbers, target_language,
            provider_routing=provider_routing,
        ),
        retry_call=lambda prev, report: _run_subpart_explainer_or_for_retry(
            source_path,
            identificacion,
            prev,
            report,
            model,
            mime_type,
            api_key,
            pdf_cache_entry,
            page_numbers,
            validation_context,
            target_language,
            provider_routing=provider_routing,
        ),
        openrouter_api_key=validator_api_key or api_key,
        label=f"Subpart Explainer OpenRouter [{model}]",
        validation_context=validation_context,
    )
