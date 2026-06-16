"""The scope validator must see EXACTLY the OCR pages the explainer received.

Regression for the false-positive scope violation: a subpart's section heading that
sits on the explainer's buffer page (pagina_fin + 1) used to be invisible to the
validator (which only rendered the exact [pagina_inicio, pagina_fin] window), so the
validator flagged legitimate, in-source content as fabricated.
"""
from __future__ import annotations

from backend.agents.completeness_validator import (
    ExplainerScopeItem,
    ExplainerValidationContext,
)
from backend.pdf_ocr_cache import PdfOcrCacheEntry, PdfOcrParsedPage


def _page(n: int, markdown: str) -> PdfOcrParsedPage:
    return PdfOcrParsedPage(page_number=n, markdown=markdown)


def _cache_entry() -> PdfOcrCacheEntry:
    # Pages 70..77; the disputed "Liberal" heading lives on the buffer page 77.
    pages = tuple(
        _page(n, f"Contenido de la pagina {n}." if n != 77 else "Stratification in Liberal Social Policy")
        for n in range(70, 78)
    )
    return PdfOcrCacheEntry(
        source_sha256="sha",
        engine="mistral-native",
        cache_path="cache.json",
        cache_hit=True,
        expected_page_numbers=tuple(range(70, 78)),
        cached_page_numbers=tuple(range(70, 78)),
        page_index=pages,
    )


def _subpart_context() -> ExplainerValidationContext:
    return ExplainerValidationContext(
        scope_kind="subpart",
        current=ExplainerScopeItem(
            kind="subpart",
            number="1/3",
            title="Introducción, conservadurismo y liberalismo",
            page_start=70,
            page_end=76,  # núcleo declarado: 70-76 (más estrecho que la ventana real del explainer)
        ),
    )


def test_validation_evidence_matches_explainer_buffered_window():
    import main as m

    content_page_set = frozenset(range(70, 78))
    # Explainer realmente recibió 70..77 (núcleo 70-76 + buffer ±1).
    explainer_pages = tuple(range(70, 78))

    evidence = m._build_mistral_ocr_validation_evidence(
        cache_entry=_cache_entry(),
        content_page_set=content_page_set,
        context=_subpart_context(),
        explainer_pages=explainer_pages,
    )

    assert evidence is not None
    # El validador ve EXACTAMENTE las páginas del explainer, incluida la 77 (buffer).
    assert evidence.pages == explainer_pages
    assert "<pagina_77>" in evidence.text
    assert "Stratification in Liberal Social Policy" in evidence.text


def test_validation_evidence_falls_back_to_unit_range_without_explainer_pages():
    import main as m

    content_page_set = frozenset(range(70, 78))

    evidence = m._build_mistral_ocr_validation_evidence(
        cache_entry=_cache_entry(),
        content_page_set=content_page_set,
        context=_subpart_context(),
        explainer_pages=(),
    )

    assert evidence is not None
    # Sin ventana del explainer, se cae al rango núcleo declarado 70-76 (sin la 77).
    assert evidence.pages == tuple(range(70, 77))
    assert "<pagina_77>" not in evidence.text
