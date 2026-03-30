"""Unit tests for page-range coverage validation (segmentation_page_coverage)."""

from __future__ import annotations

import pytest

from backend.segmentation_page_coverage import (
    build_page_coverage_retry_suffix,
    validate_page_coverage,
)

# Pages 3-20 are content in most tests
CONTENT = frozenset(range(3, 21))


def _parte(num: int, pi: int, pf: int, subpartes: list[dict] | None = None, temas: list[str] | None = None) -> dict:
    p: dict = {"numero": num, "titulo": f"Parte {num}", "pagina_inicio": pi, "pagina_fin": pf}
    if subpartes is not None:
        p["subpartes"] = subpartes
    if temas is not None:
        p["temas_cubiertos"] = temas
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


def test_part_level_error_skips_subpart_validation_for_that_part():
    """If a part has an invalid range, its subparts are not validated (avoids noise)."""
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


# ── Retry suffix — semantic anchoring ────────────────────────────────────────

def test_retry_suffix_contains_instruccion_critica():
    """Retry suffix must include an explicit 'only fix page ranges' instruction."""
    seg = {"partes": [_parte(1, 3, 9), _parte(2, 12, 20)]}
    report = validate_page_coverage(seg, CONTENT)
    text = build_page_coverage_retry_suffix(
        attempt=0, segmentation=seg, report=report, content_page_set=CONTENT
    )
    assert "INSTRUCCIÓN CRÍTICA" in text or "SOLO modifica" in text


def test_retry_suffix_includes_temas_identificados_when_present():
    """When segmentation has temas_identificados, they must appear in the retry suffix."""
    temas = ["La querella de las investiduras", "El Papado gregoriano", "El Imperio y el Papado"]
    seg = {
        "temas_identificados": temas,
        "partes": [
            _parte(1, 3, 9, temas=["La querella de las investiduras"]),
            _parte(2, 12, 20, temas=["El Papado gregoriano", "El Imperio y el Papado"]),
        ],
    }
    report = validate_page_coverage(seg, CONTENT)
    text = build_page_coverage_retry_suffix(
        attempt=0, segmentation=seg, report=report, content_page_set=CONTENT
    )
    assert "La querella de las investiduras" in text
    assert "El Papado gregoriano" in text


def test_retry_suffix_temas_section_absent_when_no_temas_identificados():
    """When temas_identificados is missing, suffix still works without crash."""
    seg = {"partes": [_parte(1, 3, 9), _parte(2, 12, 20)]}
    report = validate_page_coverage(seg, CONTENT)
    text = build_page_coverage_retry_suffix(
        attempt=0, segmentation=seg, report=report, content_page_set=CONTENT
    )
    assert "<correccion_rangos_pagina>" in text
    assert "</correccion_rangos_pagina>" in text


def test_compact_segmentation_ranges_includes_temas_cubiertos():
    """_compact_segmentation_ranges must include temas_cubiertos in part entries."""
    from backend.segmentation_page_coverage import _compact_segmentation_ranges
    seg = {
        "partes": [
            _parte(1, 3, 9, temas=["Tema A", "Tema B"]),
            _parte(2, 12, 20, temas=["Tema C"]),
        ]
    }
    text = _compact_segmentation_ranges(seg)
    assert "Tema A" in text
    assert "Tema B" in text
    assert "Tema C" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
