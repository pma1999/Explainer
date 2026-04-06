"""Unit tests for _build_content_pages_prefix in main."""

from __future__ import annotations

import importlib
import sys


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
