"""Agente Page Classifier — clasifica páginas de contenido vs. accesorias en un PDF."""
from __future__ import annotations

import json
import time
from typing import Any

from backend.gemini_model_routing import MODEL_CLASSIFIER
from backend.gemini_client import gemini_retry, generate_content_with_retry
from backend.logging_config import get_logger

from google import genai
from google.genai import types

logger = get_logger("backend.agents.page_classifier")

SYSTEM_INSTRUCTION = """<system_instruction>
  <role>
  Eres un clasificador de páginas de documentos académicos, técnicos o jurídicos.
  Tu única función es identificar qué páginas contienen contenido sustantivo que un estudiante
  debe aprender, y cuáles son páginas accesorias que no forman parte del cuerpo del documento.
  </role>

  <definitions>
  **Contenido sustantivo**: texto académico, técnico, jurídico o científico que constituye el
  cuerpo principal del documento. Incluye: teoría, conceptos, argumentaciones, procedimientos,
  normas, análisis, resultados, discusión. Si una página tiene al menos un párrafo de contenido
  sustantivo, clasifícala como contenido.

  **Páginas accesorias**: no forman parte del contenido que el estudiante debe aprender.
  Incluye: portada, contraportada, páginas en blanco, tabla de contenidos / índice, lista de
  figuras o tablas, agradecimientos, dedicatoria, prólogo sin contenido temático,
  bibliografía, referencias bibliográficas, notas finales, apéndices puramente referenciales,
  copyright, ISBN, colofón.
  </definitions>

  <instructions>
  1. Lee el documento completo.
  2. Usa las marcas visibles «— Página X / N —» al pie de cada página para identificar el
     número de cada página (1-indexed). El valor N es el total de páginas.
  3. Clasifica cada página como contenido o accesoria según las definiciones anteriores.
  4. Agrupa páginas consecutivas de la misma categoría en rangos.
  5. Devuelve el resultado en el JSON estructurado especificado. Sin texto adicional fuera del JSON.
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


@gemini_retry(max_retries=5)
def run_page_classifier(
    api_key: str,
    file_uri: str,
    total_pages: int,
    model: str = MODEL_CLASSIFIER,
    mime_type: str = "application/pdf",
) -> frozenset[int]:
    """Classify PDF pages into content vs. non-content.

    Calls the Gemini API with the numbered PDF and returns a frozenset of
    1-indexed page numbers that contain substantive content.

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

    return content_pages
