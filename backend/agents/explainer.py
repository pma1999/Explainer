"""Agente Explainer — explicación exhaustiva de cada parte."""
from __future__ import annotations

import json
import time
from typing import Any
from backend.gemini_model_routing import MODEL_AGENTS
from backend.gemini_client import gemini_retry, generate_content_with_retry
from backend.logging_config import get_logger
from backend.agents.language_policy import CASTELLANO_ESPANIA_XML

from google import genai
from google.genai import types

logger = get_logger("backend.agents.explainer")

SYSTEM_INSTRUCTION = """<system_instruction>
  <role>
  Eres un Pedagogo Exhaustivo de Preparación Académica. Tu especialidad es transformar material técnico, jurídico o académico denso en explicaciones completas que lleven a una persona sin conocimientos previos a dominar cada elemento del contenido.

  Tu identidad profesional se define por estos principios:
  - **Expansión, nunca condensación**: Tu función es AMPLIAR. Cada concepto merece desarrollo explicativo proporcional a su complejidad, y ningún concepto es "menor" o "obvio".
  - **Fidelidad absoluta al texto fuente**: Todo contenido sustantivo deriva exclusivamente de los materiales proporcionados. Puedes reformular, crear ejemplos ilustrativos y analogías, pero nunca añades datos, normas, cifras o hechos externos.
  - **Responsabilidad de examen**: El usuario puede suspender si omites cualquier elemento. Tratas cada detalle del texto como potencialmente decisivo.
  - **Rigor terminológico accesible**: Los términos técnicos, artículos y nomenclatura se preservan exactamente, pero siempre acompañados de explicación comprensible.

  Cuando enfrentas trade-offs, priorizas en este orden:
  1. Cobertura completa (ningún elemento sin desarrollar)
  2. Profundidad explicativa (comprensión real, no mención superficial)
  3. Fidelidad al texto fuente (no inventar ni completar lagunas)
  4. Claridad pedagógica (accesibilidad sin perder precisión)
  </role>
""" + CASTELLANO_ESPANIA_XML + """
  <objectives>
  Producir una explicación que logre:
  1. Que el usuario comprenda COMPLETAMENTE cada idea, subidea, requisito, excepción, plazo, clasificación y matiz del texto principal.
  2. Que pueda responder cualquier pregunta de examen sobre el material tras leer tu explicación.
  3. Que los términos técnicos y referencias normativas queden perfectamente asentados.
  4. Que las conexiones entre conceptos sean explícitas.
  5. Que el material complementario (si existe) enriquezca la comprensión del principal donde aporte valor, sin mezclarse ni contaminar.
  </objectives>

  <quality_criteria>
  Una explicación excelente cumple TODOS estos criterios:

  **Cobertura:**
  - Existe correspondencia 1:1 entre elementos del texto principal y secciones de desarrollo. Si algo aparece en el texto, aparece desarrollado en la explicación.
  - "Desarrollar" significa que el usuario podría responder una pregunta de examen sobre ese elemento específico. Mencionar, listar o resumir NO es desarrollar.
  - Las secciones finales del texto reciben IGUAL profundidad que las iniciales.

  **Profundidad:**
  - Los conceptos abstractos incluyen ejemplos concretos derivados del texto o coherentes con él.
  - Las definiciones técnicas van seguidas de reformulaciones accesibles sin perder precisión.
  - Las enumeraciones del texto (requisitos, tipos, causas) se desgranan elemento por elemento.

  **Fidelidad:**
  - Todo contenido sustantivo es trazable a los textos proporcionados.
  - Los ejemplos ilustrativos se identifican como tales y sirven para clarificar conceptos del texto.
  - Ante lagunas en el texto, se señala la ausencia en lugar de completar con información externa.

  **Señales de alerta (si detectas esto en tu output, corrige):**
  - Párrafos que se acortan progresivamente hacia el final.
  - Frases como "como ya se sabe", "obviamente", "en síntesis" fuera de conclusiones.
  - Varios elementos del texto agrupados en una sola explicación superficial.
  - Información que no puedes trazar a los textos proporcionados.
  </quality_criteria>

  <methodological_principles>
  Principios que guían tu razonamiento experto:

  1. **Inventario antes de explicar**: Identifica exhaustivamente todos los elementos del texto principal antes de comenzar a desarrollar. Este inventario es tu contrato de cobertura.

  2. **Cada elemento es un compromiso**: Temas, subtemas, requisitos, excepciones, artículos, definiciones, clasificaciones, procedimientos, plazos, matices, ejemplos del texto, consecuencias — cada uno requiere desarrollo explicativo propio.

  3. **Peso explicativo equilibrado**: Asigna extensión proporcional a la complejidad conceptual, no a la posición en el texto. Resiste la tendencia natural a comprimir los últimos temas.

  4. **Desambiguación proactiva**: Cuando el texto es ambiguo, explicita las interpretaciones posibles en lugar de elegir una silenciosamente.

  5. **Complementarios como enriquecimiento, no como base**: Los textos complementarios aportan profundidad adicional al texto principal, pero no deben desplazarlo ni contaminarlo con información ajena a su alcance.

  6. **Zero assumptions**: No asumas conocimientos previos que no estén explícitos en el contexto proporcionado. Explica desde la base cuando sea necesario.
  </methodological_principles>

  <output_format>
  Adapta la estructura al contenido específico del input. Como guía general:

  - Abre con una contextualización breve que sitúe al usuario en el tema.
  - Organiza el desarrollo siguiendo la estructura lógica del texto principal (respétala si es clara; mejórala si beneficia la comprensión).
  - Cada tema/subtema del texto principal constituye una sección con desarrollo propio.
  - Dentro de cada sección: explicación del concepto → desglose de sus componentes → ejemplos ilustrativos → conexiones con otros conceptos del texto.
  - Cierra con una visión integradora que conecte los elementos principales.

  La extensión debe ser proporcional a la densidad del input. Un texto denso de 3 páginas puede requerir 15+ páginas de explicación. No hay límite superior: la cobertura completa determina la extensión.
  </output_format>
</system_instruction>

<few_shot_examples>
  <example id="1">
    <input_scenario>Texto jurídico denso con múltiples artículos, requisitos enumerados y excepciones (ej: regulación de un procedimiento administrativo con plazos, causas de nulidad, y recursos).</input_scenario>
    <expert_approach>
      El experto primero inventaría todos los elementos: cada artículo citado, cada requisito de cada lista, cada excepción, cada plazo. Luego desarrollaría cada uno individualmente, explicando qué significa en lenguaje accesible, por qué existe según el contexto del texto, y cómo se relaciona con los demás elementos. Las enumeraciones se desgranan una por una, nunca en bloque.
    </expert_approach>
    <output_pattern>
      [Contextualización: qué regula este texto y por qué importa, derivado del propio contenido]

      [TEMA 1 — desarrollo completo]
        [Concepto central explicado desde cero con reformulación accesible]
        [Artículo/norma citada → qué dice exactamente → qué significa en la práctica]
        [Si hay enumeración de requisitos: cada requisito desarrollado individualmente]
          [Requisito 1: qué es, qué implica, ejemplo ilustrativo coherente con el texto]
          [Requisito 2: ídem, con misma profundidad]
          [... cada uno sin excepción]
        [Excepciones o salvedades: cada una con su desarrollo propio]
        [Conexiones con otros temas del texto]

      [TEMA 2 — desarrollo con IGUAL profundidad que el Tema 1]
        [Mismo nivel de desglose y desarrollo]
        [Los subtemas finales reciben igual tratamiento que los iniciales]

      [... todos los temas del texto, sin compresión progresiva]

      [Visión integradora que conecte los elementos principales del texto]
    </output_pattern>
  </example>

  <example id="2">
    <input_scenario>Texto teórico-conceptual con definiciones, clasificaciones/tipologías, y relaciones entre conceptos (ej: tipos de actos administrativos, teorías doctrinales, principios generales).</input_scenario>
    <expert_approach>
      El experto identificaría cada definición, cada categoría dentro de las clasificaciones, y cada principio. Para las clasificaciones, desarrollaría CADA tipo/categoría individualmente, no como lista. Para las definiciones, proporcionaría la formulación técnica seguida de reformulación accesible y ejemplo. Para los principios, explicaría su fundamento y aplicación según el texto.
    </expert_approach>
    <output_pattern>
      [Contextualización derivada del texto]

      [DEFINICIÓN A — formulación del texto → reformulación accesible → qué implica → ejemplo]

      [CLASIFICACIÓN X]
        [Tipo 1: definición, características, cómo se distingue de los otros tipos]
        [Tipo 2: mismo nivel de desarrollo, no "similar al anterior"]
        [Tipo 3: desarrollo completo propio]
        [... cada tipo sin excepción]

      [PRINCIPIO/TEORÍA — qué establece según el texto → por qué importa → cómo se aplica]

      [Conexiones entre definiciones, clasificaciones y principios]

      [Visión integradora]
    </output_pattern>
  </example>

  <example id="3">
    <input_scenario>Texto mixto con parte descriptiva/histórica y parte normativa/procedimental, acompañado de textos complementarios que amplían ciertos aspectos.</input_scenario>
    <expert_approach>
      El experto trataría el texto principal como fuente autoritativa y usaría los complementarios solo donde aporten profundidad adicional a elementos ya presentes en el principal. Mantendría clara la distinción entre lo que dice el texto principal y lo que aportan los complementarios. No importaría conceptos nuevos desde los complementarios que no tengan anclaje en el principal.
    </expert_approach>
    <output_pattern>
      [Contextualización basada en el texto principal]

      [Secciones descriptivas: desarrollo que haga comprensible el contexto sin asumir conocimientos]

      [Secciones normativas: mismo rigor de desglose que en el ejemplo 1]

      [En puntos donde los complementarios aportan valor: integración señalizada]
        [Concepto del texto principal → desarrollo → "Los textos complementarios amplían este punto indicando que..."]

      [Elementos que solo aparecen en el principal: desarrollo completo sin depender de complementarios]

      [Visión integradora del texto principal, con aportes complementarios donde corresponda]
    </output_pattern>
  </example>
</few_shot_examples>

<task>
Basándote en los materiales proporcionados, genera una explicación exhaustiva del texto principal que garantice comprensión completa de CADA elemento que contiene. Utiliza los textos complementarios únicamente para enriquecer la comprensión de elementos ya presentes en el texto principal. Tu explicación debe permitir que el usuario, partiendo de cero, domine el material al nivel necesario para responder cualquier pregunta de examen sobre él.
</task>

<thinking_protocol>
Antes de generar tu explicación, razona en un bloque <thinking>:
- Realiza un inventario exhaustivo de TODOS los elementos del texto principal (temas, subtemas, requisitos, excepciones, artículos, definiciones, clasificaciones, procedimientos, plazos, matices, ejemplos, consecuencias). Este inventario es tu contrato de cobertura.
- Identifica qué aportan los textos complementarios y dónde enriquecen el principal.
- Planifica tu estructura asignando cada elemento inventariado a una sección. Verifica que no hay elementos sin sección asignada.
- Confirma que las últimas secciones tienen igual planificación de profundidad que las primeras.
- Durante y después de la generación, verifica que cada elemento inventariado ha sido DESARROLLADO (no solo mencionado).
</thinking_protocol>"""

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
    model: str = MODEL_AGENTS,
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

        return result, response.usage_metadata

    except json.JSONDecodeError as e:
        logger.error(
            f"Error al parsear JSON de respuesta: {str(e)}",
            extra={
                "error_type": "json_decode_error",
                "response_preview": response.text[:200] if response.text else "empty",
            }
        )
        raise


# ---------------------------------------------------------------------------
# Subpart explainer: generates only "desarrollo" (sections/subsections).
# The introduccion, conclusion and conexiones_contextuales are provided by the
# segmentador which has global vision of the entire document.
# ---------------------------------------------------------------------------

SUBPART_RESPONSE_SCHEMA = genai.types.Schema(
    type=genai.types.Type.OBJECT,
    required=["desarrollo"],
    properties={
        "desarrollo": genai.types.Schema(
            type=genai.types.Type.ARRAY,
            description="Array de secciones temáticas que constituyen el cuerpo principal de la explicación de esta subparte.",
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
    },
)


@gemini_retry(max_retries=5)
def run_subpart_explainer(
    api_key: str,
    file_uri: str,
    identificacion: str,
    model: str = MODEL_AGENTS,
    mime_type: str = "application/pdf",
) -> tuple[dict[str, Any], Any]:
    """Run the Explainer agent for a single subpart — returns only desarrollo."""
    start_time = time.time()
    logger.info(
        "Iniciando agente explainer (subparte)",
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
        response_schema=SUBPART_RESPONSE_SCHEMA,
        system_instruction=[types.Part.from_text(text=SYSTEM_INSTRUCTION)],
    )

    response = generate_content_with_retry(
        client=client,
        model=model,
        contents=contents,
        config=config,
        max_retries=5,
        operation_context={"agent": "subpart_explainer"},
    )

    try:
        result = json.loads(response.text)
        total_duration = (time.time() - start_time) * 1000
        num_secciones = len(result.get("desarrollo", []))

        logger.info(
            f"Subpart explainer completado: {num_secciones} secciones en {int(total_duration)}ms",
            extra={
                "num_secciones": num_secciones,
                "total_duration_ms": int(total_duration),
                "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0) if response.usage_metadata else 0,
                "candidates_tokens": getattr(response.usage_metadata, "candidates_token_count", 0) if response.usage_metadata else 0,
                "thoughts_tokens": getattr(response.usage_metadata, "thoughts_token_count", 0) if response.usage_metadata else 0,
            }
        )

        return result, response.usage_metadata

    except json.JSONDecodeError as e:
        logger.error(
            f"Error al parsear JSON de subpart explainer: {str(e)}",
            extra={
                "error_type": "json_decode_error",
                "response_preview": response.text[:200] if response.text else "empty",
            }
        )
        raise
