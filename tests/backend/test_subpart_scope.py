"""Tests for subpart scope helper blocks."""

from __future__ import annotations


def _sp(num: int, title: str, content: str, temas: list[str], pi: int, pf: int, next_heading: str = "") -> dict:
    return {
        "numero_subparte": num,
        "titulo": title,
        "contenido": content,
        "temas_cubiertos": temas,
        "pagina_inicio": pi,
        "pagina_fin": pf,
        "delimitacion_explainer": {
            "inicio": {"encabezado": f"{num}.0 Inicio", "ancla_texto": f"Texto inicial {num}"},
            "fin": {
                "ancla_texto": f"Texto final {num}",
                "encabezado_siguiente_excluido": next_heading,
            },
            "transicion_compartida": {
                "hay_transicion": num == 2,
                "pagina": 19 if num == 2 else 0,
                "hasta_texto_inclusive": "última frase previa" if num == 2 else "",
                "desde_texto_inclusive": "nuevo encabezado" if num == 2 else "",
            },
        },
    }


def test_positive_scope_block_includes_pages_anchors_and_transition():
    from backend.subpart_scope import build_subpart_scope_contract_block

    text = build_subpart_scope_contract_block(
        _sp(2, "Cambios estructurales", "Reforma administrativa", ["Burocracia"], 19, 22, "2.4 Consejos")
    )

    assert "CONTRATO ESTRUCTURADO DE ALCANCE DE LA SUBPARTE" in text
    assert "Páginas núcleo: 19-22" in text
    assert "Texto inicial 2" in text
    assert "Texto final 2" in text
    assert "2.4 Consejos" in text
    assert "PÁGINA COMPARTIDA" in text


def test_negative_scope_block_lists_previous_and_next_neighbors():
    from backend.subpart_scope import build_subpart_negative_scope_block

    subpartes = [
        _sp(1, "Precursores", "Tomás de Aquino y Maquiavelo", ["Tomás de Aquino", "Maquiavelo"], 18, 19),
        _sp(2, "Cambios estructurales", "Reforma administrativa", ["Burocracia"], 19, 22, "2.4 Consejos"),
        _sp(3, "Consejos", "Régimen polisinodial", ["Consejos", "Audiencias"], 23, 27),
    ]

    text = build_subpart_negative_scope_block(subpartes[1], subpartes)

    assert "FRONTERAS NEGATIVAS (NO DESARROLLAR)" in text
    assert "Subparte 1 (anterior)" in text
    assert "Subparte 3 (siguiente)" in text
    assert "Tomás de Aquino" in text
    assert "Consejos" in text


def test_negative_scope_block_uses_neighbor_content_and_topics():
    from backend.subpart_scope import build_subpart_negative_scope_block

    subpartes = [
        _sp(1, "Anterior", "Contenido anterior", ["Tema anterior"], 10, 12),
        _sp(2, "Actual", "Contenido actual", ["Tema actual"], 13, 15),
    ]

    text = build_subpart_negative_scope_block(subpartes[1], subpartes)

    assert "Contenido anterior" in text
    assert "Tema anterior" in text
    assert "Tema actual" not in text
