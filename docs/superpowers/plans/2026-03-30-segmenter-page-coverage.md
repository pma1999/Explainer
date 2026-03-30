# Segmenter Page Coverage Guarantee — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee that PDF segmentations always cover every content page exactly once, with no gaps or overlaps at part level or subpart level.

**Architecture:** A new `gemini-3-flash-preview` classifier identifies which pages are content vs. accessory before segmentation; this map is injected into the segmentador prompt as a hard constraint; after each segmentador call both MECE-tema and page-range reports are evaluated together; a single unified retry loop generates combined correction messages until both pass or attempts are exhausted.

**Tech Stack:** Python 3.12, FastAPI, google-genai SDK, pypdf, pytest. Follows existing patterns in `backend/agents/` and `backend/segmentation_tema_coverage.py`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/gemini_model_routing.py` | Modify | Add `MODEL_CLASSIFIER` constant |
| `backend/agents/page_classifier.py` | Create | Gemini agent that classifies pages as content/accessory |
| `backend/segmentation_page_coverage.py` | Create | Deterministic page-range validation + retry suffix builder |
| `backend/agents/segmentador.py` | Modify | Add PASO 8 to `thinking_protocol` (page coverage self-check) |
| `main.py` | Modify | Add `_build_content_pages_prefix`, integrate classifier, unified retry loop |
| `tests/backend/test_page_classifier.py` | Create | Unit tests for `_parse_classifier_result` |
| `tests/backend/test_segmentation_page_coverage.py` | Create | Unit tests for `validate_page_coverage` and `build_page_coverage_retry_suffix` |
| `tests/backend/test_main_helpers.py` | Create | Unit tests for `_build_content_pages_prefix` |

---

## Task 1: Add MODEL_CLASSIFIER constant

**Files:**
- Modify: `backend/gemini_model_routing.py`

No test needed for a single constant.

- [ ] **Step 1: Add the constant**

Open `backend/gemini_model_routing.py`. The file currently contains two lines. Add the third:

```python
"""Canonical Gemini model IDs for the Explainer pipeline."""

MODEL_SEGMENTADOR = "gemini-3.1-pro-preview"
MODEL_AGENTS = "gemini-3.1-flash-lite-preview"
MODEL_CLASSIFIER = "gemini-3-flash-preview"   # Lightweight content-page classifier
```

- [ ] **Step 2: Commit**

```bash
git add backend/gemini_model_routing.py
git commit -m "feat: add MODEL_CLASSIFIER constant for page classifier agent"
```

---

## Task 2: Create page classifier agent + tests

**Files:**
- Create: `backend/agents/page_classifier.py`
- Create: `tests/backend/test_page_classifier.py`

The public function `run_page_classifier` calls the Gemini API (not unit-testable without mocking). All logic that converts the JSON response to a `frozenset[int]` lives in `_parse_classifier_result`, which is pure and directly testable.

- [ ] **Step 1: Write the failing tests**

Create `tests/backend/test_page_classifier.py`:

```python
"""Unit tests for _parse_classifier_result in page_classifier."""

from __future__ import annotations

import pytest


def test_single_content_range():
    from backend.agents.page_classifier import _parse_classifier_result
    r = {"total_paginas": 10, "rangos_contenido": [{"inicio": 3, "fin": 8}], "rangos_no_contenido": []}
    pages = _parse_classifier_result(r, total_pages=10)
    assert pages == frozenset(range(3, 9))


def test_multiple_content_ranges():
    from backend.agents.page_classifier import _parse_classifier_result
    r = {
        "total_paginas": 20,
        "rangos_contenido": [{"inicio": 1, "fin": 5}, {"inicio": 8, "fin": 12}],
        "rangos_no_contenido": [],
    }
    pages = _parse_classifier_result(r, total_pages=20)
    assert pages == frozenset([1, 2, 3, 4, 5, 8, 9, 10, 11, 12])


def test_all_pages_content():
    from backend.agents.page_classifier import _parse_classifier_result
    r = {"total_paginas": 5, "rangos_contenido": [{"inicio": 1, "fin": 5}], "rangos_no_contenido": []}
    pages = _parse_classifier_result(r, total_pages=5)
    assert pages == frozenset(range(1, 6))


def test_no_content_pages():
    from backend.agents.page_classifier import _parse_classifier_result
    r = {"total_paginas": 5, "rangos_contenido": [], "rangos_no_contenido": []}
    pages = _parse_classifier_result(r, total_pages=5)
    assert pages == frozenset()


def test_inverted_range_is_ignored():
    """A range with inicio > fin produces no pages (safe skip)."""
    from backend.agents.page_classifier import _parse_classifier_result
    r = {"total_paginas": 5, "rangos_contenido": [{"inicio": 5, "fin": 2}], "rangos_no_contenido": []}
    pages = _parse_classifier_result(r, total_pages=5)
    assert pages == frozenset()


def test_total_pages_mismatch_logs_warning_but_returns_pages(caplog):
    """Mismatch between pypdf count and model count: log warning, return classification."""
    import logging
    from backend.agents.page_classifier import _parse_classifier_result
    r = {"total_paginas": 10, "rangos_contenido": [{"inicio": 1, "fin": 5}], "rangos_no_contenido": []}
    with caplog.at_level(logging.WARNING, logger="backend.agents.page_classifier"):
        pages = _parse_classifier_result(r, total_pages=12)
    assert pages == frozenset(range(1, 6))
    assert any("12" in rec.message or "10" in rec.message for rec in caplog.records)


def test_single_page_range():
    from backend.agents.page_classifier import _parse_classifier_result
    r = {"total_paginas": 3, "rangos_contenido": [{"inicio": 2, "fin": 2}], "rangos_no_contenido": []}
    pages = _parse_classifier_result(r, total_pages=3)
    assert pages == frozenset([2])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:/Users/PcVIP/Documents/Stuff/Explainer
python -m pytest tests/backend/test_page_classifier.py -v
```

Expected: `ImportError: cannot import name '_parse_classifier_result' from 'backend.agents.page_classifier'`

- [ ] **Step 3: Create `backend/agents/page_classifier.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/backend/test_page_classifier.py -v
```

Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/agents/page_classifier.py tests/backend/test_page_classifier.py
git commit -m "feat: add page classifier agent and unit tests"
```

---

## Task 3: Create segmentation page coverage validator + tests

**Files:**
- Create: `backend/segmentation_page_coverage.py`
- Create: `tests/backend/test_segmentation_page_coverage.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/backend/test_segmentation_page_coverage.py`:

```python
"""Unit tests for page-range coverage validation (segmentation_page_coverage)."""

from __future__ import annotations

import pytest

from backend.segmentation_page_coverage import (
    build_page_coverage_retry_suffix,
    validate_page_coverage,
)

# Pages 3-20 are content in most tests
CONTENT = frozenset(range(3, 21))


def _parte(num: int, pi: int, pf: int, subpartes: list[dict] | None = None) -> dict:
    p: dict = {"numero": num, "titulo": f"Parte {num}", "pagina_inicio": pi, "pagina_fin": pf}
    if subpartes is not None:
        p["subpartes"] = subpartes
    return p


def _sp(num: int, pi: int, pf: int) -> dict:
    return {"numero_subparte": num, "titulo": f"SP{num}", "pagina_inicio": pi, "pagina_fin": pf}


# ── Part-level ────────────────────────────────────────────────────────────────

def test_valid_single_part_covers_all():
    r = validate_page_coverage({"partes": [_parte(1, 3, 20)]}, CONTENT)
    assert r.is_valid
    assert not r.part_errors
    assert not r.subpart_errors


def test_valid_two_parts_contiguous():
    r = validate_page_coverage({"partes": [_parte(1, 3, 10), _parte(2, 11, 20)]}, CONTENT)
    assert r.is_valid


def test_parts_overlap():
    r = validate_page_coverage({"partes": [_parte(1, 3, 12), _parte(2, 10, 20)]}, CONTENT)
    assert not r.is_valid
    assert any(e.type == "overlap" for e in r.part_errors)


def test_content_page_uncovered():
    # Pages 10-11 are content but not in any part
    r = validate_page_coverage({"partes": [_parte(1, 3, 9), _parte(2, 12, 20)]}, CONTENT)
    assert not r.is_valid
    missing = [e for e in r.part_errors if e.type == "missing_content_pages"]
    assert missing
    assert "10" in missing[0].detail or "11" in missing[0].detail


def test_gap_in_non_content_pages_is_valid():
    # Pages 10-11 are NOT content → gap is acceptable
    content = frozenset(range(3, 10)) | frozenset(range(12, 21))
    r = validate_page_coverage({"partes": [_parte(1, 3, 9), _parte(2, 12, 20)]}, content)
    assert r.is_valid


def test_invalid_range_pi_greater_than_pf():
    r = validate_page_coverage({"partes": [_parte(1, 10, 5)]}, frozenset(range(1, 11)))
    assert not r.is_valid
    assert any(e.type == "invalid_range" for e in r.part_errors)


def test_missing_pagina_inicio_is_invalid_range():
    seg = {"partes": [{"numero": 1, "titulo": "P1", "pagina_fin": 10}]}
    r = validate_page_coverage(seg, frozenset(range(1, 11)))
    assert not r.is_valid
    assert any(e.type == "invalid_range" for e in r.part_errors)


def test_partes_not_a_list():
    r = validate_page_coverage({"partes": "bad"}, CONTENT)
    assert not r.is_valid


def test_empty_content_set_no_missing_errors():
    """No content pages → no missing-pages error even if parts leave gaps."""
    r = validate_page_coverage({"partes": [_parte(1, 5, 10), _parte(2, 15, 20)]}, frozenset())
    # Only possible errors are overlaps (none here), so should be valid
    assert r.is_valid


# ── Subpart-level ─────────────────────────────────────────────────────────────

def test_valid_subpartes_contiguous():
    part = _parte(1, 3, 20, subpartes=[_sp(1, 3, 10), _sp(2, 11, 20)])
    r = validate_page_coverage({"partes": [part]}, CONTENT)
    assert r.is_valid


def test_subpart_gap():
    part = _parte(1, 3, 20, subpartes=[_sp(1, 3, 9), _sp(2, 12, 20)])
    r = validate_page_coverage({"partes": [part]}, CONTENT)
    assert not r.is_valid
    assert any(e.type == "gap" for e in r.subpart_errors)
    gap_err = next(e for e in r.subpart_errors if e.type == "gap")
    assert "10" in gap_err.detail or "11" in gap_err.detail


def test_subpart_overlap():
    part = _parte(1, 3, 20, subpartes=[_sp(1, 3, 12), _sp(2, 10, 20)])
    r = validate_page_coverage({"partes": [part]}, CONTENT)
    assert not r.is_valid
    assert any(e.type == "overlap" for e in r.subpart_errors)


def test_subpart_doesnt_start_at_part():
    part = _parte(1, 3, 20, subpartes=[_sp(1, 5, 10), _sp(2, 11, 20)])
    r = validate_page_coverage({"partes": [part]}, CONTENT)
    assert not r.is_valid
    assert any(e.type == "doesnt_start_at_part" for e in r.subpart_errors)


def test_subpart_doesnt_end_at_part():
    part = _parte(1, 3, 20, subpartes=[_sp(1, 3, 10), _sp(2, 11, 18)])
    r = validate_page_coverage({"partes": [part]}, CONTENT)
    assert not r.is_valid
    assert any(e.type == "doesnt_end_at_part" for e in r.subpart_errors)


def test_empty_subpartes_list_is_valid():
    part = _parte(1, 3, 20, subpartes=[])
    r = validate_page_coverage({"partes": [part]}, CONTENT)
    assert r.is_valid


def test_no_subpartes_key_is_valid():
    # _parte called without subpartes kwarg → no "subpartes" key in dict
    part = _parte(1, 3, 20)
    r = validate_page_coverage({"partes": [part]}, CONTENT)
    assert r.is_valid


def test_subpart_invalid_range():
    part = _parte(1, 3, 20, subpartes=[_sp(1, 3, 10), _sp(2, 15, 12)])  # 15 > 12
    r = validate_page_coverage({"partes": [part]}, CONTENT)
    assert not r.is_valid
    assert any(e.type == "invalid_range" for e in r.subpart_errors)


def test_part_level_error_does_not_trigger_subpart_validation_for_that_part():
    """If a part has an invalid range, its subparts are not validated (avoids noise)."""
    # Part 1 has invalid range → skip its subpart validation
    # Part 2 is valid and has a subpart gap → subpart error for part 2
    part1 = _parte(1, 10, 5, subpartes=[_sp(1, 10, 7), _sp(2, 8, 5)])  # invalid range
    part2 = _parte(2, 11, 20, subpartes=[_sp(1, 11, 14), _sp(2, 16, 20)])  # gap at 15
    r = validate_page_coverage({"partes": [part1, part2]}, frozenset(range(3, 21)))
    assert not r.is_valid
    # Subpart errors only for part 2, not part 1
    assert all(e.part_numero == 2 for e in r.subpart_errors)


# ── Retry suffix ──────────────────────────────────────────────────────────────

def test_retry_suffix_wrapping_tags():
    seg = {"partes": [_parte(1, 3, 9), _parte(2, 12, 20)]}
    report = validate_page_coverage(seg, CONTENT)
    text = build_page_coverage_retry_suffix(
        attempt=1, segmentation=seg, report=report, content_page_set=CONTENT
    )
    assert "<correccion_rangos_pagina>" in text
    assert "</correccion_rangos_pagina>" in text


def test_retry_suffix_missing_pages_mentioned():
    seg = {"partes": [_parte(1, 3, 9), _parte(2, 12, 20)]}
    report = validate_page_coverage(seg, CONTENT)
    text = build_page_coverage_retry_suffix(
        attempt=0, segmentation=seg, report=report, content_page_set=CONTENT
    )
    # Pages 10-11 are missing
    assert "10" in text or "11" in text


def test_retry_suffix_subpart_errors_mentioned():
    part = _parte(1, 3, 20, subpartes=[_sp(1, 3, 9), _sp(2, 12, 20)])
    seg = {"partes": [part]}
    report = validate_page_coverage(seg, CONTENT)
    text = build_page_coverage_retry_suffix(
        attempt=0, segmentation=seg, report=report, content_page_set=CONTENT
    )
    assert "subparte" in text.lower()


def test_retry_suffix_requirements_block():
    seg = {"partes": [_parte(1, 3, 20)]}
    content = frozenset(range(3, 25))  # pages 21-24 uncovered
    report = validate_page_coverage(seg, content)
    text = build_page_coverage_retry_suffix(
        attempt=0, segmentation=seg, report=report, content_page_set=content
    )
    assert "REQUISITOS" in text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/backend/test_segmentation_page_coverage.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.segmentation_page_coverage'`

- [ ] **Step 3: Create `backend/segmentation_page_coverage.py`**

```python
"""Page-range validation for PDF segmentations.

Validates that:
- Part page ranges cover all content pages without gaps or overlaps (level 1).
- Subpart page ranges within each part are contiguous and cover the full part range (level 2).

Used after run_segmentador to detect and describe page coverage errors,
and to build retry instructions when the model output is incorrect.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

MAX_PAGE_COVERAGE_ATTEMPTS = 3

SEGMENTATION_PAGE_COVERAGE_USER_MESSAGE = (
    "La segmentación no pudo asignar correctamente los rangos de página "
    "tras varios intentos. Revisa el documento o vuelve a intentar el procesamiento."
)


@dataclass(frozen=True, slots=True)
class PartPageError:
    type: str  # "invalid_range" | "overlap" | "missing_content_pages"
    part_numero: int
    detail: str


@dataclass(frozen=True, slots=True)
class SubpartPageError:
    type: str  # "invalid_range" | "gap" | "overlap" | "doesnt_start_at_part" | "doesnt_end_at_part"
    part_numero: int
    subpart_numero: int
    detail: str


@dataclass(frozen=True, slots=True)
class PageCoverageReport:
    is_valid: bool
    part_errors: tuple[PartPageError, ...]
    subpart_errors: tuple[SubpartPageError, ...]


def _try_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def validate_page_coverage(
    segmentation: dict[str, Any],
    content_page_set: frozenset[int],
) -> PageCoverageReport:
    """Validate page range coverage for a PDF segmentation at part and subpart level.

    Args:
        segmentation: The segmentation dict returned by run_segmentador.
        content_page_set: Frozenset of 1-indexed page numbers classified as content.
                          May be empty (e.g. classifier fallback), in which case
                          only overlap errors are detected.

    Returns:
        PageCoverageReport with is_valid=True iff no errors are found.
    """
    part_errors: list[PartPageError] = []
    subpart_errors: list[SubpartPageError] = []

    partes = segmentation.get("partes")
    if not isinstance(partes, list):
        return PageCoverageReport(is_valid=False, part_errors=(), subpart_errors=())

    # ── Level 1: validate part ranges ────────────────────────────────────────
    valid_parts: list[dict[str, Any]] = []

    for parte in partes:
        if not isinstance(parte, dict):
            continue
        num = _try_int(parte.get("numero"))
        if num is None:
            continue
        pi = _try_int(parte.get("pagina_inicio"))
        pf = _try_int(parte.get("pagina_fin"))
        if pi is None or pf is None or pi < 1 or pf < 1 or pi > pf:
            part_errors.append(PartPageError(
                type="invalid_range",
                part_numero=num,
                detail=(
                    f"Parte {num}: pagina_inicio={parte.get('pagina_inicio')!r}, "
                    f"pagina_fin={parte.get('pagina_fin')!r} — rango inválido o ausente."
                ),
            ))
        else:
            valid_parts.append(parte)

    # Sort by pagina_inicio for overlap/gap detection
    valid_parts.sort(key=lambda p: int(p["pagina_inicio"]))

    # Overlap detection between consecutive parts
    for i in range(len(valid_parts) - 1):
        a = valid_parts[i]
        b = valid_parts[i + 1]
        a_num = int(a["numero"])
        b_num = int(b["numero"])
        a_end = int(a["pagina_fin"])
        b_start = int(b["pagina_inicio"])
        if a_end >= b_start:
            part_errors.append(PartPageError(
                type="overlap",
                part_numero=a_num,
                detail=(
                    f"Parte {a_num} (termina en pág. {a_end}) se solapa con "
                    f"Parte {b_num} (empieza en pág. {b_start})."
                ),
            ))

    # Content page gap detection (skip if any invalid_range errors to avoid noise)
    has_invalid_range = any(e.type == "invalid_range" for e in part_errors)
    if not has_invalid_range and content_page_set:
        covered: set[int] = set()
        for parte in valid_parts:
            pi = int(parte["pagina_inicio"])
            pf = int(parte["pagina_fin"])
            covered.update(range(pi, pf + 1))
        missing = sorted(content_page_set - covered)
        if missing:
            part_errors.append(PartPageError(
                type="missing_content_pages",
                part_numero=0,  # 0 = not attributed to a single part
                detail=f"Páginas de contenido sin cubrir por ninguna parte: {_compact_page_list(missing)}",
            ))

    # ── Level 2: validate subpart ranges within each part ────────────────────
    # Only validate parts that had no level-1 errors
    errored_part_numbers = {e.part_numero for e in part_errors if e.part_numero != 0}

    for parte in valid_parts:
        p_num = int(parte["numero"])
        if p_num in errored_part_numbers:
            continue
        p_pi = int(parte["pagina_inicio"])
        p_pf = int(parte["pagina_fin"])

        subpartes = parte.get("subpartes")
        if not subpartes:  # None or empty list → valid (whole part is one implicit subpart)
            continue
        if not isinstance(subpartes, list):
            continue

        valid_sps: list[dict[str, Any]] = []
        for sp in subpartes:
            if not isinstance(sp, dict):
                continue
            sp_num = _try_int(sp.get("numero_subparte"))
            sp_pi = _try_int(sp.get("pagina_inicio"))
            sp_pf = _try_int(sp.get("pagina_fin"))
            if sp_num is None or sp_pi is None or sp_pf is None or sp_pi < 1 or sp_pf < 1 or sp_pi > sp_pf:
                subpart_errors.append(SubpartPageError(
                    type="invalid_range",
                    part_numero=p_num,
                    subpart_numero=sp_num or 0,
                    detail=(
                        f"Parte {p_num} Subparte {sp_num}: "
                        f"pagina_inicio={sp.get('pagina_inicio')!r}, "
                        f"pagina_fin={sp.get('pagina_fin')!r} — inválido."
                    ),
                ))
            else:
                valid_sps.append(sp)

        if not valid_sps:
            continue

        valid_sps.sort(key=lambda s: int(s["pagina_inicio"]))

        # First subpart must start at part's pagina_inicio
        first_start = int(valid_sps[0]["pagina_inicio"])
        first_num = int(valid_sps[0]["numero_subparte"])
        if first_start != p_pi:
            subpart_errors.append(SubpartPageError(
                type="doesnt_start_at_part",
                part_numero=p_num,
                subpart_numero=first_num,
                detail=(
                    f"Parte {p_num}: la primera subparte (SP{first_num}) empieza en pág. {first_start} "
                    f"pero la parte empieza en pág. {p_pi}."
                ),
            ))

        # Last subpart must end at part's pagina_fin
        last_end = int(valid_sps[-1]["pagina_fin"])
        last_num = int(valid_sps[-1]["numero_subparte"])
        if last_end != p_pf:
            subpart_errors.append(SubpartPageError(
                type="doesnt_end_at_part",
                part_numero=p_num,
                subpart_numero=last_num,
                detail=(
                    f"Parte {p_num}: la última subparte (SP{last_num}) termina en pág. {last_end} "
                    f"pero la parte termina en pág. {p_pf}."
                ),
            ))

        # Gaps and overlaps between consecutive subparts
        for j in range(len(valid_sps) - 1):
            a = valid_sps[j]
            b = valid_sps[j + 1]
            a_num = int(a["numero_subparte"])
            b_num = int(b["numero_subparte"])
            a_end = int(a["pagina_fin"])
            b_start = int(b["pagina_inicio"])
            if a_end + 1 < b_start:
                subpart_errors.append(SubpartPageError(
                    type="gap",
                    part_numero=p_num,
                    subpart_numero=a_num,
                    detail=(
                        f"Parte {p_num}: hueco entre SP{a_num} (termina pág. {a_end}) "
                        f"y SP{b_num} (empieza pág. {b_start}). "
                        f"Páginas sin cubrir: {_compact_page_list(list(range(a_end + 1, b_start)))}."
                    ),
                ))
            elif a_end >= b_start:
                subpart_errors.append(SubpartPageError(
                    type="overlap",
                    part_numero=p_num,
                    subpart_numero=a_num,
                    detail=(
                        f"Parte {p_num}: solapamiento entre SP{a_num} (termina pág. {a_end}) "
                        f"y SP{b_num} (empieza pág. {b_start})."
                    ),
                ))

    is_valid = not part_errors and not subpart_errors
    return PageCoverageReport(
        is_valid=is_valid,
        part_errors=tuple(part_errors),
        subpart_errors=tuple(subpart_errors),
    )


def _compact_page_list(pages: list[int]) -> str:
    """Convert a sorted list of page numbers to a compact range string.

    E.g. [3, 4, 5, 10] → '3-5, 10'
    """
    if not pages:
        return ""
    ranges: list[str] = []
    start = prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
        else:
            ranges.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = p
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ", ".join(ranges)


def _compact_segmentation_ranges(segmentation: dict[str, Any], max_chars: int = 6000) -> str:
    """Extract only page-range fields from segmentation for the retry message."""
    partes = segmentation.get("partes")
    slim: list[dict[str, Any]] = []
    if isinstance(partes, list):
        for p in partes:
            if not isinstance(p, dict):
                continue
            entry: dict[str, Any] = {
                "numero": p.get("numero"),
                "titulo": p.get("titulo"),
                "pagina_inicio": p.get("pagina_inicio"),
                "pagina_fin": p.get("pagina_fin"),
            }
            sps = p.get("subpartes")
            if isinstance(sps, list):
                entry["subpartes"] = [
                    {
                        "numero_subparte": sp.get("numero_subparte"),
                        "pagina_inicio": sp.get("pagina_inicio"),
                        "pagina_fin": sp.get("pagina_fin"),
                    }
                    for sp in sps
                    if isinstance(sp, dict)
                ]
            slim.append(entry)
    text = json.dumps(slim, ensure_ascii=False, indent=2)
    if len(text) > max_chars:
        text = text[: max_chars - 20] + "\n… [truncado]"
    return text


def build_page_coverage_retry_suffix(
    *,
    attempt: int,
    segmentation: dict[str, Any],
    report: PageCoverageReport,
    content_page_set: frozenset[int],
) -> str:
    """Build a correction message block for a page coverage retry.

    Returns a string starting with <correccion_rangos_pagina> that describes
    each error and lists the requirements for a valid correction.
    """
    lines: list[str] = [
        "<correccion_rangos_pagina>",
        f"Intento de corrección: {attempt + 1}. Los rangos de página de la respuesta anterior no son correctos.",
        "",
        f"PÁGINAS DE CONTENIDO QUE DEBEN CUBRIRSE: {_compact_page_list(sorted(content_page_set))}",
        "",
    ]

    range_and_overlap_errors = [e for e in report.part_errors if e.type != "missing_content_pages"]
    missing_errors = [e for e in report.part_errors if e.type == "missing_content_pages"]

    if range_and_overlap_errors:
        lines.append("ERRORES EN RANGOS DE PARTES:")
        for e in range_and_overlap_errors:
            lines.append(f"  - {e.detail}")
        lines.append("")

    if missing_errors:
        for e in missing_errors:
            lines.append(f"COBERTURA INCOMPLETA: {e.detail}")
        lines.append("")

    if report.subpart_errors:
        by_part: dict[int, list[SubpartPageError]] = {}
        for e in report.subpart_errors:
            by_part.setdefault(e.part_numero, []).append(e)
        lines.append("ERRORES EN RANGOS DE SUBPARTES:")
        for p_num in sorted(by_part):
            lines.append(f"  Parte {p_num}:")
            for e in by_part[p_num]:
                lines.append(f"    - {e.detail}")
        lines.append("")

    lines += [
        "REQUISITOS PARA LA CORRECCIÓN:",
        "  - pagina_inicio y pagina_fin de cada parte: enteros positivos con pagina_inicio ≤ pagina_fin.",
        "  - Rangos de partes sin solapamientos: parte_i.pagina_fin < parte_{i+1}.pagina_inicio.",
        "  - Todas las páginas de contenido cubiertas por exactamente una parte.",
        "  - Subpartes de cada parte contiguas: subparte_j.pagina_fin + 1 == subparte_{j+1}.pagina_inicio.",
        "  - Primera subparte de cada parte: pagina_inicio == parte.pagina_inicio.",
        "  - Última subparte de cada parte: pagina_fin == parte.pagina_fin.",
        "",
        "RESPUESTA ANTERIOR — rangos de página (corrige y devuelve el JSON completo válido):",
        _compact_segmentation_ranges(segmentation),
        "</correccion_rangos_pagina>",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/backend/test_segmentation_page_coverage.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/segmentation_page_coverage.py tests/backend/test_segmentation_page_coverage.py
git commit -m "feat: add page coverage validator and retry suffix builder"
```

---

## Task 4: Reinforce segmentador thinking_protocol

**Files:**
- Modify: `backend/agents/segmentador.py`

The PDF `SYSTEM_INSTRUCTION` ends at line 222–224:

```python
Solo tras completar estos 7 pasos, genera tu output estructurado en el formato especificado.
</thinking_protocol>
</system_instruction>"""
```

No unit test is possible for a prompt string (it's verified by the model at runtime). Verify manually that the string is syntactically intact after editing.

- [ ] **Step 1: Add PASO 8 to the thinking_protocol**

In `backend/agents/segmentador.py`, find and replace the closing lines of the PDF `SYSTEM_INSTRUCTION` `thinking_protocol` block. The current last lines of the block are:

```
Solo tras completar estos 7 pasos, genera tu output estructurado en el formato especificado.
</thinking_protocol>
</system_instruction>"""
```

Replace with:

```
**PASO 8 — VERIFICACIÓN EXPLÍCITA DE COBERTURA DE PÁGINAS:**
Si tu input incluye una sección `<paginas_contenido_verificado>`, ejecuta este paso obligatoriamente antes de generar el output:

1. Extrae la lista de páginas de contenido del bloque `<paginas_contenido_verificado>`.
2. Para cada página de contenido, identifica en qué parte (número) y subparte (número) queda asignada. Construye mentalmente una tabla: página → parte → subparte.
3. Verifica que ninguna página de contenido queda sin asignación.
4. Verifica que ninguna página de contenido aparece en más de una parte.
5. Para cada parte, verifica que sus subpartes cubren exactamente el rango [pagina_inicio, pagina_fin]:
   - La primera subparte empieza en pagina_inicio de la parte.
   - La última subparte termina en pagina_fin de la parte.
   - No hay huecos entre subpartes consecutivas (subparte_j.pagina_fin + 1 == subparte_{j+1}.pagina_inicio).
   - No hay solapamientos entre subpartes consecutivas (subparte_j.pagina_fin < subparte_{j+1}.pagina_inicio).
6. Si detectas algún error, corrígelo antes de generar el output.

Solo tras completar estos 8 pasos, genera tu output estructurado en el formato especificado.
</thinking_protocol>
</system_instruction>"""
```

- [ ] **Step 2: Verify the string is syntactically valid Python**

```bash
python -c "import backend.agents.segmentador; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/agents/segmentador.py
git commit -m "feat: add PASO 8 page coverage self-check to segmentador thinking_protocol"
```

---

## Task 5: Integrate classifier and unified retry loop in main.py

**Files:**
- Modify: `main.py`
- Create: `tests/backend/test_main_helpers.py`

This task has five sub-steps. Read each carefully — show the exact surrounding context when editing to locate the right insertion point.

### Sub-step A: Add imports

- [ ] **Step 1: Write the failing test for `_build_content_pages_prefix`**

Create `tests/backend/test_main_helpers.py`:

```python
"""Unit tests for main.py helper functions."""

from __future__ import annotations

import pytest


def test_prefix_single_range():
    from main import _build_content_pages_prefix
    pages = frozenset(range(3, 13))  # 3-12
    result = _build_content_pages_prefix(pages, total_pages=15)
    assert "<paginas_contenido_verificado>" in result
    assert "3-12" in result
    assert "13-15" in result  # non-content range


def test_prefix_multiple_ranges():
    from main import _build_content_pages_prefix
    pages = frozenset(range(1, 6)) | frozenset(range(8, 12))  # 1-5, 8-11
    result = _build_content_pages_prefix(pages, total_pages=15)
    assert "1-5" in result
    assert "8-11" in result


def test_prefix_empty_set_returns_empty_string():
    from main import _build_content_pages_prefix
    result = _build_content_pages_prefix(frozenset(), total_pages=10)
    assert result == ""


def test_prefix_all_pages_content_no_non_content_line():
    from main import _build_content_pages_prefix
    pages = frozenset(range(1, 6))
    result = _build_content_pages_prefix(pages, total_pages=5)
    assert "<paginas_contenido_verificado>" in result
    assert "RESTRICCIÓN" in result
    assert "accesorias" not in result


def test_prefix_single_page():
    from main import _build_content_pages_prefix
    pages = frozenset([7])
    result = _build_content_pages_prefix(pages, total_pages=10)
    assert "7" in result
    assert result.startswith("<paginas_contenido_verificado>")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/backend/test_main_helpers.py -v
```

Expected: `ImportError: cannot import name '_build_content_pages_prefix' from 'main'`

- [ ] **Step 3: Add imports to `main.py`**

In `main.py`, find the existing import block that contains `MODEL_AGENTS` and `MODEL_SEGMENTADOR`:

```python
from backend.gemini_model_routing import MODEL_AGENTS, MODEL_SEGMENTADOR
```

Replace with:

```python
from backend.gemini_model_routing import MODEL_AGENTS, MODEL_SEGMENTADOR, MODEL_CLASSIFIER
```

Find the existing import block that contains `upload_file_with_retry`:

```python
from backend.gemini_client import upload_file_with_retry, GeminiError, GeminiRateLimitError
```

Replace with:

```python
from backend.gemini_client import upload_file_with_retry, GeminiError, GeminiRateLimitError
from backend.agents.page_classifier import run_page_classifier
from backend.segmentation_page_coverage import (
    MAX_PAGE_COVERAGE_ATTEMPTS,
    SEGMENTATION_PAGE_COVERAGE_USER_MESSAGE,
    build_page_coverage_retry_suffix,
    validate_page_coverage,
)
```

Also add `PdfReader` import. Find the line:

```python
from backend.pdf_utils import add_page_numbers, extract_page_range
```

Replace with:

```python
from backend.pdf_utils import add_page_numbers, extract_page_range
from pypdf import PdfReader
```

### Sub-step B: Add `_build_content_pages_prefix` helper

- [ ] **Step 4: Add the helper function to `main.py`**

Find the existing helper `_build_pdf_table_of_contents` (around line 377). Insert the new function **before** it:

```python
def _build_content_pages_prefix(content_page_set: frozenset[int], total_pages: int) -> str:
    """Build the <paginas_contenido_verificado> block injected into the segmentador prompt.

    Returns empty string if content_page_set is empty (e.g. non-PDF or classifier skipped).
    """
    if not content_page_set:
        return ""

    def _to_ranges(pages: list[int]) -> str:
        if not pages:
            return ""
        ranges: list[str] = []
        start = prev = pages[0]
        for p in pages[1:]:
            if p == prev + 1:
                prev = p
            else:
                ranges.append(f"{start}-{prev}" if start != prev else str(start))
                start = prev = p
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
        return ", ".join(ranges)

    content_str = _to_ranges(sorted(content_page_set))
    non_content = sorted(set(range(1, total_pages + 1)) - content_page_set)
    non_content_line = (
        f"\nPáginas sin contenido (accesorias, pueden excluirse): {_to_ranges(non_content)}"
        if non_content
        else ""
    )

    return (
        "<paginas_contenido_verificado>\n"
        f"Páginas con contenido sustantivo (DEBEN cubrirse): {content_str}{non_content_line}\n"
        "RESTRICCIÓN OBLIGATORIA: Los rangos pagina_inicio/pagina_fin de las partes deben cubrir "
        "colectivamente TODAS las páginas de contenido, sin huecos ni solapamientos entre partes. "
        "Las subpartes de cada parte deben ser contiguas y cubrir exactamente el rango de su parte padre.\n"
        "</paginas_contenido_verificado>\n\n"
    )


```

- [ ] **Step 5: Run the helper tests to verify they pass**

```bash
python -m pytest tests/backend/test_main_helpers.py -v
```

Expected: 5 tests PASS.

### Sub-step C: Initialize `pdf_total_pages` and `content_page_set`

- [ ] **Step 6: Add variable initializations at the top of `_process_project`**

In `_process_project` (around line 979), find the block that initializes process-level variables:

```python
    pdf_temp_path = None
    numbered_pdf_path = None
    segment_pdf_paths: list[str] = []
```

Replace with:

```python
    pdf_temp_path = None
    numbered_pdf_path = None
    pdf_total_pages: int = 0
    content_page_set: frozenset[int] = frozenset()
    segment_pdf_paths: list[str] = []
```

### Sub-step D: Capture `pdf_total_pages` and call the classifier

- [ ] **Step 7: Read `pdf_total_pages` after creating the numbered PDF**

In `_process_project`, find:

```python
            numbered_pdf_path = await asyncio.to_thread(add_page_numbers, pdf_temp_path)
            logger.info(f"[Process] PDF numerado creado: {numbered_pdf_path}")
```

Replace with:

```python
            numbered_pdf_path = await asyncio.to_thread(add_page_numbers, pdf_temp_path)
            pdf_total_pages = len(PdfReader(numbered_pdf_path).pages)
            logger.info(f"[Process] PDF numerado creado: {numbered_pdf_path} ({pdf_total_pages} páginas)")
```

- [ ] **Step 8: Add the classifier call after the PDF is uploaded**

Find the block that ends the PDF upload phase:

```python
            update_project(project_id, user_id, {"file_uri": file_uri, "status": "segmenting"})
            await send_event(project_id, {"type": "segmenting"})

        # Fase de segmentación (con validación MECE de temas y reintentos)
```

Insert the classifier call between the `send_event` and the segmentation comment:

```python
            update_project(project_id, user_id, {"file_uri": file_uri, "status": "segmenting"})
            await send_event(project_id, {"type": "segmenting"})

            # Classify content vs. accessory pages before segmentation
            try:
                content_page_set = await asyncio.to_thread(
                    run_page_classifier,
                    api_key,
                    file_uri,
                    pdf_total_pages,
                    MODEL_CLASSIFIER,
                )
                logger.info(
                    f"[Process] Clasificador: {len(content_page_set)}/{pdf_total_pages} páginas de contenido",
                    extra={"content_pages_count": len(content_page_set), "total_pages": pdf_total_pages},
                )
            except Exception as clf_err:
                content_page_set = frozenset(range(1, pdf_total_pages + 1))
                logger.warning(
                    f"[Process] Clasificador falló tras reintentos; todas las páginas tratadas como contenido: {clf_err}",
                    extra={"error_type": type(clf_err).__name__},
                )

        # Fase de segmentación (con validación MECE de temas y reintentos)
```

### Sub-step E: Replace the segmentation loop

- [ ] **Step 9: Replace the entire segmentation loop**

Find the current loop — it starts with the comment and variable declarations:

```python
        # Fase de segmentación (con validación MECE de temas y reintentos)
        logger.info("[Process] Iniciando segmentación del documento")
        seg_start = time.time()
        segmentation: dict | None = None
        tema_report = None
        for seg_attempt in range(MAX_SEGMENTATION_COVERAGE_ATTEMPTS):
```

And ends with the `return` on line 1320:

```python
            return
```

Replace the entire block (from the comment through the `return`) with:

```python
        # Fase de segmentación (validación MECE de temas + cobertura de páginas, reintentos unificados)
        logger.info("[Process] Iniciando segmentación del documento")
        seg_start = time.time()
        segmentation: dict | None = None
        tema_report = None
        page_report = None
        is_pdf_seg = source_type == "pdf"
        MAX_COMBINED_ATTEMPTS = max(MAX_SEGMENTATION_COVERAGE_ATTEMPTS, MAX_PAGE_COVERAGE_ATTEMPTS)
        content_pages_prefix = (
            _build_content_pages_prefix(content_page_set, pdf_total_pages)
            if is_pdf_seg and content_page_set
            else ""
        )

        for seg_attempt in range(MAX_COMBINED_ATTEMPTS):
            base_desc = (project["description"].strip() or DEFAULT_DESCRIPTION)

            if seg_attempt == 0:
                seg_description = content_pages_prefix + base_desc
            else:
                assert segmentation is not None
                correction_parts: list[str] = []
                if tema_report is not None and not tema_report.is_valid:
                    correction_parts.append(
                        build_tema_coverage_retry_suffix(
                            attempt=seg_attempt,
                            segmentation=segmentation,
                            report=tema_report,
                        )
                    )
                if page_report is not None and not page_report.is_valid:
                    correction_parts.append(
                        build_page_coverage_retry_suffix(
                            attempt=seg_attempt,
                            segmentation=segmentation,
                            report=page_report,
                            content_page_set=content_page_set,
                        )
                    )
                correction_suffix = "\n\n".join(correction_parts)
                seg_description = content_pages_prefix + base_desc + "\n\n" + correction_suffix

            segmentation, usage_meta = await asyncio.to_thread(
                run_segmentador,
                api_key,
                file_uri,
                seg_description,
                MODEL_SEGMENTADOR,
                source_mime_type,
                source_kind,
            )
            phase = "segmentation" if seg_attempt == 0 else f"segmentation_retry_{seg_attempt}"
            _update_usage(usage_meta, phase=phase, cost_model=MODEL_SEGMENTADOR)
            await send_event(project_id, {"type": "usage_update", "usage": cumulative_usage})

            tema_report = validate_tema_partition(segmentation)
            page_report = (
                validate_page_coverage(segmentation, content_page_set)
                if is_pdf_seg
                else None
            )

            both_valid = tema_report.is_valid and (page_report is None or page_report.is_valid)

            if both_valid:
                if tema_report.empty_temas_inventory:
                    logger.warning(
                        "[Process] Segmentación sin temas_identificados; se omite validación MECE de temas",
                        extra={"project_id": project_id, "seg_attempt": seg_attempt},
                    )
                if seg_attempt > 0:
                    logger.info(
                        "[Process] Segmentación corregida tras reintento (temas + páginas)",
                        extra={"project_id": project_id, "seg_attempt": seg_attempt},
                    )
                break

            logger.warning(
                "[Process] Validación fallida; se reintentará el segmentador si quedan intentos",
                extra={
                    "seg_attempt": seg_attempt,
                    "tema_valid": tema_report.is_valid,
                    "page_valid": page_report.is_valid if page_report else True,
                    "tema_missing": len(tema_report.missing),
                    "tema_duplicates": len(tema_report.duplicates),
                    "page_part_errors": len(page_report.part_errors) if page_report else 0,
                    "page_subpart_errors": len(page_report.subpart_errors) if page_report else 0,
                },
            )
        else:
            assert segmentation is not None
            error_bits: list[str] = []
            if tema_report and not tema_report.is_valid:
                if tema_report.missing:
                    error_bits.append(f"{len(tema_report.missing)} tema(s) sin asignar")
                if tema_report.duplicates:
                    error_bits.append(f"{len(tema_report.duplicates)} tema(s) duplicados entre partes")
                if tema_report.orphans:
                    error_bits.append(f"{len(tema_report.orphans)} entrada(s) huérfana(s)")
                if tema_report.structural_errors:
                    error_bits.append(f"{len(tema_report.structural_errors)} error(es) de forma")
            if page_report and not page_report.is_valid:
                if page_report.part_errors:
                    error_bits.append(f"{len(page_report.part_errors)} error(es) de rango en partes")
                if page_report.subpart_errors:
                    error_bits.append(f"{len(page_report.subpart_errors)} error(es) de rango en subpartes")
            detail = "; ".join(error_bits) if error_bits else "inconsistencias en segmentación"
            logger.error(
                "[Process] Segmentación abortada tras agotar reintentos",
                extra={"attempts": MAX_COMBINED_ATTEMPTS, "detail": detail},
            )
            update_project(
                project_id,
                user_id,
                {
                    "segmentation": segmentation,
                    "partes_contenido": {},
                    "status": "error",
                    "error_message": SEGMENTATION_TEMA_COVERAGE_USER_MESSAGE,
                },
            )
            await send_event(
                project_id,
                {"type": "error", "message": SEGMENTATION_TEMA_COVERAGE_USER_MESSAGE},
            )
            return
```

- [ ] **Step 10: Verify `main.py` imports correctly**

```bash
python -c "import main; print('OK')"
```

Expected: `OK`

- [ ] **Step 11: Run all unit tests**

```bash
python -m pytest tests/backend/test_page_classifier.py tests/backend/test_segmentation_page_coverage.py tests/backend/test_main_helpers.py -v
```

Expected: all tests PASS.

- [ ] **Step 12: Run the full test suite to check for regressions**

```bash
python -m pytest tests/ -v --ignore=tests/backend/test_gemini_pdf_live_investiture.py --ignore=tests/backend/test_formatter_live.py --ignore=tests/backend/test_pdf_process_flow.py --ignore=tests/backend/test_web_url_support.py -x
```

Expected: all non-live tests PASS. The ignored tests require live API keys and are out of scope.

- [ ] **Step 13: Commit**

```bash
git add main.py tests/backend/test_main_helpers.py
git commit -m "feat: integrate page classifier and unified retry loop in main.py"
```

---

## Self-Review Checklist

After completing all tasks, verify:

- [ ] `MODEL_CLASSIFIER = "gemini-3-flash-preview"` in `gemini_model_routing.py`
- [ ] `_parse_classifier_result` is importable and all 7 tests pass
- [ ] `validate_page_coverage` is importable and all 17 tests pass
- [ ] `build_page_coverage_retry_suffix` output contains `<correccion_rangos_pagina>` and `</correccion_rangos_pagina>`
- [ ] `_build_content_pages_prefix` returns empty string for empty frozenset, and a well-formed block otherwise
- [ ] `segmentador.py` contains "PASO 8" and `python -c "import backend.agents.segmentador"` succeeds
- [ ] `main.py` imports cleanly with `python -c "import main"`
- [ ] The classifier call is inside the PDF branch only (guarded by `source_type == "pdf"`)
- [ ] `page_report = None` for non-PDF sources, so `both_valid` treats it as valid
- [ ] The fallback sets `content_page_set = frozenset(range(1, pdf_total_pages + 1))` — all pages treated as content
- [ ] No existing test that was passing before now fails
