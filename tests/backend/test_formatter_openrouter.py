"""Unit tests for OpenRouter formatter path (no real API calls)."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.agents.formatter import (
    FORMATTER_OPENROUTER_MODEL,
    OPENROUTER_JSON_RETRY_INSTRUCTION,
    _format_text_or_sync,
    format_explainer_content_or,
)


MAX_REASONING = {"effort": "xhigh", "exclude": True}


def _usage(*, cost_usd: float | None = 0.00001):
    return SimpleNamespace(
        prompt_token_count=10,
        candidates_token_count=5,
        thoughts_token_count=0,
        total_token_count=15,
        cost_usd=cost_usd,
    )


def test_format_text_or_sync_uses_deepseek_and_json_contract(monkeypatch):
    captured: dict = {}

    def fake_call(**kwargs):
        captured.update(kwargs)
        return {"markdown": "**Hola** mundo"}, _usage()

    monkeypatch.setattr(
        "backend.agents.formatter.call_openrouter_chat",
        fake_call,
    )

    out, usage = _format_text_or_sync("sk-or-test", "Hola mundo", "Sección 1")

    assert out == "**Hola** mundo"
    assert usage is not None
    assert captured["model"] == FORMATTER_OPENROUTER_MODEL
    assert captured["model"] == "deepseek/deepseek-v4-flash"
    assert captured["provider"] == {"order": ["deepseek"], "allow_fallbacks": False}
    assert captured["reasoning"] == MAX_REASONING
    assert captured["response_format"] == "json_object"
    assert captured["enable_response_healing"] is True
    assert captured["temperature"] == 0.1
    assert "markdown" in captured["json_retry_instruction"]
    assert "[Contexto del apartado: Sección 1]" in captured["messages"][0]["content"]


def test_format_text_or_sync_fail_safe_on_invalid_json(monkeypatch):
    monkeypatch.setattr(
        "backend.agents.formatter.call_openrouter_chat",
        lambda **kwargs: ({"markdown": "   "}, _usage()),
    )

    original = "Texto original intacto."
    out, usage = _format_text_or_sync("sk-or-test", original)

    assert out == original
    assert usage is not None


def test_format_text_or_sync_fail_safe_on_openrouter_error(monkeypatch):
    from backend.openrouter_client import OpenRouterError

    def raise_error(**kwargs):
        raise OpenRouterError("fallo simulado")

    monkeypatch.setattr("backend.agents.formatter.call_openrouter_chat", raise_error)

    original = "Conservar si falla."
    out, usage = _format_text_or_sync("sk-or-test", original)

    assert out == original
    assert usage is None


@pytest.mark.asyncio
async def test_format_explainer_content_or_parallel_and_cost(monkeypatch):
    call_count = 0

    def fake_call(**kwargs):
        nonlocal call_count
        call_count += 1
        text = kwargs["messages"][0]["content"]
        return {"markdown": f"**{text[:20]}**"}, _usage(cost_usd=0.00002)

    monkeypatch.setattr(
        "backend.agents.formatter.call_openrouter_chat",
        fake_call,
    )

    data = {
        "introduccion": "Intro sin formato.",
        "conclusion": "Conclusión sin formato.",
        "desarrollo": [
            {
                "titulo_seccion": "T1",
                "explicacion_introductoria": "Intro sección.",
                "subsecciones": [
                    {
                        "titulo_subseccion": "S1",
                        "explicacion_detallada": "Detalle sub.",
                    }
                ],
            }
        ],
        "conexiones_contextuales": [
            {
                "seccion_temario_relacionada": "Tema",
                "descripcion_conexion": "Conexión.",
            }
        ],
    }

    result, usage_summary = await format_explainer_content_or("sk-or-test", data)

    assert call_count == 5
    assert result["introduccion"].startswith("**")
    assert result["desarrollo"][0]["explicacion_introductoria"].startswith("**")
    assert result["desarrollo"][0]["subsecciones"][0]["explicacion_detallada"].startswith("**")
    assert result["conexiones_contextuales"][0]["descripcion_conexion"].startswith("**")
    assert usage_summary["input_tokens"] == 50
    assert usage_summary["output_tokens"] == 25
    assert usage_summary["total_tokens"] == 75
    assert usage_summary["cost"] == pytest.approx(0.0001, rel=1e-6)

    # Input dict unchanged (deep copy).
    assert data["introduccion"] == "Intro sin formato."


@pytest.mark.asyncio
async def test_format_explainer_content_or_empty_dict():
    result, usage = await format_explainer_content_or("sk-or-test", {})
    assert result == {}
    assert usage["cost"] == 0.0
    assert usage["total_tokens"] == 0
