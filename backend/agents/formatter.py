"""Formatter agent: post-processes explainer content with a fast model.

After the explainer agent generates its structured JSON output, this module
sends every text field (introduccion, conclusion, each subsection's
explicacion_detallada, each section's explicacion_introductoria, and each
conexion's descripcion_conexion) in a single parallel batch for markdown formatting.

- Gemini flow: MODEL_AGENTS (Flash Lite) via ``format_explainer_content``.
- OpenRouter flow: ``deepseek/deepseek-v4-flash`` via ``format_explainer_content_or``.

Each call uses JSON mode with a single ``markdown`` field so only the body is
persisted (no metatext or duplicate titles).

KEY RULES:
- Content is never shortened, summarized, or substantively rewritten.
- The formatter may apply minimal surface normalization when the source contains
  accidental anglicisms, foreign-language contamination, mojibake, or malformed
  token fragments that break readability in the selected target language. This cleanup must preserve
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
import math
import time
from typing import Any

from google import genai
from google.genai import types

from backend.logging_config import get_logger
from backend.deepseek_client import DeepSeekError, call_deepseek_chat
from backend.deepseek_model_routing import DEEPSEEK_MODEL_AUXILIARY, max_reasoning_effort
from backend.codex_client import CodexError, call_codex_chat
from backend.codex_model_routing import CODEX_MODEL
from backend.openrouter_client import OpenRouterError, call_openrouter_chat
from backend.openrouter_model_routing import (
    OPENROUTER_MODEL_AUXILIARY,
    deepseek_provider_preferences,
    max_reasoning_preferences,
)
from backend.pricing import calculate_cost
from backend.gemini_model_routing import MODEL_AGENTS
from backend.agents.language_policy import FORMATTER_CASTELLANO_RULE, build_formatter_language_rule

logger = get_logger("backend.agents.formatter")

# Fast, low-latency models used for the formatting pass.
FORMATTER_MODEL = MODEL_AGENTS
FORMATTER_OPENROUTER_MODEL = OPENROUTER_MODEL_AUXILIARY
FORMATTER_DEEPSEEK_MODEL = DEEPSEEK_MODEL_AUXILIARY

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


def _extract_formatted_markdown(raw: str | dict[str, Any]) -> str | None:
    """Parse formatter JSON output; return markdown string or None if invalid or empty."""
    if isinstance(raw, dict):
        obj = raw
    else:
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


OPENROUTER_JSON_RETRY_INSTRUCTION = """El objeto JSON esperado tiene exactamente una clave raíz:
{
  "markdown": "string"
}
`markdown` debe contener solo el cuerpo formateado en Markdown válido para el lector.
La raíz debe ser un objeto JSON, nunca un array ni texto fuera del JSON."""


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
  - **Legibilidad lingüística:** si el texto contiene palabras accidentales en otro idioma, mojibake, transliteraciones rotas o fragmentos claramente corruptos que dificultan la lectura en el idioma objetivo, se corrigen de forma natural en ese mismo idioma objetivo sin acortar ni alterar el significado.
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

  <openrouter_json_contract>
  Devuelve exclusivamente un objeto JSON raíz con esta estructura exacta:
  {
    "markdown": "cuerpo formateado en Markdown válido"
  }
  No devuelvas un array raíz ni texto fuera del JSON.
  </openrouter_json_contract>
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
Formatea en Markdown el texto proporcionado (el cuerpo tras el contexto, si existe). Preserva todo el contenido sustantivo del original. Además, limpia artefactos lingüísticos accidentales que rompan la lectura en el idioma objetivo, sin acortar nada, sin traducir a otro idioma ni perder información. Aplica formato tipográfico proporcionado a la naturaleza y complejidad del texto. Rellena el campo JSON únicamente con ese cuerpo formateado.
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


def build_formatter_system_prompt(target_language: str = "es-ES") -> str:
    """Return formatter prompt for the selected target language."""

    return FORMATTER_SYSTEM_PROMPT.replace(
        FORMATTER_CASTELLANO_RULE,
        build_formatter_language_rule(target_language),
    )


async def _format_text(
    client: genai.Client,
    text: str,
    context: str = "",
    target_language: str = "es-ES",
) -> tuple[str, Any]:
    """Format a single text block as Markdown using the fast model.

    Returns ``(formatted_text, usage_metadata)``.  On any exception or empty
    response the original *text* is returned with ``None`` as usage_metadata
    (fail-safe guarantee).
    """
    if not text or not text.strip():
        return text, None

    try:
        user_message = _build_formatter_user_message(text, context)

        response = await client.aio.models.generate_content(
            model=FORMATTER_MODEL,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=build_formatter_system_prompt(target_language),
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


def _build_formatter_user_message(text: str, context: str = "") -> str:
    if context:
        return f"[Contexto del apartado: {context}]\n\n{text}"
    return text


def _collect_formatter_field_tasks(
    result: dict[str, Any],
) -> list[tuple[tuple[Any, ...], str, str]]:
    """Return (path, text, context) tuples for every prose field to format."""
    tasks: list[tuple[tuple[Any, ...], str, str]] = []

    def _add(path: tuple[Any, ...], text: str, ctx: str = "") -> None:
        if text and text.strip():
            tasks.append((path, text, ctx))

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

    return tasks


def _openrouter_field_cost(usage_meta: Any) -> float | None:
    """Return per-call USD cost when OpenRouter reports ``cost_usd``."""
    raw_cost = getattr(usage_meta, "cost_usd", None)
    if isinstance(raw_cost, (int, float)) and math.isfinite(raw_cost) and raw_cost >= 0:
        return round(float(raw_cost), 6)
    return None


def _empty_formatter_usage() -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "thoughts_tokens": 0,
        "total_tokens": 0,
        "cost": 0.0,
    }


def _build_formatter_usage_summary(
    *,
    model: str,
    usages: list[Any | None],
    total_input: int,
    total_candidates: int,
    total_thoughts: int,
) -> dict[str, Any]:
    billed_output = total_candidates + total_thoughts
    per_field_costs: list[float] = []
    sum_openrouter_costs = True
    for usage in usages:
        if usage is None:
            per_field_costs.append(0.0)
            continue
        field_cost = _openrouter_field_cost(usage)
        if field_cost is None:
            sum_openrouter_costs = False
            break
        per_field_costs.append(field_cost)

    if sum_openrouter_costs and per_field_costs:
        fmt_cost = round(sum(per_field_costs), 6)
    else:
        fmt_cost = calculate_cost(
            model,
            {
                "prompt_token_count": total_input,
                "candidates_token_count": total_candidates,
                "thoughts_token_count": total_thoughts,
            },
        )
    return {
        "input_tokens": total_input,
        "output_tokens": billed_output,
        "thoughts_tokens": total_thoughts,
        "total_tokens": total_input + billed_output,
        "cost": fmt_cost,
    }


async def _apply_parallel_formatter_results(
    result: dict[str, Any],
    field_tasks: list[tuple[tuple[Any, ...], str, str]],
    gathered: list[Any],
    *,
    provider_label: str,
    start_time: float,
) -> tuple[dict[str, Any], dict[str, Any], list[Any | None]]:
    """Write gathered formatter outputs into *result* and build usage aggregates."""
    paths = [path for path, _, _ in field_tasks]
    success_count = 0
    total_input = 0
    total_candidates = 0
    total_thoughts = 0
    usages: list[Any | None] = []

    for path, value in zip(paths, gathered):
        if isinstance(value, Exception):
            logger.warning(
                f"Formatter ({provider_label}) task failed for path {path}, keeping original: {value}",
                extra={"path": str(path), "error": str(value)[:200]},
            )
            usages.append(None)
            continue

        formatted_text, usage_meta = value
        usages.append(usage_meta)

        if usage_meta is not None:
            total_input += _usage_int_field(usage_meta, "prompt_token_count")
            total_candidates += _usage_int_field(usage_meta, "candidates_token_count")
            total_thoughts += _usage_int_field(usage_meta, "thoughts_token_count")

        target: Any = result
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = formatted_text
        success_count += 1

    elapsed_ms = int((time.time() - start_time) * 1000)
    total_tasks = len(field_tasks)
    logger.info(
        f"Formatter ({provider_label}) completed: {success_count}/{total_tasks} fields formatted "
        f"in {elapsed_ms}ms",
        extra={
            "formatted_fields": success_count,
            "total_fields": total_tasks,
            "elapsed_ms": elapsed_ms,
            "provider": provider_label,
        },
    )
    return result, usages, [total_input, total_candidates, total_thoughts]


def _format_text_or_sync(
    api_key: str,
    text: str,
    context: str = "",
    target_language: str = "es-ES",
) -> tuple[str, Any]:
    """Format one text block via OpenRouter (sync; run in a thread from async code)."""
    if not text or not text.strip():
        return text, None

    user_message = _build_formatter_user_message(text, context)

    try:
        content, usage = call_openrouter_chat(
            messages=[{"role": "user", "content": user_message}],
            model=FORMATTER_OPENROUTER_MODEL,
            system_prompt=build_formatter_system_prompt(target_language),
            api_key=api_key,
            response_format="json_object",
            enable_response_healing=True,
            reasoning=max_reasoning_preferences(FORMATTER_OPENROUTER_MODEL),
            provider=deepseek_provider_preferences(),
            temperature=0.1,
            json_retry_instruction=OPENROUTER_JSON_RETRY_INSTRUCTION,
        )
    except OpenRouterError as exc:
        logger.warning(
            f"Formatter OpenRouter call failed, keeping original text: {exc}",
            extra={"context_preview": context[:80], "error": str(exc)[:200]},
        )
        return text, None
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"Formatter OpenRouter call failed, keeping original text: {exc}",
            extra={"context_preview": context[:80], "error": str(exc)[:200]},
        )
        return text, None

    if not isinstance(content, dict):
        logger.warning(
            "Formatter OpenRouter returned non-object JSON, keeping original text",
            extra={"context_preview": context[:80], "content_type": type(content).__name__},
        )
        return text, usage

    parsed = _extract_formatted_markdown(content)
    if parsed is not None:
        return parsed, usage

    logger.warning(
        "Formatter OpenRouter JSON parse failed or empty markdown field, keeping original text",
        extra={"context_preview": context[:80], "response_preview": str(content)[:200]},
    )
    return text, usage


async def _format_text_or(
    api_key: str,
    text: str,
    context: str = "",
    target_language: str = "es-ES",
) -> tuple[str, Any]:
    return await asyncio.to_thread(_format_text_or_sync, api_key, text, context, target_language)


def _format_text_ds_sync(
    api_key: str,
    text: str,
    context: str = "",
    target_language: str = "es-ES",
) -> tuple[str, Any]:
    """Format one text block via direct DeepSeek (sync; run in a thread from async code)."""
    if not text or not text.strip():
        return text, None

    user_message = _build_formatter_user_message(text, context)

    try:
        content, usage = call_deepseek_chat(
            messages=[{"role": "user", "content": user_message}],
            model=FORMATTER_DEEPSEEK_MODEL,
            system_prompt=build_formatter_system_prompt(target_language),
            api_key=api_key,
            response_format="json_object",
            reasoning_effort=max_reasoning_effort(),
            temperature=0.1,
            json_retry_instruction=OPENROUTER_JSON_RETRY_INSTRUCTION,
        )
    except DeepSeekError as exc:
        logger.warning(
            f"Formatter DeepSeek call failed, keeping original text: {exc}",
            extra={"context_preview": context[:80], "error": str(exc)[:200]},
        )
        return text, None
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"Formatter DeepSeek call failed, keeping original text: {exc}",
            extra={"context_preview": context[:80], "error": str(exc)[:200]},
        )
        return text, None

    if not isinstance(content, dict):
        logger.warning(
            "Formatter DeepSeek returned non-object JSON, keeping original text",
            extra={"context_preview": context[:80], "content_type": type(content).__name__},
        )
        return text, usage

    parsed = _extract_formatted_markdown(content)
    if parsed is not None:
        return parsed, usage

    logger.warning(
        "Formatter DeepSeek JSON parse failed or empty markdown field, keeping original text",
        extra={"context_preview": context[:80], "response_preview": str(content)[:200]},
    )
    return text, usage


async def _format_text_ds(
    api_key: str,
    text: str,
    context: str = "",
    target_language: str = "es-ES",
) -> tuple[str, Any]:
    return await asyncio.to_thread(_format_text_ds_sync, api_key, text, context, target_language)


async def _format_text_codex(
    user_id: str,
    text: str,
    context: str = "",
    target_language: str = "es-ES",
) -> tuple[str, Any]:
    """Format one text block via Codex (app-server; corrutina, sin to_thread)."""
    if not text or not text.strip():
        return text, None

    user_message = _build_formatter_user_message(text, context)

    try:
        content, usage = await call_codex_chat(
            user_id=user_id,
            messages=[{"role": "user", "content": user_message}],
            model=CODEX_MODEL,
            system_prompt=build_formatter_system_prompt(target_language),
            response_format="json_object",
            temperature=0.1,
        )
    except CodexError as exc:
        logger.warning(
            f"Formatter Codex call failed, keeping original text: {exc}",
            extra={"context_preview": context[:80], "error": str(exc)[:200]},
        )
        return text, None
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"Formatter Codex call failed, keeping original text: {exc}",
            extra={"context_preview": context[:80], "error": str(exc)[:200]},
        )
        return text, None

    if not isinstance(content, dict):
        logger.warning(
            "Formatter Codex returned non-object JSON, keeping original text",
            extra={"context_preview": context[:80], "content_type": type(content).__name__},
        )
        return text, usage

    parsed = _extract_formatted_markdown(content)
    if parsed is not None:
        return parsed, usage

    logger.warning(
        "Formatter Codex JSON parse failed or empty markdown field, keeping original text",
        extra={"context_preview": context[:80], "response_preview": str(content)[:200]},
    )
    return text, usage


async def format_explainer_content(
    api_key: str,
    explainer_data: dict[str, Any],
    target_language: str = "es-ES",
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
    field_tasks = _collect_formatter_field_tasks(result)

    if not field_tasks:
        return result, _empty_formatter_usage()

    coros = [
        _format_text(client, text, ctx, target_language=target_language)
        for _, text, ctx in field_tasks
    ]
    gathered = await asyncio.gather(*coros, return_exceptions=True)

    result, usages, token_totals = await _apply_parallel_formatter_results(
        result,
        field_tasks,
        gathered,
        provider_label="gemini",
        start_time=start_time,
    )
    total_input, total_candidates, total_thoughts = token_totals
    usage_summary = _build_formatter_usage_summary(
        model=FORMATTER_MODEL,
        usages=usages,
        total_input=total_input,
        total_candidates=total_candidates,
        total_thoughts=total_thoughts,
    )
    return result, usage_summary


async def format_explainer_content_or(
    api_key: str,
    explainer_data: dict[str, Any],
    target_language: str = "es-ES",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Format all prose fields via OpenRouter (DeepSeek Flash) in parallel.

    Same schema and fail-safe semantics as ``format_explainer_content``.
    """
    start_time = time.time()
    result = copy.deepcopy(explainer_data)
    field_tasks = _collect_formatter_field_tasks(result)

    if not field_tasks:
        return result, _empty_formatter_usage()

    coros = [
        _format_text_or(api_key, text, ctx, target_language)
        for _, text, ctx in field_tasks
    ]
    gathered = await asyncio.gather(*coros, return_exceptions=True)

    result, usages, token_totals = await _apply_parallel_formatter_results(
        result,
        field_tasks,
        gathered,
        provider_label="openrouter",
        start_time=start_time,
    )
    total_input, total_candidates, total_thoughts = token_totals
    usage_summary = _build_formatter_usage_summary(
        model=FORMATTER_OPENROUTER_MODEL,
        usages=usages,
        total_input=total_input,
        total_candidates=total_candidates,
        total_thoughts=total_thoughts,
    )
    return result, usage_summary


async def format_explainer_content_ds(
    api_key: str,
    explainer_data: dict[str, Any],
    target_language: str = "es-ES",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Format all prose fields via direct DeepSeek Flash in parallel.

    Same schema and fail-safe semantics as ``format_explainer_content``.
    """
    start_time = time.time()
    result = copy.deepcopy(explainer_data)
    field_tasks = _collect_formatter_field_tasks(result)

    if not field_tasks:
        return result, _empty_formatter_usage()

    coros = [
        _format_text_ds(api_key, text, ctx, target_language)
        for _, text, ctx in field_tasks
    ]
    gathered = await asyncio.gather(*coros, return_exceptions=True)

    result, usages, token_totals = await _apply_parallel_formatter_results(
        result,
        field_tasks,
        gathered,
        provider_label="deepseek",
        start_time=start_time,
    )
    total_input, total_candidates, total_thoughts = token_totals
    usage_summary = _build_formatter_usage_summary(
        model=FORMATTER_DEEPSEEK_MODEL,
        usages=usages,
        total_input=total_input,
        total_candidates=total_candidates,
        total_thoughts=total_thoughts,
    )
    return result, usage_summary


async def format_explainer_content_codex(
    user_id: str,
    explainer_data: dict[str, Any],
    target_language: str = "es-ES",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Format all prose fields via Codex (app-server) in parallel.

    Same schema and fail-safe semantics as ``format_explainer_content``.
    Corrutina async: cada campo se espera directo vía `call_codex_chat`
    (nunca `asyncio.to_thread`); el `gather` no se acota más que la variante
    `_ds` (el semáforo por proceso del app-server serializa los excesos).
    """
    start_time = time.time()
    result = copy.deepcopy(explainer_data)
    field_tasks = _collect_formatter_field_tasks(result)

    if not field_tasks:
        return result, _empty_formatter_usage()

    coros = [
        _format_text_codex(user_id, text, ctx, target_language)
        for _, text, ctx in field_tasks
    ]
    gathered = await asyncio.gather(*coros, return_exceptions=True)

    result, usages, token_totals = await _apply_parallel_formatter_results(
        result,
        field_tasks,
        gathered,
        provider_label="codex",
        start_time=start_time,
    )
    total_input, total_candidates, total_thoughts = token_totals
    usage_summary = _build_formatter_usage_summary(
        model=CODEX_MODEL,
        usages=usages,
        total_input=total_input,
        total_candidates=total_candidates,
        total_thoughts=total_thoughts,
    )
    # RC-01: cada campo formateado es un turno Codex (`quota_requests=1` por
    # CodexUsage). El resumen conserva el total de peticiones de cuota (turnos
    # paralelos incluidos) para que los callers las acumulen en
    # `codex_quota_requests` sin añadir coste USD.
    usage_summary["quota_requests"] = sum(
        getattr(usage, "quota_requests", 0) or 0
        for usage in usages
        if usage is not None
    )
    return result, usage_summary
