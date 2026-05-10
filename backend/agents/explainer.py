"""Agente Explainer — explicación exhaustiva de cada parte."""
from __future__ import annotations

import json
import time
from typing import Any
from backend.gemini_model_routing import MODEL_AGENTS
from backend.gemini_client import gemini_retry, generate_content_with_retry
from backend.logging_config import get_logger
from backend.agents.explainer_prompts import (
    SUBPART_SYSTEM_INSTRUCTION,
    SYSTEM_INSTRUCTION,
)
from backend.agents.completeness_validator import (
    ExplainerValidationContext,
    ExplainerValidationReport,
    build_explainer_retry_system_suffix,
    format_explainer_retry_context,
    run_with_explainer_validation,
)

from google import genai
from google.genai import types

logger = get_logger("backend.agents.explainer")

RESPONSE_SCHEMA = genai.types.Schema(
    type=genai.types.Type.OBJECT,
    required=["introduccion", "desarrollo", "conclusion"],
    properties={
        "introduccion": genai.types.Schema(
            type=genai.types.Type.STRING,
            description=(
                "Uno o dos párrafos breves que contextualizan el tema y su importancia, "
                "y anticipan la estructura de la explicación. NO desarrolla contenido sustantivo."
            ),
        ),
        "desarrollo": genai.types.Schema(
            type=genai.types.Type.ARRAY,
            description="Array de secciones temáticas que constituyen el cuerpo principal de la explicación.",
            items=genai.types.Schema(
                type=genai.types.Type.OBJECT,
                required=["titulo_seccion", "explicacion_introductoria", "subsecciones"],
                properties={
                    "titulo_seccion": genai.types.Schema(type=genai.types.Type.STRING),
                    "explicacion_introductoria": genai.types.Schema(type=genai.types.Type.STRING),
                    "subsecciones": genai.types.Schema(
                        type=genai.types.Type.ARRAY,
                        items=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=["titulo_subseccion", "explicacion_detallada"],
                            properties={
                                "titulo_subseccion": genai.types.Schema(type=genai.types.Type.STRING),
                                "explicacion_detallada": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description=(
                                        "Explicación exhaustiva y en prosa del elemento. "
                                        "Integra: definición técnica + reformulación accesible, "
                                        "términos clave preservados exactamente, ejemplos concretos, "
                                        "analogías cuando el concepto sea abstracto, desarrollo de matices. "
                                        "NUNCA condensar artificialmente."
                                    ),
                                ),
                            },
                        ),
                    ),
                },
            ),
        ),
        "conclusion": genai.types.Schema(
            type=genai.types.Type.STRING,
            description=(
                "Uno o dos párrafos breves que sintetizan las ideas clave y refuerzan "
                "las conexiones principales. ÚNICO lugar donde está permitido sintetizar."
            ),
        ),
        "conexiones_contextuales": genai.types.Schema(
            type=genai.types.Type.ARRAY,
            description="Referencias a otras secciones del temario. Devolver null si no aplica.",
            items=genai.types.Schema(
                type=genai.types.Type.OBJECT,
                required=["seccion_temario_relacionada", "descripcion_conexion"],
                properties={
                    "seccion_temario_relacionada": genai.types.Schema(type=genai.types.Type.STRING),
                    "descripcion_conexion": genai.types.Schema(type=genai.types.Type.STRING),
                },
            ),
        ),
    },
)


@gemini_retry(max_retries=5)
def run_explainer(
    api_key: str,
    file_uri: str,
    identificacion: str,
    model: str = MODEL_AGENTS,
    mime_type: str = "application/pdf",
) -> tuple[dict[str, Any], Any]:
    """Run the Explainer agent and return (structured_result, usage_metadata)."""
    start_time = time.time()
    logger.info(
        "Iniciando agente explainer",
        extra={
            "file_uri_prefix": file_uri[:60] + "..." if len(file_uri) > 60 else file_uri,
            "identificacion_length": len(identificacion),
            "identificacion_preview": identificacion[:150] + "..." if len(identificacion) > 150 else identificacion,
            "mime_type": mime_type,
        }
    )

    client = genai.Client(api_key=api_key)

    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_uri(file_uri=file_uri, mime_type=mime_type),
                types.Part.from_text(text=identificacion),
            ],
        ),
    ]

    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
        system_instruction=[types.Part.from_text(text=SYSTEM_INSTRUCTION)],
    )

    logger.debug("Enviando request a Gemini para generar explicación")

    response = generate_content_with_retry(
        client=client,
        model=model,
        contents=contents,
        config=config,
        max_retries=5,
        operation_context={"agent": "explainer"},
    )

    # Procesar respuesta
    parse_start = time.time()
    try:
        result = json.loads(response.text)
        parse_duration = (time.time() - parse_start) * 1000
        total_duration = (time.time() - start_time) * 1000

        # Extraer información relevante
        num_secciones = len(result.get("desarrollo", []))
        intro_length = len(result.get("introduccion", ""))
        conclusion_length = len(result.get("conclusion", ""))

        logger.info(
            f"Explainer completado: {num_secciones} secciones en {int(total_duration)}ms",
            extra={
                "num_secciones": num_secciones,
                "intro_length": intro_length,
                "conclusion_length": conclusion_length,
                "parse_duration_ms": int(parse_duration),
                "total_duration_ms": int(total_duration),
                "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0) if response.usage_metadata else 0,
                "candidates_tokens": getattr(response.usage_metadata, "candidates_token_count", 0) if response.usage_metadata else 0,
                "thoughts_tokens": getattr(response.usage_metadata, "thoughts_token_count", 0) if response.usage_metadata else 0,
                "total_tokens": getattr(response.usage_metadata, "total_token_count", 0) if response.usage_metadata else 0,
            }
        )

        # Quality preview (visible en desarrollo, nivel DEBUG)
        logger.debug("Explainer — intro: %d chars", intro_length)
        for sec in result.get("desarrollo", [])[:6]:
            subs = sec.get("subsecciones", [])
            logger.debug(
                "  Sección: \"%s\" (%d subsecciones)",
                sec.get("titulo_seccion", "?")[:70], len(subs),
            )
            for sub in subs[:3]:
                exp = sub.get("explicacion_detallada", "")
                logger.debug(
                    "    └─ \"%s\": %d chars",
                    sub.get("titulo_subseccion", "?")[:60], len(exp),
                )

        return result, response.usage_metadata

    except json.JSONDecodeError as e:
        logger.error(
            f"Error al parsear JSON de respuesta: {str(e)}",
            extra={
                "error_type": "json_decode_error",
                "response_preview": response.text[:200] if response.text else "empty",
            }
        )
        raise


# ---------------------------------------------------------------------------
# Subpart explainer: generates only "desarrollo" (sections/subsections).
# The introduccion, conclusion and conexiones_contextuales are provided by the
# segmentador which has global vision of the entire document.
# ---------------------------------------------------------------------------

SUBPART_RESPONSE_SCHEMA = genai.types.Schema(
    type=genai.types.Type.OBJECT,
    required=["desarrollo"],
    properties={
        "desarrollo": genai.types.Schema(
            type=genai.types.Type.ARRAY,
            description="Array de secciones temáticas que constituyen el cuerpo principal de la explicación de esta subparte.",
            items=genai.types.Schema(
                type=genai.types.Type.OBJECT,
                required=["titulo_seccion", "explicacion_introductoria", "subsecciones"],
                properties={
                    "titulo_seccion": genai.types.Schema(type=genai.types.Type.STRING),
                    "explicacion_introductoria": genai.types.Schema(type=genai.types.Type.STRING),
                    "subsecciones": genai.types.Schema(
                        type=genai.types.Type.ARRAY,
                        items=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=["titulo_subseccion", "explicacion_detallada"],
                            properties={
                                "titulo_subseccion": genai.types.Schema(type=genai.types.Type.STRING),
                                "explicacion_detallada": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description=(
                                        "Explicación exhaustiva y en prosa del elemento. "
                                        "Integra: definición técnica + reformulación accesible, "
                                        "términos clave preservados exactamente, ejemplos concretos, "
                                        "analogías cuando el concepto sea abstracto, desarrollo de matices. "
                                        "NUNCA condensar artificialmente."
                                    ),
                                ),
                            },
                        ),
                    ),
                },
            ),
        ),
    },
)


@gemini_retry(max_retries=5)
def run_subpart_explainer(
    api_key: str,
    file_uri: str,
    identificacion: str,
    model: str = MODEL_AGENTS,
    mime_type: str = "application/pdf",
) -> tuple[dict[str, Any], Any]:
    """Run the Explainer agent for a single subpart — returns only desarrollo."""
    start_time = time.time()
    logger.info(
        "Iniciando agente explainer (subparte)",
        extra={
            "file_uri_prefix": file_uri[:60] + "..." if len(file_uri) > 60 else file_uri,
            "identificacion_length": len(identificacion),
            "identificacion_preview": identificacion[:150] + "..." if len(identificacion) > 150 else identificacion,
            "mime_type": mime_type,
        }
    )

    client = genai.Client(api_key=api_key)

    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_uri(file_uri=file_uri, mime_type=mime_type),
                types.Part.from_text(text=identificacion),
            ],
        ),
    ]

    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
        response_mime_type="application/json",
        response_schema=SUBPART_RESPONSE_SCHEMA,
        system_instruction=[types.Part.from_text(text=SUBPART_SYSTEM_INSTRUCTION)],
    )

    response = generate_content_with_retry(
        client=client,
        model=model,
        contents=contents,
        config=config,
        max_retries=5,
        operation_context={"agent": "subpart_explainer"},
    )

    try:
        result = json.loads(response.text)
        total_duration = (time.time() - start_time) * 1000
        num_secciones = len(result.get("desarrollo", []))

        logger.info(
            f"Subpart explainer completado: {num_secciones} secciones en {int(total_duration)}ms",
            extra={
                "num_secciones": num_secciones,
                "total_duration_ms": int(total_duration),
                "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0) if response.usage_metadata else 0,
                "candidates_tokens": getattr(response.usage_metadata, "candidates_token_count", 0) if response.usage_metadata else 0,
                "thoughts_tokens": getattr(response.usage_metadata, "thoughts_token_count", 0) if response.usage_metadata else 0,
            }
        )

        return result, response.usage_metadata

    except json.JSONDecodeError as e:
        logger.error(
            f"Error al parsear JSON de subpart explainer: {str(e)}",
            extra={
                "error_type": "json_decode_error",
                "response_preview": response.text[:200] if response.text else "empty",
            }
        )
        raise


# ---------------------------------------------------------------------------
# Retry helpers — misma lógica que los originales pero con contexto de
# explicación anterior incompleta inyectado en system instruction y user message.
# ---------------------------------------------------------------------------

def _run_explainer_for_retry(
    api_key: str,
    file_uri: str,
    identificacion: str,
    previous_result: dict[str, Any],
    validation_report: ExplainerValidationReport,
    model: str = MODEL_AGENTS,
    mime_type: str = "application/pdf",
    validation_context: ExplainerValidationContext | None = None,
) -> tuple[dict[str, Any], Any]:
    """Reintento de run_explainer con contexto de validación de la salida anterior."""
    logger.info(
        "Reintentando explainer completo por validación fallida",
        extra={
            "file_uri_prefix": file_uri[:60],
            "model": model,
            "is_complete": validation_report.is_complete,
            "scope_status": validation_report.scope_status,
        },
    )
    client = genai.Client(api_key=api_key)

    retry_ctx = format_explainer_retry_context(
        previous_result,
        validation_report,
        validation_context=validation_context,
    )
    extended_system = SYSTEM_INSTRUCTION + build_explainer_retry_system_suffix(
        validation_report,
        validation_context=validation_context,
    )

    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_uri(file_uri=file_uri, mime_type=mime_type),
                types.Part.from_text(text=identificacion),
                types.Part.from_text(text=retry_ctx),
            ],
        ),
    ]

    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
        system_instruction=[types.Part.from_text(text=extended_system)],
    )

    response = generate_content_with_retry(
        client=client,
        model=model,
        contents=contents,
        config=config,
        max_retries=5,
        operation_context={"agent": "explainer_validation_retry"},
    )

    result = json.loads(response.text)
    logger.info(
        "Reintento explainer completado: %d secciones",
        len(result.get("desarrollo", [])),
        extra={"num_secciones": len(result.get("desarrollo", []))},
    )
    return result, response.usage_metadata


def _run_subpart_explainer_for_retry(
    api_key: str,
    file_uri: str,
    identificacion: str,
    previous_result: dict[str, Any],
    validation_report: ExplainerValidationReport,
    model: str = MODEL_AGENTS,
    mime_type: str = "application/pdf",
    validation_context: ExplainerValidationContext | None = None,
) -> tuple[dict[str, Any], Any]:
    """Reintento de run_subpart_explainer con contexto de validación de la salida anterior."""
    logger.info(
        "Reintentando explainer de subparte por validación fallida",
        extra={
            "file_uri_prefix": file_uri[:60],
            "model": model,
            "is_complete": validation_report.is_complete,
            "scope_status": validation_report.scope_status,
        },
    )
    client = genai.Client(api_key=api_key)

    retry_ctx = format_explainer_retry_context(
        previous_result,
        validation_report,
        validation_context=validation_context,
    )
    extended_system = SUBPART_SYSTEM_INSTRUCTION + build_explainer_retry_system_suffix(
        validation_report,
        validation_context=validation_context,
    )

    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_uri(file_uri=file_uri, mime_type=mime_type),
                types.Part.from_text(text=identificacion),
                types.Part.from_text(text=retry_ctx),
            ],
        ),
    ]

    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
        response_mime_type="application/json",
        response_schema=SUBPART_RESPONSE_SCHEMA,
        system_instruction=[types.Part.from_text(text=extended_system)],
    )

    response = generate_content_with_retry(
        client=client,
        model=model,
        contents=contents,
        config=config,
        max_retries=5,
        operation_context={"agent": "subpart_explainer_validation_retry"},
    )

    result = json.loads(response.text)
    logger.info(
        "Reintento subpart explainer completado: %d secciones",
        len(result.get("desarrollo", [])),
        extra={"num_secciones": len(result.get("desarrollo", []))},
    )
    return result, response.usage_metadata


# ---------------------------------------------------------------------------
# Funciones públicas con validación de completitud integrada.
# Devuelven (result, main_usage, list[validator_usages]) en lugar del 2-tuple
# original, para que el llamador pueda trackear el coste del validador.
# ---------------------------------------------------------------------------

def run_explainer_validated(
    api_key: str,
    file_uri: str,
    identificacion: str,
    model: str = MODEL_AGENTS,
    mime_type: str = "application/pdf",
    validation_context: ExplainerValidationContext | None = None,
) -> tuple[dict[str, Any], Any, list[Any]]:
    """run_explainer con validación de completitud y reintento automático.

    Returns:
        (result, usage_metadata, validator_usages_list)
    """
    return run_with_explainer_validation(
        initial_call=lambda: run_explainer(api_key, file_uri, identificacion, model, mime_type),
        retry_call=lambda prev, report: _run_explainer_for_retry(
            api_key,
            file_uri,
            identificacion,
            prev,
            report,
            model,
            mime_type,
            validation_context,
        ),
        gemini_api_key=api_key,
        label=f"Explainer Gemini [{file_uri[:40]}]",
        validation_context=validation_context,
    )


def run_subpart_explainer_validated(
    api_key: str,
    file_uri: str,
    identificacion: str,
    model: str = MODEL_AGENTS,
    mime_type: str = "application/pdf",
    validation_context: ExplainerValidationContext | None = None,
) -> tuple[dict[str, Any], Any, list[Any]]:
    """run_subpart_explainer con validación de completitud y reintento automático.

    Returns:
        (result, usage_metadata, validator_usages_list)
    """
    return run_with_explainer_validation(
        initial_call=lambda: run_subpart_explainer(api_key, file_uri, identificacion, model, mime_type),
        retry_call=lambda prev, report: _run_subpart_explainer_for_retry(
            api_key,
            file_uri,
            identificacion,
            prev,
            report,
            model,
            mime_type,
            validation_context,
        ),
        gemini_api_key=api_key,
        label=f"Subpart Explainer Gemini [{file_uri[:40]}]",
        validation_context=validation_context,
    )
