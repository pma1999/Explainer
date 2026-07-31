"""Comprehensive tests for PDF page-aware segmentation feature.

Tests cover:
1. pdf_utils.add_page_numbers - Page number overlay on multi-page PDFs
2. pdf_utils.extract_page_range - Page range extraction with buffer
3. Segmentador schema - Validates pagina_inicio/pagina_fin in schema
4. Main.py TOC generation - Table of contents builder logic
5. Edge cases - Single page PDFs, boundary conditions, error handling
"""

import json
import os
import sys
import tempfile

# Add project root to path (parent of tests/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from pypdf import PdfReader

from backend.pdf_utils import add_page_numbers, extract_page_range, extract_pages


# ============================================================
# TEST HELPERS
# ============================================================

def create_test_pdf(num_pages: int, content_per_page: dict[int, str] | None = None) -> str:
    """Create a multi-page test PDF with content on each page.

    Args:
        num_pages: Number of pages to generate.
        content_per_page: Optional dict {page_num (1-indexed): "content text"}.

    Returns:
        Path to the temporary test PDF.
    """
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)

    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4

    for i in range(1, num_pages + 1):
        # Header
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(width / 2, height - 50, f"Test Page {i}")

        # Content
        c.setFont("Helvetica", 12)
        if content_per_page and i in content_per_page:
            text = content_per_page[i]
        else:
            text = f"This is the content of page {i}. It contains test material for verification."
        c.drawCentredString(width / 2, height / 2, text)

        c.showPage()

    c.save()
    return path


def print_test(test_name: str, passed: bool, detail: str = ""):
    """Print test result in a readable format."""
    status = "✅ PASS" if passed else "❌ FAIL"
    detail_str = f" — {detail}" if detail else ""
    print(f"  {status}: {test_name}{detail_str}")
    return passed


# ============================================================
# TEST 1: add_page_numbers - Basic functionality
# ============================================================

def test_add_page_numbers_basic():
    """Test that add_page_numbers creates a numbered PDF with correct page count."""
    print("\n═══ TEST 1: add_page_numbers - Basic functionality ═══")
    all_passed = True

    # Create a 5-page test PDF
    test_pdf = create_test_pdf(5)
    numbered_pdf = None

    try:
        numbered_pdf = add_page_numbers(test_pdf)

        # Check that output file exists
        all_passed &= print_test(
            "Output file exists",
            os.path.isfile(numbered_pdf),
            f"Path: {numbered_pdf}"
        )

        # Check that output file is not empty
        size = os.path.getsize(numbered_pdf)
        all_passed &= print_test(
            "Output file is not empty",
            size > 0,
            f"Size: {size} bytes"
        )

        # Check that page count is preserved
        reader = PdfReader(numbered_pdf)
        all_passed &= print_test(
            "Page count preserved (5 pages)",
            len(reader.pages) == 5,
            f"Got: {len(reader.pages)} pages"
        )

        # Check that output is different from input (page numbers added)
        input_size = os.path.getsize(test_pdf)
        all_passed &= print_test(
            "Output file is larger than input (overlay added)",
            size > input_size,
            f"Input: {input_size}B, Output: {size}B"
        )

    finally:
        if os.path.isfile(test_pdf):
            os.unlink(test_pdf)
        if numbered_pdf and os.path.isfile(numbered_pdf):
            os.unlink(numbered_pdf)

    return all_passed


# ============================================================
# TEST 2: add_page_numbers - Single page PDF
# ============================================================

def test_add_page_numbers_single_page():
    """Test add_page_numbers with a single-page PDF."""
    print("\n═══ TEST 2: add_page_numbers - Single page PDF ═══")
    all_passed = True

    test_pdf = create_test_pdf(1)
    numbered_pdf = None

    try:
        numbered_pdf = add_page_numbers(test_pdf)

        reader = PdfReader(numbered_pdf)
        all_passed &= print_test(
            "Single page preserved",
            len(reader.pages) == 1,
            f"Got: {len(reader.pages)} pages"
        )

        all_passed &= print_test(
            "Output file exists and non-empty",
            os.path.isfile(numbered_pdf) and os.path.getsize(numbered_pdf) > 0
        )

    finally:
        if os.path.isfile(test_pdf):
            os.unlink(test_pdf)
        if numbered_pdf and os.path.isfile(numbered_pdf):
            os.unlink(numbered_pdf)

    return all_passed


# ============================================================
# TEST 3: add_page_numbers - Large PDF (20 pages)
# ============================================================

def test_add_page_numbers_large_pdf():
    """Test add_page_numbers with a larger PDF."""
    print("\n═══ TEST 3: add_page_numbers - Large PDF (20 pages) ═══")
    all_passed = True

    test_pdf = create_test_pdf(20)
    numbered_pdf = None

    try:
        numbered_pdf = add_page_numbers(test_pdf)

        reader = PdfReader(numbered_pdf)
        all_passed &= print_test(
            "All 20 pages preserved",
            len(reader.pages) == 20,
            f"Got: {len(reader.pages)} pages"
        )

    finally:
        if os.path.isfile(test_pdf):
            os.unlink(test_pdf)
        if numbered_pdf and os.path.isfile(numbered_pdf):
            os.unlink(numbered_pdf)

    return all_passed


# ============================================================
# TEST 4: add_page_numbers - Error handling
# ============================================================

def test_add_page_numbers_errors():
    """Test that add_page_numbers raises errors appropriately."""
    print("\n═══ TEST 4: add_page_numbers - Error handling ═══")
    all_passed = True

    # Non-existent file
    try:
        add_page_numbers("/nonexistent/path/to/file.pdf")
        all_passed &= print_test("FileNotFoundError for missing file", False, "No exception raised")
    except FileNotFoundError:
        all_passed &= print_test("FileNotFoundError for missing file", True)
    except Exception as e:
        all_passed &= print_test("FileNotFoundError for missing file", False, f"Got: {type(e).__name__}: {e}")

    return all_passed


# ============================================================
# TEST 4b: add_page_numbers - Text content preserved on every page
# Regression test: pypdf merge_page emptied content streams on pages that
# use compressed or form-XObject resources (e.g. UOC-format section titles).
# ============================================================

def test_add_page_numbers_preserves_text_content():
    """Every page must retain its original text after add_page_numbers."""
    unique_texts = {
        1: "Introduction chapter text that must survive numbering.",
        2: "Section two paragraph unique content here.",
        3: "Chapter three body with distinctive words.",
    }
    test_pdf = create_test_pdf(3, content_per_page=unique_texts)
    numbered_pdf = None
    try:
        numbered_pdf = add_page_numbers(test_pdf)
        reader = PdfReader(numbered_pdf)
        for page_num, expected_fragment in unique_texts.items():
            extracted = (reader.pages[page_num - 1].extract_text() or "").replace("\n", " ")
            assert expected_fragment in extracted, (
                f"Page {page_num}: original text lost after add_page_numbers.\n"
                f"Expected: {expected_fragment!r}\nGot: {extracted[:200]!r}"
            )
    finally:
        if os.path.isfile(test_pdf):
            os.unlink(test_pdf)
        if numbered_pdf and os.path.isfile(numbered_pdf):
            os.unlink(numbered_pdf)


# ============================================================
# TEST 5: extract_page_range - Basic extraction
# ============================================================

def test_extract_page_range_basic():
    """Test basic page range extraction."""
    print("\n═══ TEST 5: extract_page_range - Basic extraction ═══")
    all_passed = True

    test_pdf = create_test_pdf(10)
    extracted = None

    try:
        # Extract pages 3-7 with buffer=1 → should get pages 2-8 (7 pages)
        extracted = extract_page_range(test_pdf, start_page=3, end_page=7, buffer=1)

        reader = PdfReader(extracted)
        expected_pages = 7  # pages 2,3,4,5,6,7,8
        all_passed &= print_test(
            f"Extract pages 3-7 (buffer=1) → {expected_pages} pages",
            len(reader.pages) == expected_pages,
            f"Got: {len(reader.pages)} pages"
        )

        all_passed &= print_test(
            "Extracted file exists and non-empty",
            os.path.isfile(extracted) and os.path.getsize(extracted) > 0
        )

    finally:
        if os.path.isfile(test_pdf):
            os.unlink(test_pdf)
        if extracted and os.path.isfile(extracted):
            os.unlink(extracted)

    return all_passed


# ============================================================
# TEST 6: extract_page_range - Edge: first pages
# ============================================================

def test_extract_page_range_first_pages():
    """Test extraction starting from page 1 (buffer should not go below 1)."""
    print("\n═══ TEST 6: extract_page_range - Edge: first pages ═══")
    all_passed = True

    test_pdf = create_test_pdf(10)
    extracted = None

    try:
        # Extract pages 1-3 with buffer=1 → clamp to 1-4 (4 pages)
        extracted = extract_page_range(test_pdf, start_page=1, end_page=3, buffer=1)

        reader = PdfReader(extracted)
        expected_pages = 4  # pages 1,2,3,4 (buffer clamped at start)
        all_passed &= print_test(
            f"Extract pages 1-3 (buffer=1, clamped start) → {expected_pages} pages",
            len(reader.pages) == expected_pages,
            f"Got: {len(reader.pages)} pages"
        )

    finally:
        if os.path.isfile(test_pdf):
            os.unlink(test_pdf)
        if extracted and os.path.isfile(extracted):
            os.unlink(extracted)

    return all_passed


# ============================================================
# TEST 7: extract_page_range - Edge: last pages
# ============================================================

def test_extract_page_range_last_pages():
    """Test extraction ending at last page (buffer should not exceed total)."""
    print("\n═══ TEST 7: extract_page_range - Edge: last pages ═══")
    all_passed = True

    test_pdf = create_test_pdf(10)
    extracted = None

    try:
        # Extract pages 8-10 with buffer=1 → clamp to 7-10 (4 pages)
        extracted = extract_page_range(test_pdf, start_page=8, end_page=10, buffer=1)

        reader = PdfReader(extracted)
        expected_pages = 4  # pages 7,8,9,10 (buffer clamped at end)
        all_passed &= print_test(
            f"Extract pages 8-10 (buffer=1, clamped end) → {expected_pages} pages",
            len(reader.pages) == expected_pages,
            f"Got: {len(reader.pages)} pages"
        )

    finally:
        if os.path.isfile(test_pdf):
            os.unlink(test_pdf)
        if extracted and os.path.isfile(extracted):
            os.unlink(extracted)

    return all_passed


# ============================================================
# TEST 8: extract_page_range - Single page
# ============================================================

def test_extract_page_range_single_page():
    """Test extracting a single page with buffer."""
    print("\n═══ TEST 8: extract_page_range - Single page ═══")
    all_passed = True

    test_pdf = create_test_pdf(10)
    extracted = None

    try:
        # Extract page 5-5 with buffer=1 → pages 4,5,6 (3 pages)
        extracted = extract_page_range(test_pdf, start_page=5, end_page=5, buffer=1)

        reader = PdfReader(extracted)
        expected_pages = 3  # pages 4,5,6
        all_passed &= print_test(
            f"Extract page 5 only (buffer=1) → {expected_pages} pages",
            len(reader.pages) == expected_pages,
            f"Got: {len(reader.pages)} pages"
        )

    finally:
        if os.path.isfile(test_pdf):
            os.unlink(test_pdf)
        if extracted and os.path.isfile(extracted):
            os.unlink(extracted)

    return all_passed


# ============================================================
# TEST 9: extract_page_range - No buffer
# ============================================================

def test_extract_page_range_no_buffer():
    """Test extraction with buffer=0."""
    print("\n═══ TEST 9: extract_page_range - No buffer ═══")
    all_passed = True

    test_pdf = create_test_pdf(10)
    extracted = None

    try:
        # Extract pages 3-5 with buffer=0 → exactly 3 pages
        extracted = extract_page_range(test_pdf, start_page=3, end_page=5, buffer=0)

        reader = PdfReader(extracted)
        expected_pages = 3
        all_passed &= print_test(
            f"Extract pages 3-5 (buffer=0) → {expected_pages} pages",
            len(reader.pages) == expected_pages,
            f"Got: {len(reader.pages)} pages"
        )

    finally:
        if os.path.isfile(test_pdf):
            os.unlink(test_pdf)
        if extracted and os.path.isfile(extracted):
            os.unlink(extracted)

    return all_passed


# ============================================================
# TEST 10: extract_page_range - Full document
# ============================================================

def test_extract_page_range_full_document():
    """Test extracting entire document."""
    print("\n═══ TEST 10: extract_page_range - Full document ═══")
    all_passed = True

    test_pdf = create_test_pdf(5)
    extracted = None

    try:
        # Extract pages 1-5 with buffer=1 → all 5 pages (clamped)
        extracted = extract_page_range(test_pdf, start_page=1, end_page=5, buffer=1)

        reader = PdfReader(extracted)
        all_passed &= print_test(
            "Extract all pages 1-5 (buffer=1) → 5 pages",
            len(reader.pages) == 5,
            f"Got: {len(reader.pages)} pages"
        )

    finally:
        if os.path.isfile(test_pdf):
            os.unlink(test_pdf)
        if extracted and os.path.isfile(extracted):
            os.unlink(extracted)

    return all_passed


# ============================================================
# TEST 11: extract_page_range - Error handling
# ============================================================

def test_extract_page_range_errors():
    """Test error handling for invalid inputs."""
    print("\n═══ TEST 11: extract_page_range - Error handling ═══")
    all_passed = True

    test_pdf = create_test_pdf(5)

    try:
        # Non-existent file
        try:
            extract_page_range("/nonexistent/file.pdf", 1, 3)
            all_passed &= print_test("FileNotFoundError for missing file", False)
        except FileNotFoundError:
            all_passed &= print_test("FileNotFoundError for missing file", True)

        # Invalid range (start > end)
        try:
            extract_page_range(test_pdf, 5, 3)
            all_passed &= print_test("ValueError for start > end", False)
        except ValueError:
            all_passed &= print_test("ValueError for start > end", True)

        # Invalid range (page 0)
        try:
            extract_page_range(test_pdf, 0, 3)
            all_passed &= print_test("ValueError for page 0", False)
        except ValueError:
            all_passed &= print_test("ValueError for page 0", True)

    finally:
        if os.path.isfile(test_pdf):
            os.unlink(test_pdf)

    return all_passed


def test_extract_pages_preserves_requested_order():
    """extract_pages should preserve the explicit page order exactly."""
    test_pdf = create_test_pdf(
        5,
        {
            1: "Contenido página 1",
            2: "Contenido página 2",
            3: "Contenido página 3",
            4: "Contenido página 4",
            5: "Contenido página 5",
        },
    )
    extracted = None

    try:
        extracted = extract_pages(test_pdf, [3, 5, 2])
        reader = PdfReader(extracted)

        assert len(reader.pages) == 3
        assert "Test Page 3" in (reader.pages[0].extract_text() or "")
        assert "Test Page 5" in (reader.pages[1].extract_text() or "")
        assert "Test Page 2" in (reader.pages[2].extract_text() or "")
    finally:
        if os.path.isfile(test_pdf):
            os.unlink(test_pdf)
        if extracted and os.path.isfile(extracted):
            os.unlink(extracted)


def test_extract_pages_rejects_duplicates():
    """extract_pages rejects duplicate pages to keep canonical cache inputs stable."""
    test_pdf = create_test_pdf(3)
    try:
        try:
            extract_pages(test_pdf, [1, 2, 2])
        except ValueError as exc:
            assert "Duplicate pages" in str(exc)
        else:
            raise AssertionError("extract_pages debería rechazar páginas duplicadas")
    finally:
        if os.path.isfile(test_pdf):
            os.unlink(test_pdf)


def test_select_openrouter_pdf_pages_filters_to_content_pages():
    """The OpenRouter canonical flow must only send substantive pages."""
    from main import _select_openrouter_pdf_pages

    content_pages = frozenset({2, 3, 5, 6, 9})
    selected = _select_openrouter_pdf_pages(
        content_page_set=content_pages,
        start_page=4,
        end_page=6,
        buffer=1,
    )

    assert selected == (3, 5, 6)


# ============================================================
# TEST 12: Integration - add_page_numbers + extract_page_range
# ============================================================

def test_integration_number_then_extract():
    """Test that we can add page numbers and then extract a range."""
    print("\n═══ TEST 12: Integration - Number then Extract ═══")
    all_passed = True

    test_pdf = create_test_pdf(8)
    numbered_pdf = None
    extracted = None

    try:
        # Step 1: Add page numbers
        numbered_pdf = add_page_numbers(test_pdf)
        reader = PdfReader(numbered_pdf)
        all_passed &= print_test(
            "Step 1: Numbered PDF has 8 pages",
            len(reader.pages) == 8
        )

        # Step 2: Extract pages 3-6 with buffer=1
        extracted = extract_page_range(numbered_pdf, start_page=3, end_page=6, buffer=1)
        reader2 = PdfReader(extracted)
        expected = 6  # pages 2,3,4,5,6,7
        all_passed &= print_test(
            f"Step 2: Extracted sub-PDF has {expected} pages",
            len(reader2.pages) == expected,
            f"Got: {len(reader2.pages)} pages"
        )

        # Step 3: The extracted PDF should be smaller than the numbered one
        numbered_size = os.path.getsize(numbered_pdf)
        extracted_size = os.path.getsize(extracted)
        all_passed &= print_test(
            "Step 3: Extracted PDF is smaller than full numbered PDF",
            extracted_size < numbered_size,
            f"Full: {numbered_size}B, Segment: {extracted_size}B"
        )

    finally:
        for path in [test_pdf, numbered_pdf, extracted]:
            if path and os.path.isfile(path):
                os.unlink(path)

    return all_passed


# ============================================================
# TEST 13: Segmentador schema validation
# ============================================================

def test_segmentador_schema():
    """Verify that segmentador schema includes pagina_inicio and pagina_fin."""
    print("\n═══ TEST 13: Segmentador schema validation ═══")
    all_passed = True

    from backend.agents.segmentador import RESPONSE_SCHEMA

    # Navigate schema to find partes.items.properties
    partes_schema = RESPONSE_SCHEMA.properties["partes"]
    parte_item = partes_schema.items
    required_fields = parte_item.required
    properties = parte_item.properties

    all_passed &= print_test(
        "pagina_inicio is in required fields",
        "pagina_inicio" in required_fields,
        f"Required: {required_fields}"
    )

    all_passed &= print_test(
        "pagina_fin is in required fields",
        "pagina_fin" in required_fields,
        f"Required: {required_fields}"
    )

    all_passed &= print_test(
        "pagina_inicio property exists in schema",
        "pagina_inicio" in properties
    )

    all_passed &= print_test(
        "pagina_fin property exists in schema",
        "pagina_fin" in properties
    )

    # Verify they are INTEGER type
    from google.genai import types as genai_types
    all_passed &= print_test(
        "pagina_inicio is INTEGER type",
        properties["pagina_inicio"].type == genai_types.Type.INTEGER
    )

    all_passed &= print_test(
        "pagina_fin is INTEGER type",
        properties["pagina_fin"].type == genai_types.Type.INTEGER
    )

    from backend.agents.segmentador import META_OBRA_SCHEMA

    all_passed &= print_test(
        "meta_obra is in required fields",
        "meta_obra" in RESPONSE_SCHEMA.required,
        f"Required: {RESPONSE_SCHEMA.required}"
    )

    all_passed &= print_test(
        "meta_obra property exists in schema",
        "meta_obra" in RESPONSE_SCHEMA.properties
    )

    all_passed &= print_test(
        "meta_obra is OBJECT type",
        RESPONSE_SCHEMA.properties["meta_obra"].type == genai_types.Type.OBJECT
    )

    meta_required = META_OBRA_SCHEMA.required
    meta_props = META_OBRA_SCHEMA.properties
    all_passed &= print_test(
        "META_OBRA_SCHEMA requires titulo",
        "titulo" in meta_required,
        f"Required: {meta_required}"
    )

    all_passed &= print_test(
        "META_OBRA_SCHEMA requires autor",
        "autor" in meta_required
    )

    all_passed &= print_test(
        "META_OBRA_SCHEMA requires descripcion",
        "descripcion" in meta_required
    )

    all_passed &= print_test(
        "META_OBRA_SCHEMA has titulo/autor/descripcion properties",
        all(k in meta_props for k in ("titulo", "autor", "descripcion"))
    )

    return all_passed


# ============================================================
# TEST 14: TOC generation logic
# ============================================================

def test_toc_generation():
    """Test Table of Contents generation logic (mirrors main.py)."""
    print("\n═══ TEST 14: TOC generation logic ═══")
    all_passed = True

    # Simulate segmentation result
    segmentation = {
        "partes": [
            {"numero": 1, "titulo": "Introducción al Derecho", "pagina_inicio": 1, "pagina_fin": 5},
            {"numero": 2, "titulo": "Principios Fundamentales", "pagina_inicio": 6, "pagina_fin": 12},
            {"numero": 3, "titulo": "Aplicación Práctica", "pagina_inicio": 13, "pagina_fin": 20},
        ]
    }
    num_partes = len(segmentation["partes"])

    # Build TOC (same logic as main.py)
    toc_lines = ["TABLA DE CONTENIDOS DEL DOCUMENTO COMPLETO:"]
    for p in segmentation["partes"]:
        pg_start = p.get("pagina_inicio", "?")
        pg_end = p.get("pagina_fin", "?")
        toc_lines.append(
            f"  Parte {p['numero']}/{num_partes}: \"{p['titulo']}\" (Páginas {pg_start}-{pg_end})"
        )
    table_of_contents = "\n".join(toc_lines)

    all_passed &= print_test(
        "TOC has header line",
        "TABLA DE CONTENIDOS" in table_of_contents
    )

    all_passed &= print_test(
        "TOC contains all 3 parts",
        "Parte 1/3" in table_of_contents and
        "Parte 2/3" in table_of_contents and
        "Parte 3/3" in table_of_contents
    )

    all_passed &= print_test(
        "TOC contains page ranges",
        "(Páginas 1-5)" in table_of_contents and
        "(Páginas 6-12)" in table_of_contents and
        "(Páginas 13-20)" in table_of_contents
    )

    all_passed &= print_test(
        "TOC contains titles",
        "Introducción al Derecho" in table_of_contents and
        "Principios Fundamentales" in table_of_contents
    )

    # Test part marker replacement (same logic as main.py)
    part_id = 2
    toc_with_marker = table_of_contents.replace(
        f"  Parte {part_id}/{num_partes}:",
        f"  ▶ Parte {part_id}/{num_partes} [PARTE ACTUAL]:"
    )

    all_passed &= print_test(
        "Current part marker applied correctly",
        "▶ Parte 2/3 [PARTE ACTUAL]:" in toc_with_marker
    )

    all_passed &= print_test(
        "Other parts not marked",
        "  Parte 1/3:" in toc_with_marker and
        "  Parte 3/3:" in toc_with_marker
    )

    return all_passed


# ============================================================
# TEST 15: Augmented prompt generation
# ============================================================

def test_augmented_prompt():
    """Test that the augmented prompt correctly combines TOC + identification."""
    print("\n═══ TEST 15: Augmented prompt generation ═══")
    all_passed = True

    table_of_contents = (
        "TABLA DE CONTENIDOS DEL DOCUMENTO COMPLETO:\n"
        "  Parte 1/2: \"Tema A\" (Páginas 1-5)\n"
        "  Parte 2/2: \"Tema B\" (Páginas 6-10)"
    )
    identificacion = "Esta parte cubre desde 'Las fuentes del derecho...' hasta 'la jurisprudencia como fuente complementaria.'"
    part_id = 1
    num_partes = 2

    # Build augmented prompt (same logic as main.py)
    toc_with_marker = table_of_contents.replace(
        f"  Parte {part_id}/{num_partes}:",
        f"  ▶ Parte {part_id}/{num_partes} [PARTE ACTUAL]:"
    )
    agent_prompt = (
        f"{toc_with_marker}\n\n"
        f"---\n\n"
        f"INSTRUCCIONES PARA ESTA PARTE:\n"
        f"Procesa ÚNICAMENTE la Parte {part_id}/{num_partes}. "
        f"El PDF adjunto contiene las páginas relevantes para esta parte. "
        f"La tabla de contenidos anterior muestra la estructura completa del documento "
        f"para que tengas contexto de dónde se sitúa esta parte.\n\n"
        f"IDENTIFICACIÓN DE LA PARTE:\n{identificacion}"
    )

    all_passed &= print_test(
        "Prompt contains TOC",
        "TABLA DE CONTENIDOS" in agent_prompt
    )

    all_passed &= print_test(
        "Prompt marks current part",
        "▶ Parte 1/2 [PARTE ACTUAL]:" in agent_prompt
    )

    all_passed &= print_test(
        "Prompt contains separator",
        "---" in agent_prompt
    )

    all_passed &= print_test(
        "Prompt contains instructions",
        "Procesa ÚNICAMENTE la Parte 1/2" in agent_prompt
    )

    all_passed &= print_test(
        "Prompt contains original identification",
        "Las fuentes del derecho" in agent_prompt
    )

    all_passed &= print_test(
        "Prompt mentions PDF context",
        "El PDF adjunto contiene las páginas relevantes" in agent_prompt
    )

    return all_passed


# ============================================================
# TEST 16: TOC with missing page numbers (graceful fallback)
# ============================================================

def test_toc_missing_pages():
    """Test TOC generation when pagina_inicio/pagina_fin are missing."""
    print("\n═══ TEST 16: TOC with missing page numbers ═══")
    all_passed = True

    # Simulate segmentation with missing page info
    segmentation = {
        "partes": [
            {"numero": 1, "titulo": "Parte Sin Páginas"},
            {"numero": 2, "titulo": "Parte Con Páginas", "pagina_inicio": 5, "pagina_fin": 10},
        ]
    }
    num_partes = len(segmentation["partes"])

    toc_lines = ["TABLA DE CONTENIDOS DEL DOCUMENTO COMPLETO:"]
    for p in segmentation["partes"]:
        pg_start = p.get("pagina_inicio", "?")
        pg_end = p.get("pagina_fin", "?")
        toc_lines.append(
            f"  Parte {p['numero']}/{num_partes}: \"{p['titulo']}\" (Páginas {pg_start}-{pg_end})"
        )
    table_of_contents = "\n".join(toc_lines)

    all_passed &= print_test(
        "Missing pages shown as '?'",
        "(Páginas ?-?)" in table_of_contents
    )

    all_passed &= print_test(
        "Present pages shown correctly",
        "(Páginas 5-10)" in table_of_contents
    )

    return all_passed


# ============================================================
# TEST 17: YouTube flow isolation
# ============================================================

def test_source_type_routing_flags():
    """Verify that PDF routing is explicit and web stays outside the PDF branch."""
    print("\n═══ TEST 17: Source type routing flags ═══")
    all_passed = True

    # Same logic as main.py
    for source_type, expected in [("pdf", True), ("youtube", False), ("web", False), ("", False)]:
        is_pdf_source = source_type == "pdf"
        all_passed &= print_test(
            f"source_type='{source_type}' → is_pdf_source={expected}",
            is_pdf_source == expected
        )

    return all_passed


def test_youtube_flow_isolation():
    """Backward-compatible alias for the updated routing test."""
    return test_source_type_routing_flags()


# ============================================================
# TEST 18: Multiple sequential extractions (simulates part loop)
# ============================================================

def test_multiple_sequential_extractions():
    """Simulate the main.py loop: extract multiple segments from the same PDF."""
    print("\n═══ TEST 18: Multiple sequential extractions ═══")
    all_passed = True

    test_pdf = create_test_pdf(15)
    numbered_pdf = None
    extracted_paths = []

    try:
        numbered_pdf = add_page_numbers(test_pdf)

        # Simulate 3 segments
        segments = [
            (1, 5),   # Part 1: pages 1-5
            (6, 10),  # Part 2: pages 6-10
            (11, 15), # Part 3: pages 11-15
        ]

        for i, (start, end) in enumerate(segments, 1):
            extracted = extract_page_range(numbered_pdf, start, end, buffer=1)
            extracted_paths.append(extracted)

            reader = PdfReader(extracted)
            # With buffer: part 1 → pages 1-6 (6), part 2 → 5-11 (7), part 3 → 10-15 (6)
            expected_min = end - start + 1  # At least the requested pages
            all_passed &= print_test(
                f"Segment {i} (pages {start}-{end}) extracted successfully",
                len(reader.pages) >= expected_min,
                f"Got: {len(reader.pages)} pages (buffer included)"
            )

        all_passed &= print_test(
            "All 3 segments created successfully",
            len(extracted_paths) == 3
        )

    finally:
        for path in [test_pdf, numbered_pdf] + extracted_paths:
            if path and os.path.isfile(path):
                os.unlink(path)

    return all_passed


# ============================================================
# TEST 19: Segmentador prompt contains page numbering instructions
# ============================================================

def test_segmentador_prompt_content():
    """Verify segmentador system instruction mentions page numbering."""
    print("\n═══ TEST 19: Segmentador prompt content ═══")
    all_passed = True

    from backend.agents.segmentador import SYSTEM_INSTRUCTION

    all_passed &= print_test(
        "Prompt mentions 'Página X / N' format",
        "Página X / N" in SYSTEM_INSTRUCTION
    )

    all_passed &= print_test(
        "Prompt mentions visible page marks",
        "marca visible" in SYSTEM_INSTRUCTION
    )

    all_passed &= print_test(
        "Prompt mentions pagina_inicio",
        "pagina_inicio" in SYSTEM_INSTRUCTION
    )

    all_passed &= print_test(
        "Prompt mentions pagina_fin",
        "pagina_fin" in SYSTEM_INSTRUCTION
    )

    all_passed &= print_test(
        "Prompt requires EXACT match with visible marks",
        "EXACTAMENTE" in SYSTEM_INSTRUCTION
    )

    return all_passed


# ============================================================
# TEST 20: Text/web segmentador prompt keeps block rigor
# ============================================================

def test_text_segmentador_prompt_content():
    """Verify text/web segmentador system instruction is rigorous and block-aware."""
    print("\n═══ TEST 20: Text/Web segmentador prompt content ═══")
    all_passed = True

    from backend.agents.segmentador import TEXT_SYSTEM_INSTRUCTION

    all_passed &= print_test(
        "Text prompt mentions visible block markers",
        "=== BLOQUE X ===" in TEXT_SYSTEM_INSTRUCTION
    )

    all_passed &= print_test(
        "Text prompt mentions bloque_inicio",
        "bloque_inicio" in TEXT_SYSTEM_INSTRUCTION
    )

    all_passed &= print_test(
        "Text prompt mentions bloque_fin",
        "bloque_fin" in TEXT_SYSTEM_INSTRUCTION
    )

    all_passed &= print_test(
        "Text prompt requires exact visible marker matching",
        "EXACTAMENTE" in TEXT_SYSTEM_INSTRUCTION
    )

    all_passed &= print_test(
        "Text prompt enforces contiguous block ranges",
        "rango continuo de bloques" in TEXT_SYSTEM_INSTRUCTION
    )

    all_passed &= print_test(
        "Text prompt distinguishes technical header from substantive content",
        "cabecera técnica" in TEXT_SYSTEM_INSTRUCTION
    )

    all_passed &= print_test(
        "Text prompt includes six-step thinking protocol",
        "PASO 6 - DEFINICIÓN PRECISA DE IDENTIFICACIÓN Y BLOQUES" in TEXT_SYSTEM_INSTRUCTION
    )

    all_passed &= print_test(
        "Text prompt mentions bad scrape detection",
        "mal scrape" in TEXT_SYSTEM_INSTRUCTION or "scrape defectuoso" in TEXT_SYSTEM_INSTRUCTION
    )

    all_passed &= print_test(
        "Text prompt requires evaluacion_fuente.es_segmentable",
        "evaluacion_fuente.es_segmentable" in TEXT_SYSTEM_INSTRUCTION
    )

    return all_passed


# ============================================================
# TEST 21: Text/web segmentador schema includes refusal contract
# ============================================================

def test_text_segmentador_schema_refusal_contract():
    """Verify text/web schema requires the bad-scrape refusal contract."""
    print("\n═══ TEST 21: Text/Web segmentador schema refusal contract ═══")
    all_passed = True

    from backend.agents.segmentador import TEXT_RESPONSE_SCHEMA
    from google.genai import types as genai_types

    required_fields = TEXT_RESPONSE_SCHEMA.required
    properties = TEXT_RESPONSE_SCHEMA.properties
    evaluation_schema = properties["evaluacion_fuente"]

    all_passed &= print_test(
        "evaluacion_fuente is required",
        "evaluacion_fuente" in required_fields,
        f"Required: {required_fields}"
    )

    all_passed &= print_test(
        "evaluacion_fuente property exists",
        "evaluacion_fuente" in properties
    )

    all_passed &= print_test(
        "evaluacion_fuente is OBJECT type",
        evaluation_schema.type == genai_types.Type.OBJECT
    )

    all_passed &= print_test(
        "es_segmentable is required inside evaluacion_fuente",
        "es_segmentable" in evaluation_schema.required,
        f"Required: {evaluation_schema.required}"
    )

    all_passed &= print_test(
        "motivo is required inside evaluacion_fuente",
        "motivo" in evaluation_schema.required,
        f"Required: {evaluation_schema.required}"
    )

    all_passed &= print_test(
        "indicios is required inside evaluacion_fuente",
        "indicios" in evaluation_schema.required,
        f"Required: {evaluation_schema.required}"
    )

    all_passed &= print_test(
        "es_segmentable is BOOLEAN type",
        evaluation_schema.properties["es_segmentable"].type == genai_types.Type.BOOLEAN
    )

    all_passed &= print_test(
        "meta_obra is required in TEXT_RESPONSE_SCHEMA",
        "meta_obra" in required_fields,
        f"Required: {required_fields}"
    )

    all_passed &= print_test(
        "meta_obra property exists in TEXT_RESPONSE_SCHEMA",
        "meta_obra" in properties
    )

    return all_passed


# ============================================================
# TEST 22: OpenRouter JSON contracts include meta_obra
# ============================================================

def test_openrouter_json_contracts_include_meta_obra():
    """Verify both OpenRouter segmentador contracts include meta_obra."""
    print("\n═══ TEST 22: OpenRouter JSON contracts include meta_obra ═══")
    all_passed = True

    from backend.agents.segmentador import (
        OPENROUTER_PDF_JSON_CONTRACT,
        OPENROUTER_TEXT_JSON_CONTRACT,
    )

    all_passed &= print_test(
        "PDF contract includes meta_obra",
        '"meta_obra"' in OPENROUTER_PDF_JSON_CONTRACT
    )

    all_passed &= print_test(
        "PDF contract meta_obra has titulo",
        '"titulo"' in OPENROUTER_PDF_JSON_CONTRACT
    )

    all_passed &= print_test(
        "Text contract includes meta_obra",
        '"meta_obra"' in OPENROUTER_TEXT_JSON_CONTRACT
    )

    all_passed &= print_test(
        "Text contract meta_obra has autor",
        '"autor"' in OPENROUTER_TEXT_JSON_CONTRACT
    )

    all_passed &= print_test(
        "Text contract meta_obra has descripcion",
        '"descripcion"' in OPENROUTER_TEXT_JSON_CONTRACT
    )

    return all_passed


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("  COMPREHENSIVE TEST SUITE: PDF Page-Aware Segmentation")
    print("=" * 70)

    tests = [
        test_add_page_numbers_basic,
        test_add_page_numbers_single_page,
        test_add_page_numbers_large_pdf,
        test_add_page_numbers_errors,
        test_extract_page_range_basic,
        test_extract_page_range_first_pages,
        test_extract_page_range_last_pages,
        test_extract_page_range_single_page,
        test_extract_page_range_no_buffer,
        test_extract_page_range_full_document,
        test_extract_page_range_errors,
        test_integration_number_then_extract,
        test_segmentador_schema,
        test_toc_generation,
        test_augmented_prompt,
        test_toc_missing_pages,
        test_youtube_flow_isolation,
        test_multiple_sequential_extractions,
        test_segmentador_prompt_content,
        test_text_segmentador_prompt_content,
        test_text_segmentador_schema_refusal_contract,
        test_openrouter_json_contracts_include_meta_obra,
    ]

    results = []
    for test_fn in tests:
        try:
            passed = test_fn()
            results.append((test_fn.__name__, passed))
        except Exception as e:
            print(f"\n  💥 EXCEPTION in {test_fn.__name__}: {type(e).__name__}: {e}")
            results.append((test_fn.__name__, False))

    # Summary
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)

    passed_count = sum(1 for _, p in results if p)
    failed_count = sum(1 for _, p in results if not p)
    total = len(results)

    for name, passed in results:
        status = "✅" if passed else "❌"
        print(f"  {status} {name}")

    print(f"\n  Total: {total} tests, {passed_count} passed, {failed_count} failed")

    if failed_count == 0:
        print("\n  🎉 ALL TESTS PASSED!")
    else:
        print(f"\n  ⚠️  {failed_count} TEST(S) FAILED!")

    return failed_count == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
