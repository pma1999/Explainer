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


def test_validate_classifier_partition_ok():
    from backend.agents.page_classifier import validate_classifier_partition
    r = {
        "total_paginas": 5,
        "rangos_contenido": [{"inicio": 2, "fin": 4}],
        "rangos_no_contenido": [
            {"inicio": 1, "fin": 1, "razon": "portada"},
            {"inicio": 5, "fin": 5, "razon": "colofon"},
        ],
    }
    ok, errs = validate_classifier_partition(r, 5)
    assert ok and errs == []


def test_validate_classifier_partition_overlap():
    from backend.agents.page_classifier import validate_classifier_partition
    r = {
        "total_paginas": 3,
        "rangos_contenido": [{"inicio": 1, "fin": 2}],
        "rangos_no_contenido": [{"inicio": 2, "fin": 3, "razon": "x"}],
    }
    ok, errs = validate_classifier_partition(r, 3)
    assert not ok
    assert any("Solapamiento" in e for e in errs)
