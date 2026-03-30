"""Unit tests for _build_content_pages_prefix in main."""

from __future__ import annotations

import importlib
import sys


def _get_helper():
    # Import the function without running the FastAPI app
    import main as m
    return m._build_content_pages_prefix


def test_single_range():
    fn = _get_helper()
    result = fn(frozenset(range(3, 11)), total_pages=12)
    assert "<paginas_contenido_verificado>" in result
    assert "</paginas_contenido_verificado>" in result
    assert "3-10" in result


def test_multiple_ranges():
    fn = _get_helper()
    result = fn(frozenset([1, 2, 3, 5, 6]), total_pages=6)
    assert "1-3" in result
    assert "5-6" in result


def test_empty_frozenset_returns_empty_string():
    fn = _get_helper()
    result = fn(frozenset(), total_pages=10)
    assert result == ""


def test_all_pages_content_no_non_content_line():
    fn = _get_helper()
    result = fn(frozenset(range(1, 6)), total_pages=5)
    assert "accesorias" not in result


def test_single_page():
    fn = _get_helper()
    result = fn(frozenset([7]), total_pages=10)
    assert "7" in result
    assert "<paginas_contenido_verificado>" in result
