"""Agente Esquema Visual — genera un diagrama Mermaid optimizado para memorización activa."""
from __future__ import annotations

import re
import time
from typing import Any

from backend.deepseek_client import DeepSeekError, call_deepseek_chat
from backend.deepseek_model_routing import DEEPSEEK_MODEL_V4_FLASH, max_reasoning_effort
from backend.logging_config import get_logger

logger = get_logger("backend.agents.mermaid_agent")

SYSTEM_INSTRUCTION = """<system_instruction>
  <role>
  Eres un Arquitecto de Esquemas Cognitivos: especialista en diseño instruccional y visualización del conocimiento.
  Tu expertise combina:
  - Pedagogía cognitiva: codificación dual (Paivio), carga cognitiva (Sweller), chunking (Miller 7±2), principios gestálticos.
  - Dominio técnico de Mermaid: todos los tipos de diagrama (graph/flowchart, mindmap, timeline, stateDiagram, classDiagram, erDiagram, quadrantChart, block-beta, sankey, pie, etc.) y sus capacidades de estilizado (directivas, classDef, estilos inline, iconos, subgraphs).
  Principios que guían tu trabajo:
  - Priorizas recuperabilidad mnemónica sobre fidelidad literal.
  - Ante tensión entre completitud y claridad visual, diseñas para claridad y señalas lo omitido.
  - Cada conjunto de apuntes es un problema de diseño único: la estructura del contenido dicta el tipo de diagrama, nunca al revés.
  - Audaz en simplificación, riguroso en preservar relaciones conceptuales y terminología técnica definitoria.
  </role>

  <objectives>
  Transformar apuntes académicos densos en un esquema visual Mermaid que funcione como herramienta de memorización activa.
  El usuario debe poder:
  1. Captar la arquitectura conceptual completa en menos de 30 segundos.
  2. Reconstruir mentalmente el contenido sin consultar los apuntes originales.
  3. Usar el esquema como ancla mnemónica para preparar un examen.
  El resultado NO es un resumen textual ni una copia reformateada de la estructura del documento.
  </objectives>

  <quality_criteria>
  Respuesta excelente:
  - Completitud conceptual: cubre todos los conceptos principales, de inicio a fin.
  - Claridad instantánea: jerarquía y relaciones se captan sin esfuerzo.
  - Eficiencia cognitiva: máx. 20-25 nodos principales; máx. 8-10 palabras/nodo; 3-4 niveles jerárquicos.
  - Memorabilidad: código cromático coherente (máx. 4-5 colores con propósito semántico), agrupación visual, etiquetas como disparadores mnemónicos.
  - Autonomía: el esquema se entiende por sí solo.
  Evita: paredes de texto en nodos, replicar estructura lineal de apuntes sin revelar relaciones, forzar un tipo de diagrama inadecuado al contenido.
  </quality_criteria>

  <methodological_principles>
  Análisis cognitivo previo al código Mermaid:
  - Identifica conceptos nucleares y estructura lógica dominante (jerárquica, cronológica, comparativa, causal, procedimental o mixta).
  - Detecta relaciones: causa-efecto, parte-todo, oposición, secuencia, dependencia, clasificación.
  - Evalúa densidad conceptual para decidir nivel de compresión.
  Síntesis:
  - Frases nominales y palabras clave como disparadores, no oraciones completas.
  - Preserva terminología técnica definitoria; elimina redundancia seleccionando el ejemplo más representativo.
  - Criterio de inclusión: ¿necesario para entender el resto? → incluir. ¿Ayuda a recordar estructura/lista? → incluir. ¿Solo contextual? → evaluar omitir.
  Elección del diagrama:
  - La estructura del contenido dicta el tipo. Selecciona entre todas las opciones de Mermaid según cuál represente mejor las relaciones detectadas.
  - Combina recursos dentro de un diagrama (subgraphs, estilos, formas de nodo variadas) cuando aporte claridad.
  - Orientación LR para contenido secuencial/procesual; TD para jerarquías; mindmap para contenido radial con núcleo central.
  </methodological_principles>

  <output_format>
  **[ANÁLISIS]**: 2-3 líneas: estructura conceptual detectada, tipo de diagrama elegido y por qué.
  **[ESQUEMA VISUAL]**: Bloque de código Mermaid completo con estilos y código cromático. Autocontenido y renderizable directamente.
  **[GUÍA DE LECTURA]**: 2-4 indicaciones breves: punto de entrada, ruta sugerida, significado de colores/formas.
  **[DECISIONES DE SÍNTESIS]**: Solo si hubo omisiones significativas, indica qué y por qué.
  </output_format>
</system_instruction>"""

USER_TEMPLATE = """<context>
{explanation_text}
</context>

<few_shot_examples>
  <example id="1">
    <input_scenario>Apuntes extensos (~3000 palabras), tema jurídico, estructura procesual: tres fases secuenciales con subfases y relaciones causales entre ellas.</input_scenario>
    <expert_approach>
      Detecta estructura procesual-secuencial → flowchart LR/TD con subgraphs por fase. Color semántico por fase. Cada subfase comprimida en 4-6 palabras clave. Flechas etiquetadas para relaciones causales. ~15 nodos, 3 subgraphs, legible en 20s.
    </expert_approach>
    <output_pattern>
      [ANÁLISIS: estructura procesual + justificación flowchart]
      [ESQUEMA: flowchart con subgraphs por fase, estilos cromáticos, flechas causales]
      [GUÍA: entrada → ruta secuencial → significado de colores]
      [DECISIONES: ejemplos jurisprudenciales omitidos por ilustrativos, no estructurales]
    </output_pattern>
  </example>

  <example id="2">
    <input_scenario>~2000 palabras, clasificación taxonómica: concepto central → 4 categorías → 2-3 subcategorías con características. Sin secuencia ni causalidad, pura jerarquía.</input_scenario>
    <expert_approach>
      Estructura jerárquica/taxonómica → mindmap o graph TD según densidad. Concepto central como raíz, ramas por categoría. Formas de nodo distintas para categorías vs. características. Color por rama. Solo la característica más distintiva como disparador mnemónico.
    </expert_approach>
    <output_pattern>
      [ANÁLISIS: taxonomía detectada + justificación mindmap/graph]
      [ESQUEMA: concepto raíz, ramas por categoría, nodos hoja con rasgos clave, estilos diferenciados]
      [GUÍA: lectura radial desde centro → exploración por rama → formas de nodo]
      [DECISIONES: definiciones extensas reducidas a rasgo diferenciador]
    </output_pattern>
  </example>

  <example id="3">
    <input_scenario>~2500 palabras comparando dos sistemas/teorías en múltiples dimensiones (origen, principios, aplicación, críticas). Estructura comparativa/contrastiva.</input_scenario>
    <expert_approach>
      Estructura comparativa → flowchart con columnas paralelas conectadas por dimensiones, o block-beta con layout tabular. Color para diferenciar sistemas, conectores para convergencias/divergencias. Prioriza dimensiones más relevantes para memorización.
    </expert_approach>
    <output_pattern>
      [ANÁLISIS: estructura comparativa + justificación del tipo]
      [ESQUEMA: representación dual, dimensiones como ejes, señalización visual de similitudes/diferencias]
      [GUÍA: lectura en paralelo → conexiones cruzadas → colores]
      [DECISIONES: dimensiones secundarias omitidas o fusionadas]
    </output_pattern>
  </example>
</few_shot_examples>

<task>
Basándote en los apuntes del contexto, diseña un esquema visual Mermaid optimizado para memorización activa. Elige el tipo de diagrama que mejor capture la estructura conceptual. Aplica tus criterios de calidad para producir un esquema completo, claro, eficiente y memorable. Entrega en el formato de salida especificado.
</task>

<thinking_protocol>
Antes de generar tu respuesta final, razona en un bloque <thinking>:
- Estructura conceptual dominante de los apuntes.
- Conceptos nucleares y relaciones clave.
- Tipo de diagrama Mermaid óptimo y por qué.
- Distribución visual: nodos, agrupaciones, código cromático.
- Si la densidad requiere omisiones, cuáles y por qué.
</thinking_protocol>"""


def assemble_explanation_text(explainer_data: dict) -> str:
    """Converts structured explainer JSON into a full plain-text document (untrimmed)."""
    if not explainer_data:
        return ""

    # Handle post-formatter markdown format
    if explainer_data.get("_format") == "markdown":
        return explainer_data.get("content", "")

    parts: list[str] = []

    if explainer_data.get("introduccion"):
        parts.append(f"## Introducción\n\n{explainer_data['introduccion']}")

    for section in explainer_data.get("desarrollo", []):
        section_parts: list[str] = [f"## {section.get('titulo_seccion', '')}"]
        if section.get("explicacion_introductoria"):
            section_parts.append(section["explicacion_introductoria"])
        for sub in section.get("subsecciones", []):
            section_parts.append(f"### {sub.get('titulo_subseccion', '')}")
            if sub.get("explicacion_detallada"):
                section_parts.append(sub["explicacion_detallada"])
        parts.append("\n\n".join(section_parts))

    if explainer_data.get("conclusion"):
        parts.append(f"## Conclusión\n\n{explainer_data['conclusion']}")

    conexiones = explainer_data.get("conexiones_contextuales", [])
    if conexiones:
        cx_parts = ["## Conexiones Contextuales"]
        for cx in conexiones:
            cx_parts.append(f"### {cx.get('seccion_temario_relacionada', '')}")
            if cx.get("descripcion_conexion"):
                cx_parts.append(cx["descripcion_conexion"])
        parts.append("\n\n".join(cx_parts))

    return "\n\n---\n\n".join(parts)


def _parse_response(text: str) -> dict[str, str]:
    """Extracts structured fields from the model's formatted text response."""
    # Strip any <thinking>...</thinking> block the model may include verbatim
    text = re.sub(r"<thinking>[\s\S]*?</thinking>\s*", "", text).strip()

    # Extract the Mermaid code block (most critical)
    mermaid_match = re.search(r"```mermaid\s*\n([\s\S]*?)```", text)
    if not mermaid_match:
        # Fallback: any code block
        mermaid_match = re.search(r"```\s*\n([\s\S]*?)```", text)
    mermaid_code = mermaid_match.group(1).strip() if mermaid_match else ""

    if not mermaid_code:
        raise DeepSeekError(
            "No se encontró bloque de código Mermaid en la respuesta del modelo. "
            f"Respuesta recibida (primeros 500 chars): {text[:500]}"
        )

    def _extract_section(src: str, marker: str, stop_markers: list[str]) -> str:
        start = re.search(marker, src, re.IGNORECASE)
        if not start:
            return ""
        content_start = start.end()
        earliest = len(src)
        for stop in stop_markers:
            m = re.search(stop, src[content_start:], re.IGNORECASE)
            if m:
                earliest = min(earliest, content_start + m.start())
        return src[content_start:earliest].strip()

    _all_stops = [
        r"\*\*\[ESQUEMA VISUAL\]\*\*",
        r"\*\*\[GUÍA DE LECTURA\]\*\*",
        r"\*\*\[DECISIONES DE SÍNTESIS\]\*\*",
    ]

    analysis = _extract_section(text, r"\*\*\[AN[AÁ]LISIS\]\*\*\s*:?\s*", _all_stops)
    reading_guide = _extract_section(
        text,
        r"\*\*\[GU[IÍ]A DE LECTURA\]\*\*\s*:?\s*",
        [r"\*\*\[DECISIONES DE S[IÍ]NTESIS\]\*\*"],
    )
    synthesis = _extract_section(
        text, r"\*\*\[DECISIONES DE S[IÍ]NTESIS\]\*\*\s*:?\s*", []
    )

    return {
        "analysis": analysis,
        "mermaid_code": mermaid_code,
        "reading_guide": reading_guide,
        "synthesis_decisions": synthesis,
    }


def generate_mermaid(
    api_key: str,
    explanation_text: str,
) -> tuple[dict[str, Any], Any]:
    """Run the Mermaid diagram agent and return (parsed_result, usage_metadata).

    Siempre usa el modelo DeepSeek directo ``deepseek-v4-flash``.
    """
    start_time = time.time()
    logger.info(
        "Iniciando agente mermaid",
        extra={
            "explanation_length": len(explanation_text),
            "model": DEEPSEEK_MODEL_V4_FLASH,
        },
    )

    user_text = USER_TEMPLATE.format(explanation_text=explanation_text)

    try:
        content, usage = call_deepseek_chat(
            messages=[{"role": "user", "content": user_text}],
            model=DEEPSEEK_MODEL_V4_FLASH,
            system_prompt=SYSTEM_INSTRUCTION,
            api_key=api_key,
            response_format="text",
            reasoning_effort=max_reasoning_effort(),
            max_retries=5,
        )
    except DeepSeekError as exc:
        logger.warning(
            "[Mermaid] Llamada DeepSeek falló: %s",
            str(exc)[:300],
            extra={"model": DEEPSEEK_MODEL_V4_FLASH},
        )
        raise

    total_duration = int((time.time() - start_time) * 1000)
    logger.info(
        f"Respuesta Mermaid recibida en {total_duration}ms",
        extra={
            "total_duration_ms": total_duration,
            "prompt_tokens": getattr(usage, "prompt_token_count", 0),
            "candidates_tokens": getattr(usage, "candidates_token_count", 0),
            "thoughts_tokens": getattr(usage, "thoughts_token_count", 0),
        },
    )

    if not isinstance(content, str):
        raise DeepSeekError(
            "DeepSeek devolvió contenido no textual en el agente Mermaid: "
            f"{type(content).__name__}"
        )

    result = _parse_response(content)
    return result, usage
