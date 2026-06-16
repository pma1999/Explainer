"""Canonical DeepSeek direct model routing."""
from __future__ import annotations

DEEPSEEK_MODEL_V4_PRO = "deepseek-v4-pro"
DEEPSEEK_MODEL_V4_FLASH = "deepseek-v4-flash"
DEEPSEEK_MODEL_AUXILIARY = DEEPSEEK_MODEL_V4_FLASH
DEEPSEEK_MAX_REASONING_EFFORT = "max"
DEEPSEEK_FALLBACK_REASONING_EFFORT = "high"

DEEPSEEK_EXPLAINER_MODELS: frozenset[str] = frozenset(
    {
        DEEPSEEK_MODEL_V4_PRO,
        DEEPSEEK_MODEL_V4_FLASH,
    }
)


def max_reasoning_effort() -> str:
    """Return the strongest documented DeepSeek thinking effort."""
    return DEEPSEEK_MAX_REASONING_EFFORT
