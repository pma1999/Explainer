"""Canonical OpenRouter model and provider routing for non-explainer agents."""
from __future__ import annotations

from typing import Any

OPENROUTER_MODEL_AUXILIARY = "deepseek/deepseek-v4-flash"
OPENROUTER_DEEPSEEK_PROVIDER_ORDER = ("deepseek",)
OPENROUTER_MAX_REASONING_EFFORT = "xhigh"


def deepseek_provider_preferences() -> dict[str, Any]:
    """Force OpenRouter to use DeepSeek capacity and fail instead of falling back."""
    return {
        "order": list(OPENROUTER_DEEPSEEK_PROVIDER_ORDER),
        "allow_fallbacks": False,
    }


def max_reasoning_preferences() -> dict[str, Any]:
    """Use the highest OpenRouter reasoning effort while keeping reasoning text hidden."""
    return {
        "effort": OPENROUTER_MAX_REASONING_EFFORT,
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
