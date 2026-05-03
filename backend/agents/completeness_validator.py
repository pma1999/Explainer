"""Validador de completitud de explicaciones — detecta truncamientos con Gemini Flash Lite.

El validador llama siempre a Gemini 3.1 Flash Lite independientemente del proveedor que
generó la explicación (Gemini o OpenRouter).  Si el validador detecta un truncamiento,
el llamador puede reintentar con el mismo modelo original pasando el resultado incompleto
como contexto adicional.

Uso típico:
    from backend.agents.completeness_validator import run_with_completeness_validation
    result, usage, val_usages = run_with_completeness_validation(
        initial_call=lambda: run_explainer(...),
        retry_call=lambda prev: _retry_explainer(..., previous_result=prev),
        gemini_api_key=api_key,
        label="Explainer Gemini parte 3",
    )
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable

from google import genai
from google.genai import types

from backend.gemini_client import generate_content_with_retry
from backend.logging_config import get_logger

logger = get_logger("backend.agents.completeness_validator")

# Siempre Gemini 3.1 Flash Lite para el validador, al margen del proveedor del explainer.
COMPLETENESS_VALIDATOR_MODEL = "gemini-3.1-flash-lite-preview"

# Número máximo de reintentos de completitud (sin contar el intento inicial).
# Con MAX_COMPLETENESS_RETRIES = 2: hasta 3 llamadas al explainer + 3 al validador.
MAX_COMPLETENESS_RETRIES = 2

# Sufijo añadido al system prompt cuando se detecta un truncamiento y se reintenta.
INCOMPLETE_RETRY_SYSTEM_SUFFIX = """

<aviso_regeneracion_por_truncamiento>
ATENCIÓN CRÍTICA: La explicación generada anteriormente para esta sección fue INCOMPLETA —
quedó truncada abruptamente a mitad sin terminar correctamente.

Para esta nueva generación debes:
1. Generar una explicación COMPLETAMENTE NUEVA y COMPLETA que no se corte bajo ninguna circunstancia.
2. Asegurarte de que cada sección y subsección tiene un cierre natural y completo.
3. Si necesitas ser algo más conciso en secciones intermedias para garantizar que el texto
   completo llegue al final correctamente, hazlo — es preferible una explicación algo más
   breve pero completa a una más extensa pero truncada.
4. Verificar que la última oración de la explicación esté gramaticalmente completa y
   termine con puntuación correcta (punto, interrogación o exclamación).
</aviso_regeneracion_por_truncamiento>"""

_VALIDATOR_SYSTEM_PROMPT = """Eres un evaluador de completitud textual. Tu única tarea es determinar si una explicación académica está completa o ha sido truncada/cortada abruptamente.

Analiza ESPECIALMENTE el FINAL del texto recibido.

El texto está INCOMPLETO (truncado) si detectas alguna de estas señales:
- La última oración no termina con puntuación final (punto, interrogación o exclamación)
- El texto termina con conjunciones, preposiciones o artículos ("y", "pero", "de", "con", "que", "el", "la", "un", "una")
- El texto termina en medio de una lista o enumeración sin concluirla
- El último párrafo plantea una idea sin cerrarla o desarrollarla completamente
- Hay palabras finales que insinúan continuación ("además", "sin embargo", "también", "por otro lado", "asimismo", "igualmente")
- Una subsección o sección tiene su explicación claramente cortada antes de terminar

El texto está COMPLETO si:
- Termina con una oración bien formada con puntuación correcta
- El último párrafo o la última sección tienen un cierre natural
- No hay indicios sintácticos de continuación truncada

Devuelve ÚNICAMENTE un objeto JSON con exactamente este formato (sin texto adicional):
{"is_complete": true, "reason": "Razón breve de la evaluación"}
o
{"is_complete": false, "reason": "Razón breve: describe específicamente dónde y cómo está truncado"}"""

_VALIDATOR_SCHEMA = genai.types.Schema(
    type=genai.types.Type.OBJECT,
    required=["is_complete", "reason"],
    properties={
        "is_complete": genai.types.Schema(
            type=genai.types.Type.BOOLEAN,
            description="True si la explicación está completa, False si está truncada.",
        ),
        "reason": genai.types.Schema(
            type=genai.types.Type.STRING,
            description="Breve justificación de la evaluación.",
        ),
    },
)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _serialize_for_validation(explanation: dict) -> str:
    """Extrae todo el texto en prosa de un dict de explicación para evaluarlo."""
    parts: list[str] = []

    if "introduccion" in explanation:
        val = explanation["introduccion"]
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())

    for section in explanation.get("desarrollo") or []:
        intro = section.get("explicacion_introductoria", "")
        if isinstance(intro, str) and intro.strip():
            parts.append(intro.strip())
        for subsection in section.get("subsecciones") or []:
            body = subsection.get("explicacion_detallada", "")
            if isinstance(body, str) and body.strip():
                parts.append(body.strip())

    if "conclusion" in explanation:
        val = explanation["conclusion"]
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def format_incomplete_context(previous_result: dict) -> str:
    """Formatea el resultado incompleto anterior para incluirlo en el prompt de reintento."""
    try:
        serialized = json.dumps(previous_result, ensure_ascii=False, indent=2)
    except Exception:
        serialized = str(previous_result)
    return (
        "<explicacion_anterior_incompleta>\n"
        "La siguiente explicación fue generada pero quedó TRUNCADA/INCOMPLETA "
        "(sirve de contexto para que no repitas el mismo error):\n\n"
        f"{serialized}\n"
        "</explicacion_anterior_incompleta>"
    )


def check_explanation_completeness(
    explanation: dict,
    gemini_api_key: str,
) -> tuple[bool, str, Any]:
    """Verifica si una explicación está completa usando Gemini Flash Lite.

    Returns:
        (is_complete, reason, usage_metadata)
        En caso de error del validador devuelve (True, descripción_error, None)
        para no bloquear el flujo principal.
    """
    start = time.time()
    try:
        text = _serialize_for_validation(explanation)
        if not text.strip():
            return True, "Explicación vacía — se considera completa por defecto.", None

        client = genai.Client(api_key=gemini_api_key)

        user_message = (
            "Evalúa si la siguiente explicación académica está completa o ha sido truncada:\n\n"
            f"{text}"
        )

        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_message)],
            )
        ]

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
            operation_context={"agent": "completeness_validator"},
        )

        result = json.loads(response.text)
        is_complete = bool(result.get("is_complete", True))
        reason = result.get("reason", "")
        elapsed_ms = int((time.time() - start) * 1000)

        logger.info(
            "Completitud evaluada: %s — %s (%dms)",
            "COMPLETA" if is_complete else "INCOMPLETA",
            reason[:150],
            elapsed_ms,
            extra={
                "is_complete": is_complete,
                "reason": reason[:200],
                "elapsed_ms": elapsed_ms,
                "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0) if response.usage_metadata else 0,
                "candidates_tokens": getattr(response.usage_metadata, "candidates_token_count", 0) if response.usage_metadata else 0,
            },
        )

        return is_complete, reason, response.usage_metadata

    except Exception as exc:
        elapsed_ms = int((time.time() - start) * 1000)
        logger.warning(
            "Error en validador de completitud (%dms) — se asume completa. Error: %s",
            elapsed_ms,
            str(exc)[:200],
            extra={"error_type": type(exc).__name__, "elapsed_ms": elapsed_ms},
        )
        return True, f"Error en validador ({type(exc).__name__}) — resultado aceptado.", None


def run_with_completeness_validation(
    *,
    initial_call: Callable[[], tuple[dict, Any]],
    retry_call: Callable[[dict], tuple[dict, Any]],
    gemini_api_key: str,
    label: str,
) -> tuple[dict, Any, list[Any]]:
    """Ejecuta initial_call, valida completitud y reintenta si es necesario.

    Args:
        initial_call: Función sin args que devuelve (result_dict, usage).
        retry_call:   Función que recibe el resultado incompleto anterior y devuelve
                      (result_dict, usage) con un nuevo intento.
        gemini_api_key: Clave de Gemini para el validador (siempre Flash Lite).
        label:        Etiqueta descriptiva para logs.

    Returns:
        (best_result, best_usage, list_of_validator_usages)
        Si todos los reintentos fallan la validación, devuelve el primer intento.
    """
    # --- Llamada inicial ---
    result, usage = initial_call()
    first_result, first_usage = result, usage
    validator_usages: list[Any] = []

    for attempt in range(MAX_COMPLETENESS_RETRIES + 1):
        # Validar resultado actual
        is_complete, reason, val_usage = check_explanation_completeness(result, gemini_api_key)
        if val_usage is not None:
            validator_usages.append(val_usage)

        if is_complete:
            if attempt > 0:
                logger.info(
                    "%s: completitud confirmada tras %d reintento(s).",
                    label, attempt,
                    extra={"label": label, "successful_attempt": attempt},
                )
            return result, usage, validator_usages

        logger.warning(
            "%s: explicación INCOMPLETA (evaluación %d/%d) — %s",
            label,
            attempt + 1,
            MAX_COMPLETENESS_RETRIES + 1,
            reason[:150],
            extra={
                "label": label,
                "validation_attempt": attempt + 1,
                "max_validations": MAX_COMPLETENESS_RETRIES + 1,
                "reason": reason[:200],
            },
        )

        if attempt >= MAX_COMPLETENESS_RETRIES:
            # Agotados los reintentos — salir del bucle
            break

        # --- Reintento ---
        try:
            result, usage = retry_call(result)
        except Exception as exc:
            logger.error(
                "%s: error en reintento %d de completitud — %s. Se usará el primer resultado.",
                label,
                attempt + 1,
                str(exc)[:200],
                extra={"label": label, "retry_attempt": attempt + 1, "error_type": type(exc).__name__},
            )
            break

    logger.warning(
        "%s: completitud no lograda tras %d intento(s) — usando primer resultado.",
        label,
        MAX_COMPLETENESS_RETRIES + 1,
        extra={"label": label, "total_attempts": MAX_COMPLETENESS_RETRIES + 1},
    )
    return first_result, first_usage, validator_usages
