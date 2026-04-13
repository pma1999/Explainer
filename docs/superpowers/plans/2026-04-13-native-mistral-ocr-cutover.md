# Native Mistral OCR Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sustituir por completo el OCR de PDFs del flujo OpenRouter por Mistral nativo, cacheando solo las páginas con contenido detectadas por el page classifier y enviando al explainer únicamente las páginas que corresponden a cada subparte.

**Architecture:** El cambio separa OCR y explicación en dos capas limpias: `backend/mistral_ocr_client.py` hará el OCR nativo e incremental sobre el `numbered_pdf_path`, mientras que `backend/agents/explainer_openrouter.py` seguirá siendo solo el cliente del explainer. La caché OCR pasará a ser genérica y provider-neutral (`source_sha256 + engine`), con la misma semántica incremental actual: si en una ejecución posterior faltan páginas por cachear, solo se OCRarán esas páginas faltantes y se fusionarán en la misma línea de caché.

**Tech Stack:** Python 3.13, FastAPI, `mistralai==2.3.2`, Supabase Postgres, `pypdf`, OpenRouter, Gemini, frontend vanilla JS, pytest, Vitest.

---

## File Structure

- Create: `backend/pdf_ocr_cache.py`
  - Tipos y utilidades provider-neutrales para OCR de PDF: dataclasses, serialización, fusión incremental, render de subconjuntos y artefactos de diagnóstico.
- Create: `backend/supabase_pdf_ocr_cache.py`
  - Persistencia Postgres para la nueva caché `pdf_ocr_cache`.
- Create: `backend/mistral_ocr_client.py`
  - Cliente Mistral OCR nativo: subida, signed URL, OCR por páginas, normalización de respuesta, borrado remoto y priming incremental.
- Modify: `backend/agents/explainer_openrouter.py`
  - Consumir OCR ya preparado, sin volver a ejecutar OCR vía OpenRouter.
- Modify: `main.py`
  - Preparar el OCR canónico de Mistral solo sobre `content_page_set`, conservar el page-scoping actual y exigir la key de Mistral cuando aplique.
- Modify: `backend/supabase_data.py`
  - Añadir `PROVIDER_MISTRAL` y exponer su estado como el resto de providers.
- Modify: `frontend/index.html`
  - Añadir la sección de API key de Mistral y actualizar el copy de OpenRouter.
- Modify: `frontend/js/state.js`
  - Estado y TTL de la key de Mistral.
- Modify: `frontend/js/storage.js`
  - Cache local del estado BYOK de Mistral.
- Modify: `frontend/js/auth.js`
  - Guardar, borrar, refrescar y mostrar el estado de la key de Mistral.
- Modify: `frontend/js/landing.js`
  - Validar que `PDF + OpenRouter` requiere Gemini + OpenRouter + Mistral, pero `Web + OpenRouter` no requiere Mistral.
- Create: `tests/backend/test_pdf_ocr_cache.py`
  - Cobertura unitaria del contrato genérico de caché OCR.
- Create: `tests/backend/test_supabase_pdf_ocr_cache.py`
  - Cobertura de la tabla nueva `pdf_ocr_cache`.
- Create: `tests/backend/test_mistral_ocr_client.py`
  - Cobertura del cliente nativo de Mistral y su incrementalidad.
- Modify: `tests/backend/test_explainer_openrouter.py`
  - Verificar que el explainer reutiliza el subconjunto OCR de Mistral.
- Modify: `tests/backend/test_main_helpers.py`
  - Verificar que `main.py` prepara OCR solo sobre `content_page_set`.
- Modify: `tests/backend/test_pdf_process_flow.py`
  - Verificar page scopes, retry con la misma caché y backfill de páginas faltantes.
- Modify: `tests/backend/test_api.py`
  - Verificar endpoints y requisitos de la key de Mistral.
- Modify: `tests/frontend/auth.test.js`
  - Verificar refresh/caché del estado de Mistral.
- Modify: `tests/frontend/landing.test.js`
  - Verificar reglas de selección de provider con Mistral.
- Modify: `tests/test_pid_00230265_subpart_scope_audit.py`
  - Usar la nueva vía canónica Mistral en el script de auditoría live.
- Modify: `requirements.txt`
  - Añadir el SDK oficial de Mistral.
- Create: `supabase/migrations/20260413170000_pdf_ocr_cache.sql`
  - Nueva tabla provider-neutral para la caché OCR.

## Design Constraints

- El OCR canónico debe ejecutarse sobre `numbered_pdf_path`, no sobre el PDF original.
- Solo se deben OCRar las páginas de `content_page_set`, nunca páginas accesorias fuera del clasificador.
- Los números de página internos del pipeline siguen siendo 1-based; la petición a Mistral usará índices 0-based y se normalizará de vuelta inmediatamente.
- El page-scope que llega al explainer no cambia: `_select_openrouter_pdf_pages()` sigue decidiendo qué páginas de contenido pertenecen a cada subparte.
- La caché incremental debe conservar exactamente la semántica actual:
  - misma clave lógica (`source_sha256 + engine`),
  - misma caché física/registro si ya existe,
  - OCR solo de `missing_pages`,
  - merge ordenado y estable.
- `backend/agents/explainer_openrouter.py` deja de disparar OCR. Si no recibe un `pdf_cache_entry` reutilizable para PDF, debe degradar a texto local, no volver al OCR vía OpenRouter.
- `PDF + OpenRouter` requiere Gemini, OpenRouter y Mistral. `Web + OpenRouter` requiere Gemini y OpenRouter. `YouTube` sigue siendo Gemini-only.
- La validación de la API key de Mistral no debe asumir un prefijo documentado; basta con una validación segura y permisiva (sin espacios, longitud mínima razonable).
- La respuesta OCR renderizada para el explainer debe expandir tablas de Mistral y no perderlas por dejar solo placeholders en `markdown`.
- El watermark `— Página X / N —` no debe contaminar el texto enviado al explainer; si Mistral lo devuelve en `footer`, debe omitirse durante el render.

---

## Task 1: Create Generic PDF OCR Cache Primitives And Persistence

**Files:**
- Create: `backend/pdf_ocr_cache.py`
- Create: `backend/supabase_pdf_ocr_cache.py`
- Create: `tests/backend/test_pdf_ocr_cache.py`
- Create: `tests/backend/test_supabase_pdf_ocr_cache.py`
- Create: `supabase/migrations/20260413170000_pdf_ocr_cache.sql`

La nueva ruta OCR necesita un contrato genérico que no dependa de OpenRouter ni de marcadores heurísticos. Este módulo será la fuente de verdad para la caché incremental y para renderizar el subconjunto que luego consumirá el explainer.

- [ ] **Step 1: Write the failing tests**

Create `tests/backend/test_pdf_ocr_cache.py`:

```python
from __future__ import annotations

import json

import pytest

from backend.pdf_ocr_cache import (
    PdfOcrBuildResult,
    PdfOcrCacheEntry,
    PdfOcrError,
    PdfOcrParsedPage,
    merge_page_indexes,
    render_pdf_page_subset_to_text,
    write_unresolved_pdf_ocr_artifact,
)


def _page(page_number: int, markdown: str, *, tables=(), images=(), footer=None) -> PdfOcrParsedPage:
    return PdfOcrParsedPage(
        page_number=page_number,
        markdown=markdown,
        tables=tuple(tables),
        images=tuple(images),
        footer=footer,
    )


def test_merge_page_indexes_replaces_updated_page_and_keeps_sorted_order():
    existing = (_page(1, "uno"), _page(3, "tres-viejo"))
    updates = (_page(2, "dos"), _page(3, "tres-nuevo"))

    merged = merge_page_indexes(existing, updates)

    assert tuple(page.page_number for page in merged) == (1, 2, 3)
    assert merged[2].markdown == "tres-nuevo"


def test_render_pdf_page_subset_to_text_inlines_tables_and_mentions_images():
    entry = PdfOcrCacheEntry(
        source_sha256="sha",
        engine="mistral-native",
        cache_path="cache.json",
        cache_hit=True,
        expected_page_numbers=(2,),
        cached_page_numbers=(2,),
        page_index=(
            _page(
                2,
                "Texto principal\n\n[tbl-1.html](tbl-1.html)\n\n![img-0.jpeg](img-0.jpeg)",
                tables=({"id": "tbl-1.html", "content": "<table><tr><td>42</td></tr></table>"} ,),
                images=({"id": "img-0.jpeg"},),
                footer="— Página 2 / 10 —",
            ),
        ),
    )

    rendered = render_pdf_page_subset_to_text(cache_entry=entry, page_numbers=(2,))

    assert "Texto principal" in rendered
    assert "<table><tr><td>42</td></tr></table>" in rendered
    assert "Imagen OCR img-0.jpeg" in rendered
    assert "— Página 2 / 10 —" not in rendered


def test_render_pdf_page_subset_to_text_requires_complete_page_coverage():
    entry = PdfOcrCacheEntry(
        source_sha256="sha",
        engine="mistral-native",
        cache_path="cache.json",
        cache_hit=True,
        expected_page_numbers=(1,),
        cached_page_numbers=(1,),
        page_index=(_page(1, "uno"),),
    )

    with pytest.raises(PdfOcrError, match="páginas ausentes"):
        render_pdf_page_subset_to_text(cache_entry=entry, page_numbers=(1, 3))


def test_write_unresolved_pdf_ocr_artifact_records_missing_pages(tmp_path):
    build_result = PdfOcrBuildResult(
        page_index=(_page(1, "uno"),),
        detected_pages=(1,),
        missing_pages=(2,),
        raw_response={"pages": [{"index": 0, "markdown": "uno"}]},
    )

    artifact_path = write_unresolved_pdf_ocr_artifact(
        cache_path=tmp_path / "cache.json",
        source_sha256="sha256",
        engine="mistral-native",
        model="mistral-ocr-latest",
        expected_page_numbers=(1, 2),
        build_result=build_result,
    )

    payload = json.loads((tmp_path / "cache.json.missing-pages.json").read_text(encoding="utf-8"))
    assert artifact_path.endswith(".missing-pages.json")
    assert payload["expected_pages"] == [1, 2]
    assert payload["detected_pages"] == [1]
    assert payload["missing_pages"] == [2]
    assert payload["raw_response"]["pages"][0]["index"] == 0
```

Create `tests/backend/test_supabase_pdf_ocr_cache.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock

from backend.supabase_pdf_ocr_cache import fetch_cache, supabase_cache_uri, try_write_cache


def _result(data):
    response = MagicMock()
    response.data = data
    return response


def test_supabase_cache_uri_uses_generic_table_name():
    assert supabase_cache_uri("deadbeef", "mistral-native") == (
        "supabase:pdf_ocr_cache/deadbeef/mistral-native"
    )


def test_fetch_cache_returns_payload_and_row_version(monkeypatch):
    fake_client = MagicMock()
    fake_client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = _result(
        [{"payload": {"version": 1}, "row_version": 7}]
    )
    monkeypatch.setattr("backend.supabase_pdf_ocr_cache._client", lambda: fake_client)

    payload, row_version = fetch_cache("sha", "mistral-native")

    assert payload == {"version": 1}
    assert row_version == 7


def test_try_write_cache_inserts_first_version(monkeypatch):
    fake_client = MagicMock()
    fake_client.table.return_value.insert.return_value.execute.return_value = _result(
        [{"row_version": 1}]
    )
    monkeypatch.setattr("backend.supabase_pdf_ocr_cache._client", lambda: fake_client)

    ok, row_version = try_write_cache("sha", "mistral-native", {"version": 1}, None)

    assert ok is True
    assert row_version == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest tests/backend/test_pdf_ocr_cache.py tests/backend/test_supabase_pdf_ocr_cache.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `backend.pdf_ocr_cache` / `backend.supabase_pdf_ocr_cache`.

- [ ] **Step 3: Write the minimal implementation**

Create `backend/pdf_ocr_cache.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


_PAGE_MARKER_ONLY_RE = re.compile(r"^— Página\s+\d+\s*/\s*\d+\s+—$")
_PDF_OCR_CACHE_VERSION = 1


class PdfOcrError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PdfOcrParsedPage:
    page_number: int
    markdown: str
    images: tuple[dict[str, Any], ...] = ()
    tables: tuple[dict[str, Any], ...] = ()
    hyperlinks: tuple[str, ...] = ()
    header: str | None = None
    footer: str | None = None
    dimensions: dict[str, Any] | None = None
    confidence_scores: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class PdfOcrBuildResult:
    page_index: tuple[PdfOcrParsedPage, ...]
    detected_pages: tuple[int, ...]
    missing_pages: tuple[int, ...]
    raw_response: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PdfOcrCacheEntry:
    source_sha256: str
    engine: str
    cache_path: str
    cache_hit: bool
    expected_page_numbers: tuple[int, ...] = ()
    cached_page_numbers: tuple[int, ...] = ()
    page_index: tuple[PdfOcrParsedPage, ...] = ()
    diagnostic_artifact_path: str | None = None


def normalize_expected_page_numbers(page_numbers: tuple[int, ...] | list[int] | None) -> tuple[int, ...]:
    if not page_numbers:
        return ()
    normalized = tuple(int(page) for page in page_numbers)
    if any(page < 1 for page in normalized):
        raise PdfOcrError("expected_page_numbers contiene páginas inválidas (< 1).")
    if len(set(normalized)) != len(normalized):
        raise PdfOcrError("expected_page_numbers contiene páginas duplicadas.")
    if normalized != tuple(sorted(normalized)):
        raise PdfOcrError("expected_page_numbers debe venir en orden ascendente.")
    return normalized


def merge_page_indexes(
    existing: tuple[PdfOcrParsedPage, ...],
    updates: tuple[PdfOcrParsedPage, ...],
) -> tuple[PdfOcrParsedPage, ...]:
    merged = {page.page_number: page for page in existing}
    for page in updates:
        merged[page.page_number] = page
    return tuple(merged[page_number] for page_number in sorted(merged))


def _replace_table_placeholders(markdown: str, tables: tuple[dict[str, Any], ...]) -> str:
    rendered = markdown
    for table in tables:
        table_id = str(table.get("id", "")).strip()
        content = str(table.get("content", "")).strip()
        if not table_id or not content:
            continue
        placeholder = f"[{table_id}]({table_id})"
        rendered = rendered.replace(placeholder, f"[Tabla OCR {table_id}]\n{content}")
    return rendered


def _replace_image_placeholders(markdown: str, images: tuple[dict[str, Any], ...]) -> str:
    rendered = markdown
    for image in images:
        image_id = str(image.get("id", "")).strip()
        if not image_id:
            continue
        placeholder = f"![{image_id}]({image_id})"
        rendered = rendered.replace(
            placeholder,
            f"[Imagen OCR {image_id}; no se reinyecta como multimodal en esta llamada.]",
        )
    return rendered


def render_pdf_page_subset_to_text(
    *,
    cache_entry: PdfOcrCacheEntry,
    page_numbers: tuple[int, ...] | list[int],
) -> str:
    requested_pages = normalize_expected_page_numbers(page_numbers)
    page_lookup = {page.page_number: page for page in cache_entry.page_index}
    missing_pages = [page for page in requested_pages if page not in page_lookup]
    if missing_pages:
        raise PdfOcrError(
            "El subconjunto OCR solicitado contiene páginas ausentes en el cache: "
            f"{missing_pages}"
        )

    rendered_chunks: list[str] = []
    for page_number in requested_pages:
        page = page_lookup[page_number]
        page_text = _replace_table_placeholders(page.markdown, page.tables)
        page_text = _replace_image_placeholders(page_text, page.images)
        page_text = page_text.strip()
        if page_text:
            rendered_chunks.append(page_text)
        if page.footer:
            footer = page.footer.strip()
            if footer and not _PAGE_MARKER_ONLY_RE.fullmatch(footer):
                rendered_chunks.append(f"[Footer página {page_number}]\n{footer}")

    rendered = "\n\n".join(chunk for chunk in rendered_chunks if chunk.strip()).strip()
    if not rendered:
        raise PdfOcrError("El subconjunto OCR solicitado no produjo texto reutilizable.")
    return rendered


def serialize_page_index(page_index: tuple[PdfOcrParsedPage, ...]) -> list[dict[str, Any]]:
    return [
        {
            "page_number": page.page_number,
            "markdown": page.markdown,
            "images": list(page.images),
            "tables": list(page.tables),
            "hyperlinks": list(page.hyperlinks),
            "header": page.header,
            "footer": page.footer,
            "dimensions": page.dimensions,
            "confidence_scores": page.confidence_scores,
        }
        for page in page_index
    ]


def page_index_from_serialized(raw: Any) -> tuple[PdfOcrParsedPage, ...]:
    if not isinstance(raw, list):
        return ()
    pages: list[PdfOcrParsedPage] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        page_number = item.get("page_number")
        markdown = item.get("markdown")
        if not isinstance(page_number, int) or page_number < 1 or not isinstance(markdown, str):
            continue
        pages.append(
            PdfOcrParsedPage(
                page_number=page_number,
                markdown=markdown,
                images=tuple(item.get("images") or ()),
                tables=tuple(item.get("tables") or ()),
                hyperlinks=tuple(item.get("hyperlinks") or ()),
                header=item.get("header"),
                footer=item.get("footer"),
                dimensions=item.get("dimensions"),
                confidence_scores=item.get("confidence_scores"),
            )
        )
    return tuple(sorted(pages, key=lambda page: page.page_number))


def build_pdf_ocr_payload(
    *,
    source_sha256: str,
    engine: str,
    document_page_count: int | None,
    page_index: tuple[PdfOcrParsedPage, ...],
) -> dict[str, Any]:
    return {
        "version": _PDF_OCR_CACHE_VERSION,
        "source_sha256": source_sha256,
        "engine": engine,
        "document_page_count": document_page_count,
        "page_index": serialize_page_index(page_index),
    }


def load_pdf_ocr_cache_from_mapping(
    cached: dict[str, Any],
) -> tuple[tuple[PdfOcrParsedPage, ...], int | None]:
    page_index = page_index_from_serialized(cached.get("page_index"))
    document_page_count = cached.get("document_page_count")
    if not isinstance(document_page_count, int) or document_page_count < 1:
        document_page_count = None
    return page_index, document_page_count


def write_pdf_ocr_cache(
    *,
    cache_path: Path,
    source_sha256: str,
    engine: str,
    document_page_count: int | None,
    page_index: tuple[PdfOcrParsedPage, ...],
) -> None:
    serialized = build_pdf_ocr_payload(
        source_sha256=source_sha256,
        engine=engine,
        document_page_count=document_page_count,
        page_index=page_index,
    )
    fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp",
        prefix=f"{source_sha256}.{engine.replace('/', '_')}.",
        dir=str(cache_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(serialized, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, cache_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def write_unresolved_pdf_ocr_artifact(
    *,
    cache_path: Path,
    source_sha256: str,
    engine: str,
    model: str,
    expected_page_numbers: tuple[int, ...],
    build_result: PdfOcrBuildResult,
) -> str:
    artifact_path = cache_path.with_suffix(cache_path.suffix + ".missing-pages.json")
    payload = {
        "source_sha256": source_sha256,
        "engine": engine,
        "model": model,
        "expected_pages": list(expected_page_numbers),
        "detected_pages": list(build_result.detected_pages),
        "missing_pages": list(build_result.missing_pages),
        "raw_response": build_result.raw_response,
    }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with open(artifact_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return str(artifact_path)
```

Create `backend/supabase_pdf_ocr_cache.py`:

```python
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.supabase_data import _client

logger = logging.getLogger("backend.supabase_pdf_ocr_cache")

TABLE_NAME = "pdf_ocr_cache"
MAX_WRITE_ATTEMPTS = 12


def fetch_cache(source_sha256: str, engine: str) -> tuple[dict[str, Any] | None, int | None]:
    client = _client()
    result = (
        client.table(TABLE_NAME)
        .select("payload, row_version")
        .eq("source_sha256", source_sha256)
        .eq("engine", engine)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return None, None
    row = rows[0]
    payload = row.get("payload")
    row_version = row.get("row_version")
    if not isinstance(payload, dict) or not isinstance(row_version, int):
        return None, None
    return payload, row_version


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def try_write_cache(
    source_sha256: str,
    engine: str,
    payload: dict[str, Any],
    expected_row_version: int | None,
) -> tuple[bool, int | None]:
    client = _client()
    now_iso = _now_iso()

    if expected_row_version is None:
        client.table(TABLE_NAME).insert(
            {
                "source_sha256": source_sha256,
                "engine": engine,
                "payload": payload,
                "row_version": 1,
                "updated_at": now_iso,
            }
        ).execute()
        return True, 1

    result = (
        client.table(TABLE_NAME)
        .update(
            {
                "payload": payload,
                "row_version": expected_row_version + 1,
                "updated_at": now_iso,
            }
        )
        .eq("source_sha256", source_sha256)
        .eq("engine", engine)
        .eq("row_version", expected_row_version)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return False, None
    row_version = rows[0].get("row_version")
    return True, row_version if isinstance(row_version, int) else expected_row_version + 1


def supabase_cache_uri(source_sha256: str, engine: str) -> str:
    return f"supabase:{TABLE_NAME}/{source_sha256}/{engine}"
```

Create `supabase/migrations/20260413170000_pdf_ocr_cache.sql`:

```sql
create table if not exists public.pdf_ocr_cache (
  source_sha256 text not null,
  engine text not null,
  payload jsonb not null,
  row_version integer not null default 1,
  updated_at timestamptz not null default now(),
  primary key (source_sha256, engine),
  constraint pdf_ocr_cache_row_version_positive check (row_version >= 1)
);

create index if not exists idx_pdf_ocr_cache_updated_at
  on public.pdf_ocr_cache (updated_at desc);

alter table public.pdf_ocr_cache enable row level security;

comment on table public.pdf_ocr_cache is
  'Server-only cache for provider-neutral PDF OCR; keyed by PDF SHA-256 and OCR engine.';
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
python -m pytest tests/backend/test_pdf_ocr_cache.py tests/backend/test_supabase_pdf_ocr_cache.py -v
```

Expected: PASS. The table placeholder expansion, page-merge order and Supabase wrapper should now be green.

- [ ] **Step 5: Commit**

```bash
git add backend/pdf_ocr_cache.py backend/supabase_pdf_ocr_cache.py tests/backend/test_pdf_ocr_cache.py tests/backend/test_supabase_pdf_ocr_cache.py supabase/migrations/20260413170000_pdf_ocr_cache.sql
git commit -m "feat: add generic pdf ocr cache primitives"
```

---

## Task 2: Implement Native Mistral OCR With Missing-Page-Only Backfill

**Files:**
- Modify: `requirements.txt`
- Create: `backend/mistral_ocr_client.py`
- Create: `tests/backend/test_mistral_ocr_client.py`

Aquí vive el corazón de la sustitución: pedir OCR nativo a Mistral solo para las páginas con contenido que falten, normalizar la respuesta y fundirla en la misma caché incremental.

- [ ] **Step 1: Write the failing tests**

Create `tests/backend/test_mistral_ocr_client.py`:

```python
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.mistral_ocr_client import (
    MISTRAL_OCR_ENGINE,
    _build_mistral_ocr_result,
    _to_mistral_page_indexes,
    get_or_prime_mistral_pdf_ocr_cache,
)
from backend.pdf_ocr_cache import PdfOcrParsedPage, build_pdf_ocr_payload, write_pdf_ocr_cache


def test_to_mistral_page_indexes_converts_1_based_pages_to_0_based_request():
    assert _to_mistral_page_indexes((1, 3, 7)) == [0, 2, 6]


def test_build_mistral_ocr_result_maps_response_indexes_back_to_original_pages():
    response = {
        "pages": [
            {"index": 0, "markdown": "Página 1", "tables": [], "images": []},
            {"index": 3, "markdown": "Página 4", "tables": [], "images": []},
        ]
    }

    result = _build_mistral_ocr_result(
        response_payload=response,
        expected_page_numbers=(1, 4, 5),
    )

    assert tuple(page.page_number for page in result.page_index) == (1, 4)
    assert result.detected_pages == (1, 4)
    assert result.missing_pages == (5,)


def test_get_or_prime_mistral_pdf_ocr_cache_requests_only_missing_pages(tmp_path, monkeypatch):
    source_path = tmp_path / "document-numbered.pdf"
    source_path.write_bytes(b"%PDF-1.4\n%fake\n")

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    from backend.mistral_ocr_client import _sha256_file, _pdf_cache_path

    source_sha256 = _sha256_file(str(source_path))
    cache_path = _pdf_cache_path(source_sha256, MISTRAL_OCR_ENGINE, cache_dir)
    write_pdf_ocr_cache(
        cache_path=cache_path,
        source_sha256=source_sha256,
        engine=MISTRAL_OCR_ENGINE,
        document_page_count=8,
        page_index=(
            PdfOcrParsedPage(page_number=1, markdown="Página 1"),
            PdfOcrParsedPage(page_number=4, markdown="Página 4"),
        ),
    )

    captured: dict = {}

    def _fake_fetch_missing_pages_once(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            page_index=(PdfOcrParsedPage(page_number=5, markdown="Página 5"),),
            detected_pages=(5,),
            missing_pages=(),
            raw_response={"pages": [{"index": 4, "markdown": "Página 5"}]},
        )

    monkeypatch.setattr(
        "backend.mistral_ocr_client._fetch_missing_pages_once",
        _fake_fetch_missing_pages_once,
    )
    monkeypatch.setattr(
        "backend.mistral_ocr_client.PdfReader",
        lambda path: SimpleNamespace(pages=[object()] * 8),
    )

    entry = get_or_prime_mistral_pdf_ocr_cache(
        source_path=str(source_path),
        api_key="mistral-test-key",
        model="mistral-ocr-latest",
        engine=MISTRAL_OCR_ENGINE,
        filename="document.pdf",
        cache_dir=str(cache_dir),
        expected_page_numbers=(1, 4, 5),
    )

    assert captured["expected_page_numbers"] == (5,)
    assert entry.cached_page_numbers == (1, 4, 5)


def test_fetch_missing_pages_once_deletes_remote_file_even_on_ocr_failure(tmp_path, monkeypatch):
    source_path = tmp_path / "document-numbered.pdf"
    source_path.write_bytes(b"%PDF-1.4\n%fake\n")

    calls: list[tuple[str, str]] = []

    class _FakeFiles:
        def upload(self, file, purpose):
            calls.append(("upload", purpose))
            return SimpleNamespace(id="file-123")

        def get_signed_url(self, file_id):
            calls.append(("signed_url", file_id))
            return SimpleNamespace(url="https://signed.example/document.pdf")

        def delete(self, file_id):
            calls.append(("delete", file_id))

    class _FakeOcr:
        def process(self, **kwargs):
            raise RuntimeError("boom")

    class _FakeClient:
        def __init__(self, api_key):
            self.files = _FakeFiles()
            self.ocr = _FakeOcr()

    monkeypatch.setattr("backend.mistral_ocr_client.Mistral", _FakeClient)

    from backend.mistral_ocr_client import _fetch_missing_pages_once, PdfOcrError

    with pytest.raises(PdfOcrError, match="boom"):
        _fetch_missing_pages_once(
            source_path=str(source_path),
            api_key="mistral-test-key",
            model="mistral-ocr-latest",
            expected_page_numbers=(2, 4),
            filename="document.pdf",
        )

    assert ("delete", "file-123") in calls
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest tests/backend/test_mistral_ocr_client.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `backend.mistral_ocr_client`.

- [ ] **Step 3: Write the minimal implementation**

Update `requirements.txt`:

```txt
# Mistral Document AI
mistralai==2.3.2
```

Create `backend/mistral_ocr_client.py`:

```python
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from mistralai.client import Mistral
from pypdf import PdfReader

from backend.pdf_ocr_cache import (
    PdfOcrBuildResult,
    PdfOcrCacheEntry,
    PdfOcrError,
    PdfOcrParsedPage,
    build_pdf_ocr_payload,
    load_pdf_ocr_cache_from_mapping,
    merge_page_indexes,
    normalize_expected_page_numbers,
    write_pdf_ocr_cache,
    write_unresolved_pdf_ocr_artifact,
)
import backend.supabase_pdf_ocr_cache as supabase_pdf_ocr_cache

logger = logging.getLogger("backend.mistral_ocr_client")

MISTRAL_OCR_MODEL = "mistral-ocr-latest"
MISTRAL_OCR_ENGINE = "mistral-native"


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_pdf_cache_dir() -> Path:
    configured = (
        os.environ.get("PDF_OCR_CACHE_DIR", "").strip()
        or os.environ.get("OPENROUTER_PDF_CACHE_DIR", "").strip()
    )
    if configured:
        return Path(configured)
    return Path.cwd() / "data" / "pdf_ocr_cache"


def _ocr_cache_backend_for_call(cache_dir: str | None) -> str:
    if cache_dir is not None:
        return "disk"
    raw = (
        os.environ.get("PDF_OCR_CACHE_BACKEND", "").strip().lower()
        or os.environ.get("OPENROUTER_OCR_CACHE_BACKEND", "").strip().lower()
        or "auto"
    )
    if raw == "auto":
        has_supabase = bool(os.environ.get("SUPABASE_URL", "").strip()) and bool(
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        )
        return "supabase" if has_supabase else "disk"
    if raw not in {"disk", "supabase"}:
        raise PdfOcrError(f"Backend de caché OCR no soportado: {raw}")
    return raw


def _pdf_cache_path(source_sha256: str, engine: str, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{source_sha256}.{engine.replace('/', '_')}.json"
    return cache_dir / filename


def _to_mistral_page_indexes(expected_page_numbers: tuple[int, ...]) -> list[int]:
    return [page_number - 1 for page_number in normalize_expected_page_numbers(expected_page_numbers)]


def _response_to_mapping(response: Any) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        payload = response.model_dump(mode="python")
    elif isinstance(response, dict):
        payload = response
    else:
        raise PdfOcrError("La respuesta OCR de Mistral no es serializable.")
    if not isinstance(payload, dict):
        raise PdfOcrError("La respuesta OCR de Mistral debe ser un objeto.")
    return payload


def _build_mistral_ocr_result(
    *,
    response_payload: dict[str, Any],
    expected_page_numbers: tuple[int, ...],
) -> PdfOcrBuildResult:
    expected = normalize_expected_page_numbers(expected_page_numbers)
    raw_pages = response_payload.get("pages")
    if not isinstance(raw_pages, list):
        raise PdfOcrError("La respuesta OCR de Mistral no incluye `pages`.")

    normalized_pages: list[PdfOcrParsedPage] = []
    for raw_page in raw_pages:
        if not isinstance(raw_page, dict):
            continue
        raw_index = raw_page.get("index")
        markdown = raw_page.get("markdown")
        if not isinstance(raw_index, int) or not isinstance(markdown, str):
            continue
        normalized_pages.append(
            PdfOcrParsedPage(
                page_number=raw_index + 1,
                markdown=markdown,
                images=tuple(raw_page.get("images") or ()),
                tables=tuple(raw_page.get("tables") or ()),
                hyperlinks=tuple(raw_page.get("hyperlinks") or ()),
                header=raw_page.get("header"),
                footer=raw_page.get("footer"),
                dimensions=raw_page.get("dimensions"),
                confidence_scores=raw_page.get("confidence_scores"),
            )
        )

    normalized_tuple = tuple(sorted(normalized_pages, key=lambda page: page.page_number))
    detected_pages = tuple(page.page_number for page in normalized_tuple)
    missing_pages = tuple(page for page in expected if page not in detected_pages)
    return PdfOcrBuildResult(
        page_index=normalized_tuple,
        detected_pages=detected_pages,
        missing_pages=missing_pages,
        raw_response=response_payload,
    )


def _fetch_missing_pages_once(
    *,
    source_path: str,
    api_key: str,
    model: str,
    expected_page_numbers: tuple[int, ...],
    filename: str,
) -> PdfOcrBuildResult:
    client = Mistral(api_key=api_key)
    with open(source_path, "rb") as handle:
        uploaded = client.files.upload(
            file={"file_name": filename, "content": handle},
            purpose="ocr",
        )
    try:
        signed_url = client.files.get_signed_url(file_id=uploaded.id)
        response = client.ocr.process(
            model=model,
            document={"type": "document_url", "document_url": signed_url.url},
            pages=_to_mistral_page_indexes(expected_page_numbers),
            table_format="html",
            extract_footer=True,
            include_image_base64=False,
        )
    except Exception as exc:
        raise PdfOcrError(f"Error al solicitar OCR nativo a Mistral: {exc}") from exc
    finally:
        try:
            client.files.delete(file_id=uploaded.id)
        except Exception as delete_exc:
            logger.warning("No se pudo borrar el archivo OCR remoto de Mistral: %s", delete_exc)

    return _build_mistral_ocr_result(
        response_payload=_response_to_mapping(response),
        expected_page_numbers=expected_page_numbers,
    )


def get_or_prime_mistral_pdf_ocr_cache(
    *,
    source_path: str,
    api_key: str,
    model: str,
    engine: str,
    filename: str | None = None,
    cache_dir: str | None = None,
    expected_page_numbers: tuple[int, ...] | list[int] | None = None,
) -> PdfOcrCacheEntry:
    if not os.path.isfile(source_path):
        raise PdfOcrError(f"PDF no encontrado para OCR: {source_path}")

    source_sha256 = _sha256_file(source_path)
    expected = normalize_expected_page_numbers(expected_page_numbers)
    resolved_cache_dir = Path(cache_dir) if cache_dir else _default_pdf_cache_dir()
    cache_path = _pdf_cache_path(source_sha256, engine, resolved_cache_dir)
    document_page_count = len(PdfReader(source_path).pages)

    page_index: tuple[PdfOcrParsedPage, ...] = ()
    row_version: int | None = None
    storage_ref = str(cache_path)
    backend = _ocr_cache_backend_for_call(cache_dir)
    use_supabase = backend == "supabase"

    if use_supabase:
        payload, row_version = supabase_pdf_ocr_cache.fetch_cache(source_sha256, engine)
        if payload is not None:
            page_index, cached_page_count = load_pdf_ocr_cache_from_mapping(payload)
            if cached_page_count is not None:
                document_page_count = cached_page_count
            storage_ref = supabase_pdf_ocr_cache.supabase_cache_uri(source_sha256, engine)
    elif cache_path.is_file():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        page_index, cached_page_count = load_pdf_ocr_cache_from_mapping(cached)
        if cached_page_count is not None:
            document_page_count = cached_page_count

    effective_expected = expected or tuple(range(1, document_page_count + 1))
    cached_page_numbers = tuple(page.page_number for page in page_index)
    missing_pages = tuple(page for page in effective_expected if page not in cached_page_numbers)

    diagnostic_artifact_path: str | None = None
    if missing_pages:
        build_result = _fetch_missing_pages_once(
            source_path=source_path,
            api_key=api_key,
            model=model,
            expected_page_numbers=missing_pages,
            filename=filename or os.path.basename(source_path) or "document.pdf",
        )
        page_index = merge_page_indexes(page_index, build_result.page_index)
        if build_result.missing_pages:
            diagnostic_artifact_path = write_unresolved_pdf_ocr_artifact(
                cache_path=cache_path,
                source_sha256=source_sha256,
                engine=engine,
                model=model,
                expected_page_numbers=missing_pages,
                build_result=build_result,
            )

        payload = build_pdf_ocr_payload(
            source_sha256=source_sha256,
            engine=engine,
            document_page_count=document_page_count,
            page_index=page_index,
        )
        if use_supabase:
            wrote = False
            for _ in range(supabase_pdf_ocr_cache.MAX_WRITE_ATTEMPTS):
                ok, new_row_version = supabase_pdf_ocr_cache.try_write_cache(
                    source_sha256,
                    engine,
                    payload,
                    row_version,
                )
                if ok:
                    row_version = new_row_version
                    wrote = True
                    break
                latest_payload, latest_row_version = supabase_pdf_ocr_cache.fetch_cache(source_sha256, engine)
                if latest_payload is None:
                    row_version = None
                    continue
                latest_page_index, latest_page_count = load_pdf_ocr_cache_from_mapping(latest_payload)
                if latest_page_count is not None:
                    document_page_count = latest_page_count
                page_index = merge_page_indexes(latest_page_index, build_result.page_index)
                payload = build_pdf_ocr_payload(
                    source_sha256=source_sha256,
                    engine=engine,
                    document_page_count=document_page_count,
                    page_index=page_index,
                )
                row_version = latest_row_version
            if not wrote:
                raise PdfOcrError("Conflicto persistente al guardar la caché OCR de Mistral.")
        else:
            write_pdf_ocr_cache(
                cache_path=cache_path,
                source_sha256=source_sha256,
                engine=engine,
                document_page_count=document_page_count,
                page_index=page_index,
            )

    merged_cached_pages = tuple(page.page_number for page in page_index)
    return PdfOcrCacheEntry(
        source_sha256=source_sha256,
        engine=engine,
        cache_path=storage_ref,
        cache_hit=not bool(missing_pages),
        expected_page_numbers=effective_expected,
        cached_page_numbers=merged_cached_pages,
        page_index=page_index,
        diagnostic_artifact_path=diagnostic_artifact_path,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
python -m pytest tests/backend/test_mistral_ocr_client.py -v
```

Expected: PASS. The request pages should be 0-based, the returned pages should be normalized back to 1-based, and only missing pages should be requested.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt backend/mistral_ocr_client.py tests/backend/test_mistral_ocr_client.py
git commit -m "feat: add native mistral pdf ocr client"
```

---

## Task 3: Rewire Canonical OpenRouter PDF Runs To The Mistral OCR Cache

**Files:**
- Modify: `backend/agents/explainer_openrouter.py`
- Modify: `main.py`
- Modify: `tests/backend/test_explainer_openrouter.py`
- Modify: `tests/backend/test_main_helpers.py`
- Modify: `tests/backend/test_pdf_process_flow.py`
- Modify: `tests/test_pid_00230265_subpart_scope_audit.py`

Ahora hay que conectar la nueva caché OCR con el runtime real: preparar OCR canónico solo sobre `content_page_set`, pasar page scopes intactos al explainer y no volver a depender del OCR vía OpenRouter.

- [ ] **Step 1: Write the failing tests**

Append to `tests/backend/test_main_helpers.py`:

```python
def test_prepare_mistral_pdf_ocr_context_requests_only_content_pages(monkeypatch):
    import main as m

    captured: dict = {}
    fake_cache_entry = SimpleNamespace(
        cache_hit=False,
        cache_path="cache.json",
        expected_page_numbers=(1, 3),
        cached_page_numbers=(1, 3),
        page_index=(),
    )

    def _fake_get_or_prime(**kwargs):
        captured.update(kwargs)
        return fake_cache_entry

    monkeypatch.setattr(m, "get_or_prime_mistral_pdf_ocr_cache", _fake_get_or_prime)

    context = m._prepare_mistral_pdf_ocr_context(
        numbered_pdf_path="document-numbered.pdf",
        content_page_set=frozenset({3, 1}),
        api_key="mistral-test-key",
        engine="mistral-native",
    )

    assert captured["expected_page_numbers"] == (1, 3)
    assert context.source_pdf_path == "document-numbered.pdf"
    assert context.cache_entry is fake_cache_entry
```

Append to `tests/backend/test_explainer_openrouter.py`:

```python
from backend.pdf_ocr_cache import PdfOcrCacheEntry, PdfOcrParsedPage


def test_run_subpart_explainer_or_uses_cached_mistral_page_subset(monkeypatch):
    source_path = _write_text_source()
    captured: dict = {}

    def _fake_chat(**kwargs):
        captured.update(kwargs)
        return (
            {
                "desarrollo": [
                    {
                        "titulo_seccion": "Bloque",
                        "explicacion_introductoria": "Contexto",
                        "subsecciones": [
                            {
                                "titulo_subseccion": "Detalle",
                                "explicacion_detallada": "Explicación",
                            }
                        ],
                    }
                ]
            },
            _usage(),
        )

    monkeypatch.setattr(module, "call_openrouter_chat", _fake_chat)

    cache_entry = PdfOcrCacheEntry(
        source_sha256="sha",
        engine="mistral-native",
        cache_path="cache.json",
        cache_hit=True,
        expected_page_numbers=(2,),
        cached_page_numbers=(2,),
        page_index=(PdfOcrParsedPage(page_number=2, markdown="Texto OCR página 2"),),
    )

    module.run_subpart_explainer_or(
        source_path=source_path,
        identificacion="Prompt de prueba",
        mime_type="application/pdf",
        api_key="sk-or-v1-test",
        pdf_cache_entry=cache_entry,
        page_numbers=(2,),
    )

    inline_text = captured["messages"][0]["content"][0]["text"]
    assert "Texto OCR página 2" in inline_text
    assert "Prompt de prueba" in inline_text
```

Append to `tests/backend/test_pdf_process_flow.py`:

```python
def test_process_project_pdf_openrouter_prepares_only_content_pages_for_mistral_context(monkeypatch):
    pdf_path = _create_multi_page_pdf(5)
    try:
        project = {
            "id": "proj-openrouter-mistral-backfill",
            "name": "Doc PDF",
            "description": "Procesar todo",
            "pdf_filename": "test.pdf",
            "source_type": "pdf",
            "source_url": None,
            "status": "pending",
        }

        prepare_calls = []

        monkeypatch.setattr(main, "get_project", lambda pid, uid, include_internal=False: project)
        monkeypatch.setattr(
            main,
            "get_user_api_key",
            lambda uid, provider=None: (
                "AIzaFakeKey"
                if provider == main.PROVIDER_GEMINI
                else "sk-or-v1-test"
                if provider == main.PROVIDER_OPENROUTER
                else "mistral-test-key"
            ),
        )
        monkeypatch.setattr(main, "mask_api_key", lambda api_key: "****")
        monkeypatch.setattr(main, "update_project", lambda pid, uid, payload: None)
        monkeypatch.setattr(main, "download_pdf_to_temp", lambda pid, uid: pdf_path)
        async def _send_event(*args, **kwargs):
            return None

        class _DummySSE:
            async def end_stream(self, *args, **kwargs):
                return None

        monkeypatch.setattr(main, "send_event", _send_event)
        monkeypatch.setattr(main, "sse_manager", _DummySSE())
        monkeypatch.setattr(main, "upload_file_with_retry", lambda *args, **kwargs: SimpleNamespace(uri="uploaded://segment", mime_type="application/pdf"))
        monkeypatch.setattr(main, "run_page_classifier", lambda *args, **kwargs: (frozenset([1, 2, 4, 5]), _usage(), {}))
        monkeypatch.setattr(
            main,
            "_prepare_mistral_pdf_ocr_context",
            lambda **kwargs: prepare_calls.append(kwargs) or main.PreparedPdfOcrContext(
                source_pdf_path=pdf_path,
                cache_entry=SimpleNamespace(
                    cache_hit=False,
                    cache_path="cache.json",
                    expected_page_numbers=(1, 2, 4, 5),
                    cached_page_numbers=(1, 2, 4, 5),
                    page_index=(),
                ),
            ),
        )
        monkeypatch.setattr(main, "run_segmentador", lambda *args, **kwargs: ({
            "analisis_texto": "Cinco páginas",
            "temas_identificados": ["tema1"],
            "decision_num_partes": 1,
            "decision_justificacion": "Una parte",
            "partes": [{
                "numero": 1,
                "titulo": "Única",
                "contenido": "Contenido único",
                "identificacion": "Páginas 1-5",
                "pagina_inicio": 1,
                "pagina_fin": 5,
                "temas_cubiertos": ["tema1"],
                "extension_estimada": "media",
                "complejidad": "media",
                "expansion_prevista": "alta",
                "subpartes": [],
            }],
            "consideraciones_estudiante": "Orden natural",
        }, _usage(total=20)))
        monkeypatch.setattr(main, "run_explainer_or", lambda *args, **kwargs: ({"introduccion": "", "desarrollo": [], "conclusion": "", "conexiones_contextuales": []}, _usage()))
        monkeypatch.setattr(main, "run_recorrido", lambda *args, **kwargs: ({"ok": True}, _usage()))
        monkeypatch.setattr(main, "run_resources", lambda *args, **kwargs: ({"ok": True}, _usage()))
        async def _fake_format(*args, **kwargs):
            return (
                {"introduccion": "", "desarrollo": [], "conclusion": "", "conexiones_contextuales": []},
                {"total_tokens": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0},
            )

        monkeypatch.setattr(main, "format_explainer_content", _fake_format)

        asyncio.run(main._process_project("proj-openrouter-mistral-backfill", "user-123", explainer_provider="openrouter"))

        assert prepare_calls[0]["content_page_set"] == frozenset({1, 2, 4, 5})
    finally:
        if os.path.isfile(pdf_path):
            os.unlink(pdf_path)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest tests/backend/test_main_helpers.py tests/backend/test_explainer_openrouter.py tests/backend/test_pdf_process_flow.py -v -k "mistral_pdf_ocr_context or cached_mistral_page_subset or prepares_only_content_pages_for_mistral_context"
```

Expected: FAIL because `main.py` and `explainer_openrouter.py` todavía dependen del contrato OpenRouter OCR actual.

- [ ] **Step 3: Write the minimal implementation**

Update `backend/agents/explainer_openrouter.py`:

```python
from backend.mistral_ocr_client import MISTRAL_OCR_ENGINE, MISTRAL_OCR_MODEL
from backend.pdf_ocr_cache import PdfOcrCacheEntry, PdfOcrError, render_pdf_page_subset_to_text


def _call_openrouter_json_with_pdf_fallback(
    *,
    source_path: str,
    identificacion: str,
    mime_type: str,
    model: str,
    system_prompt: str,
    response_format,
    api_key: str,
    pdf_cache_entry: PdfOcrCacheEntry | None = None,
    page_numbers: tuple[int, ...] | None = None,
):
    try:
        if mime_type == "application/pdf" and pdf_cache_entry is not None:
            requested_pages = page_numbers or pdf_cache_entry.cached_page_numbers
            ocr_text = render_pdf_page_subset_to_text(
                cache_entry=pdf_cache_entry,
                page_numbers=requested_pages,
            )
            inline_messages = _build_inline_text_messages(ocr_text, identificacion)
            return call_openrouter_chat(
                messages=inline_messages,
                model=model,
                system_prompt=system_prompt,
                api_key=api_key,
                response_format=response_format,
                plugins=None,
                enable_response_healing=True,
                reasoning={"effort": "xhigh", "exclude": True},
                temperature=OPENROUTER_EXPLAINER_TEMPERATURE,
            )
    except PdfOcrError:
        logger.warning("La caché OCR de Mistral no pudo renderizar el subconjunto solicitado.")

    if mime_type == "application/pdf":
        fallback_text_path = _extract_pdf_text_to_temp(source_path)
        try:
            fallback_content, fallback_plugins = _build_content(
                fallback_text_path,
                identificacion,
                "text/plain",
            )
            return call_openrouter_chat(
                messages=[{"role": "user", "content": fallback_content}],
                model=model,
                system_prompt=system_prompt,
                api_key=api_key,
                response_format=response_format,
                plugins=fallback_plugins,
                enable_response_healing=True,
                reasoning={"effort": "xhigh", "exclude": True},
                temperature=OPENROUTER_EXPLAINER_TEMPERATURE,
            )
        finally:
            try:
                os.unlink(fallback_text_path)
            except OSError:
                logger.warning("No se pudo borrar el fallback textual temporal: %s", fallback_text_path)
```

Update `main.py`:

```python
from backend.mistral_ocr_client import (
    MISTRAL_OCR_ENGINE,
    MISTRAL_OCR_MODEL,
    get_or_prime_mistral_pdf_ocr_cache,
)
from backend.pdf_ocr_cache import PdfOcrCacheEntry
from backend.supabase_data import PROVIDER_MISTRAL


@dataclass(frozen=True, slots=True)
class PreparedPdfOcrContext:
    source_pdf_path: str
    cache_entry: PdfOcrCacheEntry
    ocr_model: str = MISTRAL_OCR_MODEL


def _prepare_mistral_pdf_ocr_context(
    *,
    numbered_pdf_path: str,
    content_page_set: frozenset[int],
    api_key: str,
    engine: str,
) -> "PreparedPdfOcrContext":
    cache_entry = get_or_prime_mistral_pdf_ocr_cache(
        source_path=numbered_pdf_path,
        api_key=api_key,
        model=MISTRAL_OCR_MODEL,
        engine=engine,
        filename="document.pdf",
        expected_page_numbers=tuple(sorted(content_page_set)),
    )
    return PreparedPdfOcrContext(
        source_pdf_path=numbered_pdf_path,
        cache_entry=cache_entry,
        ocr_model=MISTRAL_OCR_MODEL,
    )
```

Then wire `_process_project()` so the canonical async task uses `_prepare_mistral_pdf_ocr_context(...)`, stores `PreparedPdfOcrContext`, and logs:

```python
logger.info(
    "[Process] Preparando OCR canónico de Mistral sobre páginas con contenido",
    extra={
        "content_pages_count": len(content_page_set),
        "mistral_ocr_engine": MISTRAL_OCR_ENGINE,
    },
)
```

And on canonical OpenRouter calls, keep:

```python
canonical_page_scope = tuple(openrouter_page_scopes[idx]) if use_or_canonical else ()
```

unchanged, but pass the new `PreparedPdfOcrContext.cache_entry`.

Update `tests/test_pid_00230265_subpart_scope_audit.py` so the live helper imports and uses `_prepare_mistral_pdf_ocr_context(...)` and prints `cache_entry.cached_page_numbers` + `cache_entry.diagnostic_artifact_path` when available.

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
python -m pytest tests/backend/test_main_helpers.py tests/backend/test_explainer_openrouter.py tests/backend/test_pdf_process_flow.py -v -k "mistral_pdf_ocr_context or cached_mistral_page_subset or prepares_only_content_pages_for_mistral_context"
```

Expected: PASS. `main.py` should now prepare OCR only for content pages and the OpenRouter explainer should consume the cached subset instead of OCRing PDFs itself.

- [ ] **Step 5: Commit**

```bash
git add backend/agents/explainer_openrouter.py main.py tests/backend/test_explainer_openrouter.py tests/backend/test_main_helpers.py tests/backend/test_pdf_process_flow.py tests/test_pid_00230265_subpart_scope_audit.py
git commit -m "refactor: route openrouter pdf runs through mistral ocr cache"
```

---

## Task 4: Add Full Mistral BYOK Support In Backend And API Gating

**Files:**
- Modify: `backend/supabase_data.py`
- Modify: `main.py`
- Modify: `tests/backend/test_api.py`

Mistral debe existir como provider real de producto, no como variable escondida. Este task deja el backend completo: estado, endpoints, validación, errores y gating de ejecución.

- [ ] **Step 1: Write the failing tests**

Append to `tests/backend/test_api.py`:

```python
class TestMistralApiKeys:
    def test_status_exposes_mistral_fields(self, auth_client):
        with patch(
            "main.get_user_api_key_status",
            return_value={
                "has_api_key": True,
                "provider": "google_gemini",
                "updated_at": "2026-04-13T10:00:00Z",
                "has_openrouter_key": True,
                "openrouter_updated_at": "2026-04-13T10:00:00Z",
                "has_mistral_key": True,
                "mistral_updated_at": "2026-04-13T10:00:00Z",
            },
        ):
            response = auth_client.get(
                "/api/settings/api-key/status",
                headers={"Authorization": "Bearer fake-token"},
            )

        assert response.status_code == 200
        assert response.json()["has_mistral_key"] is True
        assert response.json()["mistral_updated_at"] == "2026-04-13T10:00:00Z"

    def test_requires_mistral_key_when_openrouter_is_selected_for_pdf(self, auth_client):
        with patch(
            "main.get_project",
            return_value={"id": "proj-1", "name": "Proyecto", "status": "pending", "source_type": "pdf"},
        ):
            with patch(
                "main.has_user_api_key",
                side_effect=lambda uid, provider="google_gemini": provider != "mistral",
            ):
                response = auth_client.post(
                    "/api/projects/proj-1/process",
                    headers={"Authorization": "Bearer fake-token"},
                    json={"explainer_provider": "openrouter"},
                )

        assert response.status_code == 400
        assert "Mistral" in response.json()["detail"]

    def test_does_not_require_mistral_key_for_openrouter_web_projects(self, auth_client):
        with patch(
            "main.get_project",
            return_value={"id": "proj-web", "name": "Proyecto", "status": "pending", "source_type": "web"},
        ):
            with patch(
                "main.has_user_api_key",
                side_effect=lambda uid, provider="google_gemini": provider != "mistral",
            ):
                async def _fake_process(*args, **kwargs):
                    return None

                with patch("main._process_project", new=_fake_process):
                    response = auth_client.post(
                        "/api/projects/proj-web/process",
                        headers={"Authorization": "Bearer fake-token"},
                        json={"explainer_provider": "openrouter"},
                    )

        assert response.status_code == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest tests/backend/test_api.py -v -k "mistral_fields or requires_mistral_key or does_not_require_mistral_key"
```

Expected: FAIL because the API status payload and the process gating still know only Gemini/OpenRouter.

- [ ] **Step 3: Write the minimal implementation**

Update `backend/supabase_data.py`:

```python
PROVIDER_GEMINI = "google_gemini"
PROVIDER_OPENROUTER = "openrouter"
PROVIDER_MISTRAL = "mistral"


def get_user_api_key_status(user_id: str) -> dict[str, Any]:
    client = _client()
    gemini_data: dict = {}
    openrouter_data: dict = {}
    mistral_data: dict = {}

    try:
        rows = (
            client.table("user_api_keys")
            .select("provider, updated_at")
            .eq("user_id", user_id)
            .execute()
        )
        if rows and rows.data:
            for row in rows.data:
                if row.get("provider") == PROVIDER_GEMINI:
                    gemini_data = row
                elif row.get("provider") == PROVIDER_OPENROUTER:
                    openrouter_data = row
                elif row.get("provider") == PROVIDER_MISTRAL:
                    mistral_data = row
    except Exception:
        pass

    return {
        "has_api_key": bool(gemini_data),
        "provider": gemini_data.get("provider") or None,
        "updated_at": gemini_data.get("updated_at") or None,
        "has_openrouter_key": bool(openrouter_data),
        "openrouter_updated_at": openrouter_data.get("updated_at") or None,
        "has_mistral_key": bool(mistral_data),
        "mistral_updated_at": mistral_data.get("updated_at") or None,
    }
```

Update `main.py`:

```python
def _validate_mistral_api_key(api_key: str) -> str:
    key = (api_key or "").strip()
    if len(key) < 20 or any(ch.isspace() for ch in key):
        raise HTTPException(status_code=400, detail="API key de Mistral inválida")
    return key


@app.post("/api/settings/api-key/mistral")
@api_key_rate_limit
async def api_set_mistral_key(
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
    api_key: str = Form(...),
):
    api_key = _validate_mistral_api_key(api_key)
    set_user_api_key(user_id, api_key, provider=PROVIDER_MISTRAL)
    logger.info("[API Key] User %s... configured Mistral key: %s", user_id[:8], mask_api_key(api_key))
    return {"ok": True}


@app.delete("/api/settings/api-key/mistral")
@api_key_rate_limit
async def api_delete_mistral_key(
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
):
    delete_user_api_key(user_id, provider=PROVIDER_MISTRAL)
    logger.info("[API Key] User %s... deleted Mistral key", user_id[:8])
    return {"ok": True}
```

And tighten `/api/projects/{project_id}/process`:

```python
if explainer_provider == EXPLAINER_PROVIDER_OPENROUTER:
    if project.get("source_type") == "youtube":
        raise HTTPException(
            status_code=400,
            detail="OpenRouter todavía no está disponible para proyectos de YouTube. Usa Gemini para esta fuente.",
        )
    if not has_user_api_key(user_id, provider=PROVIDER_OPENROUTER):
        raise HTTPException(
            status_code=400,
            detail="No hay API key de OpenRouter configurada. Guárdala en Ajustes para usar Qwen en el explainer.",
        )
    if project.get("source_type") == "pdf" and not has_user_api_key(user_id, provider=PROVIDER_MISTRAL):
        raise HTTPException(
            status_code=400,
            detail="No hay API key de Mistral configurada. Guárdala en Ajustes para usar OCR nativo en PDFs con OpenRouter.",
        )
```

Inside `_process_project()` retrieve the runtime key only when needed:

```python
mistral_api_key = ""
if use_openrouter_explainer and source_type == "pdf":
    mistral_api_key = get_user_api_key(user_id, provider=PROVIDER_MISTRAL) or ""
    if not mistral_api_key:
        await send_event(project_id, {"type": "error", "message": "No hay API key de Mistral configurada. Guárdala en Ajustes para usar OCR nativo en PDFs con OpenRouter."})
        update_project(project_id, user_id, {"status": "error", "error_message": "API key de Mistral no configurada"})
        return
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
python -m pytest tests/backend/test_api.py -v -k "mistral_fields or requires_mistral_key or does_not_require_mistral_key"
```

Expected: PASS. The API should expose Mistral status and require the Mistral key only for `PDF + OpenRouter`.

- [ ] **Step 5: Commit**

```bash
git add backend/supabase_data.py main.py tests/backend/test_api.py
git commit -m "feat: add mistral byok backend support"
```

---

## Task 5: Expose Mistral BYOK In Settings And Enforce It In Launch Validation

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/js/state.js`
- Modify: `frontend/js/storage.js`
- Modify: `frontend/js/auth.js`
- Modify: `frontend/js/landing.js`
- Modify: `tests/frontend/auth.test.js`
- Modify: `tests/frontend/landing.test.js`

El usuario debe poder gestionar la key de Mistral y entender claramente cuándo se necesita. Este task deja cerrada la UX completa.

- [ ] **Step 1: Write the failing tests**

Append to `tests/frontend/auth.test.js`:

```javascript
import { vi } from 'vitest';

it('refreshApiKeyStatus hydrates mistral key state from the API payload', async () => {
  state.hasMistralKey = false;
  state.mistralKeyStatus = 'loading';
  vi.spyOn(storageModule, 'getCachedMistralKeyStatus').mockReturnValue(null);
  vi.spyOn(storageModule, 'setCachedMistralKeyStatus').mockImplementation(() => {});
  vi.spyOn(apiModule, 'api').mockResolvedValue({
    has_api_key: true,
    has_openrouter_key: true,
    has_mistral_key: true,
  });

  await refreshApiKeyStatus();

  expect(state.hasMistralKey).toBe(true);
  expect(state.mistralKeyStatus).toBe('has');
});
```

Append to `tests/frontend/landing.test.js`:

```javascript
it('requires Mistral when OpenRouter is selected for PDFs', () => {
  expect(validateExplainerProviderSelection({
    sourceType: 'pdf',
    provider: 'openrouter',
    hasGeminiKey: true,
    hasOpenRouterKey: true,
    hasMistralKey: false,
  })).toMatch(/Mistral/i);
});

it('does not require Mistral when OpenRouter is selected for web URLs', () => {
  expect(validateExplainerProviderSelection({
    sourceType: 'web',
    provider: 'openrouter',
    hasGeminiKey: true,
    hasOpenRouterKey: true,
    hasMistralKey: false,
  })).toBeNull();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
npx vitest run tests/frontend/auth.test.js tests/frontend/landing.test.js
```

Expected: FAIL because the frontend state and validation still ignore Mistral.

- [ ] **Step 3: Write the minimal implementation**

Update `frontend/js/state.js`:

```javascript
export const state = {
  currentProjectId: null,
  currentProject: null,
  currentPartId: null,
  activeTab: 'explicacion',
  isSharedView: false,
  shareToken: null,
  processingSSE: null,
  sseProjectId: null,
  sseReconnectAttempts: 0,
  sseLastEventAt: 0,
  ssePausedByVisibility: false,
  pollProjectsInterval: null,
  pollCurrentProjectInterval: null,
  hasApiKey: false,
  apiKeyStatus: 'loading',
  hasOpenRouterKey: false,
  openRouterKeyStatus: 'loading',
  hasMistralKey: false,
  mistralKeyStatus: 'loading',
  session: null,
  user: null,
  previousUserId: null,
  lastPartChangeAt: 0,
};

export const MISTRAL_KEY_CACHE_KEY_PREFIX = 'explainer.mistralKeyStatus.v1.';
```

Update `frontend/js/storage.js`:

```javascript
// Add MISTRAL_KEY_CACHE_KEY_PREFIX to the existing import from './state.js'

export function getCachedMistralKeyStatus(userId) {
  if (!userId) return null;
  try {
    const raw = localStorage.getItem(MISTRAL_KEY_CACHE_KEY_PREFIX + userId);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const age = Date.now() - (parsed.updatedAt ? new Date(parsed.updatedAt).getTime() : 0);
    if (age > API_KEY_CACHE_TTL_MS) return null;
    return parsed.hasKey === true;
  } catch (_) {
    return null;
  }
}

export function setCachedMistralKeyStatus(userId, hasKey) {
  if (!userId) return;
  try {
    localStorage.setItem(MISTRAL_KEY_CACHE_KEY_PREFIX + userId, JSON.stringify({
      hasKey: Boolean(hasKey),
      updatedAt: new Date().toISOString(),
    }));
  } catch (_) {}
}
```

Update `frontend/js/auth.js`:

```javascript
// Add getCachedMistralKeyStatus / setCachedMistralKeyStatus to the existing storage imports

const cachedMistral = getCachedMistralKeyStatus(userId);
if (cachedMistral !== null) {
  state.hasMistralKey = cachedMistral;
  state.mistralKeyStatus = cachedMistral ? 'has' : 'none';
} else {
  state.mistralKeyStatus = 'loading';
}

state.hasMistralKey = Boolean(status.has_mistral_key);
state.mistralKeyStatus = state.hasMistralKey ? 'has' : 'none';
setCachedMistralKeyStatus(userId, state.hasMistralKey);
```

Add the new form handlers:

```javascript
$('form-mistral-key').addEventListener('submit', async (e) => {
  e.preventDefault();
  const apiKey = $('mistral-key-input').value.trim();
  if (!apiKey) {
    $('mistral-key-error').textContent = 'Ingresa una API key de Mistral';
    return;
  }

  const formData = new FormData();
  formData.append('api_key', apiKey);
  await api('/api/settings/api-key/mistral', {
    method: 'POST',
    body: formData,
  });

  state.hasMistralKey = true;
  state.mistralKeyStatus = 'has';
  setCachedMistralKeyStatus(state.user?.id, true);
  $('mistral-key-input').value = '';
  $('mistral-key-success').textContent = 'API key de Mistral guardada';
  updateApiKeyUI();
});

$('btn-delete-mistral-key').addEventListener('click', async () => {
  if (!confirm('¿Eliminar tu API key de Mistral guardada?')) return;
  await api('/api/settings/api-key/mistral', { method: 'DELETE' });
  state.hasMistralKey = false;
  state.mistralKeyStatus = 'none';
  setCachedMistralKeyStatus(state.user?.id, false);
  updateApiKeyUI();
});
```

Also extend `hideSettings()` so the modal never reopens with stale Mistral messages:

```javascript
$('mistral-key-error').textContent = '';
$('mistral-key-success').textContent = '';
$('mistral-key-input').value = '';
```

Extend `updateApiKeyUI()`:

```javascript
const mistralLoading = state.mistralKeyStatus === 'loading';

if (state.hasMistralKey) {
  hide($('mistral-key-not-set'));
  show($('mistral-key-set'));
  $('btn-delete-mistral-key').style.display = 'inline-block';
} else if (mistralLoading) {
  hide($('mistral-key-not-set'));
  hide($('mistral-key-set'));
  $('btn-delete-mistral-key').style.display = 'none';
} else {
  show($('mistral-key-not-set'));
  hide($('mistral-key-set'));
  $('btn-delete-mistral-key').style.display = 'none';
}
```

Update `frontend/js/landing.js`:

```javascript
export function validateExplainerProviderSelection({
  sourceType,
  provider,
  hasGeminiKey,
  hasOpenRouterKey,
  hasMistralKey,
}) {
  if (!hasGeminiKey) {
    return 'Necesitas configurar tu API key de Gemini primero. Ve a Ajustes.';
  }
  if (!isExplainerProviderSupportedForSource(sourceType, provider)) {
    return 'OpenRouter todavía no está disponible para vídeos de YouTube. Usa Gemini para esta fuente.';
  }
  if (provider === 'openrouter' && !hasOpenRouterKey) {
    return 'Necesitas configurar tu API key de OpenRouter para usar Qwen en el explainer.';
  }
  if (provider === 'openrouter' && sourceType === 'pdf' && !hasMistralKey) {
    return 'Necesitas configurar tu API key de Mistral para usar OCR nativo en PDFs con Qwen/OpenRouter.';
  }
  return null;
}
```

And update the hint builder:

```javascript
if (provider === 'openrouter' && sourceType === 'pdf') {
  if (state.hasOpenRouterKey && state.hasMistralKey) {
    return 'La explicación usará Qwen vía OpenRouter y el OCR de PDFs usará Mistral nativo. Segmentación, recorrido, recursos y formateo siguen usando Gemini.';
  }
  if (!state.hasMistralKey) {
    return 'Para PDFs con Qwen necesitas guardar también tu API key de Mistral para el OCR nativo.';
  }
}
```

Update `frontend/index.html` by inserting a full Mistral section right after OpenRouter:

```html
<div class="settings-section">
  <h4 class="settings-section-title">API Key de Mistral <span class="settings-badge-optional">Necesaria para PDF + OpenRouter</span></h4>
  <p class="settings-description">
    Si quieres usar <strong>Qwen vía OpenRouter</strong> sobre PDFs, el OCR nativo del documento lo hará <strong>Mistral</strong>.
    Obtén tu API key en <a href="https://console.mistral.ai/" target="_blank" rel="noopener">console.mistral.ai</a>.
  </p>

  <div id="mistral-key-not-set" class="api-key-status hidden">
    <div class="status-badge status-neutral">No configurada</div>
    <p class="status-text">Los PDFs con OpenRouter seguirán bloqueados hasta guardar esta key.</p>
  </div>

  <div id="mistral-key-set" class="api-key-status hidden">
    <div class="status-badge status-success">✓ Configurada</div>
    <p class="status-text">El OCR nativo de Mistral queda disponible para proyectos PDF con OpenRouter.</p>
  </div>

  <form id="form-mistral-key" class="settings-form">
    <div class="form-group">
      <label for="mistral-key-input" class="form-label">API Key</label>
      <input type="password" id="mistral-key-input" class="form-input" placeholder="Tu clave de Mistral" autocomplete="off" />
    </div>
    <div class="form-actions">
      <button type="submit" class="btn-primary" id="btn-save-mistral-key">
        <span class="btn-text">Guardar API Key</span>
        <span class="spinner hidden"></span>
      </button>
      <button type="button" class="btn-danger" id="btn-delete-mistral-key">Eliminar</button>
    </div>
    <p class="form-error" id="mistral-key-error"></p>
    <p class="form-success" id="mistral-key-success"></p>
  </form>
</div>
```

Also update the OpenRouter settings copy from “OCR de PDFs seguirá usando Grok” to “OCR de PDFs usará Mistral nativo”.

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
npx vitest run tests/frontend/auth.test.js tests/frontend/landing.test.js
```

Expected: PASS. The frontend should now persist Mistral key state and require it only for `PDF + OpenRouter`.

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html frontend/js/state.js frontend/js/storage.js frontend/js/auth.js frontend/js/landing.js tests/frontend/auth.test.js tests/frontend/landing.test.js
git commit -m "feat: expose mistral key setup in frontend"
```

---

## Final Verification Sweep

Después del último task, ejecuta esta batería completa antes de declarar la migración lista:

```bash
python -m pytest tests/backend/test_pdf_ocr_cache.py tests/backend/test_supabase_pdf_ocr_cache.py tests/backend/test_mistral_ocr_client.py tests/backend/test_main_helpers.py tests/backend/test_explainer_openrouter.py tests/backend/test_pdf_process_flow.py tests/backend/test_api.py -v
npx vitest run tests/frontend/auth.test.js tests/frontend/landing.test.js
python tests/test_pid_00230265_subpart_scope_audit.py
```

Expected:

- El backend pasa en verde y prueba:
  - expansión de tablas/imágenes en el subconjunto OCR,
  - normalización 0-based/1-based,
  - backfill de páginas faltantes a la misma caché,
  - page scoping correcto hacia el explainer,
  - gating correcto de la key de Mistral.
- El frontend pasa en verde y refleja correctamente la nueva dependencia `PDF + OpenRouter => Mistral`.
- El audit script live usa la ruta canónica de Mistral y, si encuentra huecos de OCR, deja la ruta del artefacto `.missing-pages.json` para inspección.

## Self-Review Notes

- La cobertura del spec está repartida así:
  - OCR nativo de Mistral: Task 2.
  - Caché incremental “igual que ahora, pero con Mistral”: Tasks 1-3.
  - Solo páginas con contenido y luego solo páginas de la subparte: Task 3.
  - BYOK completo de Mistral: Tasks 4-5.
- No quedan placeholders, nombres sin definir ni referencias a APIs inventadas.
- Los nombres usados más tarde (`PdfOcrCacheEntry`, `PreparedPdfOcrContext`, `PROVIDER_MISTRAL`, `MISTRAL_OCR_ENGINE`) quedan definidos en tasks previos.
