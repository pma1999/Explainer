"""Agente Review — repaso activo: 5 preguntas de autoevaluación por parte.

Chat de texto puro (sin PDF, sin búsqueda): recibe el contenido del explainer
ya generado de la parte y produce 5 preguntas de comprensión con respuesta
razonada. Tres implementaciones con el mismo contrato de salida:
- run_review      → Gemini (response_schema + generate_content_with_retry)
- run_review_or   → OpenRouter (json contract + validation retries)
- run_review_ds   → DeepSeek (json contract + validation retries)
"""
from __future__ import annotations

import json
import time
from typing import Any, Awaitable, Callable

from backend.gemini_model_routing import MODEL_AGENTS
from backend.gemini_client import gemini_retry, generate_content_with_retry
from backend.logging_config import get_logger
from backend.codex_client import CodexError, CodexUsage, call_codex_chat
from backend.codex_model_routing import CODEX_MODEL
from backend.openrouter_client import (
    OpenRouterError,
    OpenRouterJsonSchemaResponseFormat,
    call_openrouter_chat,
)
from backend.agents.explainer_openrouter import (
    OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES,
    _resolve_openrouter_response_format,
)
from backend.deepseek_client import DeepSeekError, DeepSeekUsage, call_deepseek_chat
from backend.deepseek_model_routing import DEEPSEEK_MODEL_AUXILIARY, max_reasoning_effort
from backend.openrouter_model_routing import (
    OPENROUTER_MODEL_AUXILIARY,
    deepseek_provider_preferences,
    max_reasoning_preferences,
)

from google import genai
from google.genai import types

logger = get_logger("backend.agents.review")

REVIEW_NUM_QUESTIONS = 5


def build_review_system_instruction(target_language: str = "es-ES") -> str:
    """System prompt for the review agent in the target language."""
    return (
        "<system_instruction>\n"
        "  <role>\n"
        "  Eres un tutor académico que prepara repaso activo.\n"
        "  </role>\n"
        "  <task>\n"
        "  A partir de la explicación de una sección de un texto académico, genera "
        "exactamente 5 preguntas de autoevaluación que pongan a prueba la comprensión, "
        "no la memorización. Cada pregunta debe requerir razonar y sintetizar la información.\n"
        "  </task>\n"
        "  <requirements>\n"
        "  - 5 preguntas exactamente, numeradas del 1 al 5.\n"
        "  - Incluye la respuesta razonada en 2-4 frases.\n"
        "  - Si el contenido permite inferir la ubicación (páginas, sección, subsección), "
        "indícala en 'referencia'; si no, cadena vacía.\n"
        "  - Las preguntas deben cubrir las ideas centrales y sus conexiones, no datos sueltos.\n"
        "  - 'nota' es un consejo de estudio breve (máximo 2 frases), opcional.\n"
        "  </requirements>\n"
        f"  <idioma_objetivo>\n"
        f"  Todo el contenido (preguntas, respuestas, referencias y nota) DEBE estar en: {target_language}.\n"
        f"  </idioma_objetivo>\n"
        "</system_instruction>"
    )


REVIEW_JSON_CONTRACT = """Devuelve exclusivamente un objeto JSON raíz con esta estructura exacta:
{
  "preguntas": [
    {
      "numero": 1,
      "pregunta": "string",
      "respuesta_razonada": "string — 2-4 frases con la respuesta y su razonamiento",
      "referencia": "string opcional — p.ej. 'págs. 12-14' o 'Sección 2.3' si es inferible del contenido"
    }
  ],
  "nota": "string opcional — consejo de estudio breve (máx 2 frases)"
}
Exactamente 5 elementos en 'preguntas'. No devuelvas un array raíz ni texto fuera del JSON."""


REVIEW_JSON_RETRY_INSTRUCTION = """El objeto JSON esperado tiene las claves raíz `preguntas` y `nota`.
`preguntas` es un array con EXACTAMENTE 5 objetos, cada uno con `numero` (entero), `pregunta` (string), `respuesta_razonada` (string) y `referencia` (string, puede ser vacía).
`nota` es un string opcional.
La raíz debe ser un objeto JSON, nunca un array."""


_REVIEW_QUESTION_SCHEMA = genai.types.Schema(
    type=genai.types.Type.OBJECT,
    required=["numero", "pregunta", "respuesta_razonada"],
    properties={
        "numero": genai.types.Schema(
            type=genai.types.Type.INTEGER,
            description="Número de la pregunta (1 a 5).",
        ),
        "pregunta": genai.types.Schema(
            type=genai.types.Type.STRING,
            description="Pregunta de autoevaluación que exige comprensión y síntesis.",
        ),
        "respuesta_razonada": genai.types.Schema(
            type=genai.types.Type.STRING,
            description="Respuesta razonada en 2-4 frases.",
        ),
        "referencia": genai.types.Schema(
            type=genai.types.Type.STRING,
            description="Ubicación inferible del contenido (páginas, sección, subsección). Vacío si no aplica.",
        ),
    },
)

REVIEW_RESPONSE_SCHEMA = genai.types.Schema(
    type=genai.types.Type.OBJECT,
    required=["preguntas"],
    properties={
        "preguntas": genai.types.Schema(
            type=genai.types.Type.ARRAY,
            description="Exactamente 5 preguntas de autoevaluación.",
            min_items=REVIEW_NUM_QUESTIONS,
            max_items=REVIEW_NUM_QUESTIONS,
            items=_REVIEW_QUESTION_SCHEMA,
        ),
        "nota": genai.types.Schema(
            type=genai.types.Type.STRING,
            description="Consejo de estudio breve (máximo 2 frases). Vacío si no aplica.",
        ),
    },
)

OPENROUTER_REVIEW_JSON_SCHEMA = OpenRouterJsonSchemaResponseFormat(
    name="review_questions",
    strict=True,
    schema={
        "type": "object",
        "description": "Review activo: 5 preguntas de autoevaluación con respuesta razonada.",
        "properties": {
            "preguntas": {
                "type": "array",
                "description": "Exactamente 5 preguntas de autoevaluación.",
                "minItems": REVIEW_NUM_QUESTIONS,
                "maxItems": REVIEW_NUM_QUESTIONS,
                "items": {
                    "type": "object",
                    "description": "Una pregunta con su respuesta razonada.",
                    "properties": {
                        "numero": {"type": "integer", "description": "Número de la pregunta (1 a 5)."},
                        "pregunta": {"type": "string"},
                        "respuesta_razonada": {"type": "string"},
                        "referencia": {
                            "type": "string",
                            "description": "Ubicación inferible (páginas, sección). Vacío si no aplica.",
                        },
                    },
                    "required": ["numero", "pregunta", "respuesta_razonada"],
                    "additionalProperties": False,
                },
            },
            "nota": {"type": "string", "description": "Consejo de estudio breve (máx 2 frases)."},
        },
        "required": ["preguntas"],
        "additionalProperties": False,
    },
)


def _serialize_explainer(explainer_content: dict | str) -> str:
    """Serialize the stored explainer (dict o markdown ya formateado) to text."""
    if isinstance(explainer_content, str):
        return explainer_content
    return json.dumps(explainer_content, ensure_ascii=False, indent=2)


def _build_user_message(explainer_content: dict | str, part_title: str) -> str:
    return (
        "<titulo_de_la_parte>\n"
        f"{part_title}\n"
        "</titulo_de_la_parte>\n\n"
        "<explicacion_de_la_parte>\n"
        f"{_serialize_explainer(explainer_content)}\n"
        "</explicacion_de_la_parte>\n\n"
        f"Genera exactamente {REVIEW_NUM_QUESTIONS} preguntas de autoevaluación sobre esta "
        "explicación, con su respuesta razonada."
    )


def _validate_review_payload(raw: Any) -> dict[str, Any]:
    """Validate the review structure; raises OpenRouterError-style errors on invalid payloads."""
    if not isinstance(raw, dict):
        raise OpenRouterError("Campo inválido en review: se esperaba un objeto JSON.")

    preguntas = raw.get("preguntas")
    if not isinstance(preguntas, list):
        raise OpenRouterError("Campo inválido en review.preguntas: se esperaba una lista.")
    if len(preguntas) != REVIEW_NUM_QUESTIONS:
        raise OpenRouterError(
            f"Campo inválido en review.preguntas: se esperaban exactamente "
            f"{REVIEW_NUM_QUESTIONS} preguntas (hay {len(preguntas)})."
        )

    validated_preguntas: list[dict[str, Any]] = []
    for index, item in enumerate(preguntas):
        if not isinstance(item, dict):
            raise OpenRouterError(f"Campo inválido en review.preguntas[{index}]: se esperaba un objeto.")

        numero = item.get("numero", index + 1)
        if not isinstance(numero, int) or isinstance(numero, bool):
            try:
                numero = int(numero)
            except (TypeError, ValueError):
                raise OpenRouterError(f"Campo inválido en review.preguntas[{index}].numero: se esperaba un entero.")

        pregunta = item.get("pregunta")
        if not isinstance(pregunta, str) or not pregunta.strip():
            raise OpenRouterError(
                f"Campo inválido en review.preguntas[{index}].pregunta: se esperaba una cadena no vacía."
            )

        respuesta = item.get("respuesta_razonada")
        if not isinstance(respuesta, str) or not respuesta.strip():
            raise OpenRouterError(
                f"Campo inválido en review.preguntas[{index}].respuesta_razonada: se esperaba una cadena no vacía."
            )

        referencia = item.get("referencia")
        if referencia is not None and not isinstance(referencia, str):
            raise OpenRouterError(
                f"Campo inválido en review.preguntas[{index}].referencia: se esperaba una cadena."
            )

        validated_preguntas.append(
            {
                "numero": numero,
                "pregunta": pregunta.strip(),
                "respuesta_razonada": respuesta.strip(),
                "referencia": referencia.strip() if isinstance(referencia, str) else "",
            }
        )

    nota = raw.get("nota")
    if nota is not None and not isinstance(nota, str):
        raise OpenRouterError("Campo inválido en review.nota: se esperaba una cadena.")

    return {
        "preguntas": validated_preguntas,
        "nota": nota.strip() if isinstance(nota, str) else "",
    }


def _is_retryable_payload_validation_error(exc: Exception) -> bool:
    return str(exc).startswith("Campo inválido en ")


def _call_openrouter_with_validation_retries(
    *,
    call_operation: Callable[[], tuple[Any, Any]],
    validate_payload: Callable[[Any], dict[str, Any]],
    operation_label: str,
) -> tuple[dict[str, Any], Any]:
    """Call OpenRouter and correct invalid structured payloads with retries (pattern run_resources_or)."""
    total_attempts = OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES + 1
    for attempt in range(1, total_attempts + 1):
        raw, usage = call_operation()
        try:
            return validate_payload(raw), usage
        except Exception as exc:
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


def _call_deepseek_with_validation_retries(
    *,
    call_operation: Callable[[], tuple[Any, Any]],
    validate_payload: Callable[[Any], dict[str, Any]],
    operation_label: str,
) -> tuple[dict[str, Any], Any]:
    """Call DeepSeek and correct invalid structured payloads with retries (pattern explainer_deepseek)."""
    total_attempts = OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES + 1
    for attempt in range(1, total_attempts + 1):
        raw, usage = call_operation()
        try:
            return validate_payload(raw), usage
        except Exception as exc:
            if attempt >= total_attempts or not _is_retryable_payload_validation_error(exc):
                raise DeepSeekError(str(exc)) from exc
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
    raise DeepSeekError(
        f"{operation_label} agotó reintentos por payload inválido sin devolver JSON válido."
    )


async def _call_codex_with_validation_retries(
    *,
    call_operation: Callable[[], Awaitable[tuple[Any, Any]]],
    validate_payload: Callable[[Any], dict[str, Any]],
    operation_label: str,
) -> tuple[dict[str, Any], Any]:
    """Call Codex and correct invalid structured payloads with retries.

    Espejo async de `_call_deepseek_with_validation_retries`: `call_operation`
    queda FUERA del try, así los errores tipados del cliente
    (`CodexRateLimitError`, etc.) se propagan sin ser envueltos. Los fallos de
    validación retryables lanzan `CodexError` al agotar los reintentos.
    """
    total_attempts = OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES + 1
    for attempt in range(1, total_attempts + 1):
        raw, usage = await call_operation()
        try:
            return validate_payload(raw), usage
        except Exception as exc:
            if attempt >= total_attempts or not _is_retryable_payload_validation_error(exc):
                raise CodexError(str(exc)) from exc
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
    raise CodexError(
        f"{operation_label} agotó reintentos por payload inválido sin devolver JSON válido."
    )


def _valid_review_sample() -> dict[str, Any]:
    """A structurally valid review (used by tests)."""
    return {
        "preguntas": [
            {
                "numero": i,
                "pregunta": f"Pregunta {i}",
                "respuesta_razonada": f"Respuesta razonada {i}.",
                "referencia": "Sección 2.3" if i == 1 else "",
            }
            for i in range(1, REVIEW_NUM_QUESTIONS + 1)
        ],
        "nota": "Repasa las secciones centrales.",
    }


@gemini_retry(max_retries=5)
def run_review(
    api_key: str,
    explainer_content: dict | str,
    part_title: str,
    target_language: str = "es-ES",
    model: str = MODEL_AGENTS,
) -> tuple[dict[str, Any], Any]:
    """Run the Review agent via Gemini. Returns (review_dict, usage_metadata)."""
    start_time = time.time()
    logger.info(
        "Iniciando agente review (gemini)",
        extra={
            "part_title": part_title[:80],
            "explainer_chars": len(_serialize_explainer(explainer_content)),
            "target_language": target_language,
            "model": model,
        },
    )

    client = genai.Client(api_key=api_key)
    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=_build_user_message(explainer_content, part_title))],
        ),
    ]
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=REVIEW_RESPONSE_SCHEMA,
        system_instruction=[types.Part.from_text(text=build_review_system_instruction(target_language))],
    )

    response = generate_content_with_retry(
        client=client,
        model=model,
        contents=contents,
        config=config,
        max_retries=5,
        operation_context={"agent": "review"},
    )

    try:
        result = json.loads(response.text)
    except json.JSONDecodeError as e:
        logger.error(
            f"Error al parsear JSON de respuesta del agente review: {str(e)}",
            extra={
                "error_type": "json_decode_error",
                "response_preview": response.text[:200] if response.text else "empty",
            },
        )
        raise

    review = _validate_review_payload(result)
    logger.info(
        "Review Gemini completado: %d preguntas en %dms",
        len(review["preguntas"]),
        int((time.time() - start_time) * 1000),
        extra={
            "num_preguntas": len(review["preguntas"]),
            "total_duration_ms": int((time.time() - start_time) * 1000),
            "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0) if response.usage_metadata else 0,
            "candidates_tokens": getattr(response.usage_metadata, "candidates_token_count", 0) if response.usage_metadata else 0,
            "total_tokens": getattr(response.usage_metadata, "total_token_count", 0) if response.usage_metadata else 0,
        },
    )
    return review, response.usage_metadata


def run_review_or(
    api_key: str,
    explainer_content: dict | str,
    part_title: str,
    target_language: str = "es-ES",
    model: str = OPENROUTER_MODEL_AUXILIARY,
) -> tuple[dict[str, Any], Any]:
    """Run the Review agent via OpenRouter. Returns (review_dict, usage)."""
    start_time = time.time()
    logger.info(
        "Iniciando agente review OpenRouter",
        extra={
            "part_title": part_title[:80],
            "explainer_chars": len(_serialize_explainer(explainer_content)),
            "target_language": target_language,
            "model": model,
        },
    )

    response_format = _resolve_openrouter_response_format(
        model=model,
        json_schema=OPENROUTER_REVIEW_JSON_SCHEMA,
    )

    review, usage = _call_openrouter_with_validation_retries(
        call_operation=lambda: call_openrouter_chat(
            messages=[
                {
                    "role": "user",
                    "content": _build_user_message(explainer_content, part_title),
                }
            ],
            model=model,
            system_prompt=build_review_system_instruction(target_language),
            api_key=api_key,
            response_format=response_format,
            enable_response_healing=True,
            reasoning=max_reasoning_preferences(model),
            provider=deepseek_provider_preferences(),
            json_retry_instruction=REVIEW_JSON_RETRY_INSTRUCTION,
        ),
        validate_payload=_validate_review_payload,
        operation_label="Review OpenRouter",
    )

    logger.info(
        "Review OpenRouter completado: %d preguntas en %dms",
        len(review["preguntas"]),
        int((time.time() - start_time) * 1000),
        extra={
            "num_preguntas": len(review["preguntas"]),
            "total_duration_ms": int((time.time() - start_time) * 1000),
            "prompt_tokens": getattr(usage, "prompt_token_count", 0),
            "completion_tokens": getattr(usage, "candidates_token_count", 0),
            "model": model,
        },
    )
    return review, usage


def run_review_ds(
    api_key: str,
    explainer_content: dict | str,
    part_title: str,
    target_language: str = "es-ES",
    model: str = DEEPSEEK_MODEL_AUXILIARY,
) -> tuple[dict[str, Any], DeepSeekUsage]:
    """Run the Review agent via direct DeepSeek. Returns (review_dict, usage)."""
    start_time = time.time()
    logger.info(
        "Iniciando agente review DeepSeek",
        extra={
            "part_title": part_title[:80],
            "explainer_chars": len(_serialize_explainer(explainer_content)),
            "target_language": target_language,
            "model": model,
        },
    )

    review, usage = _call_deepseek_with_validation_retries(
        call_operation=lambda: call_deepseek_chat(
            messages=[
                {
                    "role": "user",
                    "content": _build_user_message(explainer_content, part_title),
                }
            ],
            model=model,
            system_prompt=build_review_system_instruction(target_language),
            api_key=api_key,
            response_format="json_object",
            reasoning_effort=max_reasoning_effort(),
            json_retry_instruction=REVIEW_JSON_RETRY_INSTRUCTION,
        ),
        validate_payload=_validate_review_payload,
        operation_label="Review DeepSeek",
    )

    logger.info(
        "Review DeepSeek completado: %d preguntas en %dms",
        len(review["preguntas"]),
        int((time.time() - start_time) * 1000),
        extra={
            "num_preguntas": len(review["preguntas"]),
            "total_duration_ms": int((time.time() - start_time) * 1000),
            "prompt_tokens": getattr(usage, "prompt_token_count", 0),
            "completion_tokens": getattr(usage, "candidates_token_count", 0),
            "model": model,
        },
    )
    return review, usage


async def run_review_codex(
    user_id: str,
    explainer_content: dict | str,
    part_title: str,
    target_language: str = "es-ES",
    model: str = CODEX_MODEL,
    *,
    effort: str | None = None,
) -> tuple[dict[str, Any], CodexUsage]:
    """Run the Review agent via Codex (app-server). Returns (review_dict, usage).

    Corrutina async: se espera directo (nunca en `asyncio.to_thread`). Espejo
    posicional de `run_review_ds` con `user_id` en la posición de `api_key`,
    reusando `_validate_review_payload` y los reintentos de review.
    """
    start_time = time.time()
    logger.info(
        "Iniciando agente review Codex",
        extra={
            "user_id_prefix": user_id[:8],
            "part_title": part_title[:80],
            "explainer_chars": len(_serialize_explainer(explainer_content)),
            "target_language": target_language,
            "model": model,
        },
    )

    review, usage = await _call_codex_with_validation_retries(
        call_operation=lambda: call_codex_chat(
            user_id=user_id,
            messages=[
                {
                    "role": "user",
                    "content": _build_user_message(explainer_content, part_title),
                }
            ],
            model=model,
            system_prompt=build_review_system_instruction(target_language),
            response_format="json_object",
            effort=effort,
        ),
        validate_payload=_validate_review_payload,
        operation_label="Review Codex",
    )

    logger.info(
        "Review Codex completado: %d preguntas en %dms",
        len(review["preguntas"]),
        int((time.time() - start_time) * 1000),
        extra={
            "num_preguntas": len(review["preguntas"]),
            "total_duration_ms": int((time.time() - start_time) * 1000),
            "prompt_tokens": getattr(usage, "prompt_token_count", 0),
            "completion_tokens": getattr(usage, "candidates_token_count", 0),
            "model": model,
        },
    )
    return review, usage
