from __future__ import annotations

import json
from types import SimpleNamespace


def _usage():
    return SimpleNamespace(
        prompt_token_count=10,
        candidates_token_count=5,
        thoughts_token_count=2,
        total_token_count=17,
    )


def test_run_resources_ds_uses_tavily_tool_and_max_reasoning(monkeypatch):
    from backend.agents import resources

    captured: dict = {}

    def _fake_call_deepseek_chat(**kwargs):
        captured.update(kwargs)
        return (
            {
                "titulo_mapa": "Mapa",
                "vision_general": "Visión",
                "ejes_tematicos": [],
                "nota_de_integridad": "Verificado con búsqueda web.",
            },
            _usage(),
        )

    monkeypatch.setattr(resources, "call_deepseek_chat", _fake_call_deepseek_chat)

    result, usage = resources.run_resources_ds(
        api_key="sk-ds-test",
        tavily_api_key="tvly-test",
        source_text="<pagina_1>\nContenido base\n</pagina_1>",
        identificacion="Parte 1",
    )

    assert result["titulo_mapa"] == "Mapa"
    assert usage.total_token_count == 17
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["reasoning_effort"] == "max"
    assert captured["response_format"] == "json_object"
    assert captured["tools"][0]["function"]["name"] == "tavily_search"
    assert "tavily_search" in captured["tool_handlers"]
    assert captured["max_tool_rounds"] == resources.DEEPSEEK_RESOURCES_MAX_TOOL_ROUNDS == 8
    assert "titulo_mapa" in captured["json_retry_instruction"]
    assert "<pagina_1>" in captured["messages"][0]["content"]
    assert "hasta 8 rondas de búsqueda web" in captured["messages"][0]["content"]
    assert "tavily_search" in captured["system_prompt"]


def test_run_recorrido_ds_uses_deepseek_direct(monkeypatch):
    from backend.agents import recorrido

    captured: dict = {}

    def _fake_call_deepseek_chat(**kwargs):
        captured.update(kwargs)
        return (
            {
                "recorrido_anotado": [],
                "sintesis_de_cobertura": {
                    "secciones_procesadas": "Todo",
                    "alcance": "Parte 1",
                    "contenido_excluido": "Ninguno",
                    "idioma_original": "castellano",
                    "observaciones_globales": "Completo",
                },
            },
            _usage(),
        )

    monkeypatch.setattr(recorrido, "call_deepseek_chat", _fake_call_deepseek_chat)

    result, usage = recorrido.run_recorrido_ds(
        api_key="sk-ds-test",
        source_text="<pagina_1>\nContenido base\n</pagina_1>",
        identificacion="Parte 1",
    )

    assert result["sintesis_de_cobertura"]["alcance"] == "Parte 1"
    assert usage.total_token_count == 17
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["reasoning_effort"] == "max"
    assert captured["response_format"] == "json_object"
    assert "recorrido_anotado" in captured["json_retry_instruction"]
    assert "<pagina_N>" in captured["system_prompt"]


def test_run_segmentador_ds_uses_deepseek_direct(monkeypatch):
    from backend.agents import segmentador

    captured: dict = {}

    def _fake_call_deepseek_chat_full(**kwargs):
        captured.update(kwargs)
        content = {
            "analisis_texto": "Documento OCR",
            "decision_num_partes": 1,
            "decision_justificacion": "Una unidad",
            "partes": [],
            "consideraciones_estudiante": "Orden natural",
        }
        return SimpleNamespace(
            content=content,
            usage=_usage(),
            assistant_message=SimpleNamespace(content=json.dumps(content), tool_calls=None),
        )

    monkeypatch.setattr(segmentador, "call_deepseek_chat_full", _fake_call_deepseek_chat_full)

    result, usage, conversation = segmentador.run_segmentador_ds(
        api_key="sk-ds-test",
        source_text="<pagina_1>\nContenido base\n</pagina_1>",
        description="Procesar todo",
        source_kind="pdf",
    )

    assert result["decision_num_partes"] == 1
    assert usage.total_token_count == 17
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["reasoning_effort"] == "max"
    assert captured["response_format"] == "json_object"
    assert '"partes"' in captured["json_retry_instruction"]
    assert "<pagina_N>" in captured["system_prompt"]
    # Conversation seed: user turn with the source, then the raw assistant turn for replay.
    assert conversation[0]["role"] == "user"
    assert "<pagina_1>" in conversation[0]["content"]
    assert conversation[-1]["role"] == "assistant"


def test_run_page_classifier_ds_returns_content_pages(monkeypatch):
    from backend.agents import page_classifier

    captured: dict = {}

    def _fake_call_deepseek_chat(**kwargs):
        captured.update(kwargs)
        return (
            {
                "total_paginas": 4,
                "rangos_contenido": [{"inicio": 2, "fin": 4}],
                "rangos_no_contenido": [{"inicio": 1, "fin": 1, "razon": "portada"}],
            },
            _usage(),
        )

    monkeypatch.setattr(page_classifier, "call_deepseek_chat", _fake_call_deepseek_chat)

    pages, usage, raw = page_classifier.run_page_classifier_ds(
        api_key="sk-ds-test",
        source_text="<pagina_1>\nPortada\n</pagina_1>\n<pagina_2>\nContenido\n</pagina_2>",
        total_pages=4,
    )

    assert pages == frozenset({2, 3, 4})
    assert raw["total_paginas"] == 4
    assert usage.total_token_count == 17
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["reasoning_effort"] == "max"
    assert captured["response_format"] == "json_object"
    assert "rangos_contenido" in captured["json_retry_instruction"]
    assert "<pagina_N>" in captured["system_prompt"]
