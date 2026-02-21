"""Agente Resources — mapa de recursos externos para cada parte."""
from __future__ import annotations

import json
from typing import Any
from backend.pricing import get_model_name

from google import genai
from google.genai import types

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

  <objectives>
  **Tu objetivo es producir una selección curada de recursos que logre:**

  1. **Profundización real**: Que el usuario disponga de los mejores materiales existentes en el mundo para ampliar su conocimiento sobre los temas del texto.
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


def run_resources(api_key: str, file_uri: str, identificacion: str) -> tuple[dict[str, Any], Any]:
    """Run the Resources agent and return (structured_result, usage_metadata)."""
    import os
    client = genai.Client(api_key=api_key)
    model = get_model_name()

    tools = [types.Tool(googleSearch=types.GoogleSearch())]

    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_uri(file_uri=file_uri, mime_type="application/pdf"),
                types.Part.from_text(
                    text=(
                        f"Genera un mapa de recursos externos para la siguiente parte del texto:\n\n"
                        f"{identificacion}\n\n"
                        f"Busca y recomienda los mejores recursos disponibles (libros, artículos, "
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
        system_instruction=[types.Part.from_text(text=SYSTEM_INSTRUCTION)],
    )

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )

    return json.loads(response.text), response.usage_metadata
