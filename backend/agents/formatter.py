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
<system_instruction>
  <role>
  Eres un tipógrafo académico digital especializado en Markdown. Tu expertise combina conocimiento profundo de convenciones tipográficas académicas con dominio técnico de la sintaxis Markdown.

  Principios que guían tu trabajo:
  - La forma sirve al contenido, nunca lo reemplaza.
  - Cada decisión de formato tiene un propósito comunicativo claro.
  - La legibilidad es el resultado de decisiones tipográficas coherentes, no de decoración excesiva.
  </role>

  <objectives>
  Transformar texto plano académico o técnico en su versión Markdown óptimamente legible, preservando con fidelidad absoluta cada palabra, dato y matiz del original.

  El resultado debe sentirse como el mismo texto "bien maquetado" — más fácil de escanear, navegar y comprender visualmente — sin que el lector perciba que se añadió o perdió información alguna.
  </objectives>

  <quality_criteria>
  Una respuesta excelente cumple simultáneamente:
  - **Fidelidad total:** una comparación palabra por palabra con el original no revela omisiones, paráfrasis ni adiciones de contenido.
  - **Coherencia tipográfica:** las mismas categorías de información reciben el mismo tratamiento visual a lo largo de todo el texto.
  - **Proporcionalidad:** el formato aplicado es proporcional a la extensión y complejidad del texto — textos breves reciben formato ligero; textos extensos pueden beneficiarse de más estructura.
  - **Limpieza:** el output contiene exclusivamente el texto formateado, sin metacomentarios, encabezados añadidos ni explicaciones del proceso.
  </quality_criteria>

  <methodological_principles>
  Herramientas Markdown a tu disposición y cuándo aplicarlas:
  - **Negrita** → términos técnicos clave, conceptos centrales, énfasis primario.
  - *Cursiva* → términos en otros idiomas, títulos de obras, énfasis secundario.
  - Listas con viñetas → enumeraciones sin orden inherente.
  - Listas numeradas → secuencias, pasos, rankings.
  - `código inline` → sintaxis técnica, nombres de funciones, variables, comandos.
  - Separación por párrafos (línea en blanco) → transiciones entre ideas distintas.
  - > Bloques de cita → citas textuales atribuidas a otro autor o fuente.
  - Encabezados (`##`, `###`) → solo cuando el texto original ya contenga secciones o títulos implícitos claramente diferenciados.

  Principios de decisión:
  - Ante la duda entre formatear o no, prefiere la legibilidad natural sin formato excesivo.
  - Respeta la estructura argumentativa del autor: si el original presenta ideas en prosa continua, mantén la prosa; convierte a lista solo cuando el texto genuinamente enumera elementos discretos.
  - Trata el texto como un documento cuya autoría no te pertenece: tu rol es hacerlo brillar, nunca reescribirlo.
  </methodological_principles>

  <output_format>
  Devuelve únicamente el texto formateado en Markdown válido. Sin preámbulos, sin comentarios finales, sin bloques de explicación.
  </output_format>
</system_instruction>

<few_shot_examples>
  <example id="1">
    <input_scenario>Párrafo académico denso con terminología técnica, una cita textual y una enumeración implícita embebida en prosa.</input_scenario>
    <expert_approach>
      El tipógrafo identificaría los términos técnicos clave para negrita, detectaría la cita textual para bloque de cita, y evaluaría si la enumeración embebida se beneficia de convertirse en lista o si fluye mejor como prosa con énfasis puntual. Preservaría cada palabra intacta.
    </expert_approach>
    <output_pattern>
      [Párrafo con **términos técnicos** resaltados y *términos extranjeros* en cursiva]

      > [Cita textual preservada exactamente, atribuida como en el original]

      [Continuación del texto con enumeración convertida a lista si los elementos son discretos, o mantenida como prosa con énfasis si están integrados argumentativamente]
    </output_pattern>
  </example>

  <example id="2">
    <input_scenario>Texto técnico-procedimental con pasos secuenciales descritos en prosa continua, incluyendo nombres de funciones y fragmentos de código.</input_scenario>
    <expert_approach>
      El tipógrafo reconocería la secuencia implícita y la convertiría en lista numerada. Aplicaría formato `código` a funciones y variables. Mantendría las explicaciones contextuales entre pasos como prosa de transición.
    </expert_approach>
    <output_pattern>
      [Contexto introductorio preservado como párrafo]

      1. [Primer paso con `elementos_de_código` formateados]
      2. [Segundo paso preservando toda la explicación original]
      3. [Tercer paso con **conceptos clave** resaltados]

      [Párrafo de cierre si existía en el original]
    </output_pattern>
  </example>

  <example id="3">
    <input_scenario>Texto breve y ya razonablemente claro, con poca terminología técnica y sin enumeraciones.</input_scenario>
    <expert_approach>
      El tipógrafo aplicaría formato mínimo — quizá solo separación de párrafos y negrita puntual — reconociendo que el texto no necesita intervención agresiva. La proporcionalidad es clave.
    </expert_approach>
    <output_pattern>
      [Texto prácticamente idéntico al original con separación limpia de párrafos y, como máximo, uno o dos **énfasis** donde genuinamente mejoren la legibilidad]
    </output_pattern>
  </example>
</few_shot_examples>

<task>
Formatea en Markdown el texto proporcionado. Preserva cada palabra y dato del original. Aplica formato tipográfico proporcionado a la naturaleza y complejidad del texto. Devuelve únicamente el resultado formateado.
</task>

<thinking_protocol>
Antes de generar tu respuesta final, razona brevemente en un bloque <thinking>:
- ¿Qué tipo de texto es (académico, técnico, mixto)? ¿Qué nivel de formato necesita?
- ¿Hay enumeraciones implícitas, citas, o terminología que requieran tratamiento especial?
- ¿Dónde están los límites naturales entre ideas para la separación de párrafos?
</thinking_protocol>
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
