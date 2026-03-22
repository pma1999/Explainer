"""Shared language policy: European Spanish (Spain) for model-generated study content."""

# Embedded after </role> (or equivalent) in XML-style system instructions.
CASTELLANO_ESPANIA_XML = """
  <idioma_salida>
  **Castellano de España (español peninsular), no latinoamericano:**
  - Redacta **todo** el contenido que generes tú en castellano de España culto: léxico y construcciones propias de España (p. ej. «ordenador», «móvil», «coche», «portátil»); **prohibido** voseo y usos típicos de Hispanoamérica («computadora», «celular», «carro», «platicar», etc.).
  - Los **términos técnicos**, **citas del texto fuente** o **nomenclatura** en otro idioma pueden conservarse cuando el rigor o el original lo exijan; el marco explicativo que añades tú sigue en castellano de España.
  </idioma_salida>
"""

# Resources: descriptions in Spain Spanish; official titles may stay in original language.
CASTELLANO_ESPANIA_RESOURCES_XML = """
  <idioma_salida>
  **Castellano de España (español peninsular), no latinoamericano:**
  - Redacta en castellano de España culto **todos** los campos redactados por ti: título del mapa, visión general, nombres de ejes, motivaciones, conexión con el texto, notas de integridad, etc. Sin voseo ni léxico latinoamericano habitual.
  - Los **títulos oficiales** de libros, artículos, películas, podcasts, cursos o sitios web pueden permanecer en su **idioma original** cuando así se citan en el ámbito académico o editorial; no los traduzcas artificialmente si el nombre establecido es extranjero.
  </idioma_salida>
"""

# Recorrido: reinforce (citations + translation protocol already in prompt).
CASTELLANO_RECORRIDO_REFUERZO_XML = """
  <idioma_salida refuerzo="true">
  Fuera de las **citas textuales** en su lengua original y de las **traducciones** que este prompt exige al castellano de España, **todo** lo que escribas tú (anotaciones, comentarios, síntesis) permanece en **castellano de España** peninsular exclusivamente —nunca en variantes latinoamericanas.
  </idioma_salida>
"""

FORMATTER_CASTELLANO_RULE = (
    "\n5. El texto de entrada ya está en castellano de España; al aplicar Markdown no introduzcas "
    "palabras nuevas, sinonimia latinoamericana ni cambios que alteren el registro peninsular. "
    "Solo formato, sin normalizar a otra variedad de español."
)
