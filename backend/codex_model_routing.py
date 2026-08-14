"""Canonical Codex (ChatGPT) model routing — modelo único fijo.

Contrato congelado (global-constraints.md): un solo modelo `gpt-5.6-luna`
para todas las fases, sin selector de modelo en UI ni en la API. El override
de modelo se envía por turno (`turn/start`); `model/list` es la autoridad de
disponibilidad en runtime (integration-codex-appserver.md).
"""

from __future__ import annotations

CODEX_MODEL = "gpt-5.6-luna"
CODEX_MODEL_AUXILIARY = CODEX_MODEL

CODEX_EXPLAINER_MODELS: frozenset[str] = frozenset({CODEX_MODEL})
