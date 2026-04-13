"""Schema tests for structured subpart scope contracts."""

from __future__ import annotations

from google.genai import types as genai_types


def _subparte_schema():
    from backend.agents.segmentador import RESPONSE_SCHEMA

    partes_schema = RESPONSE_SCHEMA.properties["partes"]
    subpartes_schema = partes_schema.items.properties["subpartes"]
    return subpartes_schema.items


def test_delimitacion_explainer_is_required():
    schema = _subparte_schema()
    assert "delimitacion_explainer" in schema.required


def test_delimitacion_explainer_shape():
    schema = _subparte_schema()
    contract = schema.properties["delimitacion_explainer"]

    assert contract.type == genai_types.Type.OBJECT
    assert set(contract.required) == {"inicio", "fin", "transicion_compartida"}

    inicio = contract.properties["inicio"]
    assert inicio.type == genai_types.Type.OBJECT
    assert set(inicio.required) == {"encabezado", "ancla_texto"}

    fin = contract.properties["fin"]
    assert fin.type == genai_types.Type.OBJECT
    assert set(fin.required) == {"ancla_texto", "encabezado_siguiente_excluido"}

    transition = contract.properties["transicion_compartida"]
    assert transition.type == genai_types.Type.OBJECT
    assert set(transition.required) == {
        "hay_transicion",
        "pagina",
        "hasta_texto_inclusive",
        "desde_texto_inclusive",
    }
    assert transition.properties["hay_transicion"].type == genai_types.Type.BOOLEAN
    assert transition.properties["pagina"].type == genai_types.Type.INTEGER
