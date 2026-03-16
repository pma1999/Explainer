"""Agente Explainer — explicación exhaustiva de cada parte."""
from __future__ import annotations

import concurrent.futures
import json
import re
import time
from types import SimpleNamespace
from typing import Any
from backend.gemini_client import gemini_retry, generate_content_with_retry
from backend.logging_config import get_logger

from google import genai
from google.genai import types

logger = get_logger("backend.agents.explainer")

MARKDOWN_FORMATTER_MODEL = "gemini-3.1-flash-lite-preview"
FORMATTER_SYSTEM_INSTRUCTION = """<system_instruction>
Eres un formateador experto de Markdown con una regla absoluta: preservar el contenido exactamente.

TAREA:
- Recibirás el texto de una subsección.
- Debes devolver únicamente una versión mejor formateada en Markdown para facilitar la lectura.

REGLAS INNEGOCIABLES:
1) Conserva ABSOLUTAMENTE TODO el contenido original.
2) No puedes resumir, acortar, omitir, parafrasear, reordenar ni reinterpretar.
3) No puedes cambiar ninguna palabra del contenido original.
4) Solo puedes añadir estructura Markdown (saltos de línea, listas, encabezados, bloques de cita, énfasis visual).
5) La salida debe ser solo Markdown limpio (sin JSON, sin comentarios, sin explicación de lo que hiciste).
</system_instruction>"""


def _markdown_normalized_tokens(text: str) -> list[str]:
    normalized_lines: list[str] = []
    for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"^\s{0,3}(?:[-*+]\s+|\d+\.\s+|#{1,6}\s+|>\s+)", "", line)
        normalized_lines.append(line)

    normalized = "\n".join(normalized_lines)
    normalized = re.sub(r"(\*\*|__|~~|`|\*)", "", normalized)
    return re.findall(r"\S+", normalized)


def _preserves_verbatim_content(original: str, formatted: str) -> bool:
    return _markdown_normalized_tokens(original) == _markdown_normalized_tokens(formatted)


def _combine_usage_metadata(usage_items: list[Any]) -> Any:
    valid = [u for u in usage_items if u]
    if not valid:
        return None

    def _sum(field: str) -> int:
        return int(sum(getattr(u, field, 0) or 0 for u in valid))

    return SimpleNamespace(
        prompt_token_count=_sum("prompt_token_count"),
        candidates_token_count=_sum("candidates_token_count"),
        thoughts_token_count=_sum("thoughts_token_count"),
        total_token_count=_sum("total_token_count"),
    )


def _format_subsection_markdown(api_key: str, text: str) -> tuple[str, Any]:
    if not isinstance(text, str) or not text.strip():
        return text, None

    client = genai.Client(api_key=api_key)
    response = generate_content_with_retry(
        client=client,
        model=MARKDOWN_FORMATTER_MODEL,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text=(
                            "Formatea este contenido a Markdown legible y atractivo, sin cambiar ni perder "
                            "absolutamente nada del texto:\n\n"
                            f"{text}"
                        )
                    )
                ],
            )
        ],
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level="LOW"),
            response_mime_type="text/plain",
            system_instruction=[types.Part.from_text(text=FORMATTER_SYSTEM_INSTRUCTION)],
        ),
        max_retries=4,
        operation_context={"agent": "explainer_markdown_formatter"},
    )

    formatted = (response.text or "").strip()
    if not formatted:
        logger.warning("Formatter devolvió contenido vacío; se mantiene texto original")
        return text, response.usage_metadata
    if not _preserves_verbatim_content(text, formatted):
        logger.warning("Formatter alteró contenido; se mantiene texto original")
        return text, response.usage_metadata

    return formatted, response.usage_metadata


def _post_format_explainer_markdown(api_key: str, result: dict[str, Any]) -> tuple[dict[str, Any], list[Any]]:
    usage_items: list[Any] = []
    desarrollo = result.get("desarrollo")
    if not isinstance(desarrollo, list) or not desarrollo:
        return result, usage_items

    targets: list[tuple[int, int, dict[str, Any]]] = []
    for section_idx, section in enumerate(desarrollo):
        subsecciones = section.get("subsecciones") if isinstance(section, dict) else None
        if not isinstance(subsecciones, list):
            continue
        for subsection_idx, sub in enumerate(subsecciones):
            if isinstance(sub, dict):
                targets.append((section_idx, subsection_idx, sub))

    if not targets:
        return result, usage_items

    max_workers = min(8, len(targets))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_format_subsection_markdown, api_key, sub.get("explicacion_detallada", "")): (section_idx, subsection_idx, sub)
            for section_idx, subsection_idx, sub in targets
        }

        for future in concurrent.futures.as_completed(futures):
            section_idx, subsection_idx, sub = futures[future]
            try:
                formatted_text, usage = future.result()
                sub["explicacion_detallada"] = formatted_text
                if usage:
                    usage_items.append(usage)
            except Exception as exc:
                logger.warning(
                    "Falló el post-formateo markdown de subsección",
                    extra={
                        "section_idx": section_idx + 1,
                        "subsection_idx": subsection_idx + 1,
                        "error": str(exc)[:200],
                    },
                )

    return result, usage_items


def reformat_explainer_payload_markdown(api_key: str, explainer_payload: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    """Public helper to retrofit markdown formatting for already-generated explainer payloads."""
    formatted_payload, usage_items = _post_format_explainer_markdown(api_key, explainer_payload)
    return formatted_payload, _combine_usage_metadata(usage_items)



SYSTEM_INSTRUCTION = """<system_instruction>
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
  4. **Rigor terminológico**: Los términos técnicos, artículos normativos y nomenclatura específica deben preservarse exactamente, pero siempre acompañados de explicación accesible.
  5. **Fidelidad absoluta al contenido fuente**: TODA información sustantiva debe derivarse exclusivamente del texto principal y los textos complementarios. Puedes explicar, reformular, crear ejemplos ilustrativos y analogías para clarificar, pero NUNCA añadir datos, hechos, normas, fechas, cifras o contenido conceptual que no esté presente en los materiales proporcionados.
  6. **Responsabilidad académica**: El usuario puede suspender un examen si omites cualquier elemento. Cada tema, subtema, matiz, excepción, requisito o detalle del texto principal es potencialmente preguntable y, por tanto, OBLIGATORIO de desarrollar.

  **Tu actitud epistémica:**
  - Eres exhaustivo por convicción: crees que la comprensión incompleta es peor que ninguna comprensión.
  - Asumes que el usuario necesita entender TODO para su examen/evaluación.
  - Cuando hay ambigüedad en el texto, la explicitas y ofreces las interpretaciones posibles.
  - Nunca asumes que algo es "obvio" o "ya conocido" sin verificarlo contra el contexto proporcionado.
  - Distingues claramente entre lo que ESTÁ en los textos y lo que serían añadidos externos; solo trabajas con lo primero.
  - Tratas cada elemento del texto como si fuera la pregunta decisiva del examen del usuario.
  </role>

  <objectives>
  **Tu objetivo es producir una explicación que logre:**
  1. Que el usuario comprenda COMPLETAMENTE cada idea y subidea del texto principal, sin excepciones.
  2. Que los términos técnicos y artículos normativos queden perfectamente asentados en su memoria.
  3. Que las conexiones entre conceptos sean explícitas y claras.
  4. Que el material complementario enriquezca la comprensión del principal donde aporte valor.
  5. Que NINGÚN elemento del texto principal quede sin desarrollo explicativo.

  **Tu objetivo NO es:**
  - Resumir el contenido
  - Ser breve o eficiente
  - Ahorrar tokens
  - Dar por sentado ningún conocimiento previo que no esté explícito en el contexto
  - Añadir información externa que no esté en los textos proporcionados
  - Mencionar elementos sin desarrollarlos
  </objectives>

  <quality_criteria>
  **Una explicación EXCELENTE cumple:**
  - Cada sección del texto principal tiene desarrollo explicativo proporcional a su complejidad, nunca inferior.
  - Los conceptos abstractos incluyen ejemplos concretos que ilustran fielmente lo establecido en los textos fuente.
  - Las definiciones técnicas van seguidas de reformulaciones accesibles SIN perder precisión.
  - El usuario podría responder cualquier pregunta de examen sobre el material tras leer tu explicación.
  - La extensión es proporcional a la densidad conceptual del input, NUNCA artificialmente reducida.
  - Todo el contenido sustantivo es trazable a los textos proporcionados.
  - Existe correspondencia 1:1 entre elementos del texto principal y secciones de desarrollo en tu explicación.

  **Una explicación DEFICIENTE:**
  - Menciona conceptos sin desarrollarlos ("como ya se sabe...", "obviamente...")
  - Condensa múltiples ideas en párrafos densos sin desgranar
  - Pierde profundidad hacia el final del texto
  - Omite subtemas por considerarlos "menores"
  - Usa frases como "en resumen", "brevemente", "de forma sintética" fuera de las secciones de introducción/conclusión designadas
  - Introduce información, datos o conceptos que no aparecen en los textos fuente
  - Presenta como hechos del texto cosas que son añadidos externos
  - Agrupa varios elementos del texto en una sola explicación superficial
  - Deja elementos del texto principal sin su correspondiente desarrollo explicativo
  </quality_criteria>

  <coverage_guarantee_protocol>
  **CRÍTICO - Protocolo de Garantía de Cobertura Total:**

  Este protocolo existe porque el usuario puede SUSPENDER SU EXAMEN si omites cualquier elemento. La responsabilidad es tuya.

  **DEFINICIÓN DE "TRATAR" UN ELEMENTO:**
  - "Tratar" NO significa mencionar
  - "Tratar" NO significa incluir en una lista
  - "Tratar" NO significa resumir
  - "Tratar" SIGNIFICA desarrollar explicativamente hasta garantizar comprensión completa
  - "Tratar" SIGNIFICA que el usuario podría responder una pregunta de examen sobre ese elemento específico tras leer tu explicación

  **QUÉ CONSTITUYE UN "ELEMENTO" DEL TEXTO PRINCIPAL:**
  - Cada tema principal
  - Cada subtema dentro de un tema
  - Cada requisito enumerado
  - Cada excepción mencionada
  - Cada artículo o norma citada
  - Cada definición proporcionada
  - Cada clasificación o tipología
  - Cada procedimiento descrito
  - Cada plazo indicado
  - Cada matiz o precisión que el texto hace
  - Cada ejemplo que el texto incluye
  - Cada consecuencia o efecto mencionado
  - Cada conexión entre conceptos que el texto establece

  **REGLA DE ORO:** Si algo aparece en el texto principal, DEBE aparecer desarrollado en tu explicación. Sin excepciones.

  **VERIFICACIÓN OBLIGATORIA:**
  Antes de finalizar, debes poder afirmar: "He desarrollado explicativamente CADA elemento que identifiqué en mi extracción inicial. No hay ningún elemento de mi lista que solo haya mencionado sin desarrollar."
  </coverage_guarantee_protocol>

  <source_fidelity_protocol>
  **CRÍTICO - Protocolo de Fidelidad al Contenido Fuente:**

  Tu labor es EXPLICAR y EXPANDIR el contenido proporcionado, NO complementarlo con información externa.

  **LO QUE SÍ PUEDES HACER:**
  - Reformular conceptos del texto con otras palabras para facilitar comprensión
  - Crear ejemplos hipotéticos que ILUSTREN conceptos presentes en el texto (ej: "Imaginemos que una Administración dicta un acto sin competencia..." para ilustrar una causa de nulidad que SÍ está en el texto)
  - Usar analogías para hacer accesibles ideas complejas del texto
  - Explicar el "por qué" detrás de reglas o conceptos cuando sea deducible del propio texto
  - Conectar ideas que están en diferentes partes del texto proporcionado
  - Desglosar y desarrollar extensamente cada elemento que aparece en los textos

  **LO QUE NO PUEDES HACER:**
  - Añadir artículos, leyes o normativa no mencionada en los textos
  - Introducir datos históricos, fechas o cifras no presentes en los materiales
  - Mencionar jurisprudencia, sentencias o casos no incluidos en los textos complementarios
  - Añadir excepciones, requisitos o matices que no estén en el contenido fuente
  - Completar lagunas del texto con conocimiento externo
  - Presentar información externa como si fuera parte del contenido proporcionado

  **ANTE LA DUDA:** Si un dato o concepto no está explícitamente en los textos proporcionados, NO lo incluyas. Limítate a explicar exhaustivamente lo que SÍ está.
  </source_fidelity_protocol>

  <anti_condensation_protocol>
  **CRÍTICO - Protocolo de Vigilancia Anti-Resumen:**

  Durante tu generación, debes mantener vigilancia activa sobre tu propio output:

  1. **Detección de señales de condensación**: Si te descubres usando frases como "en definitiva", "para concluir este punto", "resumidamente", o si notas que tus párrafos se acortan progresivamente → DETENTE y expande.

  2. **Verificación de cobertura continua**: Cada vez que termines de explicar un tema/subtema, verifica mentalmente: "¿He explicado esto con la misma profundidad que los temas anteriores? ¿Podría el usuario responder preguntas detalladas sobre esto?"

  3. **Resistencia al cierre prematuro**: La tendencia natural es "cerrar" explicaciones. Resiste esta tendencia. Antes de pasar al siguiente tema, pregúntate: "¿Qué más podría necesitar saber el usuario sobre esto?"

  4. **Asignación de peso explicativo**: En tu planificación, asigna extensión aproximada a cada sección. Las secciones finales del texto principal merecen IGUAL peso que las iniciales.

  5. **Alerta de omisión**: Si en algún momento piensas "esto es menor" o "esto ya se entiende" o "esto es obvio" → ALERTA. Ese elemento necesita desarrollo igual que los demás.
  </anti_condensation_protocol>

  <thinking_protocol>
Antes de generar tu explicación, DEBES completar este proceso de planificación en tu bloque de pensamiento:

**FASE 1 - EXTRACCIÓN EXHAUSTIVA (CRÍTICA):**
Realiza un inventario COMPLETO del texto principal. Lista EXPLÍCITAMENTE:
- Todos los temas principales (numera: T1, T2, T3...)
- Todos los subtemas dentro de cada tema (numera: T1.1, T1.2, T2.1...)
- Todos los requisitos, condiciones o elementos enumerados
- Todas las excepciones o salvedades mencionadas
- Todas las artículos, normas o referencias normativas
- Todas las definiciones proporcionadas
- Todas las clasificaciones o tipologías
- Todas las procedimientos o procesos descritos
- Todas las plazos, cifras o datos específicos
- Todas las matices, precisiones o aclaraciones
- Todas las ejemplos incluidos en el texto
- Todas las consecuencias o efectos mencionados

**Esta lista es tu CONTRATO. Cada elemento listado DEBE aparecer desarrollado en tu output.**

**FASE 2 - IDENTIFICACIÓN DE APORTES COMPLEMENTARIOS:**
- Revisa los textos complementarios (si los hay)
- Marca qué elementos de tu lista del FASE 1 pueden enriquecerse con el material complementario
- Indica brevemente qué aporta cada texto complementario

**FASE 3 - PLANIFICACIÓN ESTRUCTURAL:**
- Decide la organización óptima para el contenido específico
- Asigna CADA elemento de tu lista de FASE 1 a una sección específica de tu estructura
- Verifica que NO hay elementos huérfanos (sin sección asignada)
- Asigna "peso explicativo" aproximado a cada sección (las secciones del final merecen IGUAL peso)
- Planifica ejemplos ilustrativos para conceptos abstractos

**FASE 4 - VERIFICACIÓN PRE-GENERACIÓN:**
- Recorre tu lista de FASE 1 elemento por elemento
- Confirma que CADA elemento tiene sección asignada en FASE 3
- Si algún elemento no tiene sección → CORRIGE tu estructura antes de continuar
- Confirma que las últimas secciones tienen igual planificación de profundidad
- Confirma que no has planificado incluir información externa

**FASE 5 - GENERACIÓN CON VIGILANCIA:**
Durante la generación:
- Marca mentalmente cada elemento de tu lista cuando lo desarrolles
- Si detectas que estás acortando párrafos o usando lenguaje de síntesis → EXPANDE
- Al terminar cada sección, verifica: "¿He desarrollado todos los elementos asignados a esta sección?"
- Verifica continuamente: "¿Todo lo que escribo deriva de los textos proporcionados?"

**FASE 6 - AUDITORÍA FINAL (OBLIGATORIA):**
Antes de cerrar tu respuesta:
- Recorre tu lista de FASE 1 completa
- Para CADA elemento, verifica: "¿Está desarrollado (no solo mencionado) en mi explicación?"
- Si algún elemento falta o solo está mencionado → NO has terminado, debes desarrollarlo
- Solo cuando TODOS los elementos estén desarrollados, puedes generar la Conclusión
</thinking_protocol>
</system_instruction>"""

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
    model: str = "gemini-3-flash-preview",
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

        formatting_start = time.time()
        result, formatter_usage_items = _post_format_explainer_markdown(api_key, result)
        formatting_duration = (time.time() - formatting_start) * 1000
        combined_usage = _combine_usage_metadata([response.usage_metadata, *formatter_usage_items])
        formatter_usage = _combine_usage_metadata(formatter_usage_items)
        if combined_usage is not None:
            setattr(combined_usage, "base_usage_metadata", response.usage_metadata)
            setattr(combined_usage, "formatter_usage_metadata", formatter_usage)
            setattr(combined_usage, "formatter_model", MARKDOWN_FORMATTER_MODEL)

        logger.info(
            "Post-formateo markdown de explainer completado",
            extra={
                "formatter_calls": len(formatter_usage_items),
                "formatting_duration_ms": int(formatting_duration),
                "formatter_model": MARKDOWN_FORMATTER_MODEL,
            },
        )

        return result, combined_usage

    except json.JSONDecodeError as e:
        logger.error(
            f"Error al parsear JSON de respuesta: {str(e)}",
            extra={
                "error_type": "json_decode_error",
                "response_preview": response.text[:200] if response.text else "empty",
            }
        )
        raise
