from __future__ import annotations

import pytest

from backend.agents.language_policy import (
    build_formatter_language_rule,
    build_language_policy_xml,
    normalize_target_language,
)


def test_default_target_language_is_spain_spanish():
    target = normalize_target_language(None)

    assert target.code == "es-ES"
    assert "Castellano de España" in target.label


def test_spain_spanish_policy_explicitly_excludes_hispanoamerican_spanish():
    policy = build_language_policy_xml("es-ES", context="explainer")

    assert "castellano de España / español de España" in policy
    assert "español hispanoamericano" in policy
    assert "latinoamericano" in policy


def test_resources_policy_allows_any_resource_language():
    policy = build_language_policy_xml("en", context="resources")

    assert "English" in policy
    assert "cualquier idioma" in policy
    assert "No filtres" in policy


def test_formatter_rule_uses_selected_language_without_castilian_for_english():
    rule = build_formatter_language_rule("en")

    assert "English" in rule
    assert "castellano de España" not in rule
    assert "hispanoamericano" not in rule


def test_unknown_target_language_is_rejected():
    with pytest.raises(ValueError):
        normalize_target_language("xx-UNKNOWN")
