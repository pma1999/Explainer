"""Formatter agent: post-processes explainer content with a fast Gemini model.

After the explainer agent generates its structured JSON output, this module
sends every text field (introduccion, conclusion, each subsection's
explicacion_detallada, each section's explicacion_introductoria, and each
conexion's descripcion_conexion) to gemini-3.1-flash-lite-preview in a single
parallel batch for markdown formatting.

KEY RULES:
- Content is NEVER modified — only markdown formatting is added.
- Every call is fail-safe: if the model fails for any reason, the original
  text is preserved unchanged.
- All text fields within a single explainer dict are formatted in ONE
  asyncio.gather call, maximising throughput.
"""

from __future__ import annotations

import asyncio
import copy
import time
from typing import Any

from google import genai
from google.genai import types

from backend.logging_config import get_logger
from backend.pricing import calculate_cost
from backend.agents.language_policy import FORMATTER_CASTELLANO_RULE

logger = get_logger("backend.agents.formatter")

# Fast, low-latency model used exclusively for the formatting pass.
FORMATTER_MODEL = "gemini-3.1-flash-lite-preview"

FORMATTER_SYSTEM_PROMPT = (
"""\
Eres un experto en formateo de textos académicos y técnicos en Markdown.

Tu única tarea es aplicar formato Markdown al texto que recibes para hacerlo \
más legible y atractivo visualmente, sin alterar su contenido en absoluto.

REGLAS ABSOLUTAS E INNEGOCIABLES:
1. CONSERVA TODO EL CONTENIDO PALABRA POR PALABRA. No elimines, resumeas, \
parafrasees, condenses ni omitas nada. El texto resultante debe contener \
exactamente la misma información que el original.
2. NO añadas información nueva ni cambies el significado de ninguna frase.
3. Aplica formato Markdown únicamente donde mejore la legibilidad:
   - **negrita** para términos técnicos clave, conceptos centrales o énfasis importante.
   - *cursiva* para términos en otros idiomas, títulos de obras o énfasis secundario.
   - Listas con viñetas  (- elemento)  cuando el texto enumere elementos sin orden.
   - Listas numeradas  (1. paso)  cuando el texto describa pasos, secuencias o rankings.
   - `código`  para sintaxis técnica específica, nombres de funciones, variables, etc.
   - Párrafos separados por línea en blanco para ideas distintas.
   - > cita  cuando el texto cite textualmente a otro autor o fuente.
4. Devuelve ÚNICAMENTE el texto formateado en Markdown. No añadas comentarios, \
explicaciones, encabezados extra ni ningún texto que no estuviera en el original.
"""
+ FORMATTER_CASTELLANO_RULE
)


async def _format_text(
    client: genai.Client,
    text: str,
    context: str = "",
) -> tuple[str, Any]:
    """Format a single text block as Markdown using the fast model.

    Returns ``(formatted_text, usage_metadata)``.  On any exception or empty
    response the original *text* is returned with ``None`` as usage_metadata
    (fail-safe guarantee).
    """
    if not text or not text.strip():
        return text, None

    try:
        user_message = text
        if context:
            user_message = f"[Contexto del apartado: {context}]\n\n{text}"

        response = await client.aio.models.generate_content(
            model=FORMATTER_MODEL,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=FORMATTER_SYSTEM_PROMPT,
                temperature=0.1,
            ),
        )

        if response and response.text and response.text.strip():
            usage_meta = getattr(response, "usage_metadata", None)
            return response.text.strip(), usage_meta

        logger.warning(
            "Formatter returned empty response, keeping original text",
            extra={"context_preview": context[:80]},
        )
        return text, None

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"Formatter API call failed, keeping original text: {exc}",
            extra={"context_preview": context[:80], "error": str(exc)[:200]},
        )
        return text, None


async def format_explainer_content(
    api_key: str,
    explainer_data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Format all prose text fields in an explainer result dict in parallel.

    The explainer schema is:
        introduccion         (str)
        desarrollo[]
            titulo_seccion              (str — NOT formatted, used as heading)
            explicacion_introductoria   (str — formatted)
            subsecciones[]
                titulo_subseccion       (str — NOT formatted, used as heading)
                explicacion_detallada   (str — formatted)
        conclusion           (str)
        conexiones_contextuales[]
            seccion_temario_relacionada (str — NOT formatted, used as heading)
            descripcion_conexion        (str — formatted)

    Returns ``(formatted_dict, usage_summary)`` where *formatted_dict* is a
    deep-copy of *explainer_data* with all prose fields replaced by their
    Markdown-formatted equivalents, and *usage_summary* is::

        {
            "input_tokens":  int,
            "output_tokens": int,
            "total_tokens":  int,
            "cost":          float,   # USD, rounded to 6 decimal places
        }

    On partial failure individual fields fall back to their originals.
    """
    start_time = time.time()

    result = copy.deepcopy(explainer_data)
    client = genai.Client(api_key=api_key)

    # Build a flat ordered list of (path_tuple, coroutine) pairs.
    # path_tuple encodes how to navigate and update *result* after gather.
    tasks: list[tuple[tuple, Any]] = []

    def _add(path: tuple, text: str, ctx: str = "") -> None:
        if text and text.strip():
            tasks.append((path, _format_text(client, text, ctx)))

    _add(("introduccion",), result.get("introduccion", ""))
    _add(("conclusion",), result.get("conclusion", ""))

    for i, sec in enumerate(result.get("desarrollo") or []):
        ctx_sec = sec.get("titulo_seccion", "")
        _add(
            ("desarrollo", i, "explicacion_introductoria"),
            sec.get("explicacion_introductoria", ""),
            ctx_sec,
        )
        for j, sub in enumerate(sec.get("subsecciones") or []):
            ctx_sub = f"{ctx_sec} · {sub.get('titulo_subseccion', '')}"
            _add(
                ("desarrollo", i, "subsecciones", j, "explicacion_detallada"),
                sub.get("explicacion_detallada", ""),
                ctx_sub,
            )

    for k, cx in enumerate(result.get("conexiones_contextuales") or []):
        _add(
            ("conexiones_contextuales", k, "descripcion_conexion"),
            cx.get("descripcion_conexion", ""),
            cx.get("seccion_temario_relacionada", ""),
        )

    _empty_usage: dict[str, Any] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost": 0.0,
    }

    if not tasks:
        return result, _empty_usage

    paths, coros = zip(*tasks)

    # Run ALL formatting requests in a single parallel batch.
    gathered = await asyncio.gather(*coros, return_exceptions=True)

    success_count = 0
    total_input = 0
    total_output = 0

    for path, value in zip(paths, gathered):
        if isinstance(value, Exception):
            logger.warning(
                f"Formatter task failed for path {path}, keeping original: {value}",
                extra={"path": str(path), "error": str(value)[:200]},
            )
            continue

        # Unpack (formatted_text, usage_metadata) returned by _format_text.
        formatted_text, usage_meta = value

        # Accumulate token counts for cost reporting.
        if usage_meta is not None:
            total_input  += getattr(usage_meta, "prompt_token_count",     0) or 0
            total_output += getattr(usage_meta, "candidates_token_count", 0) or 0

        # Navigate the path and set the leaf value.
        target: Any = result
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = formatted_text
        success_count += 1

    elapsed_ms = int((time.time() - start_time) * 1000)
    total_tasks = len(tasks)
    logger.info(
        f"Formatter completed: {success_count}/{total_tasks} fields formatted "
        f"in {elapsed_ms}ms",
        extra={
            "formatted_fields": success_count,
            "total_fields": total_tasks,
            "elapsed_ms": elapsed_ms,
        },
    )

    fmt_cost = calculate_cost(
        FORMATTER_MODEL,
        {"prompt_token_count": total_input, "candidates_token_count": total_output},
    )
    usage_summary: dict[str, Any] = {
        "input_tokens":  total_input,
        "output_tokens": total_output,
        "total_tokens":  total_input + total_output,
        "cost":          fmt_cost,
    }

    return result, usage_summary
