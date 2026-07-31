"""Canonical OpenRouter model and provider routing for non-explainer agents."""
from __future__ import annotations

from typing import Any

OPENROUTER_MODEL_AUXILIARY = "deepseek/deepseek-v4-flash"
OPENROUTER_DEEPSEEK_PROVIDER_ORDER = ("deepseek",)
OPENROUTER_MAX_REASONING_EFFORT = "xhigh"

# Esfuerzo de razonamiento máximo soportado por cada modelo (según la API pública
# de OpenRouter, supported_efforts). Modelos no mapeados → OPENROUTER_MAX_REASONING_EFFORT.
OPENROUTER_MODEL_MAX_REASONING_EFFORT: dict[str, str] = {
    "deepseek/deepseek-v4-flash-0731": "max",
    "deepseek/deepseek-v4-flash": "xhigh",
    "deepseek/deepseek-v4-pro": "xhigh",
}


def deepseek_provider_preferences() -> dict[str, Any]:
    """Force OpenRouter to use DeepSeek capacity and fail instead of falling back."""
    return {
        "order": list(OPENROUTER_DEEPSEEK_PROVIDER_ORDER),
        "allow_fallbacks": False,
    }


def max_reasoning_preferences(model: str | None = None) -> dict[str, Any]:
    """Use the highest OpenRouter reasoning effort while keeping reasoning text hidden.

    El máximo depende del modelo: se resuelve con el mapeo
    OPENROUTER_MODEL_MAX_REASONING_EFFORT (lookup exacto, sin normalizar);
    modelos no mapeados usan el fallback OPENROUTER_MAX_REASONING_EFFORT.
    """
    normalized = (model or "").strip()
    effort = OPENROUTER_MODEL_MAX_REASONING_EFFORT.get(normalized, OPENROUTER_MAX_REASONING_EFFORT)
    return {
        "effort": effort,
        "exclude": True,
    }


def openrouter_web_search_tool_auto() -> dict[str, Any]:
    """OpenRouter web-search server tool configuration for Resources."""
    return {
        "type": "openrouter:web_search",
        "parameters": {
            "engine": "auto",
            "max_results": 5,
            "max_total_results": 20,
            "search_context_size": "high",
        },
    }
