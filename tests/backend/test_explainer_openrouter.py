from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.agents import explainer_openrouter as module
from backend.openrouter_client import OpenRouterError


def _usage() -> SimpleNamespace:
    return SimpleNamespace(
        prompt_token_count=17,
        candidates_token_count=31,
        thoughts_token_count=0,
        tool_use_prompt_token_count=0,
        total_token_count=48,
    )


def _write_text_source(content: str = "Contenido de prueba.") -> str:
    base_dir = Path.cwd() / "test_output" / "pytest-openrouter"
    base_dir.mkdir(parents=True, exist_ok=True)
    source = base_dir / f"{uuid4().hex}.txt"
    source.write_text(content, encoding="utf-8")
    return str(source)


def test_run_explainer_or_returns_structured_payload_and_normalizes_connections(monkeypatch):
    source_path = _write_text_source()
    captured_call: dict = {}

    def _fake_call(**kwargs):
        captured_call.update(kwargs)
        return (
            {
                "introduccion": "  Introducción de prueba.  ",
                "desarrollo": [
                    {
                        "titulo_seccion": "  Marco general  ",
                        "explicacion_introductoria": "  Apertura de la sección. ",
                        "subsecciones": [
                            {
                                "titulo_subseccion": " Idea clave ",
                                "explicacion_detallada": " Desarrollo exhaustivo. ",
                            }
                        ],
                    }
                ],
                "conclusion": "  Cierre final. ",
            },
            _usage(),
        )

    monkeypatch.setattr(module, "call_openrouter_chat", _fake_call)

    result, usage = module.run_explainer_or(
        source_path=source_path,
        identificacion="Prompt de prueba",
        mime_type="text/plain",
        api_key="sk-or-v1-test",
    )

    assert usage.total_token_count == 48
    assert result == {
        "introduccion": "Introducción de prueba.",
        "desarrollo": [
            {
                "titulo_seccion": "Marco general",
                "explicacion_introductoria": "Apertura de la sección.",
                "subsecciones": [
                    {
                        "titulo_subseccion": "Idea clave",
                        "explicacion_detallada": "Desarrollo exhaustivo.",
                    }
                ],
            }
        ],
        "conclusion": "Cierre final.",
        "conexiones_contextuales": [],
    }
    assert captured_call["response_format"] == "json_object"
    assert captured_call["enable_response_healing"] is True


def test_run_explainer_or_uses_json_schema_for_supported_models(monkeypatch):
    source_path = _write_text_source()
    captured_call: dict = {}

    def _fake_call(**kwargs):
        captured_call.update(kwargs)
        return (
            {
                "introduccion": "Introducción de prueba.",
                "desarrollo": [
                    {
                        "titulo_seccion": "Marco general",
                        "explicacion_introductoria": "Apertura de la sección.",
                        "subsecciones": [
                            {
                                "titulo_subseccion": "Idea clave",
                                "explicacion_detallada": "Desarrollo exhaustivo.",
                            }
                        ],
                    }
                ],
                "conclusion": "Cierre final.",
                "conexiones_contextuales": [],
            },
            _usage(),
        )

    monkeypatch.setattr(module, "call_openrouter_chat", _fake_call)

    result, usage = module.run_explainer_or(
        source_path=source_path,
        identificacion="Prompt de prueba",
        model="openai/gpt-5.4-nano",
        mime_type="text/plain",
        api_key="sk-or-v1-test",
    )

    assert usage.total_token_count == 48
    assert result["introduccion"] == "Introducción de prueba."
    assert captured_call["response_format"].name == "full_explainer"
    assert captured_call["response_format"].strict is True
    assert captured_call["response_format"].schema["type"] == "object"


def test_run_subpart_explainer_or_returns_validated_desarrollo(monkeypatch):
    source_path = _write_text_source()

    monkeypatch.setattr(
        module,
        "call_openrouter_chat",
        lambda **kwargs: (
            {
                "desarrollo": [
                    {
                        "titulo_seccion": "Bloque temático",
                        "explicacion_introductoria": "Contexto del bloque.",
                        "subsecciones": [
                            {
                                "titulo_subseccion": "Detalle",
                                "explicacion_detallada": "Explicación completa.",
                            }
                        ],
                    }
                ]
            },
            _usage(),
        ),
    )

    result, _ = module.run_subpart_explainer_or(
        source_path=source_path,
        identificacion="Prompt de prueba",
        mime_type="text/plain",
        api_key="sk-or-v1-test",
    )

    assert result == {
        "desarrollo": [
            {
                "titulo_seccion": "Bloque temático",
                "explicacion_introductoria": "Contexto del bloque.",
                "subsecciones": [
                    {
                        "titulo_subseccion": "Detalle",
                        "explicacion_detallada": "Explicación completa.",
                    }
                ],
            }
        ]
    }


def test_run_subpart_explainer_or_uses_json_schema_for_supported_models(monkeypatch):
    source_path = _write_text_source()
    captured_call: dict = {}

    def _fake_call(**kwargs):
        captured_call.update(kwargs)
        return (
            {
                "desarrollo": [
                    {
                        "titulo_seccion": "Bloque temático",
                        "explicacion_introductoria": "Contexto del bloque.",
                        "subsecciones": [
                            {
                                "titulo_subseccion": "Detalle",
                                "explicacion_detallada": "Explicación completa.",
                            }
                        ],
                    }
                ]
            },
            _usage(),
        )

    monkeypatch.setattr(module, "call_openrouter_chat", _fake_call)

    result, usage = module.run_subpart_explainer_or(
        source_path=source_path,
        identificacion="Prompt de prueba",
        model="openai/gpt-5.4-nano",
        mime_type="text/plain",
        api_key="sk-or-v1-test",
    )

    assert usage.total_token_count == 48
    assert result["desarrollo"][0]["titulo_seccion"] == "Bloque temático"
    assert captured_call["response_format"].name == "subpart_explainer"
    assert captured_call["response_format"].strict is True


def test_run_subpart_explainer_or_rejects_invalid_payload(monkeypatch):
    source_path = _write_text_source()

    monkeypatch.setattr(
        module,
        "call_openrouter_chat",
        lambda **kwargs: (
            {
                "desarrollo": [
                    {
                        "titulo_seccion": "Bloque temático",
                        "explicacion_introductoria": "Contexto del bloque.",
                        "subsecciones": [
                            {
                                "titulo_subseccion": "Detalle",
                            }
                        ],
                    }
                ]
            },
            _usage(),
        ),
    )

    with pytest.raises(OpenRouterError, match="explicacion_detallada"):
        module.run_subpart_explainer_or(
            source_path=source_path,
            identificacion="Prompt de prueba",
            mime_type="text/plain",
            api_key="sk-or-v1-test",
        )


def test_run_subpart_explainer_or_retries_on_payload_validation_error(monkeypatch):
    source_path = _write_text_source()
    attempts = {"count": 0}

    def _fake_call(**kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return (
                {
                    "desarrollo": [
                        {
                            "titulo_seccion": 123,
                            "explicacion_introductoria": "Contexto del bloque.",
                            "subsecciones": [
                                {
                                    "titulo_subseccion": "Detalle",
                                    "explicacion_detallada": "Explicación completa.",
                                }
                            ],
                        }
                    ]
                },
                _usage(),
            )
        return (
            {
                "desarrollo": [
                    {
                        "titulo_seccion": "Bloque temático",
                        "explicacion_introductoria": "Contexto del bloque.",
                        "subsecciones": [
                            {
                                "titulo_subseccion": "Detalle",
                                "explicacion_detallada": "Explicación completa.",
                            }
                        ],
                    }
                ]
            },
            _usage(),
        )

    monkeypatch.setattr(module, "call_openrouter_chat", _fake_call)

    result, usage = module.run_subpart_explainer_or(
        source_path=source_path,
        identificacion="Prompt de prueba",
        mime_type="text/plain",
        api_key="sk-or-v1-test",
    )

    assert attempts["count"] == 2
    assert usage.total_token_count == 48
    assert result["desarrollo"][0]["titulo_seccion"] == "Bloque temático"


def test_run_subpart_explainer_or_exhausts_validation_retries(monkeypatch):
    source_path = _write_text_source()
    attempts = {"count": 0}

    def _fake_call(**kwargs):
        attempts["count"] += 1
        return (
            {
                "desarrollo": [
                    {
                        "titulo_seccion": 123,
                        "explicacion_introductoria": "Contexto del bloque.",
                        "subsecciones": [
                            {
                                "titulo_subseccion": "Detalle",
                                "explicacion_detallada": "Explicación completa.",
                            }
                        ],
                    }
                ]
            },
            _usage(),
        )

    monkeypatch.setattr(module, "call_openrouter_chat", _fake_call)

    with pytest.raises(OpenRouterError, match="titulo_seccion"):
        module.run_subpart_explainer_or(
            source_path=source_path,
            identificacion="Prompt de prueba",
            mime_type="text/plain",
            api_key="sk-or-v1-test",
        )

    assert attempts["count"] == module.OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES + 1


def test_run_subpart_explainer_or_falls_back_to_text_when_pdf_parse_fails(monkeypatch):
    source_path = _write_text_source("Contenido local para fallback.")
    flow: list[str] = []

    def _fake_call(**kwargs):
        flow.append("fallback-call")
        content = kwargs["messages"][0]["content"]
        has_pdf_file = any(item.get("type") == "file" for item in content)
        if has_pdf_file:
            raise AssertionError("El fallback no debe reenviar el PDF a OpenRouter.")
        return (
            {
                "desarrollo": [
                    {
                        "titulo_seccion": "Bloque temático",
                        "explicacion_introductoria": "Contexto del bloque.",
                        "subsecciones": [
                            {
                                "titulo_subseccion": "Detalle",
                                "explicacion_detallada": "Explicación completa.",
                            }
                        ],
                    }
                ]
            },
            _usage(),
        )

    def _fake_prime_cache(**kwargs):
        flow.append("prime-cache")
        raise OpenRouterError(
            "OpenRouter devolvió HTTP 400: "
            "{\"error\":{\"message\":\"Failed to parse document.pdf\",\"code\":400}}"
        )

    monkeypatch.setattr(module, "get_or_prime_pdf_parse_cache", _fake_prime_cache)
    monkeypatch.setattr(module, "call_openrouter_chat", _fake_call)
    monkeypatch.setattr(module, "_extract_pdf_text_to_temp", lambda _: source_path)
    monkeypatch.setattr(module.os, "unlink", lambda _: None)

    result, usage = module.run_subpart_explainer_or(
        source_path=source_path,
        identificacion="Prompt de prueba",
        mime_type="application/pdf",
        api_key="sk-or-v1-test",
    )

    assert usage.total_token_count == 48
    assert result["desarrollo"][0]["titulo_seccion"] == "Bloque temático"
    assert flow == ["prime-cache", "fallback-call"]


def test_run_subpart_explainer_or_uses_fixed_grok_model_for_pdf_priming(monkeypatch):
    source_path = _write_text_source("Contenido local para priming.")
    captured_prime: dict = {}

    def _fake_prime_cache(**kwargs):
        captured_prime.update(kwargs)
        return SimpleNamespace(
            cache_hit=False,
            cache_path="cache.json",
            page_index=("cached",),
        )

    monkeypatch.setattr(module, "get_or_prime_pdf_parse_cache", _fake_prime_cache)
    monkeypatch.setattr(
        module,
        "render_pdf_page_subset_to_text",
        lambda **kwargs: "— Página 21 / 143 —\nTexto OCR de la página 21.",
    )
    monkeypatch.setattr(
        module,
        "call_openrouter_chat",
        lambda **kwargs: (
            {
                "desarrollo": [
                    {
                        "titulo_seccion": "Bloque temático",
                        "explicacion_introductoria": "Contexto del bloque.",
                        "subsecciones": [
                            {
                                "titulo_subseccion": "Detalle",
                                "explicacion_detallada": "Explicación completa.",
                            }
                        ],
                    }
                ]
            },
            _usage(),
        ),
    )

    module.run_subpart_explainer_or(
        source_path=source_path,
        identificacion="Prompt de prueba",
        model="minimax/minimax-m2.7",
        mime_type="application/pdf",
        api_key="sk-or-v1-test",
        page_numbers=(21,),
    )

    assert captured_prime["model"] == module.OPENROUTER_PDF_PRIMING_MODEL
    assert captured_prime["engine"] == module.OPENROUTER_PDF_PARSER_ENGINE


def test_run_subpart_explainer_or_retries_pdf_priming_with_gemini_fallback_model(monkeypatch):
    source_path = _write_text_source("Contenido local para priming con fallback.")
    priming_models: list[str] = []

    def _fake_prime_cache(**kwargs):
        priming_models.append(kwargs["model"])
        if kwargs["model"] == module.OPENROUTER_PDF_PRIMING_MODEL:
            raise OpenRouterError(
                "OpenRouter devolvió HTTP 400: "
                "{\"error\":{\"message\":\"Failed to parse document.pdf\",\"code\":400}}"
            )
        return SimpleNamespace(
            cache_hit=False,
            cache_path="cache.json",
            page_index=("cached",),
            cached_page_numbers=(21,),
            assistant_message=None,
        )

    monkeypatch.setattr(module, "get_or_prime_pdf_parse_cache", _fake_prime_cache)
    monkeypatch.setattr(
        module,
        "render_pdf_page_subset_to_text",
        lambda **kwargs: "— Página 21 / 143 —\nTexto OCR de la página 21.",
    )
    monkeypatch.setattr(
        module,
        "call_openrouter_chat",
        lambda **kwargs: (
            {
                "desarrollo": [
                    {
                        "titulo_seccion": "Bloque temático",
                        "explicacion_introductoria": "Contexto del bloque.",
                        "subsecciones": [
                            {
                                "titulo_subseccion": "Detalle",
                                "explicacion_detallada": "Explicación completa.",
                            }
                        ],
                    }
                ]
            },
            _usage(),
        ),
    )

    result, usage = module.run_subpart_explainer_or(
        source_path=source_path,
        identificacion="Prompt de prueba",
        model="minimax/minimax-m2.7",
        mime_type="application/pdf",
        api_key="sk-or-v1-test",
        page_numbers=(21,),
    )

    assert usage.total_token_count == 48
    assert result["desarrollo"][0]["titulo_seccion"] == "Bloque temático"
    assert priming_models == [
        module.OPENROUTER_PDF_PRIMING_MODEL,
        module.OPENROUTER_PDF_PRIMING_FALLBACK_MODEL,
    ]


def test_run_subpart_explainer_or_uses_cached_page_subset_without_resending_pdf(monkeypatch):
    source_path = _write_text_source("Contenido local para subset OCR.")
    captured_call: dict = {}

    monkeypatch.setattr(
        module,
        "render_pdf_page_subset_to_text",
        lambda **kwargs: "— Página 13 / 143 —\nTexto OCR de la página 13.",
    )
    monkeypatch.setattr(
        module,
        "get_or_prime_pdf_parse_cache",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("No debe reparsear si ya hay cache_entry")),
    )

    def _fake_call(**kwargs):
        captured_call.update(kwargs)
        assert kwargs["plugins"] is None
        message_content = kwargs["messages"][0]["content"]
        assert isinstance(message_content, list)
        assert all(item.get("type") != "file" for item in message_content)
        assert "Texto OCR de la página 13." in message_content[0]["text"]
        return (
            {
                "desarrollo": [
                    {
                        "titulo_seccion": "Bloque temático",
                        "explicacion_introductoria": "Contexto del bloque.",
                        "subsecciones": [
                            {
                                "titulo_subseccion": "Detalle",
                                "explicacion_detallada": "Explicación completa.",
                            }
                        ],
                    }
                ]
            },
            _usage(),
        )

    monkeypatch.setattr(module, "call_openrouter_chat", _fake_call)

    fake_cache_entry = SimpleNamespace(
        page_index=("cached",),
        cache_hit=True,
        cache_path="cache.json",
    )
    result, usage = module.run_subpart_explainer_or(
        source_path=source_path,
        identificacion="Prompt de prueba",
        mime_type="application/pdf",
        api_key="sk-or-v1-test",
        pdf_cache_entry=fake_cache_entry,
        page_numbers=(13,),
    )

    assert usage.total_token_count == 48
    assert result["desarrollo"][0]["titulo_seccion"] == "Bloque temático"
    assert captured_call["response_format"] == "json_object"


def test_run_subpart_explainer_or_uses_all_cached_pages_when_no_subset_is_given(monkeypatch):
    source_path = _write_text_source("Contenido local para OCR completo cacheado.")
    captured_call: dict = {}

    monkeypatch.setattr(
        module,
        "render_pdf_page_subset_to_text",
        lambda **kwargs: (
            "— Página 2 / 143 —\nTexto OCR de la página 2.\n\n"
            "— Página 3 / 143 —\nTexto OCR de la página 3."
        ),
    )
    monkeypatch.setattr(
        module,
        "build_messages_with_cached_pdf_annotations",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("No debe reenviar annotations si ya hay page_index")),
    )

    def _fake_call(**kwargs):
        captured_call.update(kwargs)
        message_content = kwargs["messages"][0]["content"]
        assert "Texto OCR de la página 2." in message_content[0]["text"]
        assert "Texto OCR de la página 3." in message_content[0]["text"]
        return (
            {
                "desarrollo": [
                    {
                        "titulo_seccion": "Bloque temático",
                        "explicacion_introductoria": "Contexto del bloque.",
                        "subsecciones": [
                            {
                                "titulo_subseccion": "Detalle",
                                "explicacion_detallada": "Explicación completa.",
                            }
                        ],
                    }
                ]
            },
            _usage(),
        )

    monkeypatch.setattr(module, "call_openrouter_chat", _fake_call)

    fake_cache_entry = SimpleNamespace(
        page_index=(
            SimpleNamespace(page_number=2, content_parts=({"type": "text", "text": "p2"},)),
            SimpleNamespace(page_number=3, content_parts=({"type": "text", "text": "p3"},)),
        ),
        cached_page_numbers=(2, 3),
        cache_hit=True,
        cache_path="cache.json",
        assistant_message=None,
    )
    result, usage = module.run_subpart_explainer_or(
        source_path=source_path,
        identificacion="Prompt de prueba",
        mime_type="application/pdf",
        api_key="sk-or-v1-test",
        pdf_cache_entry=fake_cache_entry,
    )

    assert usage.total_token_count == 48
    assert result["desarrollo"][0]["titulo_seccion"] == "Bloque temático"
    assert captured_call["response_format"] == "json_object"
