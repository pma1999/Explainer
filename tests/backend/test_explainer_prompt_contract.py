"""Lock the subpart explainer exclusivity rules."""

from __future__ import annotations


def test_subpart_prompt_mentions_scope_exclusivity():
    from backend.agents.explainer_prompts import SUBPART_SYSTEM_INSTRUCTION

    assert "Si un bloque de alcance te dice qué NO desarrollar, obedécelo" in SUBPART_SYSTEM_INSTRUCTION
    assert "subpartes vecinas" in SUBPART_SYSTEM_INSTRUCTION
    assert "mención puente" in SUBPART_SYSTEM_INSTRUCTION


def test_subpart_prompt_gives_precedence_to_current_scope():
    from backend.agents.explainer_prompts import SUBPART_SYSTEM_INSTRUCTION

    assert "prevalece el alcance de la subparte actual" in SUBPART_SYSTEM_INSTRUCTION
