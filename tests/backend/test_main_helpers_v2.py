"""Unit + acceptance tests for request contract widening, model-gate relaxation, and provider-routing threading."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers to import functions from main (avoids running FastAPI app)
# ---------------------------------------------------------------------------

def _resolve_explainer_model_fn():
    import main as m
    return m._resolve_explainer_model


def _build_provider_routing_fn():
    import main as m
    return m._build_openrouter_provider_routing


def _request_class():
    import main as m
    return m.ProcessProjectRequest


# ===================================================================
# ACCEPTANCE: Model validation relaxation (shape over frozenset)
# ===================================================================

class TestModelValidationRelaxation:
    """The frozenset gate is replaced by shape+regex validation.

    The 3 presets still pass; custom valid IDs resolve; malformed IDs → ValueError.
    """

    def test_preset_models_still_resolve(self):
        fn = _resolve_explainer_model_fn()
        # Each known preset must pass the shape gate
        for model_id in ("xiaomi/mimo-v2.5-pro", "xiaomi/mimo-v2.5", "deepseek/deepseek-v4-pro"):
            result = fn("openrouter", model_id)
            assert result == model_id

    def test_custom_valid_model_resolves(self):
        fn = _resolve_explainer_model_fn()
        result = fn("openrouter", "openai/gpt-5.4-nano")
        assert result == "openai/gpt-5.4-nano"

    def test_custom_valid_model_with_hyphens_colons_and_dots(self):
        fn = _resolve_explainer_model_fn()
        result = fn("openrouter", "org/model-v2.5:beta")
        assert result == "org/model-v2.5:beta"

    def test_blank_model_raises(self):
        fn = _resolve_explainer_model_fn()
        with pytest.raises(ValueError, match="Se requiere un modelo OpenRouter"):
            fn("openrouter", "")

    def test_none_model_falls_back_to_default(self):
        fn = _resolve_explainer_model_fn()
        import main as m
        result = fn("openrouter", None)
        assert result == m.OPENROUTER_EXPLAINER_MODEL

    def test_model_without_slash_raises(self):
        fn = _resolve_explainer_model_fn()
        with pytest.raises(ValueError, match="Modelo OpenRouter inválido"):
            fn("openrouter", "invalidmodel")

    def test_model_with_too_long_string_raises(self):
        fn = _resolve_explainer_model_fn()
        long_model = "x/" + "a" * 200
        with pytest.raises(ValueError, match="demasiado largo"):
            fn("openrouter", long_model)

    def test_deepseek_branch_unchanged(self):
        fn = _resolve_explainer_model_fn()
        import main as m
        result = fn("deepseek", None, "deepseek-v4-pro")
        assert result == "deepseek-v4-pro"

    def test_gemini_branch_unchanged(self):
        fn = _resolve_explainer_model_fn()
        import main as m
        result = fn("gemini", None)
        assert result == m.MODEL_AGENTS


# ===================================================================
# ACCEPTANCE: _build_openrouter_provider_routing
# ===================================================================

class TestBuildProviderRouting:
    """Provider routing dict construction from request fields."""

    def test_none_provider_returns_none(self):
        fn = _build_provider_routing_fn()
        assert fn(None, False) is None

    def test_empty_string_returns_none(self):
        fn = _build_provider_routing_fn()
        assert fn("", False) is None

    def test_whitespace_only_returns_none(self):
        fn = _build_provider_routing_fn()
        assert fn("  ", False) is None

    def test_non_string_returns_none(self):
        fn = _build_provider_routing_fn()
        assert fn(123, False) is None  # type: ignore

    def test_provider_without_only(self):
        fn = _build_provider_routing_fn()
        result = fn("novita", False)
        assert result == {"order": ["novita"]}

    def test_provider_with_only_true(self):
        fn = _build_provider_routing_fn()
        result = fn("novita", True)
        assert result == {"order": ["novita"], "allow_fallbacks": False}

    def test_provider_is_lowercased(self):
        fn = _build_provider_routing_fn()
        result = fn("NovIta", False)
        assert result == {"order": ["novita"]}

    def test_provider_with_dots_and_hyphens(self):
        fn = _build_provider_routing_fn()
        result = fn("some-provider.v2", False)
        assert result == {"order": ["some-provider.v2"]}

    def test_provider_too_long_returns_none(self):
        fn = _build_provider_routing_fn()
        long_provider = "a" * 65
        assert fn(long_provider, False) is None

    def test_provider_with_invalid_chars_returns_none(self):
        fn = _build_provider_routing_fn()
        assert fn("bad provider!", False) is None


# ===================================================================
# ACCEPTANCE: ProcessProjectRequest new fields
# ===================================================================

class TestProcessProjectRequestWidening:
    """openrouter_model is now str; openrouter_provider and openrouter_provider_only are accepted."""

    def test_openrouter_model_is_str(self):
        cls = _request_class()
        payload = cls(
            explainer_provider="openrouter",
            openrouter_model="openai/gpt-5.4-nano",
            openrouter_provider="novita",
            openrouter_provider_only=True,
        )
        assert payload.openrouter_model == "openai/gpt-5.4-nano"
        assert payload.openrouter_provider == "novita"
        assert payload.openrouter_provider_only is True

    def test_defaults_are_safe(self):
        cls = _request_class()
        payload = cls()
        assert payload.explainer_provider == "gemini"
        assert payload.openrouter_model is None
        assert payload.openrouter_provider is None
        assert payload.openrouter_provider_only is False

    def test_rejects_invalid_explainer_provider(self):
        cls = _request_class()
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            cls(explainer_provider="invalid")


# ===================================================================
# ACCEPTANCE: Fields ignored for non-OpenRouter providers (no crash)
# ===================================================================

class TestProviderFieldsIgnoredForOtherProviders:
    """Provider routing fields are silently ignored for gemini/deepseek."""

    def test_provider_fields_ignored_for_gemini(self):
        fn = _resolve_explainer_model_fn()
        # gemini ignores openrouter fields entirely — no crash
        result = fn("gemini", "openai/gpt-5.4-nano")
        import main as m
        assert result == m.MODEL_AGENTS

    def test_provider_fields_ignored_for_deepseek(self):
        fn = _resolve_explainer_model_fn()
        import main as m
        result = fn("deepseek", "openai/gpt-5.4-nano", "deepseek-v4-pro")
        assert result == "deepseek-v4-pro"


