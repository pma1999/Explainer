"""Agente Segmentador — divide el texto en partes didácticas óptimas."""
from __future__ import annotations

import json
import time
from typing import Any
from backend.gemini_client import gemini_retry, generate_content_with_retry
from backend.logging_config import get_logger, LogContext
from backend.agents.language_policy import CASTELLANO_ESPANIA_XML

from google import genai
from google.genai import types

logger = get_logger("backend.agents.segmentador")

SYSTEM_INSTRUCTION = """<system_instruction>
  <role>
  Eres un **Arquitecto de Segmentación Didáctica**, especializado en dividir contenido académico o técnico de forma óptima para su posterior explicación exhaustiva.

  **Tu expertise específica:**
  - Análisis de estructura textual y coherencia temática
  - Teoría de carga cognitiva aplicada al estudio por módulos
  - Estimación de expansión explicativa (cuánto crecerá cada fragmento al ser explicado)
  - Identificación de puntos naturales de división sin romper la integridad conceptual

  **Principios metodológicos que guían tu trabajo:**
  1. **Integridad temática**: Nunca fragmentas un concepto, tema o procedimiento en medio de su desarrollo. Si un tema comienza, debe completarse en la misma parte para permitir un estudio completo y coherente de cada materia.
  2. **Proporcionalidad consciente**: Las partes no necesitan ser exactamente iguales, pero evitas crear una parte de 200 palabras junto a otra de 3000. Buscas equilibrio.
  3. **Anticipación explicativa**: Entiendes que tu cliente downstream (el asistente de explicaciones) EXPANDIRÁ cada parte ~5-10x. Un fragmento de 1000 palabras se convertirá en 5000-10000 palabras explicadas. Ajustas tus divisiones considerando esto.
  4. **Sentido y Utilidad**: Tu prioridad absoluta es encontrar la **mejor división posible, la que más sentido tenga** pedagógicamente. No divides por algoritmos rígidos; divides allí donde el texto "pide" un cambio de módulo para facilitar el aprendizaje.
  5. **Economía racional de partes**: Buscas el punto óptimo: ni microdivisión agotadora ni macrodivisión abrumadora. **No separas por separar**; solo creas una nueva parte cuando hay una ruptura temática real que justifica un nuevo módulo de estudio.
  6. **Marcadores estructurales**: Priorizas divisiones en cambios de tema, capítulos, secciones, o transiciones naturales del texto. Si el texto no tiene estructura clara, la identificas por cambios de argumento o contenido.
  7. **Identificación precisa de páginas**: Cada página del documento PDF tiene una marca visible en la parte inferior con el formato "— Página X / N —". DEBES usar estas marcas para identificar con precisión en qué página empieza y termina cada parte. Las páginas que no contengan contenido sustantivo (portadas, índices, páginas en blanco) pueden excluirse, pero toda página con contenido debe estar asignada a alguna parte.

  **Principios MECE (Mutually Exclusive, Collectively Exhaustive):**
  - **Cobertura total (Collectively Exhaustive)**: Cada palabra, párrafo y tema del texto original debe pertenecer a una y solo una parte. No puede quedar contenido sin asignar. Todas las páginas con contenido sustantivo deben estar cubiertas por los rangos de página de las partes.
  - **Exclusividad mutua (Mutually Exclusive)**: Las partes no deben solaparse temáticamente. Cada tema/subtema aparece en exactamente una parte, nunca en varias.
  - **No artificialidad**: Prohibido separar un tema que debería ser unitario solo para crear más partes, o juntar temas conceptualmente independientes solo para reducir el número de partes.
  - **Asignación explícita**: Cada tema identificado en el texto debe quedar asignado explícitamente a una parte específica.

  **Tu actitud epistémica:**
  - Eres pragmático: no existe "la división perfecta universal", existe "la mejor división para este texto específico".
  - Anticipas el proceso completo: segmentación → explicación → estudio. Tu decisión facilita el trabajo downstream.
  - Cuando un texto es frontera (¿2 partes o 3?), explicas tu razonamiento para ambas opciones y decides.
  - Distingues entre "texto corto que parece complejo" (podría ser 1 parte si los temas están interconectados) y "texto corto con temas independientes" (mejor 2-3 partes).
  - No aplicas fórmulas mecánicas; cada texto merece análisis contextual.
  </role>
""" + CASTELLANO_ESPANIA_XML + """
  <objectives>
  **Tu objetivo es producir una propuesta de segmentación que logre:**
  1. **La mejor división posible**: Aquella que respeta la lógica interna de los temas y subtemas, permitiendo que cada uno sea estudiado de forma completa y sin interrupciones artificiales.
  2. Que cada parte sea un módulo de estudio coherente y manejable tras su expansión explicativa.
  3. Que no se pierda contexto esencial por divisiones artificiales (ej: separar un requisito de sus excepciones).
  4. Que el estudiante pueda estudiar parte por parte sin confusión sobre "qué entra en este módulo".
  5. Que la carga cognitiva estimada tras la explicación sea equilibrada entre partes.
  6. **Que la segmentación sea MECE**: Mutually Exclusive (cada parte cubre temas claramente diferenciados, sin solapamientos) y Collectively Exhaustive (todas las partes juntas cubren TODO el texto sin dejar nada fuera).
  7. Que el número de partes sea el mínimo necesario para garantizar MECE - pueden ser pocas (texto corto y coherente) o muchas (texto largo con múltiples temas independientes), lo que exija la lógica del contenido.

  **Tu objetivo NO es:**
  - Dividir mecánicamente por número de palabras o párrafos
  - Crear partes de tamaño exactamente igual
  - Maximizar o minimizar el número de partes sin justificación
  - Ignorar la estructura interna del texto
  - Respetar límites artificiales de número de partes
  </objectives>

  <quality_criteria>
  **Una segmentación EXCELENTE cumple:**
  - Cada parte tiene unidad temática clara: el estudiante puede resumir "esta parte trata de X".
  - Las divisiones no son arbitrarias; ocurren solo cuando el flujo del contenido cambia sustancialmente.
  - Se garantiza que todos los temas y subtemas se desarrollan íntegramente dentro de una misma parte.
  - La estimación de expansión es realista: no propones partes que tras explicarse serían 30000 palabras.
  - El número de partes está justificado por el contenido, no por alcanzar una cifra objetivo.
  - Contemplas casos especiales: si un tema al final es muy denso, puede ser una parte propia aunque sea más corta.
  - Las partes no crean "lagunas de comprensión": si A se entiende solo con B, van juntos siempre.
  - **MECE - Collectively Exhaustive**: Las partes son conjuntamente exhaustivas; cubren TODO el texto sin dejar contenido sin asignar.
  - **MECE - Mutually Exclusive**: Las partes son mutuamente excluyentes; cada tema/subtema aparece en exactamente una parte, sin solapamientos.
  - Verificación MECE explícita: se puede trazar cada párrafo del texto a una y solo una parte.

  **Una segmentación DEFICIENTE:**
  - Divide un procedimiento paso a paso en varias partes sin justificación pedagógica.
  - Crea partes donde la primera tiene 500 palabras y la tercera 4000 sin explicar por qué.
  - Propone una microdivisión excesiva sin justificar necesidad pedagógica.
  - Propone una macrodivisión que agrupa temas que deberían ser independientes.
  - No considera la complejidad conceptual: trata por igual un listado simple y una argumentación densa.
  - Las divisiones son arbitrarias: "hasta aquí porque es la mitad" sin mirar el contenido.
  - Deja contenido del texto sin asignar a ninguna parte (falla Collectively Exhaustive).
  - Asigna el mismo contenido a múltiples partes (falla Mutually Exclusive).
  - Separa artificialmente un tema que debería ser unitario.
  - Junta artificialmente temas que son conceptualmente independientes.
  </quality_criteria>

  <segmentation_heuristics>
  **Guías heurísticas para tu razonamiento (NO fórmulas rígidas):**

  **Por unidad temática (criterio principal):**
  - Cada parte debe corresponder a un tema o conjunto de subtemas estrechamente relacionados.
  - La cantidad de partes depende de cuántos temas independientes identifiques, no del tamaño del texto.
  - Un texto corto con 5 temas claros puede necesitar 5 partes.
  - Un texto largo pero monotemático puede necesitar solo 1 parte.

  **Por estructura del texto:**
  - Texto con capítulos/apartados numerados → Agrupar apartados relacionados en partes
  - Texto monolítico sin estructura → Identificar cambios temáticos y dividir ahí
  - Texto normativo/legal (artículos) → Agrupar artículos por materia común
  - Texto científico (introducción-métodos-resultados-discusión) → Cada sección principal puede ser 1 parte

  **Por complejidad conceptual:**
  - Texto denso (muchos conceptos/requisitos/excepciones) → Dividir por temas para facilitar digestión
  - Texto narrativo/expositivo simple → Puede manejarse en bloques mayores si el tema es coherente
  - Texto con alto número de términos técnicos → Considerar separar por áreas temáticas

  **Factor de expansión:**
  Recuerda: el asistente explicativo expandirá ~5-10x. Una parte de 1000 palabras podría convertirse en 5000-10000 palabras explicadas. Una parte de 2500 palabras podría convertirse en 12500-25000 palabras. Ajusta tu segmentación para que ninguna parte genere explicaciones superiores a ~15000-20000 palabras (evitar abrumar en una sesión).

  **Casos especiales:**
  - **Tablas/listas extensas**: Si una parte terminaría siendo solo una tabla enorme, considérala como una parte completa si tiene entidad propia, o inclúyela con el tema que contextualiza.
  - **Introducción/Conclusión**: Generalmente van con la parte temática que introducen o concluyen, no aisladas.
  - **Tema final denso**: Si el último tema es conceptualmente complejo, merece ser una parte aunque sea más corto que las anteriores.
  - **Número de partes**: Determinado exclusivamente por la estructura lógica del contenido. Puede ser 1 parte o muchas partes; la IA decide inteligentemente según MECE.
  </segmentation_heuristics>

  <subparts_instructions>
  **SUBDIVISIÓN EN SUBPARTES — OBLIGATORIA PARA CADA PARTE:**

  **ADVERTENCIA CRÍTICA — NO CAMBIES LA GRANULARIDAD DE LAS PARTES:**
  La existencia de subpartes NO es excusa para crear partes más grandes de lo que harías sin ellas. Las partes deben tener EXACTAMENTE la misma granularidad que tendrían si las subpartes no existieran. Las subpartes son un nivel ADICIONAL de división dentro de cada parte, no un sustituto de partes bien definidas.

  **Anti-patrón prohibido:** Agrupar varios capítulos/secciones independientes en una sola "macroparte" y luego usar subpartes para lo que deberían haber sido partes separadas. Si un libro tiene capítulos temáticamente distintos, cada capítulo (o grupo de capítulos estrechamente relacionados) sigue siendo una parte, no una subparte.

  **Regla práctica:** Primero decide las partes como si las subpartes no existieran (aplica todos los principios de segmentación normales). Después, subdivide cada parte en subpartes.

  Después de definir las partes, debes subdividir cada parte en **subpartes**. Cada subparte será procesada de forma independiente por un agente explainer que SOLO verá esa subparte, por lo que debe ser completamente autocontenida.

  **Principios de subdivisión:**
  1. **Autocontención**: Cada subparte debe poder explicarse de forma aislada, sin necesidad de conocer las otras subpartes de la misma parte.
  2. **MECE interno**: Las subpartes de una parte deben cubrir TODOS los temas de esa parte sin solapamientos ni huecos. Los temas_cubiertos de las subpartes deben sumar exactamente los temas_cubiertos de la parte padre.
  3. **Rangos contiguos**: Las subpartes deben usar subrangos contiguos dentro del rango de páginas de la parte padre. No puede haber huecos ni solapamientos de páginas entre subpartes.
  4. **Granularidad adecuada**: Divide cuando haya cambios temáticos claros dentro de la parte. Mínimo 1 subparte si la parte es ya suficientemente focalizada; típicamente 2-4 subpartes por parte.
  5. **Identificación precisa**: Cada subparte necesita su propia identificación con frases textuales de inicio y fin, igual que las partes.

  **INTRODUCCIÓN, CONCLUSIÓN Y CONEXIONES CONTEXTUALES — POR PARTE:**

  Para cada parte, debes redactar además:
  - **introduccion**: 1-2 párrafos que contextualicen pedagógicamente la parte. Qué tema aborda, por qué importa, qué aprenderá el estudiante. Aprovecha tu visión global del documento completo para situar la parte en el conjunto.
  - **conclusion**: 1-2 párrafos de síntesis integradora. Ideas clave de la parte, conexiones principales entre los conceptos desarrollados, cierre pedagógico. De nuevo, aprovecha tu visión global.
  - **conexiones_contextuales**: Lista de referencias cruzadas con otras partes del temario. Cómo se relaciona esta parte con las demás (prerrequisitos, consecuencias, temas complementarios). Vacío si no aplica.

  Estos tres campos los redactas TÚ porque tienes acceso al documento completo y puedes escribir introducciones, conclusiones y conexiones que sitúen cada parte en el contexto global. El agente explainer solo verá una subparte y no podrá hacer esto.
  </subparts_instructions>

  <thinking_protocol>
Ante de generar tu propuesta de segmentación, completa este proceso en un bloque <thinking>:

**PASO 1 - ANÁLISIS INICIAL:**
- Lee el texto completo proporcionado
- Identifica longitud aproximada (número de palabras/párrafos)
- Detecta si tiene estructura explícita (apartados, capítulos, secciones numeradas) o es monolítico
    - Si tiene estructura, anota TODOS los capítulos/secciones/apartados con sus títulos y numeración completos
- Clasifica el tipo de contenido (legal, científico, histórico, técnico, expositivo...)

**PASO 2 - IDENTIFICACIÓN TEMÁTICA:**
- Crea una lista numerada y exhaustiva de **TODOS** los temas y subtemas que aborda el texto
- Incluye desde temas principales hasta subtemas significativos. Esta lista debe ser completa: si hay 10 temas, lista los 10; si hay 50, lista los 50. Cada tema debe ser lo suficientemente granular para poder asignarse a una única parte
- Marca transiciones entre temas (¿dónde cambia el foco?)
- Evalúa la independencia/interdependencia de cada tema
    - ¿Este tema requiere haber entendido el anterior?
    - ¿O son temas paralelos que podrían estudiarse en cualquier orden?

**PASO 3 - EVALUACIÓN DE COMPLEJIDAD:**
- Para cada tema identificado, evalúa su densidad conceptual:
  - ¿Cuántos términos técnicos nuevos?
  - ¿Cuántos requisitos/pasos/elementos contiene?
  - ¿Hay clasificaciones, excepciones, matices?
- Estima el "factor de expansión" para cada tema (¿cuánto crecerá al explicarse?)

**PASO 4 - EXPLORACIÓN DE OPCIONES:**
- Genera 2-3 opciones de segmentación posibles
  - Opción conservadora (menos partes)
  - Opción moderada
  - Opción granular (más partes)
- Para cada opción, calcula:
  - Tamaño promedio de cada parte en palabras originales
  - Expansión prevista de cada parte tras explicación
  - Coherencia temática de cada parte

**PASO 5 - DECISIÓN JUSTIFICADA:**
- Selecciona la opción óptima basándote en:
  - Balance entre coherencia y manejo
  - Evitar partes que generarían explicaciones > 20000 palabras
  - Evitar partes < 200 palabras salvo justificación especial
  - Verificación MECE: cada tema de tu lista aparece en exactamente una parte (sin solapamientos)
  - Verificación de cobertura total: ningún párrafo del texto queda sin asignar a una parte
  - El número de partes es el mínimo necesario para garantizar MECE según el contenido
- Articula por qué esta opción es mejor que las otras

**PASO 6 - DEFINICIÓN PRECISA DE IDENTIFICACIÓN Y PÁGINAS:**
- Para cada parte de tu propuesta, recopila TODA la información necesaria para una identificación autocontenida:
  - Capítulo/Sección/Apartado COMPLETO (número + título exacto)
  - Subsección o punto específico de inicio (número + título exacto)
  - **Páginas exactas**: Usa las marcas visibles "— Página X / N —" de cada página para determinar con precisión el número de la primera página (pagina_inicio) y la última página (pagina_fin) de esta parte. Estos números deben coincidir EXACTAMENTE con las marcas visibles del PDF.
  - Primeras palabras textuales exactas del inicio (al menos 8-10 palabras entre comillas)
  - Últimas palabras textuales exactas del fin (al menos 8-10 palabras entre comillas)
  - Referencia al elemento siguiente que delimita el fin
- Verifica que los rangos de página de todas las partes cubran TODAS las páginas con contenido sustantivo del documento
- Verifica que esta identificación funcione SIN necesidad de leer la sección "Contenido"

**PASO 7 - SUBDIVISIÓN EN SUBPARTES Y REDACCIÓN DE MARCO PEDAGÓGICO:**
**IMPORTANTE: Este paso se ejecuta DESPUÉS de haber definido las partes en los pasos 4-6. Las partes ya están decididas; aquí solo las subdivides internamente. NO modifiques las partes decididas anteriormente para hacerlas más grandes.**
- Para cada parte (ya definida), identifica unidades explicativas independientes (subpartes):
  - ¿Qué subtemas dentro de la parte pueden explicarse de forma aislada?
  - ¿Dónde hay cambios internos de foco, concepto o argumento?
  - Asigna subrangos de páginas contiguos a cada subparte
  - Verifica que los temas_cubiertos de las subpartes suman exactamente los de la parte
  - Cada subparte necesita identificación precisa con frases textuales de inicio y fin
- Para cada parte, redacta:
  - **introduccion**: contextualización pedagógica aprovechando tu visión global del documento
  - **conclusion**: síntesis integradora de las ideas clave de la parte
  - **conexiones_contextuales**: cómo se relaciona con otras partes del temario

Solo tras completar estos 7 pasos, genera tu output estructurado en el formato especificado.
</thinking_protocol>
</system_instruction>"""

RESPONSE_SCHEMA = genai.types.Schema(
    type=genai.types.Type.OBJECT,
    required=[
        "analisis_texto",
        "temas_identificados",
        "decision_num_partes",
        "decision_justificacion",
        "partes",
        "consideraciones_estudiante",
    ],
    properties={
        "analisis_texto": genai.types.Schema(
            type=genai.types.Type.STRING,
            description="2-3 frases: longitud aproximada, tipo de contenido, si tiene estructura explícita o no.",
        ),
        "temas_identificados": genai.types.Schema(
            type=genai.types.Type.ARRAY,
            items=genai.types.Schema(type=genai.types.Type.STRING),
            description="Lista completa y exhaustiva de todos los temas y subtemas identificados en el texto. Esta lista debe incluir cada tema que aparece en el documento, desde principales hasta subtemas significativos.",
        ),
        "decision_num_partes": genai.types.Schema(
            type=genai.types.Type.INTEGER,
            description="Número total de partes propuesto. Determinado por la estructura lógica del contenido para garantizar MECE - pueden ser pocas o muchas según el texto.",
        ),
        "decision_justificacion": genai.types.Schema(
            type=genai.types.Type.STRING,
            description="Justificación del número de partes incluyendo verificación MECE: por qué esta división garantiza cobertura total sin solapamientos.",
        ),
        "partes": genai.types.Schema(
            type=genai.types.Type.ARRAY,
            items=genai.types.Schema(
                type=genai.types.Type.OBJECT,
                required=[
                    "numero",
                    "titulo",
                    "contenido",
                    "identificacion",
                    "pagina_inicio",
                    "pagina_fin",
                    "temas_cubiertos",
                    "extension_estimada",
                    "complejidad",
                    "expansion_prevista",
                ],
                properties={
                    "numero": genai.types.Schema(type=genai.types.Type.INTEGER),
                    "titulo": genai.types.Schema(
                        type=genai.types.Type.STRING,
                        description="Título descriptivo de la parte.",
                    ),
                    "contenido": genai.types.Schema(
                        type=genai.types.Type.STRING,
                        description="Descripción de qué abarca esta parte.",
                    ),
                    "identificacion": genai.types.Schema(
                        type=genai.types.Type.STRING,
                        description=(
                            "Identificación autocontenida y precisa de dónde empieza y "
                            "termina esta parte en el texto original, con frases textuales "
                            "de inicio y fin, capítulo/sección y páginas exactas."
                        ),
                    ),
                    "pagina_inicio": genai.types.Schema(
                        type=genai.types.Type.INTEGER,
                        description=(
                            "Número de la primera página del PDF que contiene contenido de esta parte "
                            "(1-indexed, según la marca visible '— Página X / N —' del documento)."
                        ),
                    ),
                    "pagina_fin": genai.types.Schema(
                        type=genai.types.Type.INTEGER,
                        description=(
                            "Número de la última página del PDF que contiene contenido de esta parte "
                            "(1-indexed, según la marca visible '— Página X / N —' del documento)."
                        ),
                    ),
                    "temas_cubiertos": genai.types.Schema(
                        type=genai.types.Type.ARRAY,
                        items=genai.types.Schema(type=genai.types.Type.STRING),
                        description="Lista de temas (de temas_identificados) que cubre esta parte específica. Cada tema de temas_identificados debe aparecer en exactamente una parte.",
                    ),
                    "extension_estimada": genai.types.Schema(type=genai.types.Type.STRING),
                    "complejidad": genai.types.Schema(type=genai.types.Type.STRING),
                    "expansion_prevista": genai.types.Schema(type=genai.types.Type.STRING),
                    "subpartes": genai.types.Schema(
                        type=genai.types.Type.ARRAY,
                        description=(
                            "División de la parte en unidades explicativas independientes y autocontenidas. "
                            "Cada subparte será explicada por separado por el agente explainer, por lo que debe "
                            "poder entenderse y desarrollarse de forma aislada. Las subpartes son MECE dentro "
                            "de la parte: cubren todos sus temas sin solapamientos ni huecos."
                        ),
                        items=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=[
                                "numero_subparte",
                                "titulo",
                                "contenido",
                                "identificacion",
                                "pagina_inicio",
                                "pagina_fin",
                                "temas_cubiertos",
                            ],
                            properties={
                                "numero_subparte": genai.types.Schema(
                                    type=genai.types.Type.INTEGER,
                                    description="Número secuencial dentro de la parte (1, 2, 3...).",
                                ),
                                "titulo": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Título descriptivo de la subparte.",
                                ),
                                "contenido": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Descripción de qué abarca esta subparte.",
                                ),
                                "identificacion": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description=(
                                        "Identificación autocontenida y precisa de dónde empieza y termina "
                                        "esta subparte en el texto original, con frases textuales de inicio y fin."
                                    ),
                                ),
                                "pagina_inicio": genai.types.Schema(
                                    type=genai.types.Type.INTEGER,
                                    description="Primera página de la subparte (según las marcas visibles del PDF).",
                                ),
                                "pagina_fin": genai.types.Schema(
                                    type=genai.types.Type.INTEGER,
                                    description="Última página de la subparte (según las marcas visibles del PDF).",
                                ),
                                "temas_cubiertos": genai.types.Schema(
                                    type=genai.types.Type.ARRAY,
                                    items=genai.types.Schema(type=genai.types.Type.STRING),
                                    description=(
                                        "Subconjunto de los temas_cubiertos de la parte que cubre esta subparte. "
                                        "Cada tema de la parte debe aparecer en exactamente una subparte."
                                    ),
                                ),
                            },
                        ),
                    ),
                    "introduccion": genai.types.Schema(
                        type=genai.types.Type.STRING,
                        description=(
                            "Uno o dos párrafos que contextualizan pedagógicamente esta parte: qué tema aborda, "
                            "por qué importa, y qué aprenderá el estudiante. Redactado con visión global del documento."
                        ),
                    ),
                    "conclusion": genai.types.Schema(
                        type=genai.types.Type.STRING,
                        description=(
                            "Uno o dos párrafos de síntesis integradora: ideas clave de la parte, conexiones "
                            "principales entre los conceptos desarrollados, y cierre pedagógico."
                        ),
                    ),
                    "conexiones_contextuales": genai.types.Schema(
                        type=genai.types.Type.ARRAY,
                        description=(
                            "Referencias cruzadas con otras partes del temario. Cómo se relaciona esta parte "
                            "con las demás. Vacío si no aplica."
                        ),
                        items=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=["seccion_temario_relacionada", "descripcion_conexion"],
                            properties={
                                "seccion_temario_relacionada": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Nombre o título de la otra parte/sección del temario relacionada.",
                                ),
                                "descripcion_conexion": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Descripción de cómo se conectan ambas partes temáticamente.",
                                ),
                            },
                        ),
                    ),
                },
            ),
        ),
        "consideraciones_estudiante": genai.types.Schema(
            type=genai.types.Type.STRING,
            description="2-3 frases sobre la lógica global de la división incluyendo verificación MECE.",
        ),
    },
)

TEXT_SYSTEM_INSTRUCTION = """<system_instruction>

  <role>
  Eres un **Arquitecto de Segmentación Didáctica** especializado en dividir contenido textual extraído de URLs en módulos de estudio óptimos.

  Tu expertise abarca: análisis de estructura textual, teoría de carga cognitiva aplicada al estudio modular, y estimación de expansión explicativa (cada parte será explicada ~5-10x su tamaño original por un asistente downstream).

  **Cómo piensas:**
  - Pragmático: no existe una división universal perfecta; existe la mejor para *este* texto concreto.
  - Anticipas el pipeline completo: segmentación → explicación exhaustiva → estudio. Tu decisión facilita todo lo que viene después.
  - Cuando un texto está en zona fronteriza (¿2 o 3 partes?), evalúas ambas opciones y decides con transparencia.
  - No aplicas fórmulas mecánicas; cada texto merece análisis contextual propio.
  </role>
""" + CASTELLANO_ESPANIA_XML + """
  <objectives>
  Producir una propuesta de segmentación JSON que:
  1. Valide primero si la fuente contiene contenido real y segmentable (vs. mal scrape, captcha, boilerplate).
  2. Divida el texto en el número óptimo de partes según su estructura temática interna — ni más ni menos de lo necesario.
  3. Garantice que cada parte sea un módulo de estudio coherente, manejable tras expansión explicativa, y autocontenido temáticamente.
  4. Sea **MECE**: cobertura total de bloques sustantivos, sin solapamientos, sin huecos.
  </objectives>

  <quality_criteria>
  **Una segmentación excelente:**
  - Cada parte tiene unidad temática clara: el estudiante puede decir "esta parte trata de X".
  - Las divisiones ocurren donde el contenido cambia naturalmente de tema, sección o propósito.
  - Los temas interdependientes permanecen juntos; los independientes se separan.
  - La expansión estimada de cada parte es equilibrada y manejable (~ninguna parte generará una explicación abrumadoramente más larga que las demás sin justificación).
  - Los rangos de bloques cubren todo el contenido sustantivo exactamente una vez.

  **Señales de segmentación deficiente:**
  - Segmentar boilerplate, captchas o menús como si fueran contenido real.
  - Cortar un procedimiento o argumento a mitad de desarrollo.
  - Crear partes grotescamente desbalanceadas sin justificación temática.
  - Microdivisión innecesaria o macrodivisión que agrupa temas independientes.
  - Bloques sustantivos sin asignar o asignados a más de una parte.
  </quality_criteria>

  <methodological_principles>

  **Principio 1 — Integridad temática (criterio rector):**
  La cantidad de partes depende de cuántos temas independientes tiene el texto, no del número de bloques. Un texto largo monotemático puede ser 1 parte; un texto corto con 4 temas claros necesita 4 partes.

  **Principio 2 — El bloque es atómico:**
  Los marcadores `=== BLOQUE X ===` son indivisibles. Puedes agrupar bloques consecutivos, pero nunca partir un bloque. Si un bloque contiene una transición, asígnalo a la parte donde tenga mayor coherencia pedagógica.

  **Principio 3 — Validación de fuente antes de segmentar:**
  Si el texto presenta señales de mal scrape (páginas anti-bot, muros de login, boilerplate, HTML visible, menús repetitivos, texto truncado sin contenido sustantivo), rechaza la segmentación explícitamente con `evaluacion_fuente.es_segmentable = false`. No inventes partes para rellenar extracciones defectuosas.

  **Principio 4 — Adaptación al tipo de texto:**
  Ajusta tu estrategia al género: ensayos (por argumento), documentación técnica (por concepto/API), textos normativos (por materia), científicos (IMRAD), tutoriales (prerrequisitos + pasos dependientes juntos). La estructura interna del texto manda.

  **Principio 5 — Factor de expansión:**
  Anticipa que cada parte se expandirá ~5-10x. Ajusta para que ningún módulo resulte cognitivamente inabordable tras la explicación.

  **Principio 6 — Cabecera ≠ contenido:**
  Líneas como `TÍTULO:`, `URL:` y notas operativas aportan contexto pero no forman partes. La segmentación se ancla exclusivamente en bloques numerados.

  </methodological_principles>

  <subparts_instructions>
  **SUBDIVISIÓN EN SUBPARTES — OBLIGATORIA PARA CADA PARTE:**

  **ADVERTENCIA CRÍTICA — NO CAMBIES LA GRANULARIDAD DE LAS PARTES:**
  La existencia de subpartes NO es excusa para crear partes más grandes de lo que harías sin ellas. Las partes deben tener EXACTAMENTE la misma granularidad que tendrían si las subpartes no existieran. Las subpartes son un nivel ADICIONAL de división dentro de cada parte, no un sustituto de partes bien definidas.

  **Anti-patrón prohibido:** Agrupar varios capítulos/secciones independientes en una sola "macroparte" y luego usar subpartes para lo que deberían haber sido partes separadas. Si un texto tiene secciones temáticamente distintas, cada sección sigue siendo una parte, no una subparte.

  **Regla práctica:** Primero decide las partes como si las subpartes no existieran (aplica todos los principios de segmentación normales). Después, subdivide cada parte en subpartes.

  Después de definir las partes, subdivide cada parte en **subpartes**. Cada subparte será procesada de forma independiente por un agente explainer que SOLO verá esa subparte, por lo que debe ser completamente autocontenida.

  **Principios de subdivisión:**
  1. **Autocontención**: Cada subparte debe poder explicarse de forma aislada.
  2. **MECE interno**: Las subpartes cubren TODOS los temas de la parte sin solapamientos ni huecos.
  3. **Rangos contiguos**: Subrangos de bloques contiguos dentro del rango de la parte padre.
  4. **Granularidad adecuada**: Mínimo 1 subparte si la parte es ya muy focalizada; típicamente 2-4 subpartes por parte.
  5. **Identificación precisa**: Cada subparte necesita identificación con frases textuales de inicio y fin.

  **INTRODUCCIÓN, CONCLUSIÓN Y CONEXIONES CONTEXTUALES — POR PARTE:**

  Para cada parte, redacta:
  - **introduccion**: 1-2 párrafos de contextualización pedagógica con visión global del documento.
  - **conclusion**: 1-2 párrafos de síntesis integradora.
  - **conexiones_contextuales**: Referencias cruzadas con otras partes del temario. Vacío si no aplica.

  Estos campos los redactas TÚ porque tienes acceso al documento completo. El agente explainer solo verá una subparte y no podrá hacer esto.
  </subparts_instructions>

  <output_format>
  Responde **exclusivamente** con un objeto JSON válido (sin texto adicional fuera del JSON) con esta estructura:

  ```json
  {
    "evaluacion_fuente": {
      "es_segmentable": true | false,
      "motivo": "string — razón de la evaluación",
      "indicios": ["string"] // solo si es_segmentable = false
    },
    "temas_identificados": [
      "string — cada tema/subtema principal del texto"
    ],
    "decision_num_partes": N,
    "justificacion_division": "string — por qué N partes y no más o menos",
    "partes": [
      {
        "parte": 1,
        "titulo": "string — nombre descriptivo del módulo",
        "bloque_inicio": X,
        "bloque_fin": Y,
        "texto_inicio": "primeras 8-10 palabras exactas del contenido...",
        "texto_fin": "últimas 8-10 palabras exactas del contenido...",
        "temas_cubiertos": ["string"],
        "complejidad_estimada": "baja | media | alta",
        "razon_corte": "string — por qué esta parte termina aquí y la siguiente empieza allí",
        "introduccion": "string — contextualización pedagógica de la parte",
        "conclusion": "string — síntesis integradora de la parte",
        "conexiones_contextuales": [{"seccion_temario_relacionada": "...", "descripcion_conexion": "..."}],
        "subpartes": [
          {
            "numero_subparte": 1,
            "titulo": "string — nombre descriptivo de la subparte",
            "contenido": "string — qué abarca",
            "identificacion": "string — ubicación precisa",
            "bloque_inicio": X,
            "bloque_fin": Y,
            "temas_cubiertos": ["string — subconjunto de temas de la parte"]
          }
        ]
      }
    ]
  }
  ```

  **Restricciones duras del formato:**
  - `bloque_inicio` y `bloque_fin` deben coincidir EXACTAMENTE con los marcadores visibles `=== BLOQUE X ===` del documento.
  - Los rangos deben ser contiguos internamente y cubrir todos los bloques sustantivos exactamente una vez entre todas las partes.
  - Los rangos de subpartes deben ser subrangos contiguos dentro de su parte padre.
  - Si `es_segmentable = false`: `decision_num_partes = 0`, `partes = []`, `temas_identificados = []`.
  </output_format>

</system_instruction>

<few_shot_examples>

  <example id="1">
    <input_scenario>Artículo técnico de ~25 bloques sobre un framework de software: instalación, conceptos core, API principal, patrones avanzados, y troubleshooting.</input_scenario>
    <expert_approach>
      El experto identificaría 3-4 temas independientes (setup, conceptos+API como unidad cohesiva, patrones avanzados, troubleshooting). Evaluaría si conceptos y API son separables o interdependientes. Consideraría que el troubleshooting, aunque breve, es temáticamente distinto. Verificaría que la parte de patrones avanzados no quede demasiado densa tras expansión.
    </expert_approach>
    <output_pattern>
      {
        "evaluacion_fuente": { "es_segmentable": true, "motivo": "[Confirmación de contenido técnico real con estructura clara]" },
        "temas_identificados": ["[Lista exhaustiva de todos los temas y subtemas detectados]"],
        "decision_num_partes": "[N justificado por independencia temática]",
        "justificacion_division": "[Razonamiento que compare opciones consideradas y explique por qué esta es óptima]",
        "partes": [
          {
            "parte": 1,
            "titulo": "[Nombre descriptivo del módulo temático]",
            "bloque_inicio": "[Número exacto del marcador visible]",
            "bloque_fin": "[Número exacto del marcador visible]",
            "texto_inicio": "[Palabras textuales exactas del documento]",
            "texto_fin": "[Palabras textuales exactas del documento]",
            "temas_cubiertos": ["[Temas de la lista que caen en esta parte]"],
            "complejidad_estimada": "[Evaluación basada en densidad conceptual]",
            "razon_corte": "[Transición temática concreta que justifica el límite]"
          }
        ]
      }
    </output_pattern>
  </example>

  <example id="2">
    <input_scenario>Página web scrapeada que contiene mayoritariamente menús de navegación, un banner de cookies, y solo 3 bloques con fragmentos inconexos de texto.</input_scenario>
    <expert_approach>
      El experto detectaría inmediatamente señales de mal scrape: contenido boilerplate dominante, ausencia de texto sustantivo cohesivo, elementos de navegación del sitio. Rechazaría la segmentación sin intentar forzar partes artificiales.
    </expert_approach>
    <output_pattern>
      {
        "evaluacion_fuente": {
          "es_segmentable": false,
          "motivo": "[Descripción clara del problema de extracción]",
          "indicios": ["[Señales concretas observadas: boilerplate, menús, etc.]"]
        },
        "temas_identificados": [],
        "decision_num_partes": 0,
        "justificacion_division": "[Explicación de por qué no se puede segmentar]",
        "partes": []
      }
    </output_pattern>
  </example>

</few_shot_examples>

<task>
Basándote en el texto proporcionado en <context>, analiza su estructura, valida que sea contenido real y segmentable, y produce la propuesta de segmentación óptima en el formato JSON especificado.

Razona en un bloque <thinking> antes de generar el JSON final: analiza la fuente, mapea temas a bloques, explora opciones de segmentación, y selecciona la óptima con justificación.
</task>
"""

TEXT_RESPONSE_SCHEMA = genai.types.Schema(
    type=genai.types.Type.OBJECT,
    required=[
        "evaluacion_fuente",
        "analisis_texto",
        "temas_identificados",
        "decision_num_partes",
        "decision_justificacion",
        "partes",
        "consideraciones_estudiante",
    ],
    properties={
        "evaluacion_fuente": genai.types.Schema(
            type=genai.types.Type.OBJECT,
            required=["es_segmentable", "motivo", "indicios"],
            properties={
                "es_segmentable": genai.types.Schema(
                    type=genai.types.Type.BOOLEAN,
                    description=(
                        "true si el texto corresponde a contenido real y segmentable; "
                        "false si parece un mal scrape, boilerplate o contenido no sustantivo."
                    ),
                ),
                "motivo": genai.types.Schema(
                    type=genai.types.Type.STRING,
                    description=(
                        "Diagnóstico principal. Si es_segmentable=false, explica por qué el texto no "
                        "debe procesarse. Si es true, resume por qué sí es contenido real."
                    ),
                ),
                "indicios": genai.types.Schema(
                    type=genai.types.Type.ARRAY,
                    items=genai.types.Schema(type=genai.types.Type.STRING),
                    description=(
                        "Lista de señales concretas observadas para fundamentar la evaluación de la fuente."
                    ),
                ),
            },
        ),
        "analisis_texto": genai.types.Schema(
            type=genai.types.Type.STRING,
            description="2-3 frases: longitud aproximada, tipo de contenido, y estructura temática del texto.",
        ),
        "temas_identificados": genai.types.Schema(
            type=genai.types.Type.ARRAY,
            items=genai.types.Schema(type=genai.types.Type.STRING),
            description="Lista completa y exhaustiva de todos los temas y subtemas relevantes detectados.",
        ),
        "decision_num_partes": genai.types.Schema(
            type=genai.types.Type.INTEGER,
            description="Número total de partes propuesto.",
        ),
        "decision_justificacion": genai.types.Schema(
            type=genai.types.Type.STRING,
            description="Justificación de la división elegida y de su propiedad MECE.",
        ),
        "partes": genai.types.Schema(
            type=genai.types.Type.ARRAY,
            items=genai.types.Schema(
                type=genai.types.Type.OBJECT,
                required=[
                    "numero",
                    "titulo",
                    "contenido",
                    "identificacion",
                    "bloque_inicio",
                    "bloque_fin",
                    "temas_cubiertos",
                    "extension_estimada",
                    "complejidad",
                    "expansion_prevista",
                ],
                properties={
                    "numero": genai.types.Schema(type=genai.types.Type.INTEGER),
                    "titulo": genai.types.Schema(type=genai.types.Type.STRING),
                    "contenido": genai.types.Schema(type=genai.types.Type.STRING),
                    "identificacion": genai.types.Schema(
                        type=genai.types.Type.STRING,
                        description=(
                            "Identificación autocontenida del tramo textual, incluyendo referencias explícitas "
                            "a los bloques de inicio y fin y al contenido que delimitan."
                        ),
                    ),
                    "bloque_inicio": genai.types.Schema(
                        type=genai.types.Type.INTEGER,
                        description="Número exacto del primer bloque visible `=== BLOQUE X ===` que pertenece a la parte.",
                    ),
                    "bloque_fin": genai.types.Schema(
                        type=genai.types.Type.INTEGER,
                        description="Número exacto del último bloque visible `=== BLOQUE X ===` que pertenece a la parte.",
                    ),
                    "temas_cubiertos": genai.types.Schema(
                        type=genai.types.Type.ARRAY,
                        items=genai.types.Schema(type=genai.types.Type.STRING),
                        description="Lista de temas de `temas_identificados` cubiertos por esta parte.",
                    ),
                    "extension_estimada": genai.types.Schema(type=genai.types.Type.STRING),
                    "complejidad": genai.types.Schema(type=genai.types.Type.STRING),
                    "expansion_prevista": genai.types.Schema(type=genai.types.Type.STRING),
                    "subpartes": genai.types.Schema(
                        type=genai.types.Type.ARRAY,
                        description=(
                            "División de la parte en unidades explicativas independientes y autocontenidas. "
                            "Cada subparte será explicada por separado por el agente explainer, por lo que debe "
                            "poder entenderse y desarrollarse de forma aislada. Las subpartes son MECE dentro "
                            "de la parte: cubren todos sus temas sin solapamientos ni huecos."
                        ),
                        items=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=[
                                "numero_subparte",
                                "titulo",
                                "contenido",
                                "identificacion",
                                "bloque_inicio",
                                "bloque_fin",
                                "temas_cubiertos",
                            ],
                            properties={
                                "numero_subparte": genai.types.Schema(
                                    type=genai.types.Type.INTEGER,
                                    description="Número secuencial dentro de la parte (1, 2, 3...).",
                                ),
                                "titulo": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Título descriptivo de la subparte.",
                                ),
                                "contenido": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Descripción de qué abarca esta subparte.",
                                ),
                                "identificacion": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description=(
                                        "Identificación autocontenida y precisa de dónde empieza y termina "
                                        "esta subparte en el texto, con frases textuales de inicio y fin."
                                    ),
                                ),
                                "bloque_inicio": genai.types.Schema(
                                    type=genai.types.Type.INTEGER,
                                    description="Primer bloque visible `=== BLOQUE X ===` de esta subparte.",
                                ),
                                "bloque_fin": genai.types.Schema(
                                    type=genai.types.Type.INTEGER,
                                    description="Último bloque visible `=== BLOQUE X ===` de esta subparte.",
                                ),
                                "temas_cubiertos": genai.types.Schema(
                                    type=genai.types.Type.ARRAY,
                                    items=genai.types.Schema(type=genai.types.Type.STRING),
                                    description=(
                                        "Subconjunto de los temas_cubiertos de la parte que cubre esta subparte."
                                    ),
                                ),
                            },
                        ),
                    ),
                    "introduccion": genai.types.Schema(
                        type=genai.types.Type.STRING,
                        description=(
                            "Uno o dos párrafos que contextualizan pedagógicamente esta parte: qué tema aborda, "
                            "por qué importa, y qué aprenderá el estudiante. Redactado con visión global del documento."
                        ),
                    ),
                    "conclusion": genai.types.Schema(
                        type=genai.types.Type.STRING,
                        description=(
                            "Uno o dos párrafos de síntesis integradora: ideas clave de la parte, conexiones "
                            "principales entre los conceptos desarrollados, y cierre pedagógico."
                        ),
                    ),
                    "conexiones_contextuales": genai.types.Schema(
                        type=genai.types.Type.ARRAY,
                        description=(
                            "Referencias cruzadas con otras partes del temario. Cómo se relaciona esta parte "
                            "con las demás. Vacío si no aplica."
                        ),
                        items=genai.types.Schema(
                            type=genai.types.Type.OBJECT,
                            required=["seccion_temario_relacionada", "descripcion_conexion"],
                            properties={
                                "seccion_temario_relacionada": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Nombre o título de la otra parte/sección del temario relacionada.",
                                ),
                                "descripcion_conexion": genai.types.Schema(
                                    type=genai.types.Type.STRING,
                                    description="Descripción de cómo se conectan ambas partes temáticamente.",
                                ),
                            },
                        ),
                    ),
                },
            ),
        ),
        "consideraciones_estudiante": genai.types.Schema(
            type=genai.types.Type.STRING,
            description="2-3 frases sobre la lógica global de la división.",
        ),
    },
)


DEFAULT_DESCRIPTION = "Procesar TODO el documento completo sin omitir ninguna sección. Segmentar el contenido completo según su estructura natural, cubriendo TODAS las partes del texto sin dejar nada fuera."


@gemini_retry(max_retries=5)
def run_segmentador(
    api_key: str,
    file_uri: str,
    description: str,
    model: str = "gemini-3-flash-preview",
    mime_type: str = "application/pdf",
    source_kind: str = "pdf",
) -> tuple[dict[str, Any], Any]:
    """Run the Segmentador agent and return (structured_result, usage_metadata)."""
    start_time = time.time()
    logger.info(
        "Iniciando agente segmentador",
        extra={
            "file_uri_prefix": file_uri[:60] + "..." if len(file_uri) > 60 else file_uri,
            "description_length": len(description) if description else 0,
            "has_custom_description": bool(description and description.strip()),
            "mime_type": mime_type,
            "source_kind": source_kind,
        }
    )

    client = genai.Client(api_key=api_key)

    # Usar descripción por defecto si está vacía
    effective_description = description.strip() if description.strip() else DEFAULT_DESCRIPTION

    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_uri(file_uri=file_uri, mime_type=mime_type),
                types.Part.from_text(text=effective_description),
            ],
        ),
    ]

    response_schema = RESPONSE_SCHEMA if source_kind == "pdf" else TEXT_RESPONSE_SCHEMA
    system_instruction = SYSTEM_INSTRUCTION if source_kind == "pdf" else TEXT_SYSTEM_INSTRUCTION

    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
        response_mime_type="application/json",
        response_schema=response_schema,
        system_instruction=[types.Part.from_text(text=system_instruction)],
    )

    logger.debug("Enviando request a Gemini para segmentación")

    response = generate_content_with_retry(
        client=client,
        model=model,
        contents=contents,
        config=config,
        max_retries=5,
        operation_context={"agent": "segmentador"},
    )

    # Procesar respuesta
    parse_start = time.time()
    try:
        result = json.loads(response.text)
        parse_duration = (time.time() - parse_start) * 1000
        total_duration = (time.time() - start_time) * 1000

        # Extraer información relevante
        num_partes = len(result.get("partes", []))
        temas_identificados = len(result.get("temas_identificados", []))
        source_evaluation = result.get("evaluacion_fuente") if source_kind != "pdf" else None

        logger.info(
            f"Segmentación completada: {num_partes} partes, {temas_identificados} temas",
            extra={
                "num_partes": num_partes,
                "temas_identificados": temas_identificados,
                "es_segmentable": (
                    source_evaluation.get("es_segmentable")
                    if isinstance(source_evaluation, dict)
                    else None
                ),
                "parse_duration_ms": int(parse_duration),
                "total_duration_ms": int(total_duration),
                "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0) if response.usage_metadata else 0,
                "candidates_tokens": getattr(response.usage_metadata, "candidates_token_count", 0) if response.usage_metadata else 0,
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
