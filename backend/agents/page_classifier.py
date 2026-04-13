"""Agente Page Classifier — clasifica páginas de contenido vs. accesorias en un PDF."""
from __future__ import annotations

import json
import time
from typing import Any

from backend.gemini_model_routing import MODEL_CLASSIFIER, TEMPERATURE_PAGE_CLASSIFIER
from backend.gemini_client import gemini_retry, generate_content_with_retry
from backend.logging_config import get_logger

from google import genai
from google.genai import types

logger = get_logger("backend.agents.page_classifier")

SYSTEM_INSTRUCTION = """<system_instruction>
  <role>
  Eres un clasificador de páginas de documentos académicos, técnicos o jurídicos.
  Tu única función es identificar con precisión máxima qué páginas contienen contenido sustantivo
  que un estudiante debe aprender, y cuáles son páginas accesorias.
  Se exige exactitud en ambas direcciones: no puedes perder ninguna página de contenido
  (aunque el contenido ocupe solo parte de la página), ni incluir páginas que no aporten contenido.
  </role>

  <definitions>
  **Contenido sustantivo**: texto argumentativo, analítico o expositivo que forma parte del
  cuerpo principal del documento: teoría, conceptos, argumentaciones, análisis, procedimientos,
  normas, resultados, discusión, conclusiones, introducciones de capítulo, títulos de sección
  que encabezan texto de contenido.
  UMBRAL: si una página contiene CUALQUIER fragmento de texto argumentativo, analítico o
  expositivo —aunque sea una sola frase o un párrafo incompleto a mitad de página— clasifícala
  como CONTENIDO. No se requiere que la página esté llena; cualquier fragmento real basta.
  NO activan el umbral aunque sean abundantes: entradas bibliográficas, citas, referencias,
  entradas de índice, cabeceras, pies de página, datos tabulares, listas de figuras.

  **Páginas accesorias** (lista exhaustiva — solo estas son accesorias):
  - Portada y contraportada
  - Páginas en blanco o con solo ornamentos decorativos
  - Tabla de contenidos / índice general
  - Lista de figuras, tablas o abreviaciones
  - Agradecimientos y dedicatoria
  - Prólogo o prefacio que NO contiene argumentación temática (solo presentación editorial)
  - Secciones de bibliografía o referencias: páginas ocupadas por entradas bibliográficas,
    incluso si incluyen anotaciones breves entre citas. Son ACCESORIAS porque las entradas
    bibliográficas no son texto argumentativo propio del autor.
  - Notas finales que son solo referencias bibliográficas
  - Apéndices puramente referenciales: tablas de datos, listados numéricos, glosarios simples sin explicación
  - Copyright, ISBN, colofón, información editorial
  - Páginas con solo número de página, cabecera o pie sin cuerpo de texto

  **Regla de desempate (aplica siempre que haya duda)**: clasifica como CONTENIDO.
  Una sola oración argumentativa o analítica en una página es suficiente para que sea CONTENIDO,
  aunque el resto de la página sea accesorio.
  </definitions>

  <edge_cases>
  Estos casos se resuelven siempre así, sin excepción:

  - Página de inicio de capítulo con solo título y número de capítulo, sin texto todavía → CONTENIDO.
  - Primera o última página de un capítulo con solo unas pocas líneas de texto → CONTENIDO.
  - Sección de bibliografía de capítulo o final de libro con solo entradas, incluso con
    anotaciones breves entre citas → ACCESORIA. Las entradas bibliográficas no son texto
    argumentativo aunque sean numerosas.
  - Página que mezcla último párrafo de argumentación de un capítulo con el inicio de la
    bibliografía → CONTENIDO (el párrafo argumentativo activa el umbral).
  - Prólogo o prefacio que expone ideas del campo o argumenta temáticamente → CONTENIDO.
  - Apéndice con análisis, discusión o argumentación propia → CONTENIDO.
  - Apéndice de solo tablas de datos o listados sin explicación → ACCESORIA.
  - Página con una figura o tabla sin texto explicativo propio (solo pie de figura) → CONTENIDO si
    la figura/tabla contiene información sustantiva; ACCESORIA solo si es puramente decorativa.
  - Página con solo cabecera o pie de página sin cuerpo de texto → ACCESORIA.
  </edge_cases>

  <instructions>
  1. Lee el documento completo de principio a fin.
  2. Usa las marcas visibles «— Página X / N —» al pie de cada página para identificar el
     número exacto de cada página (1-indexed). N es el total de páginas.
  3. Para cada página, aplica las definiciones y casos límite anteriores en este orden:
     a. ¿El contenido de la página es EXCLUSIVAMENTE de tipo accesorio (solo entradas
        bibliográficas, solo índice, solo datos tabulares, solo información editorial, etc.)?
        → ACCESORIA.
     b. ¿Contiene cualquier fragmento de texto argumentativo, analítico o expositivo,
        aunque sea parcial? → CONTENIDO.
     c. ¿Hay duda? → CONTENIDO (regla de desempate).
  4. Agrupa páginas consecutivas de la misma categoría en rangos.
  5. Verifica que rangos_contenido y rangos_no_contenido juntos cubren exactamente todas las
     páginas de 1 a total_paginas, sin huecos ni solapamientos.
  6. Devuelve el resultado en el JSON estructurado especificado. Sin texto adicional fuera del JSON.
  </instructions>
</system_instruction>"""

RESPONSE_SCHEMA = genai.types.Schema(
    type=genai.types.Type.OBJECT,
    required=["total_paginas", "rangos_contenido", "rangos_no_contenido"],
    properties={
        "total_paginas": genai.types.Schema(
            type=genai.types.Type.INTEGER,
            description="Número total de páginas del documento según las marcas visibles.",
        ),
        "rangos_contenido": genai.types.Schema(
            type=genai.types.Type.ARRAY,
            description="Rangos de páginas con contenido sustantivo.",
            items=genai.types.Schema(
                type=genai.types.Type.OBJECT,
                required=["inicio", "fin"],
                properties={
                    "inicio": genai.types.Schema(type=genai.types.Type.INTEGER),
                    "fin":    genai.types.Schema(type=genai.types.Type.INTEGER),
                },
            ),
        ),
        "rangos_no_contenido": genai.types.Schema(
            type=genai.types.Type.ARRAY,
            description="Rangos de páginas accesorias (portada, índice, bibliografía, etc.).",
            items=genai.types.Schema(
                type=genai.types.Type.OBJECT,
                required=["inicio", "fin", "razon"],
                properties={
                    "inicio": genai.types.Schema(type=genai.types.Type.INTEGER),
                    "fin":    genai.types.Schema(type=genai.types.Type.INTEGER),
                    "razon":  genai.types.Schema(
                        type=genai.types.Type.STRING,
                        description="Descripción breve: 'portada', 'bibliografía', etc.",
                    ),
                },
            ),
        ),
    },
)


def _parse_classifier_result(result: dict[str, Any], total_pages: int) -> frozenset[int]:
    """Convert classifier JSON output to a frozenset of content page numbers.

    Args:
        result: Parsed JSON dict from the classifier response.
        total_pages: Expected total page count from pypdf (used for sanity check only).

    Returns:
        frozenset of 1-indexed page numbers classified as substantive content.
        Ranges with inicio > fin are silently ignored (safe skip).
    """
    reported_total = result.get("total_paginas")
    if reported_total != total_pages:
        logger.warning(
            "Clasificador reportó %d páginas pero pypdf encontró %d; se usa la clasificación del modelo",
            reported_total,
            total_pages,
        )

    content_pages: set[int] = set()
    for r in result.get("rangos_contenido", []):
        inicio = int(r["inicio"])
        fin = int(r["fin"])
        if inicio <= fin:
            content_pages.update(range(inicio, fin + 1))

    return frozenset(content_pages)


def validate_classifier_partition(
    result: dict[str, Any],
    total_pages: int,
) -> tuple[bool, list[str]]:
    """Check that rangos_contenido and rangos_no_contenido partition 1..total_pages (MECE).

    Returns (is_valid, error_messages). Used for audits and tests.
    """
    from backend.segmentation_page_coverage import _compact_page_list

    errors: list[str] = []
    content_pages: set[int] = set()
    non_content_pages: set[int] = set()

    for label, key in (("contenido", "rangos_contenido"), ("no_contenido", "rangos_no_contenido")):
        for r in result.get(key, []) or []:
            if not isinstance(r, dict):
                errors.append(f"{label}: entrada no es un objeto: {r!r}")
                continue
            try:
                inicio = int(r["inicio"])
                fin = int(r["fin"])
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{label}: rango inválido {r!r}: {exc}")
                continue
            if inicio > fin:
                errors.append(f"{label}: inicio>fin ({inicio}-{fin})")
                continue
            for p in range(inicio, fin + 1):
                if p < 1 or p > total_pages:
                    errors.append(f"{label}: página {p} fuera del rango 1..{total_pages}")
                    continue
                if label == "contenido":
                    content_pages.add(p)
                else:
                    non_content_pages.add(p)

    both = content_pages & non_content_pages
    if both:
        errors.append(
            "Solapamiento contenido/accesorio en páginas: "
            f"{_compact_page_list(sorted(both))}"
        )

    all_expected = set(range(1, total_pages + 1))
    union = content_pages | non_content_pages
    missing = sorted(all_expected - union)
    if missing:
        errors.append(
            "Páginas sin clasificar (huecos): "
            f"{_compact_page_list(missing)}"
        )
    extra = sorted(union - all_expected)
    if extra:
        errors.append(f"Páginas fuera de 1..{total_pages}: {extra}")

    reported = result.get("total_paginas")
    if reported is not None:
        try:
            if int(reported) != total_pages:
                errors.append(
                    f"total_paginas en JSON ({reported}) != recuento pypdf ({total_pages})"
                )
        except (TypeError, ValueError):
            errors.append(f"total_paginas no es entero válido: {reported!r}")

    return (len(errors) == 0, errors)


@gemini_retry(max_retries=5)
def run_page_classifier(
    api_key: str,
    file_uri: str,
    total_pages: int,
    model: str = MODEL_CLASSIFIER,
    mime_type: str = "application/pdf",
) -> tuple[frozenset[int], Any, dict[str, Any]]:
    """Classify PDF pages into content vs. non-content.

    Calls the Gemini API with the numbered PDF and returns a frozenset of
    1-indexed page numbers that contain substantive content, plus ``usage_metadata``
    from the response (for token/cost tracking, same pattern as ``run_segmentador``),
    and the parsed JSON object (for auditing classifier range consistency).

    Args:
        total_pages: Expected total page count from pypdf (used for sanity check).

    Raises:
        GeminiError: On unrecoverable API failure after all retries.
        json.JSONDecodeError: If the model returns unparseable JSON.
    """
    start_time = time.time()
    logger.info(
        "Iniciando clasificador de páginas",
        extra={"file_uri_prefix": file_uri[:60], "total_pages": total_pages},
    )

    client = genai.Client(api_key=api_key)

    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_uri(file_uri=file_uri, mime_type=mime_type),
                types.Part.from_text(
                    text=(
                        "Clasifica las páginas de este documento en contenido sustantivo "
                        "y páginas accesorias, siguiendo las instrucciones del sistema."
                    )
                ),
            ],
        )
    ]

    config = types.GenerateContentConfig(
        temperature=TEMPERATURE_PAGE_CLASSIFIER,
        thinking_config=types.ThinkingConfig(thinking_level="LOW"),
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
        system_instruction=[types.Part.from_text(text=SYSTEM_INSTRUCTION)],
    )

    response = generate_content_with_retry(
        client=client,
        model=model,
        contents=contents,
        config=config,
        max_retries=5,
        operation_context={"agent": "page_classifier"},
    )

    result = json.loads(response.text)
    content_pages = _parse_classifier_result(result, total_pages)

    duration_ms = int((time.time() - start_time) * 1000)
    logger.info(
        f"Clasificador completado: {len(content_pages)}/{total_pages} páginas de contenido en {duration_ms}ms",
        extra={
            "content_pages_count": len(content_pages),
            "total_pages": total_pages,
            "duration_ms": duration_ms,
            "prompt_tokens": (
                getattr(response.usage_metadata, "prompt_token_count", 0)
                if response.usage_metadata
                else 0
            ),
        },
    )

    return content_pages, response.usage_metadata, result
