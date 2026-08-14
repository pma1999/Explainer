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

# --- Effort de razonamiento (GPT-5.6 Luna) -------------------------------- #
# Único contrato de valores (global-constraints.md §Allowlist y default;
# receta integration-effort.md §Verified Contract): orden canónico de la UI,
# default `medium`. Prohibidos en la API: none, minimal, ultra, extra_high,
# auto. `normalize_codex_effort` es el ÚNICO validador de autoridad del
# backend; el wire solo recibe valores exactos de la allowlist.
CODEX_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
CODEX_DEFAULT_EFFORT = "medium"


def normalize_codex_effort(value: str | None) -> str:
    """None/'' → medium; valor no-allowlist → ValueError; nunca devuelve otro valor.

    El vacío (`None` o `""`) es indistinguible de "no seleccionado" y degrada
    a medium (contrato congelado global-constraints.md §Allowlist y default:
    `None/'' → medium`; R-OLD-PROJECTS). Un string NO vacío fuera de la
    allowlist es un error explícito: la API lo traduce a 400 con el mensaje
    congelado y review/reformat lo degradan a medium de forma defensiva. No se
    aceptan espacios ni casing distinto (Security / quality).
    """
    if value is None or value == "":
        return CODEX_DEFAULT_EFFORT
    if value not in CODEX_EFFORT_LEVELS:
        raise ValueError(
            f"Nivel de razonamiento de Codex no soportado: '{value}'. "
            "Usa uno de: low, medium, high, xhigh, max."
        )
    return value
