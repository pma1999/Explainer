from __future__ import annotations

import json

import pytest

from backend.pdf_ocr_cache import (
    PdfOcrBuildResult,
    PdfOcrCacheEntry,
    PdfOcrError,
    PdfOcrParsedPage,
    load_pdf_ocr_cache_from_mapping,
    merge_page_indexes,
    normalize_expected_page_numbers,
    page_index_from_serialized,
    render_pdf_page_subset_to_validation_text,
    render_pdf_page_subset_to_text,
    render_pdf_pages_with_xml_tags,
    serialize_page_index,
    write_pdf_ocr_cache,
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


def test_normalize_expected_page_numbers_empty_returns_empty_tuple():
    assert normalize_expected_page_numbers(()) == ()
    assert normalize_expected_page_numbers([]) == ()
    assert normalize_expected_page_numbers(None) == ()


def test_normalize_expected_page_numbers_accepts_sorted_unique_positive_pages():
    assert normalize_expected_page_numbers((1, 2, 5)) == (1, 2, 5)
    assert normalize_expected_page_numbers([1, 3]) == (1, 3)


def test_normalize_expected_page_numbers_rejects_invalid_inputs():
    with pytest.raises(PdfOcrError, match="inválidas"):
        normalize_expected_page_numbers((0, 1))
    with pytest.raises(PdfOcrError, match="duplicadas"):
        normalize_expected_page_numbers((1, 2, 2))
    with pytest.raises(PdfOcrError, match="orden ascendente"):
        normalize_expected_page_numbers((2, 1))


def test_normalize_expected_page_numbers_rejects_non_coercible_elements():
    with pytest.raises(PdfOcrError, match="no se pueden convertir"):
        normalize_expected_page_numbers((1, "two"))  # type: ignore[arg-type]
    with pytest.raises(PdfOcrError, match="no se pueden convertir"):
        normalize_expected_page_numbers([None])  # type: ignore[list-item]
    with pytest.raises(PdfOcrError, match="no se pueden convertir"):
        normalize_expected_page_numbers([object()])  # type: ignore[list-item]


def test_serialize_and_page_index_from_serialized_round_trip():
    pages = (
        PdfOcrParsedPage(
            page_number=2,
            markdown="md",
            images=({"id": "a.png"},),
            tables=({"id": "t.html", "content": "<table/>"},),
            hyperlinks=("https://example.com",),
            header="H",
            footer="F",
            dimensions={"w": 100},
            confidence_scores={"ocr": 0.9},
        ),
    )
    raw = serialize_page_index(pages)
    restored = page_index_from_serialized(raw)
    assert restored == pages


def test_page_index_from_serialized_rejects_non_list():
    assert page_index_from_serialized({}) == ()
    assert page_index_from_serialized(None) == ()


def test_page_index_from_serialized_rejects_non_dict_row():
    assert page_index_from_serialized([{"page_number": 1, "markdown": "a"}, "bad"]) == ()


def test_page_index_from_serialized_rejects_invalid_page_or_markdown():
    assert page_index_from_serialized([{"page_number": 0, "markdown": "a"}]) == ()
    assert page_index_from_serialized([{"page_number": 1, "markdown": 123}]) == ()
    assert page_index_from_serialized([{"page_number": True, "markdown": "a"}]) == ()


def test_page_index_from_serialized_rejects_duplicate_page_numbers():
    assert page_index_from_serialized(
        [
            {"page_number": 1, "markdown": "a"},
            {"page_number": 1, "markdown": "b"},
        ]
    ) == ()


def test_page_index_from_serialized_rejects_malformed_nested_shapes():
    base = {"page_number": 1, "markdown": "x"}
    assert page_index_from_serialized([{**base, "images": "not-a-list"}]) == ()
    assert page_index_from_serialized([{**base, "images": [1]}]) == ()
    assert page_index_from_serialized([{**base, "tables": "x"}]) == ()
    assert page_index_from_serialized([{**base, "tables": [None]}]) == ()
    assert page_index_from_serialized([{**base, "hyperlinks": [1]}]) == ()
    assert page_index_from_serialized([{**base, "hyperlinks": "u"}]) == ()
    assert page_index_from_serialized([{**base, "header": 99}]) == ()
    assert page_index_from_serialized([{**base, "footer": []}]) == ()
    assert page_index_from_serialized([{**base, "dimensions": "no"}]) == ()
    assert page_index_from_serialized([{**base, "confidence_scores": [1]}]) == ()


def test_page_index_from_serialized_accepts_optional_none_header_footer_and_missing_dimensions():
    pages = page_index_from_serialized(
        [
            {
                "page_number": 1,
                "markdown": "m",
                "header": None,
                "footer": None,
                "images": [],
                "tables": [],
                "hyperlinks": [],
            }
        ]
    )
    assert pages == (PdfOcrParsedPage(page_number=1, markdown="m"),)


def test_load_pdf_ocr_cache_from_mapping_rejects_unsupported_version():
    page_index, doc_count = load_pdf_ocr_cache_from_mapping(
        {"version": 99, "page_index": [{"page_number": 1, "markdown": "x"}]}
    )
    assert page_index == ()
    assert doc_count is None

    page_index2, doc_count2 = load_pdf_ocr_cache_from_mapping(
        {"version": "1", "page_index": [{"page_number": 1, "markdown": "x"}]}
    )
    assert page_index2 == ()
    assert doc_count2 is None


def test_load_pdf_ocr_cache_from_mapping_requires_exact_version_int():
    valid_page = {"page_number": 1, "markdown": "x"}
    missing, _ = load_pdf_ocr_cache_from_mapping({"page_index": [valid_page]})
    assert missing == ()

    wrong, _ = load_pdf_ocr_cache_from_mapping({"version": 1.0, "page_index": [valid_page]})
    assert wrong == ()


def test_write_pdf_ocr_cache_round_trip_via_load_mapping(tmp_path):
    cache_path = tmp_path / "doc.sha.mistral-native.json"
    pages = (
        PdfOcrParsedPage(page_number=1, markdown="uno", footer="— Página 1 / 3 —"),
        PdfOcrParsedPage(page_number=2, markdown="dos"),
    )
    write_pdf_ocr_cache(
        cache_path=cache_path,
        source_sha256="abc123",
        engine="mistral-native",
        document_page_count=10,
        page_index=pages,
    )
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["source_sha256"] == "abc123"
    assert payload["engine"] == "mistral-native"
    assert payload["document_page_count"] == 10
    page_index, doc_count = load_pdf_ocr_cache_from_mapping(payload)
    assert doc_count == 10
    assert page_index == pages


def test_render_pdf_page_subset_to_text_raises_when_watermark_only_leaves_empty():
    entry = PdfOcrCacheEntry(
        source_sha256="sha",
        engine="mistral-native",
        cache_path="cache.json",
        cache_hit=True,
        expected_page_numbers=(1,),
        cached_page_numbers=(1,),
        page_index=(_page(1, "— Página 1 / 10 —", footer="— Página 1 / 10 —"),),
    )
    with pytest.raises(PdfOcrError, match="no produjo texto reutilizable"):
        render_pdf_page_subset_to_text(cache_entry=entry, page_numbers=(1,))


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
                tables=({"id": "tbl-1.html", "content": "<table><tr><td>42</td></tr></table>"},),
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


def test_render_pdf_page_subset_to_validation_text_uses_xml_page_tags():
    entry = PdfOcrCacheEntry(
        source_sha256="sha",
        engine="mistral-native",
        cache_path="cache.json",
        cache_hit=True,
        expected_page_numbers=(16, 17),
        cached_page_numbers=(16, 17),
        page_index=(
            _page(16, "El Edicto de Caracalla aparece aqui."),
            _page(17, "Rutilio Claudio Namaciano aparece aqui."),
        ),
    )

    rendered = render_pdf_page_subset_to_validation_text(cache_entry=entry, page_numbers=(16, 17))

    assert "<pagina_16>" in rendered
    assert "</pagina_16>" in rendered
    assert "El Edicto de Caracalla" in rendered
    assert "<pagina_17>" in rendered
    assert "</pagina_17>" in rendered
    assert "Rutilio Claudio Namaciano" in rendered
    assert "--- PAGINA" not in rendered


def test_render_pdf_pages_with_xml_tags_wraps_each_page():
    entry = PdfOcrCacheEntry(
        source_sha256="sha",
        engine="mistral-native",
        cache_path="cache.json",
        cache_hit=True,
        expected_page_numbers=(3, 4),
        cached_page_numbers=(3, 4),
        page_index=(
            _page(3, "Contenido de la pagina tres."),
            _page(4, "Contenido de la pagina cuatro."),
        ),
    )

    rendered = render_pdf_pages_with_xml_tags(cache_entry=entry, page_numbers=(3, 4))

    assert rendered.startswith("<pagina_3>")
    assert "</pagina_3>" in rendered
    assert "<pagina_4>" in rendered
    assert rendered.rstrip().endswith("</pagina_4>")
    assert "Contenido de la pagina tres." in rendered
    assert "Contenido de la pagina cuatro." in rendered


def test_render_pdf_pages_with_xml_tags_strips_watermarks():
    entry = PdfOcrCacheEntry(
        source_sha256="sha",
        engine="mistral-native",
        cache_path="cache.json",
        cache_hit=True,
        expected_page_numbers=(5,),
        cached_page_numbers=(5,),
        page_index=(_page(5, "— Página 5 / 20 —\nTexto real.", footer="— Página 5 / 20 —"),),
    )

    rendered = render_pdf_pages_with_xml_tags(cache_entry=entry, page_numbers=(5,))

    assert "<pagina_5>" in rendered
    assert "Texto real." in rendered
    assert "— Página 5 / 20 —" not in rendered


def test_render_pdf_pages_with_xml_tags_raises_when_no_text():
    entry = PdfOcrCacheEntry(
        source_sha256="sha",
        engine="mistral-native",
        cache_path="cache.json",
        cache_hit=True,
        expected_page_numbers=(1,),
        cached_page_numbers=(1,),
        page_index=(_page(1, "— Página 1 / 5 —", footer="— Página 1 / 5 —"),),
    )

    with pytest.raises(PdfOcrError, match="no produjo texto reutilizable"):
        render_pdf_pages_with_xml_tags(cache_entry=entry, page_numbers=(1,))


def test_render_pdf_pages_with_xml_tags_raises_on_missing_page():
    entry = PdfOcrCacheEntry(
        source_sha256="sha",
        engine="mistral-native",
        cache_path="cache.json",
        cache_hit=True,
        expected_page_numbers=(2,),
        cached_page_numbers=(2,),
        page_index=(_page(2, "Texto dos."),),
    )

    with pytest.raises(PdfOcrError, match="páginas ausentes"):
        render_pdf_pages_with_xml_tags(cache_entry=entry, page_numbers=(2, 9))


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
