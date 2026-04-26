"""Unit tests for _build_content_pages_prefix in main."""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace


def _get_helper():
    # Import the function without running the FastAPI app
    import main as m
    return m._build_content_pages_prefix


def _get_assemble_helper():
    import main as m
    return m._assemble_part_explainer


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


def test_prefix_contains_first_content_page_anchor():
    fn = _get_helper()
    result = fn(frozenset(range(3, 11)), total_pages=12)
    assert "Primera página de contenido (la primera parte DEBE empezar aquí o antes): 3\n" in result


def test_prefix_contains_last_content_page_anchor():
    fn = _get_helper()
    result = fn(frozenset(range(3, 11)), total_pages=12)
    assert "Última página de contenido (la última parte DEBE terminar aquí o después): 10\n" in result


def test_prefix_anchors_match_single_page():
    fn = _get_helper()
    result = fn(frozenset([7]), total_pages=10)
    assert "Primera página de contenido (la primera parte DEBE empezar aquí o antes): 7\n" in result
    assert "Última página de contenido (la última parte DEBE terminar aquí o después): 7\n" in result


def test_assemble_part_explainer_merges_segmentador_scaffold_with_subpart_desarrollo():
    fn = _get_assemble_helper()
    parte = {
        "introduccion": "Intro global",
        "conclusion": "Cierre global",
        "conexiones_contextuales": [
            {
                "seccion_temario_relacionada": "Tema relacionado",
                "descripcion_conexion": "Conexión principal",
            }
        ],
    }
    subpart_desarrollos = [
        [
            {
                "titulo_seccion": "Sección 1",
                "explicacion_introductoria": "Apertura 1",
                "subsecciones": [
                    {
                        "titulo_subseccion": "Sub 1",
                        "explicacion_detallada": "Detalle 1",
                    }
                ],
            }
        ],
        [
            {
                "titulo_seccion": "Sección 2",
                "explicacion_introductoria": "Apertura 2",
                "subsecciones": [
                    {
                        "titulo_subseccion": "Sub 2",
                        "explicacion_detallada": "Detalle 2",
                    }
                ],
            }
        ],
    ]

    result = fn(parte, subpart_desarrollos)

    assert result["introduccion"] == "Intro global"
    assert result["conclusion"] == "Cierre global"
    assert result["conexiones_contextuales"] == parte["conexiones_contextuales"]
    assert [section["titulo_seccion"] for section in result["desarrollo"]] == ["Sección 1", "Sección 2"]


def _scope_handoff():
    import main as m

    return m.PartHandoffContext(
        titulo="Parte 2",
        resumen_alcance="Instituciones del Estado Moderno",
        temas_cubiertos=("Concepto de Estado", "Burocracia"),
        intent_usuario=None,
        continuidad_previa=None,
        vision_global_division=None,
    )


def test_build_subpart_pdf_prompt_includes_structured_scope_and_negative_neighbors():
    import main as m

    parte = {
        "numero": 2,
        "titulo": "El Estado Moderno",
        "identificacion": "Parte 2 completa",
        "pagina_inicio": 12,
        "pagina_fin": 27,
    }
    subpartes = [
        {
            "numero_subparte": 1,
            "titulo": "Precursores",
            "contenido": "Teorización política previa",
            "temas_cubiertos": ["Tomás de Aquino", "Maquiavelo"],
            "pagina_inicio": 18,
            "pagina_fin": 19,
        },
        {
            "numero_subparte": 2,
            "titulo": "Cambios estructurales",
            "contenido": "Reforma administrativa y oficiales",
            "temas_cubiertos": ["Burocracia"],
            "pagina_inicio": 19,
            "pagina_fin": 22,
            "identificacion": "NÚCLEO SEGÚN MARCAS PDF: páginas 19–22.",
            "delimitacion_explainer": {
                "inicio": {"encabezado": "2.3", "ancla_texto": "Las monarquías modernas reforzaron"},
                "fin": {"ancla_texto": "oficio público cada vez más técnico", "encabezado_siguiente_excluido": "2.4 Régimen de Consejos"},
                "transicion_compartida": {
                    "hay_transicion": True,
                    "pagina": 19,
                    "hasta_texto_inclusive": "la mención a Bodin",
                    "desde_texto_inclusive": "2.3 Cambios estructurales",
                },
            },
        },
        {
            "numero_subparte": 3,
            "titulo": "Consejos",
            "contenido": "Régimen polisinodial",
            "temas_cubiertos": ["Consejos", "Audiencias"],
            "pagina_inicio": 23,
            "pagina_fin": 27,
        },
    ]

    prompt = m._build_subpart_pdf_prompt(
        "TABLA",
        parte,
        subpartes[1],
        subpartes,
        2,
        5,
        _scope_handoff(),
        pdf_scope_mode="subpdf_buffered",
        nucleo_inicio=12,
        nucleo_fin=27,
    )

    assert "CONTRATO ESTRUCTURADO DE ALCANCE DE LA SUBPARTE" in prompt
    assert "FRONTERAS NEGATIVAS (NO DESARROLLAR)" in prompt
    assert "Subparte 1 (anterior)" in prompt
    assert "Subparte 3 (siguiente)" in prompt
    assert "Burocracia" in prompt
    assert "Tomás de Aquino" in prompt
    assert "Consejos" in prompt


def test_prepare_mistral_pdf_ocr_context_requests_only_content_pages(monkeypatch):
    import main as m

    captured: dict = {}
    fake_cache_entry = SimpleNamespace(
        cache_hit=False,
        cache_path="cache.json",
        expected_page_numbers=(1, 3),
        cached_page_numbers=(1, 3),
        page_index=(),
    )

    def _fake_get_or_prime(**kwargs):
        captured.update(kwargs)
        return fake_cache_entry

    monkeypatch.setattr(m, "get_or_prime_mistral_pdf_ocr_cache", _fake_get_or_prime)

    context = m._prepare_mistral_pdf_ocr_context(
        numbered_pdf_path="document-numbered.pdf",
        content_page_set=frozenset({3, 1}),
        api_key="mistral-test-key",
        engine="mistral-native",
    )

    assert captured["expected_page_numbers"] == (1, 3)
    assert context.source_pdf_path == "document-numbered.pdf"
    assert context.cache_entry is fake_cache_entry


def test_adjacent_subparts_for_audit_uses_next_part_first_subpart_for_tail_boundary():
    import main as m

    partes_segmentadas = [
        {"numero": 1, "subpartes": [{"numero_subparte": 1, "titulo": "1.1"}, {"numero_subparte": 2, "titulo": "1.2"}]},
        {"numero": 2, "subpartes": [{"numero_subparte": 1, "titulo": "2.1"}, {"numero_subparte": 2, "titulo": "2.2"}]},
    ]

    prev_sp, next_sp = m._adjacent_subparts_for_audit(
        partes_segmentadas=partes_segmentadas,
        current_parte=partes_segmentadas[0],
        subpart_idx=1,
    )

    assert prev_sp is partes_segmentadas[0]["subpartes"][0]
    assert next_sp is partes_segmentadas[1]["subpartes"][0]


def test_adjacent_subparts_for_audit_uses_previous_part_last_subpart_for_head_boundary():
    import main as m

    partes_segmentadas = [
        {"numero": 1, "subpartes": [{"numero_subparte": 1, "titulo": "1.1"}, {"numero_subparte": 2, "titulo": "1.2"}]},
        {"numero": 2, "subpartes": [{"numero_subparte": 1, "titulo": "2.1"}, {"numero_subparte": 2, "titulo": "2.2"}]},
    ]

    prev_sp, next_sp = m._adjacent_subparts_for_audit(
        partes_segmentadas=partes_segmentadas,
        current_parte=partes_segmentadas[1],
        subpart_idx=0,
    )

    assert prev_sp is partes_segmentadas[0]["subpartes"][1]
    assert next_sp is partes_segmentadas[1]["subpartes"][1]


def test_adjacent_subparts_for_audit_uses_segmentation_order_and_skips_parts_without_subparts():
    import main as m

    partes_segmentadas = [
        {"numero": 10, "subpartes": [{"numero_subparte": 1, "titulo": "10.1"}]},
        {"numero": 20, "subpartes": []},
        {"numero": 40, "subpartes": [{"numero_subparte": 1, "titulo": "40.1"}]},
    ]

    prev_sp, next_sp = m._adjacent_subparts_for_audit(
        partes_segmentadas=partes_segmentadas,
        current_parte=partes_segmentadas[0],
        subpart_idx=0,
    )

    assert prev_sp is None
    assert next_sp is partes_segmentadas[2]["subpartes"][0]
