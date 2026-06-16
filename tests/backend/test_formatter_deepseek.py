"""Unit tests for direct DeepSeek formatter path (no real API calls)."""
from __future__ import annotations

import pytest
from types import SimpleNamespace

from backend.agents.formatter import (
    FORMATTER_DEEPSEEK_MODEL,
    _format_text_ds_sync,
    format_explainer_content_ds,
)


def _usage():
    return SimpleNamespace(
        prompt_token_count=10,
        candidates_token_count=5,
        thoughts_token_count=1,
        total_token_count=16,
        cost_usd=None,
    )


def test_format_text_ds_sync_uses_deepseek_direct_json_contract(monkeypatch):
    captured: dict = {}

    def fake_call(**kwargs):
        captured.update(kwargs)
        return {"markdown": "**Hola** mundo"}, _usage()

    monkeypatch.setattr(
        "backend.agents.formatter.call_deepseek_chat",
        fake_call,
    )

    out, usage = _format_text_ds_sync("sk-ds-test", "Hola mundo", "Sección 1")

    assert out == "**Hola** mundo"
    assert usage is not None
    assert captured["model"] == FORMATTER_DEEPSEEK_MODEL
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["reasoning_effort"] == "max"
    assert captured["response_format"] == "json_object"
    assert captured["temperature"] == 0.1
    assert "markdown" in captured["json_retry_instruction"]
    assert "[Contexto del apartado: Sección 1]" in captured["messages"][0]["content"]


def test_format_text_ds_sync_fail_safe_on_invalid_json(monkeypatch):
    monkeypatch.setattr(
        "backend.agents.formatter.call_deepseek_chat",
        lambda **kwargs: ({"markdown": "   "}, _usage()),
    )

    original = "Texto original intacto."
    out, usage = _format_text_ds_sync("sk-ds-test", original)

    assert out == original
    assert usage is not None


@pytest.mark.asyncio
async def test_format_explainer_content_ds_parallel_and_estimated_cost(monkeypatch):
    call_count = 0

    def fake_call(**kwargs):
        nonlocal call_count
        call_count += 1
        text = kwargs["messages"][0]["content"]
        return {"markdown": f"**{text[:20]}**"}, _usage()

    monkeypatch.setattr(
        "backend.agents.formatter.call_deepseek_chat",
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

    result, usage_summary = await format_explainer_content_ds("sk-ds-test", data)

    assert call_count == 5
    assert result["introduccion"].startswith("**")
    assert result["desarrollo"][0]["explicacion_introductoria"].startswith("**")
    assert result["desarrollo"][0]["subsecciones"][0]["explicacion_detallada"].startswith("**")
    assert result["conexiones_contextuales"][0]["descripcion_conexion"].startswith("**")
    assert usage_summary["input_tokens"] == 50
    assert usage_summary["output_tokens"] == 30
    assert usage_summary["total_tokens"] == 80
    assert usage_summary["cost"] > 0
    assert data["introduccion"] == "Intro sin formato."
