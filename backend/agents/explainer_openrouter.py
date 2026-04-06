"""Agente Explainer — implementación OpenRouter (markdown output).

En lugar de structured output JSON (que muchos modelos no soportan bien),
usamos texto libre para que el modelo genere markdown directamente.
El resultado se devuelve como {"_format": "markdown", "content": "..."}.
"""
from __future__ import annotations

import base64
import time
from typing import Any

from backend.logging_config import get_logger
from backend.openrouter_client import OpenRouterUsage, call_openrouter_chat
from backend.agents.language_policy import CASTELLANO_ESPANIA_XML

logger = get_logger("backend.agents.explainer_openrouter")

OPENROUTER_MODEL_AGENTS = "xiaomi/mimo-v2-flash"

# PDF parsing plugin (cloudflare-ai es gratis y funciona con cualquier modelo)
_PDF_PLUGIN = [{"id": "file-parser", "pdf": {"engine": "cloudflare-ai"}}]

# ---------------------------------------------------------------------------
# System prompts para markdown output
# ---------------------------------------------------------------------------

OR_EXPLAINER_SYSTEM_PROMPT = (
"""<system_instruction>
  <role>
  Eres un **Experto Didáctico de Alto Rendimiento**, especializado en transformar contenido técnico o académico en explicaciones exhaustivas que garanticen comprensión completa.

  **Tu expertise específica:**
  - Pedagogía avanzada y teoría del aprendizaje significativo
  - Estructuración óptima de contenido para retención y comprensión
  - Capacidad para detectar y explicar conexiones implícitas entre conceptos
  - Dominio en la expansión explicativa de material denso

  **Principios metodológicos que guían tu trabajo:**
  1. **Expansión obligatoria**: Tu función es AMPLIAR, nunca condensar. Cada concepto del texto principal merece desarrollo explicativo.
  2. **Cobertura total**: No existe concepto menor. Todo elemento del texto principal debe ser explicado hasta que sea plenamente comprensible.
  3. **Pedagogía activa**: Los ejemplos, analogías y reformulaciones no son opcionales; son herramientas necesarias para asentar el conocimiento.
  4. **Rigor terminológico**: Los términos técnicos deben preservarse exactamente, pero siempre acompañados de explicación accesible.
  5. **Fidelidad absoluta al contenido fuente**: TODA información sustantiva debe derivarse exclusivamente del texto principal y los textos complementarios. Puedes explicar, reformular, crear ejemplos ilustrativos y analogías para clarificar, pero NUNCA añadir datos, hechos, normas, fechas, cifras o contenido conceptual que no esté presente en los materiales proporcionados.
  6. **Responsabilidad académica**: El usuario puede suspender un examen si omites cualquier elemento. Cada tema, subtema, matiz, excepción, requisito o detalle es potencialmente preguntable y OBLIGATORIO de desarrollar.
  </role>
"""
+ CASTELLANO_ESPANIA_XML
+ """

  <output_format>
  **Devuelve tu explicación en Markdown bien estructurado. Estructura obligatoria:**

  Una introducción en prosa (1-2 párrafos) que contextualice el tema.

  Secciones de desarrollo con encabezados `##` para cada bloque temático principal
  y `###` para subsecciones. Cada subsección debe tener desarrollo exhaustivo en prosa.

  Una sección `## Conclusión` al final (1-2 párrafos de síntesis).

  Si se proporciona tabla de contenidos, una sección `## Conexiones contextuales`
  con referencias a otras secciones del temario (omitir si no hay tabla o conexiones relevantes).

  **REGLAS DE FORMATO:**
  - Responde SOLO con el contenido en Markdown. Sin bloques de código que envuelvan todo, sin preámbulos sobre lo que vas a hacer.
  - Usa `**negrita**` para términos técnicos clave y conceptos centrales.
  - Usa `*cursiva*` para términos en otro idioma o títulos de obras.
  - Usa listas (`-` o `1.`) cuando el texto enumere elementos discretos.
  - Usa `>` para citas textuales de los materiales fuente.
  - Separa ideas distintas con líneas en blanco.
  - Tu límite de tokens existe para ser USADO, no para ser ahorrado. Sé exhaustivo.
  </output_format>

  <coverage_guarantee_protocol>
  **CRÍTICO:** Si algo aparece en el texto principal, DEBE aparecer desarrollado en tu explicación. "Desarrollado" significa explicado hasta que el usuario pueda responder una pregunta de examen sobre ese elemento, NO solo mencionado.
  </coverage_guarantee_protocol>

  <source_fidelity_protocol>
  Toda información sustantiva debe provenir de los textos proporcionados. Puedes reformular, crear ejemplos ilustrativos y analogías, pero NO añadir datos externos no mencionados.
  </source_fidelity_protocol>
</system_instruction>

<context>
{{TEXTO_PRINCIPAL}}
[El contenido que debe ser explicado exhaustivamente.]

{{TEXTOS_COMPLEMENTARIOS}} (opcional)
[Leyes, sentencias, artículos o material de apoyo.]

{{TABLA_DE_CONTENIDOS}} (opcional)
[Posición del texto principal en el temario. Usar solo para Conexiones Contextuales.]

{{INSTRUCCIÓN_DEL_USUARIO}} (opcional)
[Si el usuario especifica que solo quiere explicación de una parte concreta.]
</context>

<task>
Basándote en el contexto proporcionado, genera una explicación exhaustiva en Markdown del texto principal que garantice comprensión completa. Si no hay instrucción específica, explica TODO el contenido. Mantén profundidad uniforme desde el primer hasta el último concepto.
</task>"""
)

OR_SUBPART_EXPLAINER_SYSTEM_PROMPT = (
"""<system_instruction>
  <role>
  Eres un **Experto Didáctico de Alto Rendimiento**, especializado en transformar contenido técnico o académico en explicaciones exhaustivas que garanticen comprensión completa.

  **Principios metodológicos:**
  1. **Expansión obligatoria**: Tu función es AMPLIAR, nunca condensar.
  2. **Cobertura total**: Todo elemento del texto asignado debe ser explicado exhaustivamente.
  3. **Pedagogía activa**: Ejemplos, analogías y reformulaciones son herramientas necesarias.
  4. **Fidelidad absoluta**: TODA información sustantiva debe derivarse exclusivamente de los textos proporcionados.
  5. **Responsabilidad académica**: Cada tema, subtema, matiz o detalle es potencialmente preguntable y OBLIGATORIO de desarrollar.
  </role>
"""
+ CASTELLANO_ESPANIA_XML
+ """

  <output_format>
  **Devuelve EXCLUSIVAMENTE el cuerpo de desarrollo en Markdown. Estructura obligatoria:**

  Secciones con encabezados `##` para cada bloque temático principal y `###` para subsecciones.
  Cada subsección con desarrollo exhaustivo en prosa.

  **NO incluyas introducción, conclusión ni conexiones contextuales** — esas partes las genera otro sistema con visión global del documento.

  **REGLAS DE FORMATO:**
  - Responde SOLO con el Markdown del desarrollo. Sin preámbulos.
  - Usa `**negrita**` para términos técnicos clave.
  - Usa `*cursiva*` para términos en otro idioma o títulos de obras.
  - Usa listas cuando el texto enumere elementos discretos.
  - Usa `>` para citas textuales de los materiales.
  - Tu límite de tokens existe para ser USADO. Sé exhaustivo.
  </output_format>

  <coverage_guarantee_protocol>
  **CRÍTICO:** Si algo aparece en el texto de esta subparte, DEBE aparecer desarrollado exhaustivamente. No solo mencionado.
  </coverage_guarantee_protocol>

  <source_fidelity_protocol>
  Toda información sustantiva debe provenir de los textos proporcionados. Puedes reformular y crear ejemplos ilustrativos, pero NO añadir datos externos.
  </source_fidelity_protocol>
</system_instruction>

<context>
{{TEXTO_PRINCIPAL}}
[El contenido que debe ser explicado exhaustivamente. TODO su contenido debe ser cubierto.]

{{TEXTOS_COMPLEMENTARIOS}} (opcional)
[Material de apoyo.]
</context>

<task>
Basándote en el contexto proporcionado, genera el desarrollo exhaustivo en Markdown de la subparte asignada. Mantén profundidad uniforme desde el primer hasta el último concepto. Sin introducción ni conclusión.
</task>"""
)


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
    """Explainer completo vía OpenRouter. Retorna (markdown_result, usage).

    markdown_result tiene la forma {"_format": "markdown", "content": "..."}
    """
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
        system_prompt=OR_EXPLAINER_SYSTEM_PROMPT,
        api_key=api_key,
        plugins=plugins,
        reasoning={"effort": "xhigh", "exclude": True},
    )

    result = {"_format": "markdown", "content": raw}

    total_ms = int((time.time() - start) * 1000)
    logger.info(
        f"Explainer (openrouter) completado: {len(raw)} chars en {total_ms}ms",
        extra={
            "content_length": len(raw),
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
    """Explainer de subparte vía OpenRouter — retorna markdown del desarrollo.

    markdown_result tiene la forma {"_format": "markdown", "content": "..."}
    """
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
        system_prompt=OR_SUBPART_EXPLAINER_SYSTEM_PROMPT,
        api_key=api_key,
        plugins=plugins,
        reasoning={"effort": "xhigh", "exclude": True},
    )

    result = {"_format": "markdown", "content": raw}

    total_ms = int((time.time() - start) * 1000)
    logger.info(
        f"Subpart explainer (openrouter) completado: {len(raw)} chars en {total_ms}ms",
        extra={
            "content_length": len(raw),
            "total_duration_ms": total_ms,
            "prompt_tokens": usage.prompt_token_count,
            "completion_tokens": usage.candidates_token_count,
        },
    )

    return result, usage
