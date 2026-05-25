from __future__ import annotations

from types import SimpleNamespace


def _usage():
    return SimpleNamespace(
        prompt_token_count=10,
        candidates_token_count=5,
        thoughts_token_count=0,
        total_token_count=15,
        cost_usd=0.00001,
    )


def test_run_resources_or_uses_deepseek_provider_and_web_search_auto(monkeypatch):
    from backend.agents import resources

    captured: dict = {}

    def _fake_call_openrouter_chat(**kwargs):
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

    monkeypatch.setattr(resources, "call_openrouter_chat", _fake_call_openrouter_chat)

    result, usage = resources.run_resources_or(
        api_key="sk-or-v1-test",
        source_text="<pagina_1>\nContenido base\n</pagina_1>",
        identificacion="Parte 1",
    )

    assert result["titulo_mapa"] == "Mapa"
    assert usage.total_token_count == 15
    assert captured["model"] == "deepseek/deepseek-v4-flash"
    assert captured["provider"] == {"order": ["deepseek"], "allow_fallbacks": False}
    assert captured["response_format"] == "json_object"
    assert "titulo_mapa" in captured["json_retry_instruction"]
    assert "ejes_tematicos" in captured["json_retry_instruction"]
    assert captured["tools"] == [
        {
            "type": "openrouter:web_search",
            "parameters": {
                "engine": "auto",
                "max_results": 5,
                "max_total_results": 20,
                "search_context_size": "high",
            },
        }
    ]


def test_run_recorrido_or_uses_deepseek_provider(monkeypatch):
    from backend.agents import recorrido

    captured: dict = {}

    def _fake_call_openrouter_chat(**kwargs):
        captured.update(kwargs)
        return (
            {
                "recorrido_anotado": [
                    {
                        "ubicacion": "p. 1",
                        "tipo_entrada": "cita_anotada",
                        "cita_textual": "Texto",
                        "traduccion": "",
                        "apuntes_traductologicos": "",
                        "anotacion": "Anotación",
                    }
                ],
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

    monkeypatch.setattr(recorrido, "call_openrouter_chat", _fake_call_openrouter_chat)

    result, usage = recorrido.run_recorrido_or(
        api_key="sk-or-v1-test",
        source_text="<pagina_1>\nContenido base\n</pagina_1>",
        identificacion="Parte 1",
    )

    assert result["recorrido_anotado"][0]["anotacion"] == "Anotación"
    assert usage.total_token_count == 15
    assert captured["model"] == "deepseek/deepseek-v4-flash"
    assert captured["provider"] == {"order": ["deepseek"], "allow_fallbacks": False}
    assert "recorrido_anotado" in captured["json_retry_instruction"]
    assert "sintesis_de_cobertura" in captured["json_retry_instruction"]
    assert "openrouter:web_search" not in str(captured.get("tools"))
    assert "<pagina_1>" in captured["messages"][0]["content"]
    assert "<pagina_N>" in captured["system_prompt"]


def test_run_segmentador_or_uses_deepseek_provider(monkeypatch):
    from backend.agents import segmentador

    captured: dict = {}

    def _fake_call_openrouter_chat(**kwargs):
        captured.update(kwargs)
        return (
            {
                "analisis_texto": "Documento OCR",
                "decision_num_partes": 1,
                "decision_justificacion": "Una unidad",
                "partes": [
                    {
                        "numero": 1,
                        "titulo": "Parte",
                        "contenido": "Contenido",
                        "identificacion": "Páginas 1-2",
                        "pagina_inicio": 1,
                        "pagina_fin": 2,
                        "extension_estimada": "media",
                        "complejidad": "media",
                        "expansion_prevista": "alta",
                        "subpartes": [],
                    }
                ],
                "consideraciones_estudiante": "Orden natural",
            },
            _usage(),
        )

    monkeypatch.setattr(segmentador, "call_openrouter_chat", _fake_call_openrouter_chat)

    result, usage = segmentador.run_segmentador_or(
        api_key="sk-or-v1-test",
        source_text="<pagina_1>\nContenido base\n</pagina_1>",
        description="Procesar todo",
        source_kind="pdf",
    )

    assert result["partes"][0]["pagina_inicio"] == 1
    assert usage.total_token_count == 15
    assert captured["model"] == "deepseek/deepseek-v4-flash"
    assert captured["provider"] == {"order": ["deepseek"], "allow_fallbacks": False}
    assert "objeto JSON raíz" in captured["json_retry_instruction"]
    assert '"partes"' in captured["json_retry_instruction"]
    assert '"pagina_inicio"' in captured["json_retry_instruction"]
    assert "Devuelve exactamente el objeto JSON" in captured["messages"][0]["content"]
    assert "<pagina_1>" in captured["messages"][0]["content"]
    assert "<pagina_N>" in captured["system_prompt"]


def test_run_page_classifier_or_returns_content_pages(monkeypatch):
    from backend.agents import page_classifier

    captured: dict = {}

    def _fake_call_openrouter_chat(**kwargs):
        captured.update(kwargs)
        return (
            {
                "total_paginas": 4,
                "rangos_contenido": [{"inicio": 2, "fin": 4}],
                "rangos_no_contenido": [{"inicio": 1, "fin": 1, "razon": "portada"}],
            },
            _usage(),
        )

    monkeypatch.setattr(page_classifier, "call_openrouter_chat", _fake_call_openrouter_chat)

    pages, usage, raw = page_classifier.run_page_classifier_or(
        api_key="sk-or-v1-test",
        source_text="<pagina_1>\nPortada\n</pagina_1>\n<pagina_2>\nContenido\n</pagina_2>",
        total_pages=4,
    )

    assert pages == frozenset({2, 3, 4})
    assert raw["total_paginas"] == 4
    assert usage.total_token_count == 15
    assert captured["model"] == "deepseek/deepseek-v4-flash"
    assert captured["provider"] == {"order": ["deepseek"], "allow_fallbacks": False}
    assert "total_paginas" in captured["json_retry_instruction"]
    assert "rangos_contenido" in captured["json_retry_instruction"]
    assert "<pagina_1>" in captured["messages"][0]["content"]
    assert "<pagina_N>" in captured["system_prompt"]
