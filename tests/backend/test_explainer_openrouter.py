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


def test_run_subpart_explainer_or_retries_when_desarrollo_is_empty(monkeypatch):
    source_path = _write_text_source()
    calls: list[dict] = []

    responses = [
        (
            {"desarrollo": []},
            _usage(),
        ),
        (
            {
                "desarrollo": [
                    {
                        "titulo_seccion": "Sección válida",
                        "explicacion_introductoria": "Contexto",
                        "subsecciones": [
                            {
                                "titulo_subseccion": "Sub",
                                "explicacion_detallada": "Detalle",
                            }
                        ],
                    }
                ]
            },
            _usage(),
        ),
    ]

    def _fake_call(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    monkeypatch.setattr(module, "call_openrouter_chat", _fake_call)
    monkeypatch.setattr(module.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.random, "uniform", lambda *_args, **_kwargs: 0.0)

    result, usage = module.run_subpart_explainer_or(
        source_path=source_path,
        identificacion="Prompt de prueba",
        mime_type="text/plain",
        api_key="sk-or-v1-test",
    )

    assert len(calls) == 2
    assert usage.prompt_token_count == 34
    assert usage.candidates_token_count == 62
    retry_messages = calls[1]["messages"]
    assert any(
        isinstance(item, dict)
        and item.get("role") == "user"
        and "incumple el contrato JSON" in str(item.get("content"))
        for item in retry_messages
    )
    assert result["desarrollo"][0]["titulo_seccion"] == "Sección válida"


def test_run_subpart_explainer_or_raises_after_exhausting_validation_attempts(monkeypatch):
    source_path = _write_text_source()

    monkeypatch.setattr(
        module,
        "call_openrouter_chat",
        lambda **kwargs: ({"desarrollo": []}, _usage()),
    )
    monkeypatch.setattr(module.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.random, "uniform", lambda *_args, **_kwargs: 0.0)

    with pytest.raises(OpenRouterError, match="falló tras"):
        module.run_subpart_explainer_or(
            source_path=source_path,
            identificacion="Prompt de prueba",
            mime_type="text/plain",
            api_key="sk-or-v1-test",
        )
