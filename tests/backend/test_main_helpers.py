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
        intent_usuario=None,
        continuidad_previa=None,
        vision_global_division=None,
    )


def test_extract_obra_metadata_full_dict():
    import main as m

    segmentation = {
        "meta_obra": {
            "titulo": "El Príncipe",
            "autor": "Nicolás Maquiavelo",
            "descripcion": "Ensayo político clásico sobre la adquisición y conservación del poder.",
        },
        "partes": [],
    }
    result = m._extract_obra_metadata(segmentation, None)
    assert result == {
        "titulo": "El Príncipe",
        "autor": "Nicolás Maquiavelo",
        "descripcion": "Ensayo político clásico sobre la adquisición y conservación del poder.",
    }


def test_extract_obra_metadata_missing_or_malformed_meta_obra():
    import main as m

    empty = {"titulo": "", "autor": "", "descripcion": ""}
    assert m._extract_obra_metadata(None, None) == empty
    assert m._extract_obra_metadata({}, None) == empty
    assert m._extract_obra_metadata({"partes": []}, None) == empty
    assert m._extract_obra_metadata({"meta_obra": "no-dict"}, None) == empty
    assert m._extract_obra_metadata({"meta_obra": {"titulo": None}}, None) == empty


def test_extract_obra_metadata_strips_whitespace():
    import main as m

    segmentation = {
        "meta_obra": {
            "titulo": "  El Príncipe  ",
            "autor": "  \n",
            "descripcion": "  Ensayo político.  ",
        }
    }
    result = m._extract_obra_metadata(segmentation, None)
    assert result["titulo"] == "El Príncipe"
    assert result["autor"] == ""
    assert result["descripcion"] == "Ensayo político."


def test_format_obra_context_empty_returns_empty_string():
    import main as m

    assert m._format_obra_context({}) == ""
    assert m._format_obra_context({"titulo": "", "autor": " ", "descripcion": None}) == ""


def test_format_obra_context_full_block():
    import main as m

    block = m._format_obra_context({
        "titulo": "El Príncipe",
        "autor": "Nicolás Maquiavelo",
        "descripcion": "Ensayo político clásico sobre la adquisición del poder.",
    })

    assert "CONTEXTO DE LA OBRA" in block
    assert "«El Príncipe»" in block
    assert "Nicolás Maquiavelo" in block
    assert "Descripción de la obra:" in block
    assert "SOLO contexto" in block


def test_format_obra_context_autor_only():
    import main as m

    block = m._format_obra_context({"titulo": "", "autor": "Anónimo", "descripcion": ""})
    assert "una obra de Anónimo" in block


def test_build_subpart_pdf_prompt_includes_obra_context_when_set():
    import main as m

    handoff = m.PartHandoffContext(
        titulo="Parte 2",
        resumen_alcance="Instituciones del Estado Moderno",
        intent_usuario=None,
        continuidad_previa=None,
        vision_global_division=None,
        obra_context=(
            "CONTEXTO DE LA OBRA\n"
            "Estás explicando un fragmento de: «El Príncipe» — Nicolás Maquiavelo.\n\n"
            "Descripción de la obra: Ensayo político clásico."
        ),
    )
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
            "pagina_inicio": 18,
            "pagina_fin": 19,
        },
    ]

    prompt = m._build_subpart_pdf_prompt(
        "TABLA",
        parte,
        subpartes[0],
        subpartes,
        2,
        5,
        handoff,
        pdf_scope_mode="subpdf_buffered",
        nucleo_inicio=12,
        nucleo_fin=27,
    )

    assert "CONTEXTO DE LA OBRA" in prompt
    assert "«El Príncipe»" in prompt
    # El bloque de la obra va ANTES del bloque de segmentador/usuario
    assert prompt.index("CONTEXTO DE LA OBRA") < prompt.index("CONTEXTO DEL SEGMENTADOR Y DEL USUARIO")


def test_build_subpart_pdf_prompt_omits_obra_context_when_unset():
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
            "pagina_inicio": 18,
            "pagina_fin": 19,
        },
    ]

    prompt = m._build_subpart_pdf_prompt(
        "TABLA",
        parte,
        subpartes[0],
        subpartes,
        2,
        5,
        _scope_handoff(),
        pdf_scope_mode="subpdf_buffered",
        nucleo_inicio=12,
        nucleo_fin=27,
    )

    assert "CONTEXTO DE LA OBRA" not in prompt
    assert "CONTEXTO DEL SEGMENTADOR Y DEL USUARIO" in prompt


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
            "pagina_inicio": 18,
            "pagina_fin": 19,
        },
        {
            "numero_subparte": 2,
            "titulo": "Cambios estructurales",
            "contenido": "Reforma administrativa y oficiales",
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
    assert "Reforma administrativa y oficiales" in prompt
    assert "Teorización política previa" in prompt
    assert "Régimen polisinodial" in prompt


def test_build_subpart_pdf_prompt_removes_global_scaffold_references():
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
            "pagina_inicio": 18,
            "pagina_fin": 19,
        },
        {
            "numero_subparte": 2,
            "titulo": "Cambios estructurales",
            "contenido": "Reforma administrativa y oficiales",
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

    lowered = prompt.lower()
    assert "introducción" not in lowered
    assert "conclusión" not in lowered
    assert "conexiones contextuales" not in lowered
    assert "conexiones_contextuales" not in lowered


def test_build_part_pdf_prompt_includes_structured_scope_and_negative_neighbors():
    import main as m

    partes = [
        {
            "numero": 1,
            "titulo": "Precursores",
            "contenido": "Teorización política previa",
            "identificacion": "Parte 1 completa",
            "pagina_inicio": 1,
            "pagina_fin": 11,
        },
        {
            "numero": 2,
            "titulo": "El Estado Moderno",
            "contenido": "Reforma administrativa y oficiales",
            "identificacion": "Parte 2 completa",
            "pagina_inicio": 12,
            "pagina_fin": 27,
        },
        {
            "numero": 3,
            "titulo": "Consejos",
            "contenido": "Régimen polisinodial",
            "identificacion": "Parte 3 completa",
            "pagina_inicio": 28,
            "pagina_fin": 35,
        },
    ]

    prompt = m._build_pdf_agent_prompt(
        "TABLA",
        partes[1]["identificacion"],
        2,
        3,
        _scope_handoff(),
        pdf_scope_mode="subpdf_buffered",
        nucleo_inicio=12,
        nucleo_fin=27,
        current_parte=partes[1],
        partes_segmentadas=partes,
    )

    assert "CONTRATO ESTRUCTURADO DE ALCANCE DE LA PARTE" in prompt
    assert "FRONTERAS NEGATIVAS (NO DESARROLLAR)" in prompt
    assert "Parte 1/3 (anterior)" in prompt
    assert "Parte 3/3 (siguiente)" in prompt
    assert "Reforma administrativa y oficiales" in prompt
    assert "Teorización política previa" in prompt
    assert "Régimen polisinodial" in prompt


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
        source_path="document.pdf",
        content_page_set=frozenset({3, 1}),
        api_key="mistral-test-key",
        engine="mistral-native",
    )

    assert captured["expected_page_numbers"] == (1, 3)
    assert context.source_pdf_path == "document.pdf"
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


def test_build_subpart_validation_context_uses_cross_part_neighbors():
    import main as m

    partes_segmentadas = [
        {
            "numero": 1,
            "titulo": "Parte 1",
            "contenido": "Contenido parte 1",
            "subpartes": [
                {"numero_subparte": 1, "titulo": "1.1", "contenido": "Uno uno"},
                {"numero_subparte": 2, "titulo": "1.2", "contenido": "Uno dos"},
            ],
        },
        {
            "numero": 2,
            "titulo": "Parte 2",
            "contenido": "Contenido parte 2",
            "subpartes": [
                {"numero_subparte": 1, "titulo": "2.1", "contenido": "Dos uno"},
                {"numero_subparte": 2, "titulo": "2.2", "contenido": "Dos dos"},
            ],
        },
    ]

    context = m._build_subpart_validation_context(
        partes_segmentadas=partes_segmentadas,
        current_parte=partes_segmentadas[1],
        subpart_idx=0,
    )

    assert context.scope_kind == "subpart"
    assert context.current.title == "2.1"
    assert context.parent is not None
    assert context.parent.title == "Parte 2"
    assert context.previous_neighbor is not None
    assert context.previous_neighbor.title == "1.2"
    assert context.next_neighbor is not None
    assert context.next_neighbor.title == "2.2"


def test_build_part_validation_context_for_fallback_uses_neighbor_parts():
    import main as m

    partes_segmentadas = [
        {"numero": 1, "titulo": "Parte 1", "contenido": "A"},
        {"numero": 2, "titulo": "Parte 2", "contenido": "B"},
        {"numero": 3, "titulo": "Parte 3", "contenido": "C"},
    ]

    context = m._build_part_validation_context(
        partes_segmentadas=partes_segmentadas,
        current_parte=partes_segmentadas[1],
    )

    assert context.scope_kind == "part"
    assert context.current.title == "Parte 2"
    assert context.previous_neighbor is not None
    assert context.previous_neighbor.title == "Parte 1"
    assert context.next_neighbor is not None
    assert context.next_neighbor.title == "Parte 3"
