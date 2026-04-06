"""Agente Explainer — implementación OpenRouter (minimax/minimax-m2.7)."""
from __future__ import annotations

import base64
import json
import time
from typing import Any

from backend.logging_config import get_logger
from backend.openrouter_client import OpenRouterUsage, call_openrouter_chat

# Reutilizar prompts del explainer Gemini — no duplicar
from backend.agents.explainer import SYSTEM_INSTRUCTION, SUBPART_SYSTEM_INSTRUCTION

logger = get_logger("backend.agents.explainer_openrouter")

OPENROUTER_MODEL_AGENTS = "minimax/minimax-m2.7"

# PDF parsing plugin (cloudflare-ai es gratis y funciona con cualquier modelo)
_PDF_PLUGIN = [{"id": "file-parser", "pdf": {"engine": "cloudflare-ai"}}]

# ---------------------------------------------------------------------------
# Schemas en formato JSON Schema (OpenAI/OpenRouter)
# ---------------------------------------------------------------------------

_SUBSECCION_SCHEMA = {
    "type": "object",
    "required": ["titulo_subseccion", "explicacion_detallada"],
    "additionalProperties": False,
    "properties": {
        "titulo_subseccion": {"type": "string"},
        "explicacion_detallada": {"type": "string"},
    },
}

_SECCION_SCHEMA = {
    "type": "object",
    "required": ["titulo_seccion", "explicacion_introductoria", "subsecciones"],
    "additionalProperties": False,
    "properties": {
        "titulo_seccion": {"type": "string"},
        "explicacion_introductoria": {"type": "string"},
        "subsecciones": {"type": "array", "items": _SUBSECCION_SCHEMA},
    },
}

_CONEXION_SCHEMA = {
    "type": "object",
    "required": ["seccion_temario_relacionada", "descripcion_conexion"],
    "additionalProperties": False,
    "properties": {
        "seccion_temario_relacionada": {"type": "string"},
        "descripcion_conexion": {"type": "string"},
    },
}

RESPONSE_SCHEMA_DICT = {
    "type": "object",
    "required": ["introduccion", "desarrollo", "conclusion", "conexiones_contextuales"],
    "additionalProperties": False,
    "properties": {
        "introduccion": {"type": "string"},
        "desarrollo": {"type": "array", "items": _SECCION_SCHEMA},
        "conclusion": {"type": "string"},
        "conexiones_contextuales": {
            "type": "array",
            "items": _CONEXION_SCHEMA,
        },
    },
}

SUBPART_RESPONSE_SCHEMA_DICT = {
    "type": "object",
    "required": ["desarrollo"],
    "additionalProperties": False,
    "properties": {
        "desarrollo": {"type": "array", "items": _SECCION_SCHEMA},
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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

    content, plugins = _build_content(source_path, identificacion, mime_type)
    messages = [{"role": "user", "content": content}]

    raw, usage = call_openrouter_chat(
        messages=messages,
        model=model,
        response_schema=RESPONSE_SCHEMA_DICT,
        system_prompt=SYSTEM_INSTRUCTION,
        api_key=api_key,
        plugins=plugins,
    )

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(
            f"[OpenRouter Explainer] Error parseando JSON: {e}",
            extra={"response_preview": raw[:200]},
        )
        raise

    total_ms = int((time.time() - start) * 1000)
    logger.info(
        f"Explainer (openrouter) completado: {len(result.get('desarrollo', []))} secciones en {total_ms}ms",
        extra={
            "num_secciones": len(result.get("desarrollo", [])),
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
) -> tuple[dict[str, Any], OpenRouterUsage]:
    """Explainer de subparte vía OpenRouter — retorna solo desarrollo."""
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

    content, plugins = _build_content(source_path, identificacion, mime_type)
    messages = [{"role": "user", "content": content}]

    raw, usage = call_openrouter_chat(
        messages=messages,
        model=model,
        response_schema=SUBPART_RESPONSE_SCHEMA_DICT,
        system_prompt=SUBPART_SYSTEM_INSTRUCTION,
        api_key=api_key,
        plugins=plugins,
    )

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(
            f"[OpenRouter Subpart Explainer] Error parseando JSON: {e}",
            extra={"response_preview": raw[:200]},
        )
        raise

    total_ms = int((time.time() - start) * 1000)
    logger.info(
        f"Subpart explainer (openrouter) completado: {len(result.get('desarrollo', []))} secciones en {total_ms}ms",
        extra={
            "num_secciones": len(result.get("desarrollo", [])),
            "total_duration_ms": total_ms,
            "prompt_tokens": usage.prompt_token_count,
            "completion_tokens": usage.candidates_token_count,
        },
    )

    return result, usage
