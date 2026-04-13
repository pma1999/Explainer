"""Tests for subpart scope auditor helpers."""

from __future__ import annotations

from backend.subpart_scope_auditor import (
    SubpartScopeAuditReport,
    build_subpart_scope_rewrite_brief,
    build_subpart_scope_retry_suffix,
    flatten_desarrollo_text,
)


def _extract_failed_output_reference(text: str) -> str:
    _, marker, remainder = text.partition("RESPUESTA ANTERIOR INVÁLIDA:\n")
    assert marker
    reference, marker, _ = remainder.partition("\n\nERRORES DETECTADOS POR EL AUDITOR:")
    assert marker
    return reference


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


def test_rewrite_brief_includes_failed_output_audit_reason_and_scope_summaries():
    report = SubpartScopeAuditReport(
        is_valid=False,
        invades_previous=("Teorización política",),
        invades_next=("Régimen polisinodial",),
        missing_current=("Burocracia de oficiales",),
        rationale="Invade la siguiente subparte y omite contenido propio.",
    )
    payload = {
        "desarrollo": [
            {
                "titulo_seccion": "Bloque inválido",
                "explicacion_introductoria": "Texto desarrollado contaminado",
                "subsecciones": [
                    {
                        "titulo_subseccion": "Detalle",
                        "explicacion_detallada": "Incluye material de la subparte vecina",
                    }
                ],
            }
        ]
    }

    text = build_subpart_scope_rewrite_brief(
        report,
        failed_desarrollo_payload=payload,
        current_subpart_summary="Título: Actual\nContenido: Contenido actual",
        previous_subpart_summary="Título: Anterior\nContenido: Contenido anterior",
        next_subpart_summary="Título: Siguiente\nContenido: Contenido siguiente",
    )

    assert "<reescritura_alcance_subparte>" in text
    assert "RESPUESTA ANTERIOR INVÁLIDA" in text
    assert "Texto desarrollado contaminado" in text
    assert "Invade la siguiente subparte y omite contenido propio." in text
    assert "Título: Actual" in text
    assert "Título: Anterior" in text
    assert "Título: Siguiente" in text
    assert "REESCRIBE desde cero el campo `desarrollo`" in text


def test_rewrite_brief_includes_full_failed_output_reference_even_when_long():
    report = SubpartScopeAuditReport(
        is_valid=False,
        invades_previous=(),
        invades_next=("Tema vecino",),
        missing_current=("Tema actual",),
        rationale="La salida anterior se extendió fuera de alcance.",
    )
    repeated_intro = "X" * 2200
    repeated_detail = "Y" * 2200
    tail_marker = "TAIL-CONTENT-MUST-STAY"
    payload = {
        "desarrollo": [
            {
                "titulo_seccion": "Uno",
                "explicacion_introductoria": repeated_intro,
                "subsecciones": [
                    {"titulo_subseccion": "A", "explicacion_detallada": repeated_detail + tail_marker},
                ],
            }
        ]
    }

    text = build_subpart_scope_rewrite_brief(
        report,
        failed_desarrollo_payload=payload,
        current_subpart_summary="Título: Actual",
        previous_subpart_summary="",
        next_subpart_summary="Título: Siguiente",
    )

    failed_output_reference = _extract_failed_output_reference(text)
    expected_reference = flatten_desarrollo_text(payload)

    assert failed_output_reference == expected_reference
    assert "[truncado]" not in failed_output_reference
    assert tail_marker in failed_output_reference
