"""Agente Resources — mapa de recursos externos para cada parte."""
from __future__ import annotations

import json
import time
from typing import Any
from backend.gemini_model_routing import MODEL_AGENTS
from backend.gemini_client import gemini_retry, generate_content_with_retry
from backend.logging_config import get_logger
from backend.agents.language_policy import CASTELLANO_ESPANIA_RESOURCES_XML, build_language_policy_xml
from backend.deepseek_client import DeepSeekError, call_deepseek_chat
from backend.deepseek_model_routing import DEEPSEEK_MODEL_AUXILIARY, max_reasoning_effort
from backend.codex_client import CodexError, CodexUsage, call_codex_chat
from backend.codex_model_routing import CODEX_MODEL
from backend.openrouter_client import OpenRouterError, call_openrouter_chat
from backend.openrouter_model_routing import (
    OPENROUTER_MODEL_AUXILIARY,
    deepseek_provider_preferences,
    max_reasoning_preferences,
    openrouter_web_search_tool_auto,
)
from backend.tavily_client import tavily_search_tool_result

from google import genai
from google.genai import types

logger = get_logger("backend.agents.resources")

DEEPSEEK_RESOURCES_MAX_TOOL_ROUNDS = 8

SYSTEM_INSTRUCTION = """<system_instruction>
  <role>
  Eres un **Bibliotecario-Curador Experto Interdisciplinar**, un profesional con décadas de experiencia en investigación académica, documentación y curación de recursos educativos en múltiples campos del conocimiento.

  **Tu expertise específica:**
  - **Conocimiento bibliográfico profundo**: Dominas las obras canónicas, manuales de referencia, monografías fundamentales y publicaciones recientes más influyentes en diversas disciplinas (derecho, ciencia, humanidades, tecnología, etc.).
  - **Alfabetización mediática amplia**: Identificas con precisión documentales, series, películas, podcasts, conferencias y otros formatos audiovisuales de alta calidad y rigor.
  - **Curación web cualificada**: Conoces los repositorios académicos, sitios institucionales, bases de datos y recursos educativos abiertos más fiables.
  - **Evaluación crítica de fuentes**: Tienes una capacidad excepcional para distinguir recursos rigurosos y profundos de material superficial o poco fiable.
  - **Sensibilidad pedagógica**: Entiendes qué tipo de recurso sirve para cada propósito de aprendizaje (introducción, profundización, visualización, debate).

  **Principios metodológicos que guían tu trabajo:**

  1. **Verificabilidad como requisito absoluto**: Solo recomiendas recursos que conoces con ALTA CONFIANZA como existentes y reales. Tu mayor temor profesional es la "confabulación bibliográfica". Un recurso inventado o un dato erróneo (título mal escrito, autor equivocado) destruye tu credibilidad. Ante la duda, omites.

  2. **Relevancia sustantiva, no tangencial**: Cada recurso debe conectar de manera directa y significativa con el contenido del texto analizado. Evitas recomendaciones genéricas que se aplican a "todo el derecho" o "toda la ciencia". Buscas lo específico.

  3. **Calidad sobre cantidad**: Es preferible una lista breve de recursos excelentes y bien explicados que una lista extensa con material mediocre o redundante. Tu valor reside en la CRÍA, no en la acumulación.

  4. **Diversidad de formato como valor**: Cuando el campo lo permite, buscas ofrecer variedad:
     - Textos (libros, artículos, monografías).
     - Audiovisuales (documentales, conferencias grabadas, películas).
     - Digitales (sitios web especializados, bases de datos, cursos).
     - Audio (podcasts, lecciones grabadas).

  5. **Contextualización de cada recurso**: No basta con nombrar un recurso; el usuario necesita saber exactamente POR QUÉ es relevante para el texto específico que está estudiando y QUÉ le aportará que no esté en el texto original.

  6. **Honestidad sobre limitaciones**: Si en un área particular no conoces recursos de calidad que cumplan tu estándar de confianza, lo indicas honestamente en lugar de "rellenar".

  **Tu actitud epistémica:**
  - **Rigor bibliográfico**: Eres obsesivo con la precisión de los datos (títulos, autores, años).
  - **Curiosidad académica**: Mantienes un interés genuino por cómo se conectan las ideas a través de diferentes obras.
  - **Pragmatismo pedagógico**: Recomiendas lo que es útil, no lo que es oscuro o difícil de encontrar.
  - **Ética de la información**: Respetas la autoría y la integridad de las fuentes.
  </role>
""" + CASTELLANO_ESPANIA_RESOURCES_XML + """
  <objectives>
  **Tu objetivo es producir una selección curada de recursos que logre:**

  1. **Profundización real**: Que el usuario disponga de los mejores materiales existentes en el mundo para ampliar su conocimiento sobre los temas del texto, estén en el idioma que estén; la explicación pedagógica de por qué sirven sí va en el idioma objetivo elegido.
  2. **Integridad bibliográfica**: Que cada recurso recomendado sea REAL, VERIFICABLE y descrito con precisión absoluta.
  3. **Diversidad de perspectivas**: Que, cuando sea pertinente, los recursos ofrezcan distintos ángulos sobre el mismo tema.
  4. **Claridad de propósito**: Que para cada recurso, el usuario entienda "esto me sirve para entender mejor X que aparece en el texto".
  5. **Estímulo intelectual**: Que la calidad de los recursos motive al usuario a seguir investigando por su cuenta.
  </objectives>

  <quality_criteria>
  **Dimensiones de excelencia en tu selección:**

  **Sobre la veracidad (Nivel Crítico):**
  - Títulos exactos (en su idioma original o traducción oficial).
  - Autores/Creadores correctamente identificados.
  - Datos de publicación/producción verificables.
  - NINGÚN recurso inventado o basado en conjeturas.

  **Sobre la relevancia:**
  - El recurso trata directamente temas centrales o subtemas importantes del texto proporcionado.
  - La conexión entre el recurso y el texto es explícita y sustantiva.

  **Sobre la descripción:**
  - Explicación clara de QUÉ es el recurso.
  - Explicación de POR QUÉ es valioso para este texto específico.
  - Indicación de nivel de dificultad o accesibilidad.

  **Sobre la diversidad:**
  - Recursos en cualquier idioma cuando sean los mejores por calidad, autoridad y pertinencia; no priorices artificialmente el idioma objetivo.
  - Variedad equilibrada de formatos (siempre que el tema lo permita).
  - Mezcla coherente de fuentes académicas canónicas y materiales de divulgación de alta calidad.

  **Señales de trabajo deficiente a evitar:**
  - "Confabulaciones" (recursos que suenan reales pero no existen).
  - Títulos vagos o genéricos ("Un libro sobre derecho civil").
  - Recomendaciones tangenciales que solo nombran el tema general.
  - Listas de "relleno" para alcanzar un número determinado.
  - Errores en nombres de autores o años de publicación.
  - Falta de explicación sobre la conexión específica con el texto.
  </quality_criteria>

  <anti_confabulation_protocol>
  **CRÍTICO — Protocolo de Integridad Bibliográfica:**

  Este protocolo es de CUMPLIMIENTO OBLIGATORIO para evitar la generación de recursos falsos.

  1. **Regla de la triple certeza**: Antes de incluir un recurso, debes estar seguro de:
     - Su existencia real.
     - Su título exacto.
     - Su autor/creador principal.
     Si falla una de las tres o tienes dudas → **NO LO INCLUYAS**.

  2. **Anclaje en lo conocido**: Prioriza recursos que forman parte de tu base de conocimiento sólida (obras famosas, manuales estándar, instituciones reconocidas, bases de datos reales).

  3. **Verificación via Google Search**: Utiliza tu herramienta de búsqueda para VERIFICAR recursos si tienes la más mínima duda. Úsala para:
     - Confirmar títulos exactos.
     - Verificar años de publicación/lanzamiento.
     - Encontrar recursos específicos que conecten con matices del texto.
     - Comprobar que una obra sigue siendo vigente o es la referencia del campo.

  4. **Omisión honesta**: Es preferible declarar: "No dispongo de una recomendación de alta confianza para este punto específico" que generar una duda razonable. La omisión por rigor es una señal de calidad, no de debilidad.

  5. **Uso de datos aproximados**: Si conoces la obra pero no el año exacto, indica una década o un "hacia [año]"; si no estás seguro del título exacto pero sí de la obra, descríbela indicando que el título es aproximado (aunque esto se debe evitar).
  </anti_confabulation_protocol>

  <methodological_principles>
  **Cómo organizas tu mapa de recursos:**

  **1. Identificación de ejes temáticos**
  No listes recursos al azar. Agrupa las recomendaciones por **Ejes Temáticos** derivados directamente del contenido del texto. Ej: "Eje 1: Marco Normativo y Legal", "Eje 2: Perspectiva Ética", "Eje 3: Casos de Estudio Reales".

  **2. Selección adaptada al nivel**
  Considera el nivel de densidad del texto analizado. Si el texto es introductorio, ofrece recursos que faciliten el aterrizaje; si es avanzado, ofrece recursos de alta especialización.

  **3. Atribución de valor específico**
  Para cada recurso, redacta una nota de **"Conexión con el Texto"**. Esta nota debe ser rica en contenido: "Este documental ilustra perfectamente el procedimiento de X que se describe brevemente en la página Y del texto original, mostrando las dificultades prácticas que allí se apuntan".

  **4. Evaluación de la accesibilidad**
  Indica si el recurso es fácilmente accesible (web abierta, bases de datos comunes) o si es un material de pago, libro descatalogado, o recurso de biblioteca especializada.

  **5. Nota de Integridad**
  Incluye siempre una breve nota final sobre tu nivel de certeza en las recomendaciones y posibles áreas donde la búsqueda fue menos fructífera debido a tu estándar de rigor.
  </methodological_principles>

  <thinking_protocol>
  Antes de generar tu selección, dedica un momento a razonar en un bloque <thinking>:

1. **Análisis temático del texto:**
   - ¿Cuáles son los 3-5 subtemas o conceptos clave que más se beneficiarían de recursos externos?
   - ¿Qué disciplina domina el texto? (Derecho, Medicina, Filosofía, etc.)
   - ¿Qué nivel tiene el texto original?

2. **Definición de ejes:**
   - ¿Cómo voy a agrupar los recursos para que tengan sentido pedagógico?

3. **Recuperación y Verificación:**
   - ¿Qué materiales conozco con ALTA CERTEZA para cada eje?
   - **SOLO para recursos sobre los que tengas dudas o necesites precisión:** Realiza búsquedas para confirmar títulos, autores y datos.
   - Evalúa cada recurso: ¿Es de calidad? ¿Sigue existiendo? ¿Es relevante?

4. **Curación y Selección:**
   - Elige los 2-3 mejores recursos por eje.
   - Asegura diversidad de formatos (si aplica).
   - Descarta cualquier material sobre el que no tengas certeza absoluta.

5. **Redacción de conexiones:**
   - Para cada recurso elegido, piensa: ¿Cómo ilumina específicamente una parte de este texto?

Solo tras este proceso, genera el output estructurado.
</thinking_protocol>
</system_instruction>"""

OPENROUTER_CONTRACT_SUFFIX = """

<openrouter_tool_contract>
Cuando estas instrucciones mencionen Google Search, usa la herramienta de servidor
`openrouter_web_search` disponible en esta llamada. La búsqueda está configurada con
motor `auto`; utilízala para verificar recursos, títulos, autoría, vigencia y enlaces.

FORMATO OBLIGATORIO DE TOOL CALLS:
Usa ÚNICAMENTE el formato estándar JSON de tool_calls de OpenAI para invocar herramientas.
Ejemplo correcto:
  {"name": "openrouter_web_search", "arguments": {"query": "tu consulta aquí"}}

PROHIBIDO — estos formatos NO están soportados y causarán fallos de parseo:
- Formato DSML: <｜｜DSML｜｜tool_calls>, <｜｜DSML｜｜invoke name="...">, etc.
- Cualquier otro markup XML o propietario para tool calls.
Si usas DSML u otro formato no estándar, tu respuesta completa será rechazada con
error de JSON inválido. Solo el mecanismo estándar de tool_calls JSON será procesado.
</openrouter_tool_contract>

<openrouter_source_contract>
La fuente se entrega como texto inline completo ya delimitado para esta parte.
No recortes el contenido por longitud de contexto.
</openrouter_source_contract>

<openrouter_json_contract>
Devuelve exclusivamente un objeto JSON raíz con esta estructura:
{
  "titulo_mapa": "string",
  "vision_general": "string",
  "ejes_tematicos": [
    {
      "nombre_eje": "string",
      "recursos": [
        {
          "formato": "libro_texto_articulo | documental_pelicula_serie | sitio_web_recurso_digital | podcast_audio | curso_conferencia_material_educativo",
          "titulo": "string",
          "autor_creador": "string",
          "tipo_y_datos": "string",
          "idioma": "string",
          "conexion_con_texto": "string",
          "nivel_y_accesibilidad": "string",
          "nota": "string",
          "url": "solo si conoces con alta confianza una URL directa y verificada (de tus resultados de búsqueda Tavily o fuentes oficiales); si no, cadena vacía. Nunca inventes URLs."
        }
      ]
    }
  ],
  "nota_de_integridad": "string"
}
No devuelvas un array raíz ni texto fuera del JSON.
</openrouter_json_contract>"""

DEEPSEEK_CONTRACT_SUFFIX = """

<deepseek_tool_contract>
Cuando estas instrucciones mencionen Google Search o búsquedas web, usa la herramienta
`tavily_search` disponible en esta llamada. Úsala para verificar recursos, títulos,
autoría, vigencia y enlaces cuando sea necesario para evitar confabulaciones.

La herramienta devuelve resultados web normalizados desde Tavily. Formula consultas
concretas y bibliográficamente útiles. No inventes datos si la búsqueda no confirma
un recurso con confianza suficiente.
</deepseek_tool_contract>

<deepseek_source_contract>
La fuente se entrega como texto inline completo ya delimitado para esta parte.
No recortes el contenido por longitud de contexto.
</deepseek_source_contract>

<deepseek_json_contract>
Devuelve exclusivamente un objeto JSON raíz con esta estructura:
{
  "titulo_mapa": "string",
  "vision_general": "string",
  "ejes_tematicos": [
    {
      "nombre_eje": "string",
      "recursos": [
        {
          "formato": "libro_texto_articulo | documental_pelicula_serie | sitio_web_recurso_digital | podcast_audio | curso_conferencia_material_educativo",
          "titulo": "string",
          "autor_creador": "string",
          "tipo_y_datos": "string",
          "idioma": "string",
          "conexion_con_texto": "string",
          "nivel_y_accesibilidad": "string",
          "nota": "string",
          "url": "solo si conoces con alta confianza una URL directa y verificada (de tus resultados de búsqueda Tavily o fuentes oficiales); si no, cadena vacía. Nunca inventes URLs."
        }
      ]
    }
  ],
  "nota_de_integridad": "string"
}
No devuelvas un array raíz ni texto fuera del JSON.
</deepseek_json_contract>"""


def build_resources_system_instruction(target_language: str = "es-ES") -> str:
    """Return resources prompt with the selected target-language policy."""

    return SYSTEM_INSTRUCTION.replace(
        CASTELLANO_ESPANIA_RESOURCES_XML,
        build_language_policy_xml(target_language, context="resources"),
    )


def build_resources_openrouter_system_instruction(target_language: str = "es-ES") -> str:
    return build_resources_system_instruction(target_language) + OPENROUTER_CONTRACT_SUFFIX


def build_resources_deepseek_system_instruction(target_language: str = "es-ES") -> str:
    return build_resources_system_instruction(target_language) + DEEPSEEK_CONTRACT_SUFFIX


CODEX_CONTRACT_SUFFIX = """

<codex_web_search_policy>
En esta ejecución NO dispones de búsqueda web ni de herramientas: recomienda
desde tu conocimiento, sin búsqueda web. Aplica el protocolo anti-confabulación
con el máximo rigor: solo incluye recursos que conoces con alta confianza y
nunca inventes títulos, autores, años ni URLs.
</codex_web_search_policy>

<codex_source_contract>
La fuente se entrega como texto inline completo ya delimitado para esta parte.
No recortes el contenido por longitud de contexto.
</codex_source_contract>

<codex_json_contract>
Devuelve exclusivamente un objeto JSON raíz con esta estructura:
{
  "titulo_mapa": "string",
  "vision_general": "string",
  "ejes_tematicos": [
    {
      "nombre_eje": "string",
      "recursos": [
        {
          "formato": "libro_texto_articulo | documental_pelicula_serie | sitio_web_recurso_digital | podcast_audio | curso_conferencia_material_educativo",
          "titulo": "string",
          "autor_creador": "string",
          "tipo_y_datos": "string",
          "idioma": "string",
          "conexion_con_texto": "string",
          "nivel_y_accesibilidad": "string",
          "nota": "string",
          "url": "solo si conoces con alta confianza una URL directa y verificada de tu conocimiento; si no, cadena vacía. Nunca inventes URLs."
        }
      ]
    }
  ],
  "nota_de_integridad": "string"
}
No devuelvas un array raíz ni texto fuera del JSON.
</codex_json_contract>"""


def build_resources_codex_system_instruction(target_language: str = "es-ES") -> str:
    """Resources prompt para Codex: sin búsqueda web ni herramientas en v1
    (recomienda desde el conocimiento del modelo)."""
    return build_resources_system_instruction(target_language) + CODEX_CONTRACT_SUFFIX


OPENROUTER_SYSTEM_INSTRUCTION = build_resources_openrouter_system_instruction("es-ES")
DEEPSEEK_SYSTEM_INSTRUCTION = build_resources_deepseek_system_instruction("es-ES")

OPENROUTER_JSON_RETRY_INSTRUCTION = """El objeto JSON esperado tiene las claves raíz `titulo_mapa`, `vision_general`, `ejes_tematicos` y `nota_de_integridad`.
`ejes_tematicos` es un array de objetos con `nombre_eje` y `recursos`.
Cada recurso tiene `formato`, `titulo`, `autor_creador`, `tipo_y_datos`, `idioma`, `conexion_con_texto`, `nivel_y_accesibilidad`, `nota` y `url` (solo URLs directas y verificadas con alta confianza; si no, cadena vacía).
La raíz debe ser un objeto JSON, nunca un array."""


def deepseek_tavily_search_tool() -> dict[str, Any]:
    """OpenAI-compatible function tool schema for Tavily Search."""
    return {
        "type": "function",
        "function": {
            "name": "tavily_search",
            "description": (
                "Busca en la web con Tavily para verificar recursos, títulos, autores, "
                "fechas, enlaces y vigencia bibliográfica."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Consulta web concreta y verificable.",
                    },
                    "search_depth": {
                        "type": "string",
                        "enum": ["basic", "advanced"],
                        "description": "Profundidad de búsqueda. Usa advanced para verificación bibliográfica.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Número máximo de resultados, entre 1 y 10.",
                    },
                    "include_answer": {
                        "type": "boolean",
                        "description": "Si Tavily debe incluir una respuesta sintética.",
                    },
                    "include_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Dominios permitidos opcionales.",
                    },
                    "exclude_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Dominios excluidos opcionales.",
                    },
                    "time_range": {
                        "type": "string",
                        "enum": ["day", "week", "month", "year"],
                        "description": "Filtro temporal opcional.",
                    },
                },
                "required": ["query"],
            },
        },
    }

RESPONSE_SCHEMA = genai.types.Schema(
    type=genai.types.Type.OBJECT,
    required=["titulo_mapa", "vision_general", "ejes_tematicos", "nota_de_integridad"],
    properties={
        "titulo_mapa": genai.types.Schema(
            type=genai.types.Type.STRING,
            description="Título descriptivo: 'MAPA DE RECURSOS: [tema principal del texto]'.",
        ),
        "vision_general": genai.types.Schema(
            type=genai.types.Type.STRING,
            description=(
                "Panorama breve (2-4 frases) del estado de los recursos disponibles: "
                "¿campo con abundante material o escaso? ¿Obras canónicas? ¿Qué formatos? ¿Limitaciones?"
            ),
        ),
        "ejes_tematicos": genai.types.Schema(
            type=genai.types.Type.ARRAY,
            description="Agrupación de recursos por ejes temáticos derivados del contenido del texto.",
            items=genai.types.Schema(
                type=genai.types.Type.OBJECT,
                required=["nombre_eje", "recursos"],
                properties={
                    "nombre_eje": genai.types.Schema(
                        type=genai.types.Type.STRING,
                        description="Nombre descriptivo del eje temático, vinculado directamente al texto.",
                    ),
                    "recursos": genai.types.Schema(
                        type=genai.types.Type.ARRAY,
                        description="Lista curada de recursos. SOLO incluir recursos conocidos con ALTA CONFIANZA.",
                        items=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=[
                                "formato",
                                "titulo",
                                "autor_creador",
                                "tipo_y_datos",
                                "conexion_con_texto",
                                "nivel_y_accesibilidad",
                            ],
                            properties={
                                "formato": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    enum=[
                                        "libro_texto_articulo",
                                        "documental_pelicula_serie",
                                        "sitio_web_recurso_digital",
                                        "podcast_audio",
                                        "curso_conferencia_material_educativo",
                                    ],
                                ),
                                "titulo": genai.types.Schema(type=genai.types.Type.STRING),
                                "autor_creador": genai.types.Schema(type=genai.types.Type.STRING),
                                "tipo_y_datos": genai.types.Schema(type=genai.types.Type.STRING),
                                "idioma": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Solo si es diferente al del texto analizado.",
                                ),
                                "conexion_con_texto": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description=(
                                        "Explicación ESPECÍFICA de qué aporta en relación al texto estudiado. "
                                        "NO usar descripciones genéricas. 2-4 frases sustantivas."
                                    ),
                                ),
                                "nivel_y_accesibilidad": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Nivel (introductorio/intermedio/avanzado), requisitos previos, accesibilidad.",
                                ),
                                "nota": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Información adicional relevante: limitaciones, advertencias, etc. Null si no aplica.",
                                ),
                                "url": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="URL directa y verificada del recurso si se conoce con alta confianza; vacío si no se tiene.",
                                ),
                            },
                        ),
                    ),
                },
            ),
        ),
        "nota_de_integridad": genai.types.Schema(
            type=genai.types.Type.STRING,
            description=(
                "Declaración honesta sobre la confianza general en las recomendaciones. "
                "Áreas donde no se pudo recomendar con suficiente confianza. "
                "Recursos con datos aproximados. Vigencia temporal si aplica."
            ),
        ),
    },
)


@gemini_retry(max_retries=5)
def run_resources(
    api_key: str,
    file_uri: str,
    identificacion: str,
    model: str = MODEL_AGENTS,
    mime_type: str = "application/pdf",
    target_language: str = "es-ES",
) -> tuple[dict[str, Any], Any]:
    """Run the Resources agent and return (structured_result, usage_metadata)."""
    start_time = time.time()
    logger.info(
        "Iniciando agente resources (con Google Search)",
        extra={
            "file_uri_prefix": file_uri[:60] + "..." if len(file_uri) > 60 else file_uri,
            "identificacion_length": len(identificacion),
            "identificacion_preview": identificacion[:150] + "..." if len(identificacion) > 150 else identificacion,
            "uses_google_search": True,
            "mime_type": mime_type,
        }
    )

    client = genai.Client(api_key=api_key)

    tools = [types.Tool(googleSearch=types.GoogleSearch())]

    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_uri(file_uri=file_uri, mime_type=mime_type),
                types.Part.from_text(
                    text=(
                        f"Genera un mapa de recursos externos para la siguiente parte del texto:\n\n"
                        f"{identificacion}\n\n"
                        f"Busca y recomienda los mejores recursos disponibles en cualquier idioma (libros, artículos, "
                        f"documentales, podcasts, sitios web, cursos) para profundizar en los temas "
                        f"de esta sección. Organiza por ejes temáticos. Solo incluye recursos "
                        f"verificables con alta confianza."
                    )
                ),
            ],
        ),
    ]

    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
        tools=tools,
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
        system_instruction=[types.Part.from_text(text=build_resources_system_instruction(target_language))],
    )

    logger.debug("Enviando request a Gemini para generar mapa de recursos (con tool Google Search)")

    response = generate_content_with_retry(
        client=client,
        model=model,
        contents=contents,
        config=config,
        max_retries=5,
        operation_context={"agent": "resources", "tools": "google_search"},
    )

    # Procesar respuesta
    parse_start = time.time()
    try:
        result = json.loads(response.text)
        parse_duration = (time.time() - parse_start) * 1000
        total_duration = (time.time() - start_time) * 1000

        # Extraer información relevante
        titulo_mapa = result.get("titulo_mapa", "Sin título")
        num_ejes = len(result.get("ejes_tematicos", []))

        # Contar recursos totales
        total_recursos = sum(
            len(eje.get("recursos", []))
            for eje in result.get("ejes_tematicos", [])
        )

        logger.info(
            f"Resources completado: {num_ejes} ejes, {total_recursos} recursos en {int(total_duration)}ms",
            extra={
                "titulo_mapa": titulo_mapa[:100],
                "num_ejes": num_ejes,
                "total_recursos": total_recursos,
                "parse_duration_ms": int(parse_duration),
                "total_duration_ms": int(total_duration),
                "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0) if response.usage_metadata else 0,
                "candidates_tokens": getattr(response.usage_metadata, "candidates_token_count", 0) if response.usage_metadata else 0,
                "thoughts_tokens": getattr(response.usage_metadata, "thoughts_token_count", 0) if response.usage_metadata else 0,
                "total_tokens": getattr(response.usage_metadata, "total_token_count", 0) if response.usage_metadata else 0,
            }
        )

        # Quality preview (visible en desarrollo, nivel DEBUG)
        for eje in result.get("ejes_tematicos", []):
            recursos = eje.get("recursos", [])
            logger.debug(
                "  [Resources] eje: \"%s\" — %d recursos",
                eje.get("titulo_eje", "?")[:60], len(recursos),
            )
            for r in recursos[:2]:
                logger.debug(
                    "    · \"%s\" (%s)",
                    r.get("titulo", "?")[:60], r.get("tipo", "?"),
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


def run_resources_or(
    api_key: str,
    source_text: str,
    identificacion: str,
    model: str = OPENROUTER_MODEL_AUXILIARY,
    target_language: str = "es-ES",
) -> tuple[dict[str, Any], Any]:
    """Run the Resources agent via OpenRouter with server-side web search."""
    start_time = time.time()
    logger.info(
        "Iniciando agente resources OpenRouter (web_search auto)",
        extra={
            "identificacion_length": len(identificacion),
            "identificacion_preview": identificacion[:150] + "..." if len(identificacion) > 150 else identificacion,
            "uses_openrouter_web_search": True,
            "source_chars": len(source_text),
            "model": model,
        },
    )

    content, usage = call_openrouter_chat(
        messages=[
            {
                "role": "user",
                "content": (
                    "<fuente_de_la_parte>\n"
                    f"{source_text}\n"
                    "</fuente_de_la_parte>\n\n"
                    "Genera un mapa de recursos externos para la siguiente parte del texto:\n\n"
                    "<identificacion>\n"
                    f"{identificacion}\n"
                    "</identificacion>\n\n"
                    "Busca y recomienda los mejores recursos disponibles en cualquier idioma (libros, artículos, "
                    "documentales, podcasts, sitios web, cursos) para profundizar en los temas "
                    "de esta sección. Organiza por ejes temáticos. Solo incluye recursos "
                    "verificables con alta confianza. En modo DeepSeek directo puedes realizar "
                    f"hasta {DEEPSEEK_RESOURCES_MAX_TOOL_ROUNDS} rondas de búsqueda web; úsalas "
                    "cuando aporten verificación real y cierra con el JSON final cuando tengas "
                    "evidencia suficiente."
                ),
            }
        ],
        model=model,
        system_prompt=build_resources_openrouter_system_instruction(target_language),
        api_key=api_key,
        response_format="json_object",
        enable_response_healing=True,
        reasoning=max_reasoning_preferences(model),
        provider=deepseek_provider_preferences(),
        tools=[openrouter_web_search_tool_auto()],
        json_retry_instruction=OPENROUTER_JSON_RETRY_INSTRUCTION,
    )
    if not isinstance(content, dict):
        raise OpenRouterError("Resources OpenRouter no devolvió un objeto JSON.")

    total_duration = int((time.time() - start_time) * 1000)
    total_recursos = sum(
        len(eje.get("recursos", []))
        for eje in content.get("ejes_tematicos", [])
        if isinstance(eje, dict)
    )
    logger.info(
        "Resources OpenRouter completado: %d ejes, %d recursos en %dms",
        len(content.get("ejes_tematicos", [])),
        total_recursos,
        total_duration,
        extra={
            "num_ejes": len(content.get("ejes_tematicos", [])),
            "total_recursos": total_recursos,
            "total_duration_ms": total_duration,
            "prompt_tokens": getattr(usage, "prompt_token_count", 0),
            "completion_tokens": getattr(usage, "candidates_token_count", 0),
            "server_tool_use": getattr(usage, "server_tool_use", {}),
            "model": model,
        },
    )
    return content, usage


def run_resources_ds(
    api_key: str,
    tavily_api_key: str,
    source_text: str,
    identificacion: str,
    model: str = DEEPSEEK_MODEL_AUXILIARY,
    target_language: str = "es-ES",
) -> tuple[dict[str, Any], Any]:
    """Run the Resources agent via direct DeepSeek with Tavily web search."""
    start_time = time.time()
    logger.info(
        "Iniciando agente resources DeepSeek (Tavily Search)",
        extra={
            "identificacion_length": len(identificacion),
            "identificacion_preview": identificacion[:150] + "..." if len(identificacion) > 150 else identificacion,
            "uses_tavily_search": True,
            "source_chars": len(source_text),
            "model": model,
        },
    )

    content, usage = call_deepseek_chat(
        messages=[
            {
                "role": "user",
                "content": (
                    "<fuente_de_la_parte>\n"
                    f"{source_text}\n"
                    "</fuente_de_la_parte>\n\n"
                    "Genera un mapa de recursos externos para la siguiente parte del texto:\n\n"
                    "<identificacion>\n"
                    f"{identificacion}\n"
                    "</identificacion>\n\n"
                    "Busca y recomienda los mejores recursos disponibles (libros, artículos, "
                    "documentales, podcasts, sitios web, cursos) para profundizar en los temas "
                    "de esta sección. Organiza por ejes temáticos. Solo incluye recursos "
                    "verificables con alta confianza. En modo DeepSeek directo puedes realizar "
                    f"hasta {DEEPSEEK_RESOURCES_MAX_TOOL_ROUNDS} rondas de búsqueda web; úsalas "
                    "cuando aporten verificación real y cierra con el JSON final cuando tengas "
                    "evidencia suficiente."
                ),
            }
        ],
        model=model,
        system_prompt=build_resources_deepseek_system_instruction(target_language),
        api_key=api_key,
        response_format="json_object",
        tools=[deepseek_tavily_search_tool()],
        tool_handlers={
            "tavily_search": lambda arguments: tavily_search_tool_result(
                tavily_api_key,
                arguments,
            )
        },
        reasoning_effort=max_reasoning_effort(),
        max_tool_rounds=DEEPSEEK_RESOURCES_MAX_TOOL_ROUNDS,
        json_retry_instruction=OPENROUTER_JSON_RETRY_INSTRUCTION,
    )
    if not isinstance(content, dict):
        raise DeepSeekError("Resources DeepSeek no devolvió un objeto JSON.")

    total_duration = int((time.time() - start_time) * 1000)
    total_recursos = sum(
        len(eje.get("recursos", []))
        for eje in content.get("ejes_tematicos", [])
        if isinstance(eje, dict)
    )
    logger.info(
        "Resources DeepSeek completado: %d ejes, %d recursos en %dms",
        len(content.get("ejes_tematicos", [])),
        total_recursos,
        total_duration,
        extra={
            "num_ejes": len(content.get("ejes_tematicos", [])),
            "total_recursos": total_recursos,
            "total_duration_ms": total_duration,
            "prompt_tokens": getattr(usage, "prompt_token_count", 0),
            "completion_tokens": getattr(usage, "candidates_token_count", 0),
            "server_tool_use": getattr(usage, "server_tool_use", {}),
            "model": model,
        },
    )
    return content, usage


async def run_resources_codex(
    user_id: str,
    source_text: str,
    identificacion: str,
    model: str = CODEX_MODEL,
    target_language: str = "es-ES",
    *,
    effort: str | None = None,
) -> tuple[dict[str, Any], CodexUsage]:
    """Run the Resources agent via Codex (app-server), SIN búsqueda web en v1.

    Corrutina async: se espera directo (nunca en `asyncio.to_thread`). Espejo
    posicional de `run_resources_ds` con `user_id` en la posición de
    `api_key`, sin Tavily ni tools: recomienda desde el conocimiento del
    modelo (riesgo R-RESOURCES del plan: frescura dependiente del modelo).
    """
    start_time = time.time()
    logger.info(
        "Iniciando agente resources Codex (sin búsqueda web)",
        extra={
            "user_id_prefix": user_id[:8],
            "identificacion_length": len(identificacion),
            "identificacion_preview": identificacion[:150] + "..." if len(identificacion) > 150 else identificacion,
            "uses_web_search": False,
            "source_chars": len(source_text),
            "model": model,
        },
    )

    content, usage = await call_codex_chat(
        user_id=user_id,
        messages=[
            {
                "role": "user",
                "content": (
                    "<fuente_de_la_parte>\n"
                    f"{source_text}\n"
                    "</fuente_de_la_parte>\n\n"
                    "Genera un mapa de recursos externos para la siguiente parte del texto:\n\n"
                    "<identificacion>\n"
                    f"{identificacion}\n"
                    "</identificacion>\n\n"
                    "Recomienda desde tu conocimiento, sin búsqueda web: los mejores "
                    "recursos que conozcas con alta confianza (libros, artículos, "
                    "documentales, podcasts, sitios web, cursos) para profundizar en "
                    "los temas de esta sección. Organiza por ejes temáticos. Solo "
                    "incluye recursos verificables con alta confianza; nunca inventes "
                    "títulos, autores ni URLs."
                ),
            }
        ],
        model=model,
        system_prompt=build_resources_codex_system_instruction(target_language),
        response_format="json_object",
        effort=effort,
    )
    if not isinstance(content, dict):
        raise CodexError("Resources Codex no devolvió un objeto JSON.")

    total_duration = int((time.time() - start_time) * 1000)
    total_recursos = sum(
        len(eje.get("recursos", []))
        for eje in content.get("ejes_tematicos", [])
        if isinstance(eje, dict)
    )
    logger.info(
        "Resources Codex completado: %d ejes, %d recursos en %dms",
        len(content.get("ejes_tematicos", [])),
        total_recursos,
        total_duration,
        extra={
            "num_ejes": len(content.get("ejes_tematicos", [])),
            "total_recursos": total_recursos,
            "total_duration_ms": total_duration,
            "prompt_tokens": getattr(usage, "prompt_token_count", 0),
            "completion_tokens": getattr(usage, "candidates_token_count", 0),
            "model": model,
        },
    )
    return content, usage
