"""Formatter agent: post-processes explainer content with a fast Gemini model.

After the explainer agent generates its structured JSON output, this module
sends every text field (introduccion, conclusion, each subsection's
explicacion_detallada, each section's explicacion_introductoria, and each
conexion's descripcion_conexion) to MODEL_AGENTS (Flash Lite preview) in a single
parallel batch for markdown formatting. Each call uses JSON mode with a single
``markdown`` field so only the body is persisted (no metatext or duplicate titles),
and ``thinking_level="low"`` for lighter internal reasoning (lower latency/cost than ``high``).

KEY RULES:
- Content is never shortened, summarized, or substantively rewritten.
- The formatter may apply minimal surface normalization when the source contains
  accidental anglicisms, foreign-language contamination, mojibake, or malformed
  token fragments that break readability in Spanish. This cleanup must preserve
  all meaning and all factual content.
- Every call is fail-safe: if the model fails for any reason, the original
  text is preserved unchanged.
- All text fields within a single explainer dict are formatted in ONE
  asyncio.gather call, maximising throughput.
"""

from __future__ import annotations

import asyncio
import copy
import json
import time
from typing import Any

from google import genai
from google.genai import types

from backend.logging_config import get_logger
from backend.pricing import calculate_cost
from backend.gemini_model_routing import MODEL_AGENTS
from backend.agents.language_policy import FORMATTER_CASTELLANO_RULE

logger = get_logger("backend.agents.formatter")

# Fast, low-latency model used exclusively for the formatting pass.
FORMATTER_MODEL = MODEL_AGENTS

# JSON field name for the formatted Markdown body (forced via response_schema).
FORMATTER_MARKDOWN_FIELD = "markdown"

FORMATTER_RESPONSE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    required=[FORMATTER_MARKDOWN_FIELD],
    properties={
        FORMATTER_MARKDOWN_FIELD: types.Schema(
            type=types.Type.STRING,
            description=(
                "Cuerpo del texto ya formateado en Markdown válido. Solo el contenido que debe leer "
                "el usuario: sin preámbulos, sin listas de 'plan de formato', sin metacomentarios ni "
                "explicación del proceso. No repitas como título o encabezado el nombre de la "
                "sección o subsección del contexto (la interfaz ya lo muestra aparte). "
                "Usa ## o ### solo cuando el texto original ya implique subtítulos internos claros."
            ),
        ),
    },
)


def _extract_formatted_markdown(raw: str) -> str | None:
    """Parse formatter JSON output; return markdown string or None if invalid or empty."""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    md = obj.get(FORMATTER_MARKDOWN_FIELD)
    if not isinstance(md, str):
        return None
    stripped = md.strip()
    return stripped if stripped else None


def _usage_int_field(meta: Any, field: str) -> int:
    """Return a non-negative int from SDK usage_metadata, or 0 if missing / mock / wrong type."""
    v = getattr(meta, field, None)
    if isinstance(v, int) and not isinstance(v, bool):
        return max(0, v)
    return 0


FORMATTER_SYSTEM_PROMPT = (
"""
<system_instruction>
  <role>
  Eres un tipógrafo académico digital especializado en Markdown. Tu expertise combina conocimiento profundo de convenciones tipográficas académicas con dominio técnico de la sintaxis Markdown.

  Principios que guían tu trabajo:
  - La forma sirve al contenido, nunca lo reemplaza.
  - Cada decisión de formato tiene un propósito comunicativo claro.
  - La legibilidad es el resultado de decisiones tipográficas coherentes, no de decoración excesiva.
  </role>

  <objectives>
  Transformar texto plano académico o técnico en su versión Markdown óptimamente legible, preservando con fidelidad absoluta cada dato, matiz y contenido sustantivo del original.

  El resultado debe sentirse como el mismo texto "bien maquetado" — más fácil de escanear, navegar y comprender visualmente — sin que el lector perciba que se añadió o perdió información alguna.
  </objectives>

  <quality_criteria>
  Una respuesta excelente cumple simultáneamente:
  - **Fidelidad sustantiva total:** no hay omisiones, resúmenes, paráfrasis de contenido ni adiciones informativas. Solo se permiten cambios de superficie estrictamente necesarios para maquetación y limpieza lingüística.
  - **Coherencia tipográfica:** las mismas categorías de información reciben el mismo tratamiento visual a lo largo de todo el texto.
  - **Proporcionalidad:** el formato aplicado es proporcional a la extensión y complejidad del texto — textos breves reciben formato ligero; textos extensos pueden beneficiarse de más estructura.
  - **Limpieza:** el cuerpo formateado no incluye metacomentarios, listas sobre cómo vas a formatear, encabezados que dupliquen el título del apartado, ni explicaciones del proceso.
  - **Legibilidad lingüística:** si el texto contiene anglicismos accidentales, palabras sueltas en otro idioma, mojibake, transliteraciones rotas o fragmentos claramente corruptos que dificultan la lectura en español, se corrigen al español natural sin acortar ni alterar el significado.
  </quality_criteria>

  <context_rule>
  Si el mensaje de usuario comienza con una línea entre corchetes tipo "[Contexto del apartado: …]", ese contexto es solo orientación (tono, tema). No lo copies, no lo resumas y no lo uses como título: la aplicación ya muestra el título de sección/subsección por separado.
  </context_rule>

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
  - Si detectas anglicismos accidentales o contaminación lingüística no intencional dentro de una frase en español, sustitúyelos por la formulación española equivalente más natural, manteniendo intacto el resto del contenido.
  - No "mejores" el estilo ni simplifiques el razonamiento: limpia solo lo necesario para que el texto quede plenamente entendible.
  - Conserva sin traducir nombres propios, citas, títulos de obras y términos realmente intencionales en otro idioma cuando su traducción alteraría la referencia.
  </methodological_principles>

  <output_format>
  Tu respuesta debe cumplir el esquema JSON indicado por la API: un único campo con el texto formateado en Markdown válido. Sin preámbulos fuera de ese campo, sin comentarios finales, sin bloques de explicación.
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
Formatea en Markdown el texto proporcionado (el cuerpo tras el contexto, si existe). Preserva todo el contenido sustantivo del original. Además, limpia anglicismos accidentales y artefactos lingüísticos que rompan la lectura en español, sin acortar nada ni perder información. Aplica formato tipográfico proporcionado a la naturaleza y complejidad del texto. Rellena el campo JSON únicamente con ese cuerpo formateado.
</task>

<thinking_protocol>
Antes del JSON final, razona con rigor (el modelo usa razonamiento interno; no vuelques ese razonamiento en la salida visible):
- ¿Qué tipo de texto es (académico, técnico, mixto)? ¿Qué nivel de formato necesita?
- ¿Hay enumeraciones implícitas, citas, o terminología que requieran tratamiento especial?
- ¿Dónde están los límites naturales entre ideas para la separación de párrafos?

El valor del campo JSON ``markdown`` debe ser solo el cuerpo formateado para el lector: sin prefacios de planificación, sin bloques ``<thinking>``, sin listas que describan cómo vas a formatear ni metacomentarios.
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
                thinking_config=types.ThinkingConfig(thinking_level="low"),
                response_mime_type="application/json",
                response_schema=FORMATTER_RESPONSE_SCHEMA,
            ),
        )

        if response and response.text and response.text.strip():
            usage_meta = getattr(response, "usage_metadata", None)
            parsed = _extract_formatted_markdown(response.text.strip())
            if parsed is not None:
                return parsed, usage_meta
            logger.warning(
                "Formatter JSON parse failed or empty markdown field, keeping original text",
                extra={
                    "context_preview": context[:80],
                    "response_preview": response.text[:200] if response.text else "",
                },
            )
            return text, usage_meta

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
        "thoughts_tokens": 0,
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
    total_candidates = 0
    total_thoughts = 0

    for path, value in zip(paths, gathered):
        if isinstance(value, Exception):
            logger.warning(
                f"Formatter task failed for path {path}, keeping original: {value}",
                extra={"path": str(path), "error": str(value)[:200]},
            )
            continue

        # Unpack (formatted_text, usage_metadata) returned by _format_text.
        formatted_text, usage_meta = value

        # Accumulate token counts for cost reporting (thinking billed as output per Google pricing).
        if usage_meta is not None:
            total_input += _usage_int_field(usage_meta, "prompt_token_count")
            total_candidates += _usage_int_field(usage_meta, "candidates_token_count")
            total_thoughts += _usage_int_field(usage_meta, "thoughts_token_count")

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
        {
            "prompt_token_count": total_input,
            "candidates_token_count": total_candidates,
            "thoughts_token_count": total_thoughts,
        },
    )
    # output_tokens = all generation billed at output rate (candidates + internal thinking).
    billed_output = total_candidates + total_thoughts
    usage_summary: dict[str, Any] = {
        "input_tokens": total_input,
        "output_tokens": billed_output,
        "thoughts_tokens": total_thoughts,
        "total_tokens": total_input + billed_output,
        "cost": fmt_cost,
    }

    return result, usage_summary
