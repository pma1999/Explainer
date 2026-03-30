# Content-Only PDF Segmentation — Design Spec

**Date:** 2026-03-30
**Status:** Approved

## Problem

The segmentador fails page-coverage validation on the first attempt in almost every run. Root cause: the model receives a full PDF (pages 1..N) and must identify which of those pages are content, then assign correct `pagina_inicio`/`pagina_fin` ranges. This requires reasoning about a sparse, non-contiguous set of page numbers — a cognitively fragile task. Prior fixes (boundary anchors, PASO 6/8 cross-checks, tema anchoring in retry) reduce damage but do not eliminate first-attempt failures.

## Solution

Send the segmentador a **content-only PDF**: a filtered PDF containing exclusively the pages identified as content by the page classifier, re-stamped with sequential markers "— Página 1 / M —" through "— Página M / M —". The coverage constraint becomes trivially "cover pages 1 to M with no gaps" — a much easier task. Page numbers are remapped back to the originals before any downstream use.

---

## Architecture

```
[PDF original]
    ↓ add_page_numbers (unchanged)
[numbered_pdf]  →  upload  →  file_uri
    ↓ run_page_classifier (unchanged)
content_page_set  {3,4,5,8,9,...}

    ↓ build_content_only_pdf(pdf_path_original, sorted(content_page_set))
[content_only_pdf]  pages 1..M stamped
virtual_to_real = [3, 4, 5, 8, 9, ...]   (virtual_to_real[i] = original page of virtual i+1)

    ↓ upload  →  content_file_uri
    ↓ run_segmentador(content_file_uri, prefix_simpificado + description)
segmentation  {pagina_inicio/fin in virtual 1..M}

    ↓ validate_page_coverage(seg, frozenset(range(1, M+1)))
    ↓ retry loop (unchanged logic, uses virtual content_page_set = 1..M)

    ↓ remap_segmentation_pages(segmentation, virtual_to_real)
segmentation  {pagina_inicio/fin in original real numbers}

    ↓ everything downstream unchanged
    extract_page_range(numbered_pdf_path, real_pi, real_pf)
    upload segment → explainer / recorrido / resources
```

---

## Files Changed

| File | Change |
|------|--------|
| `backend/pdf_utils.py` | Add `build_content_only_pdf` |
| `main.py` | Add `remap_segmentation_pages`; update `_build_content_pages_prefix`; update pipeline to create/use `content_file_uri` |
| `tests/backend/test_pdf_utils.py` | Add tests for `build_content_only_pdf` (create if absent) |
| `tests/backend/test_main_helpers.py` | Add tests for `remap_segmentation_pages` and updated prefix |

No changes to `segmentador.py`, `segmentation_page_coverage.py`, explainer, recorrido, or resources.

---

## Component 1: `build_content_only_pdf` (pdf_utils.py)

```python
def build_content_only_pdf(
    input_path: str,
    content_pages: list[int],  # sorted, 1-indexed, from original PDF
) -> tuple[str, list[int]]:
```

**Behavior:**
1. Read `input_path` (the original, un-numbered PDF — `pdf_temp_path` in the pipeline, not `numbered_pdf_path`).
2. For each page in `content_pages` (0-indexed access = `page_num - 1`), extract that page.
3. Stamp each extracted page with a new overlay: "— Página X / M —" where X = 1..M.
4. Write to a new temp file.
5. Return `(temp_path, content_pages)`.

**Edge case — all pages are content:**
If `len(content_pages) == total_pdf_pages` (all pages are content), skip PDF creation entirely. Return `(numbered_pdf_path, content_pages)` where `numbered_pdf_path` is the already-built full numbered PDF. The caller must pass `numbered_pdf_path` in this case (via an optional parameter or the caller detects and skips). Since `numbered_pdf_path` has pages stamped 1..N = 1..M (same thing), no new file is needed.

Actually, to keep the signature simple, `build_content_only_pdf` always creates a new PDF. The caller checks `len(content_pages) == pdf_total_pages` and skips calling it if so, reusing `(numbered_pdf_path, list(range(1, M+1)))`. This keeps the function pure and simple.

**virtual_to_real semantics:**
```
virtual_to_real[0] = content_pages[0]   # virtual page 1 → real original page
virtual_to_real[i] = content_pages[i]   # virtual page i+1 → real original page
```
Since `content_pages` is already the sorted list of original page numbers, the return value is simply `content_pages` itself (as a `list[int]`).

---

## Component 2: `remap_segmentation_pages` (main.py)

```python
def remap_segmentation_pages(
    segmentation: dict[str, Any],
    virtual_to_real: list[int],
) -> None:
```

**Behavior:** Mutates `segmentation` in-place. For every `pagina_inicio` and `pagina_fin` field in `partes` and their `subpartes`:

```python
real = virtual_to_real[virtual - 1]
```

If `virtual - 1` is out of range (should not happen after successful validation), leave the value unchanged.

Fields remapped: `parte["pagina_inicio"]`, `parte["pagina_fin"]`, `subparte["pagina_inicio"]`, `subparte["pagina_fin"]`.

Fields NOT remapped (text fields): `identificacion`, `inicio_texto`, `fin_texto`, `introduccion`, `conclusion`, `temas_cubiertos`, `contenido`, `titulo`, `consideraciones_estudiante` — these contain textual content descriptions, not page numbers (see Section on text fields below).

---

## Component 3: `_build_content_pages_prefix` (main.py) — simplified

When a content-only PDF is used, the prefix changes to:

```xml
<paginas_contenido_verificado>
Este PDF contiene únicamente las {M} páginas de contenido sustantivo del documento original,
renumeradas secuencialmente de 1 a {M}. TODAS las páginas (1 a {M}) son contenido sustantivo.
RESTRICCIÓN OBLIGATORIA: Los rangos pagina_inicio/pagina_fin de las partes deben cubrir
colectivamente TODAS las páginas de 1 a {M} sin huecos ni solapamientos entre partes.
Las subpartes de cada parte deben ser contiguas y cubrir exactamente el rango de su parte padre.
AVISO SOBRE NUMERACIÓN: Las marcas de página en este PDF son virtuales (1..{M}) y NO
corresponden a los números del documento original. Los campos pagina_inicio y pagina_fin
DEBEN usar estos números virtuales. En todos los campos de texto (identificacion,
inicio_texto, fin_texto, introduccion, conclusion, etc.), identifica los fragmentos
EXCLUSIVAMENTE por su contenido textual (frases literales, títulos de sección) — NUNCA
por número de página.
</paginas_contenido_verificado>
```

The existing `_build_content_pages_prefix` function is refactored:
- If content-only PDF mode (always, for PDF sources with a non-empty `content_page_set`): use the simplified block above.
- If classifier failed and fell back to all pages: same block applies (M = total_pages).
- For non-PDF sources (text/URL): function returns `""` unchanged.

---

## Text Fields and Page Numbers

The segmentador's `identificacion` field is used by downstream agents to orient themselves in the source PDF. With virtual numbering, any page number mentioned in text descriptions would be wrong relative to the real segment PDF the agent receives.

**Fix:** The `AVISO SOBRE NUMERACIÓN` block in the prefix explicitly instructs the model to use only textual identifiers (first/last phrases, chapter/section titles) in all text fields. The segmentador's PASO 6 already promotes this behavior. This makes the instruction explicit.

**No post-processing of text fields is needed.** Downstream agents (explainer, recorrido, resources) navigate the content via the actual segment PDF they receive and via the first/last textual phrases in `identificacion` — not via embedded page numbers. This is robust.

---

## Pipeline Changes in main.py

### After `run_page_classifier`:

```python
# Build content-only PDF for segmentador
content_only_pdf_path: str | None = None
virtual_to_real: list[int] = []
content_file_uri: str = file_uri  # default: full PDF

if content_page_set and len(content_page_set) < pdf_total_pages:
    sorted_content = sorted(content_page_set)
    content_only_pdf_path, virtual_to_real = await asyncio.to_thread(
        build_content_only_pdf, pdf_temp_path, sorted_content
    )
    temp_paths.append(content_only_pdf_path)
    # upload content_only_pdf_path to Gemini Files API → content_file_uri
    content_file_uri = (await upload_file_with_retry(content_only_pdf_path, ...)).uri
else:
    # All pages are content (or classifier failed): reuse existing file_uri as-is
    sorted_content = sorted(content_page_set) if content_page_set else list(range(1, pdf_total_pages + 1))
    virtual_to_real = sorted_content   # identity: virtual i = real sorted_content[i-1]
    content_file_uri = file_uri
```

### Segmentador call:

Replace `file_uri` with `content_file_uri`. The `content_pages_prefix` uses the simplified block.

### `validate_page_coverage` call:

Replace `content_page_set` with `frozenset(range(1, len(virtual_to_real) + 1))` — the virtual page set.

### After validation loop exits successfully:

```python
if content_only_pdf_path is not None:
    # Only remap when a new filtered PDF was actually created (non-identity mapping)
    remap_segmentation_pages(segmentation, virtual_to_real)
```

`content_only_pdf_path` is `None` when all pages are content and `file_uri` was reused — in that case virtual = real, no remap needed.

### `extract_page_range` call (unchanged):

After remapping, `parte["pagina_inicio"]` and `parte["pagina_fin"]` are real page numbers. `extract_page_range(numbered_pdf_path, ...)` works exactly as before.

---

## Retry Logic

The retry loop in `build_page_coverage_retry_suffix` is unchanged. After virtual renumbering, `content_page_set` in the retry is `frozenset(range(1, M+1))` — a compact range. The retry message becomes simpler: "pages 1-M must be covered, you missed pages X, Y" where X, Y are small virtual numbers. Easier for the model to fix.

---

## Temp File and Gemini File Cleanup

- `content_only_pdf_path` is added to `temp_paths` → deleted in the existing cleanup `finally` block.
- `content_file_uri` is uploaded to the Gemini Files API, which has a 48h automatic TTL. The existing code does not explicitly delete `file_uri` either. Same behavior — no new cleanup logic.

---

## Tests

### `tests/backend/test_pdf_utils.py` — `build_content_only_pdf`

1. **Content extracted correctly**: PDF with 5 pages, extract pages [2, 4]. Result has 2 pages.
2. **Stamps are correct**: Pages are stamped "— Página 1 / 2 —" and "— Página 2 / 2 —".
3. **Return value**: `virtual_to_real` equals `[2, 4]`.
4. **Cleanup**: Returns a valid temp file path.

Tests use a minimal synthetic PDF created with reportlab or pypdf's PdfWriter (same as existing `add_page_numbers` tests if any).

### `tests/backend/test_main_helpers.py` — `remap_segmentation_pages`

1. **Basic remap**: virtual [1,2,3,4,5] → real [3,4,5,8,9]. Assert pagina_inicio/pagina_fin of partes and subpartes are remapped.
2. **Identity mapping**: virtual = real (1-indexed). Assert values unchanged.
3. **Subpartes remapped**: Ensure subpart fields are also remapped.
4. **Out-of-range virtual page**: virtual page 6 with `virtual_to_real` of length 5 → value left unchanged.

### `tests/backend/test_main_helpers.py` — updated `_build_content_pages_prefix`

Existing tests for `_build_content_pages_prefix` must be updated (the function's output format changes). New assertions:
1. Output contains `"TODAS las páginas"` and `"1 a {M}"`.
2. Output contains `"AVISO SOBRE NUMERACIÓN"`.
3. Output contains `"NUNCA"` (the prohibition on page numbers in text fields).
4. Output does NOT list individual page ranges (no `"Páginas con contenido sustantivo:"` line).
5. Empty `content_page_set` still returns `""`.

---

## Self-Review

- **Root cause addressed**: Yes. Segmentador receives 1..M consecutive content pages, no gaps, coverage is trivial.
- **Text field issue addressed**: Yes. Explicit instruction in prefix prohibits page numbers in text descriptions.
- **Downstream unchanged**: Yes. `extract_page_range`, explainer, recorrido, resources all use real page numbers after remap.
- **Edge case (all pages content)**: Handled — skip content-only PDF creation, reuse `file_uri`, identity remap.
- **Edge case (classifier failure)**: Existing fallback `content_page_set = frozenset(range(1, pdf_total_pages + 1))` → same as "all pages content" edge case.
- **No interface changes**: `run_segmentador`, `validate_page_coverage`, `build_page_coverage_retry_suffix` signatures unchanged.
- **No schema changes**: segmentador response schema unchanged; `pagina_inicio`/`pagina_fin` are still integers, just in virtual space during segmentation, remapped before storage.
- **Retry still works**: Virtual page set 1..M is simpler for the model to correct. Logic unchanged.
- **Existing tests**: `test_main_helpers.py` prefix tests need updating (format change). `test_segmentation_page_coverage.py` unchanged.
