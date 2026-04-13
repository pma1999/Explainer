"""Tests for subpart scope auditor helpers."""

from __future__ import annotations

from backend.subpart_scope_auditor import (
    SubpartScopeAuditReport,
    build_subpart_scope_retry_suffix,
    flatten_desarrollo_text,
)


def test_flatten_desarrollo_text_preserves_section_order():
    payload = {
        "desarrollo": [
            {
                "titulo_seccion": "Uno",
                "explicacion_introductoria": "Intro uno",
                "subsecciones": [
                    {"titulo_subseccion": "A", "explicacion_detallada": "Detalle A"},
                ],
            },
            {
                "titulo_seccion": "Dos",
                "explicacion_introductoria": "Intro dos",
                "subsecciones": [
                    {"titulo_subseccion": "B", "explicacion_detallada": "Detalle B"},
                ],
            },
        ]
    }

    text = flatten_desarrollo_text(payload)
    assert "Uno" in text and "Dos" in text
    assert text.index("Uno") < text.index("Dos")


def test_retry_suffix_mentions_neighbor_leaks_and_missing_current_scope():
    report = SubpartScopeAuditReport(
        is_valid=False,
        invades_previous=("Teorización política",),
        invades_next=("Régimen polisinodial",),
        missing_current=("Burocracia de oficiales",),
        rationale="Se desarrolla material de subpartes adyacentes y falta contenido propio.",
    )

    text = build_subpart_scope_retry_suffix(report)
    assert "<correccion_alcance_subparte>" in text
    assert "Teorización política" in text
    assert "Régimen polisinodial" in text
    assert "Burocracia de oficiales" in text
    assert "SOLO corrige el alcance" in text
