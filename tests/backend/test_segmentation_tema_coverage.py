"""Unit tests for MECE tema coverage validation (segmentation_tema_coverage)."""

from __future__ import annotations

import pytest

from backend.segmentation_tema_coverage import (
    build_tema_coverage_retry_suffix,
    validate_tema_partition,
)


def _part(num: int, temas: list[str] | None) -> dict:
    return {
        "numero": num,
        "titulo": f"P{num}",
        "temas_cubiertos": temas,
    }


def test_validate_perfect_partition():
    seg = {
        "temas_identificados": ["Alpha", "Beta"],
        "partes": [
            _part(1, ["Alpha"]),
            _part(2, ["Beta"]),
        ],
    }
    r = validate_tema_partition(seg)
    assert r.is_valid
    assert not r.missing
    assert not r.duplicates
    assert not r.orphans
    assert not r.structural_errors


def test_validate_missing_tema():
    seg = {
        "temas_identificados": ["A", "B", "C"],
        "partes": [
            _part(1, ["A"]),
            _part(2, ["B"]),
        ],
    }
    r = validate_tema_partition(seg)
    assert not r.is_valid
    assert "C" in r.missing
    assert len(r.missing) == 1


def test_validate_duplicate_across_parts():
    seg = {
        "temas_identificados": ["X"],
        "partes": [
            _part(1, ["X"]),
            _part(2, ["X"]),
        ],
    }
    r = validate_tema_partition(seg)
    assert not r.is_valid
    assert len(r.duplicates) == 1
    assert r.duplicates[0].canonical == "X"
    assert r.duplicates[0].part_numbers == (1, 2)


def test_validate_orphan():
    seg = {
        "temas_identificados": ["Solo"],
        "partes": [
            _part(1, ["Solo", "No existe"]),
        ],
    }
    r = validate_tema_partition(seg)
    assert not r.is_valid
    assert len(r.orphans) == 1
    assert r.orphans[0] == (1, "No existe")


def test_validate_temas_cubiertos_missing():
    seg = {
        "temas_identificados": ["T"],
        "partes": [{"numero": 1, "titulo": "P1"}],
    }
    r = validate_tema_partition(seg)
    assert not r.is_valid
    assert any("temas_cubiertos" in e for e in r.structural_errors)


def test_validate_temas_cubiertos_not_list():
    seg = {
        "temas_identificados": ["T"],
        "partes": [_part(1, None)],  # type: ignore[arg-type]
    }
    part = seg["partes"][0]
    part["temas_cubiertos"] = "not-a-list"
    r = validate_tema_partition(seg)
    assert not r.is_valid
    assert r.structural_errors


def test_validate_duplicate_in_temas_identificados_collapses_inventory():
    """Same normalized key twice in global list: one slot; both parts claiming same string OK."""
    seg = {
        "temas_identificados": ["Same", "Same"],
        "partes": [
            _part(1, ["Same"]),
        ],
    }
    r = validate_tema_partition(seg)
    assert r.is_valid


def test_normalize_whitespace_match():
    seg = {
        "temas_identificados": ["Foo  Bar"],
        "partes": [
            _part(1, ["Foo Bar"]),
        ],
    }
    r = validate_tema_partition(seg)
    assert r.is_valid


def test_empty_inventory_valid_if_no_orphans():
    seg = {"temas_identificados": [], "partes": [_part(1, [])]}
    r = validate_tema_partition(seg)
    assert r.is_valid
    assert r.empty_temas_inventory


def test_empty_inventory_invalid_with_orphans():
    seg = {"temas_identificados": [], "partes": [_part(1, ["algo"])]}
    r = validate_tema_partition(seg)
    assert not r.is_valid


def test_build_retry_suffix_contains_lists():
    seg = {
        "temas_identificados": ["M1"],
        "partes": [_part(1, ["bad"])],
    }
    rep = validate_tema_partition(seg)
    assert not rep.is_valid
    text = build_tema_coverage_retry_suffix(attempt=1, segmentation=seg, report=rep)
    assert "<correccion_asignacion_temas>" in text
    assert "</correccion_asignacion_temas>" in text
    assert "M1" in text or "SIN ASIGNAR" in text or "huérfan" in text.lower() or "NO COINCIDEN" in text
    assert "bad" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
