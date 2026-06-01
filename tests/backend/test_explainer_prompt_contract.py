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


def test_subpart_prompt_removes_global_scaffold_sections():
    from backend.agents.explainer_prompts import SUBPART_SYSTEM_INSTRUCTION

    lowered = SUBPART_SYSTEM_INSTRUCTION.lower()

    assert "introducción" not in lowered
    assert "conclusión" not in lowered
    assert "conexiones contextuales" not in lowered
    assert "conexiones_contextuales" not in lowered


def test_explainer_prompts_use_target_language_not_source_language():
    from backend.agents.explainer_prompts import (
        SYSTEM_INSTRUCTION,
        SUBPART_SYSTEM_INSTRUCTION,
        build_explainer_system_instruction,
    )

    assert "mismo idioma en el que esté escrito el fragmento objetivo" not in SYSTEM_INSTRUCTION
    assert "mismo idioma en el que esté escrito el fragmento objetivo" not in SUBPART_SYSTEM_INSTRUCTION
    prompt = build_explainer_system_instruction("es-ES")
    assert "idioma objetivo elegido" in prompt
    assert "castellano de España / español de España" in prompt
    assert "español hispanoamericano" in prompt
