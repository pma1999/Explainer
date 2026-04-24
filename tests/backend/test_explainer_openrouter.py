from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.agents import explainer_openrouter as module
from backend.openrouter_client import OpenRouterError
from backend.pdf_ocr_cache import PdfOcrCacheEntry, PdfOcrParsedPage


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


def test_default_openrouter_explainer_model_is_deepseek_v4_flash():
    assert module.OPENROUTER_MODEL_AGENTS == "deepseek/deepseek-v4-flash"


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




def test_run_subpart_explainer_or_uses_cached_mistral_page_subset(monkeypatch):
    source_path = _write_text_source()
    captured: dict = {}

    def _fake_chat(**kwargs):
        captured.update(kwargs)
        return (
            {
                "desarrollo": [
                    {
                        "titulo_seccion": "Bloque",
                        "explicacion_introductoria": "Contexto",
                        "subsecciones": [
                            {
                                "titulo_subseccion": "Detalle",
                                "explicacion_detallada": "Explicación",
                            }
                        ],
                    }
                ]
            },
            _usage(),
        )

    monkeypatch.setattr(module, "call_openrouter_chat", _fake_chat)

    cache_entry = PdfOcrCacheEntry(
        source_sha256="sha",
        engine="mistral-native",
        cache_path="cache.json",
        cache_hit=True,
        expected_page_numbers=(2,),
        cached_page_numbers=(2,),
        page_index=(PdfOcrParsedPage(page_number=2, markdown="Texto OCR página 2"),),
    )

    module.run_subpart_explainer_or(
        source_path=source_path,
        identificacion="Prompt de prueba",
        mime_type="application/pdf",
        api_key="sk-or-v1-test",
        pdf_cache_entry=cache_entry,
        page_numbers=(2,),
    )

    inline_text = captured["messages"][0]["content"][0]["text"]
    assert "Texto OCR página 2" in inline_text
    assert "Prompt de prueba" in inline_text
