"""Tests for backend/agents/formatter.py.

All tests use mocking — no real API calls are made.
google.genai is patched at sys.modules level to avoid the system-level
cryptography library conflict present in this environment.

Coverage:
- _format_text: success, empty input, API failure (fail-safe)
  Now returns (text, usage_metadata | None) tuple.
- format_explainer_content:
    - formats every prose field
    - does NOT touch heading/title fields
    - preserves dict structure/shape (deep copy, input untouched)
    - all tasks run in a single asyncio.gather (parallel)
    - partial failure: failed fields keep original text
    - edge cases: empty dict, missing optional fields, None values
    - returns (dict, usage_summary) tuple with cost/token fields
"""

from __future__ import annotations

import asyncio
import copy
import sys
import types as _types_builtin
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Patch google.genai at sys.modules level BEFORE importing formatter.
#
# The system cryptography package is incompatible with the installed
# google-genai SDK in this environment, so we mock the entire namespace.
# ---------------------------------------------------------------------------

def _install_genai_mocks() -> None:
    """Register lightweight mocks for google and google.genai in sys.modules."""
    if "google.genai" not in sys.modules or not isinstance(sys.modules["google.genai"], MagicMock):
        genai_mock = MagicMock(name="google.genai")
        types_mock = MagicMock(name="google.genai.types")

        # Expose common attributes used by formatter.py
        genai_mock.Client = MagicMock(name="genai.Client")
        types_mock.GenerateContentConfig = MagicMock(name="GenerateContentConfig")

        sys.modules["google.genai"] = genai_mock
        sys.modules["google.genai.types"] = types_mock

        # Ensure google namespace sees genai as an attribute
        if "google" in sys.modules and not isinstance(sys.modules["google"], MagicMock):
            try:
                sys.modules["google"].genai = genai_mock  # type: ignore[attr-defined]
            except AttributeError:
                pass
        elif "google" not in sys.modules:
            google_mock = _types_builtin.ModuleType("google")
            google_mock.genai = genai_mock  # type: ignore[attr-defined]
            sys.modules["google"] = google_mock


_install_genai_mocks()

# Now safe to import formatter (google.genai is already mocked in sys.modules)
from backend.agents import formatter as _formatter_module  # noqa: E402
from backend.agents.formatter import _format_text, format_explainer_content  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(text: str) -> MagicMock:
    """Fake Gemini response object with .text and .usage_metadata attributes."""
    resp = MagicMock()
    resp.text = text
    usage = MagicMock()
    usage.prompt_token_count = 10
    usage.candidates_token_count = 5
    resp.usage_metadata = usage
    return resp


def _make_client() -> MagicMock:
    """Fake genai.Client with async models.generate_content."""
    client = MagicMock()
    client.aio = MagicMock()
    client.aio.models = MagicMock()
    return client


def _make_explainer_data(
    n_sections: int = 2,
    n_subsections: int = 3,
    with_conexiones: bool = True,
) -> dict[str, Any]:
    """Build a realistic explainer dict for testing."""
    desarrollo = []
    for i in range(n_sections):
        subsecciones = [
            {
                "titulo_subseccion": f"Título subsección {i + 1}.{j + 1}",
                "explicacion_detallada": (
                    f"Texto detallado de la subsección {i + 1}.{j + 1}. "
                    f"Contenido original sin formatear."
                ),
            }
            for j in range(n_subsections)
        ]
        desarrollo.append({
            "titulo_seccion": f"Título sección {i + 1}",
            "explicacion_introductoria": f"Introducción de la sección {i + 1}.",
            "subsecciones": subsecciones,
        })

    conexiones = (
        [
            {
                "seccion_temario_relacionada": "Tema relacionado A",
                "descripcion_conexion": "Descripción de la conexión A.",
            },
            {
                "seccion_temario_relacionada": "Tema relacionado B",
                "descripcion_conexion": "Descripción de la conexión B.",
            },
        ]
        if with_conexiones
        else []
    )

    return {
        "introduccion": "Texto de introducción general.",
        "desarrollo": desarrollo,
        "conclusion": "Texto de conclusión general.",
        "conexiones_contextuales": conexiones,
    }


# ---------------------------------------------------------------------------
# _format_text tests
# ---------------------------------------------------------------------------


class TestFormatText:
    """Unit tests for the internal _format_text coroutine.

    _format_text now returns (text, usage_metadata | None).
    """

    @pytest.mark.asyncio
    async def test_success_returns_formatted_text(self):
        """When the API responds, the formatted text is returned."""
        client = _make_client()
        client.aio.models.generate_content = AsyncMock(
            return_value=_make_response("**Texto** formateado.")
        )

        text, usage = await _format_text(client, "Texto sin formato.", "Contexto")

        assert text == "**Texto** formateado."
        assert usage is not None
        client.aio.models.generate_content.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_string_returns_as_is_no_api_call(self):
        """Empty or whitespace-only input returns immediately without calling the API."""
        client = _make_client()
        client.aio.models.generate_content = AsyncMock()

        text_empty, usage_empty = await _format_text(client, "")
        text_ws, usage_ws = await _format_text(client, "   ")

        assert text_empty == ""
        assert usage_empty is None
        assert text_ws == "   "
        assert usage_ws is None
        client.aio.models.generate_content.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_none_input_returns_none(self):
        """None input returns (None, None) without calling the API."""
        client = _make_client()
        client.aio.models.generate_content = AsyncMock()

        text, usage = await _format_text(client, None)

        assert text is None
        assert usage is None
        client.aio.models.generate_content.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_api_failure_returns_original_text(self):
        """If the API call raises any exception, the original text is returned unchanged."""
        client = _make_client()
        client.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("Network error")
        )

        original = "Texto original sin formato."
        text, usage = await _format_text(client, original, "ctx")

        assert text == original
        assert usage is None

    @pytest.mark.asyncio
    async def test_empty_api_response_returns_original_text(self):
        """If the API returns empty text, the original text is preserved."""
        client = _make_client()
        client.aio.models.generate_content = AsyncMock(
            return_value=_make_response("")
        )

        original = "Texto original."
        text, usage = await _format_text(client, original)

        assert text == original
        assert usage is None

    @pytest.mark.asyncio
    async def test_context_included_in_prompt(self):
        """When context is provided, it is prepended to the user message."""
        captured_contents: list[str] = []

        async def mock_generate(model, contents, config):
            captured_contents.append(contents)
            return _make_response("formatted")

        client = _make_client()
        client.aio.models.generate_content = mock_generate

        text, _ = await _format_text(client, "Texto original.", "Mi contexto")

        assert len(captured_contents) == 1
        assert "Mi contexto" in captured_contents[0]
        assert "Texto original." in captured_contents[0]


# ---------------------------------------------------------------------------
# format_explainer_content tests
# ---------------------------------------------------------------------------


class TestFormatExplainerContent:
    """Integration-style tests for the public format_explainer_content function.

    format_explainer_content now returns (dict, usage_summary) where
    usage_summary has keys: input_tokens, output_tokens, total_tokens, cost.
    """

    @pytest.mark.asyncio
    async def test_all_prose_fields_are_formatted(self):
        """Every prose text field in the explainer dict is sent through _format_text."""
        data = _make_explainer_data(n_sections=2, n_subsections=3, with_conexiones=True)
        call_count = 0

        async def fake_format(client, text, context=""):
            nonlocal call_count
            call_count += 1
            return text + " [FMT]", None  # (text, usage_meta)

        with patch.object(_formatter_module, "_format_text", side_effect=fake_format):
            with patch.object(_formatter_module, "genai"):
                result, usage_summary = await format_explainer_content("fake-api-key", data)

        # 1 intro + 1 conclusion + 2 sec×intro + 2×3 subs + 2 cx = 12
        n_sections, n_subs, n_cx = 2, 3, 2
        expected = 1 + 1 + n_sections + n_sections * n_subs + n_cx
        assert call_count == expected

        assert result["introduccion"].endswith(" [FMT]")
        assert result["conclusion"].endswith(" [FMT]")
        for sec in result["desarrollo"]:
            assert sec["explicacion_introductoria"].endswith(" [FMT]")
            for sub in sec["subsecciones"]:
                assert sub["explicacion_detallada"].endswith(" [FMT]")
        for cx in result["conexiones_contextuales"]:
            assert cx["descripcion_conexion"].endswith(" [FMT]")

    @pytest.mark.asyncio
    async def test_returns_usage_summary(self):
        """format_explainer_content returns a usage_summary dict with cost fields."""
        data = _make_explainer_data(n_sections=1, n_subsections=1, with_conexiones=False)

        async def fake_format(client, text, context=""):
            return text + " [FMT]", None

        with patch.object(_formatter_module, "_format_text", side_effect=fake_format):
            with patch.object(_formatter_module, "genai"):
                _, usage_summary = await format_explainer_content("fake-api-key", data)

        assert "input_tokens" in usage_summary
        assert "output_tokens" in usage_summary
        assert "total_tokens" in usage_summary
        assert "cost" in usage_summary
        assert isinstance(usage_summary["cost"], float)

    @pytest.mark.asyncio
    async def test_title_fields_are_not_modified(self):
        """Heading/title fields must never be sent through the formatter."""
        data = _make_explainer_data()
        original = copy.deepcopy(data)

        async def fake_format(client, text, context=""):
            return text + " [FMT]", None

        with patch.object(_formatter_module, "_format_text", side_effect=fake_format):
            with patch.object(_formatter_module, "genai"):
                result, _ = await format_explainer_content("fake-api-key", data)

        for i, sec in enumerate(result["desarrollo"]):
            assert sec["titulo_seccion"] == original["desarrollo"][i]["titulo_seccion"]
            for j, sub in enumerate(sec["subsecciones"]):
                assert sub["titulo_subseccion"] == original["desarrollo"][i]["subsecciones"][j]["titulo_subseccion"]

        for k, cx in enumerate(result["conexiones_contextuales"]):
            assert cx["seccion_temario_relacionada"] == original["conexiones_contextuales"][k]["seccion_temario_relacionada"]

    @pytest.mark.asyncio
    async def test_original_data_not_mutated(self):
        """format_explainer_content deep-copies the input — the original is untouched."""
        data = _make_explainer_data()
        original_intro = data["introduccion"]

        async def fake_format(client, text, context=""):
            return text + " [FMT]", None

        with patch.object(_formatter_module, "_format_text", side_effect=fake_format):
            with patch.object(_formatter_module, "genai"):
                result, _ = await format_explainer_content("fake-api-key", data)

        assert data["introduccion"] == original_intro
        assert result["introduccion"] != original_intro

    @pytest.mark.asyncio
    async def test_partial_failure_keeps_original_text(self):
        """If some _format_text calls fail, those fields keep the original text."""
        data = _make_explainer_data(n_sections=1, n_subsections=2, with_conexiones=False)
        original_intro = data["introduccion"]

        call_count = 0

        async def flaky_format(client, text, context=""):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # Fail first call (introduccion)
                raise RuntimeError("Simulated API failure")
            return text + " [OK]", None

        with patch.object(_formatter_module, "_format_text", side_effect=flaky_format):
            with patch.object(_formatter_module, "genai"):
                result, _ = await format_explainer_content("fake-api-key", data)

        # First field (introduccion) failed → original preserved
        assert result["introduccion"] == original_intro
        # Other fields succeeded
        assert result["conclusion"].endswith(" [OK]")

    @pytest.mark.asyncio
    async def test_empty_explainer_dict_returns_empty_copy(self):
        """An empty dict returns an empty dict without errors."""
        async def fake_format(client, text, context=""):
            return text + " [FMT]", None

        with patch.object(_formatter_module, "_format_text", side_effect=fake_format):
            with patch.object(_formatter_module, "genai"):
                result, usage_summary = await format_explainer_content("fake-api-key", {})

        assert result == {}
        assert usage_summary["total_tokens"] == 0
        assert usage_summary["cost"] == 0.0

    @pytest.mark.asyncio
    async def test_missing_optional_fields_no_crash(self):
        """Optional fields (conexiones_contextuales=None, empty desarrollo) don't crash."""
        data = {
            "introduccion": "Intro.",
            "desarrollo": [],
            "conclusion": "Fin.",
            "conexiones_contextuales": None,
        }

        async def fake_format(client, text, context=""):
            return text + " [FMT]", None

        with patch.object(_formatter_module, "_format_text", side_effect=fake_format):
            with patch.object(_formatter_module, "genai"):
                result, _ = await format_explainer_content("fake-api-key", data)

        assert result["introduccion"].endswith(" [FMT]")
        assert result["conclusion"].endswith(" [FMT]")
        assert result["desarrollo"] == []

    @pytest.mark.asyncio
    async def test_structure_shape_preserved(self):
        """The returned dict has exactly the same keys and nesting as the input."""
        data = _make_explainer_data(n_sections=3, n_subsections=4)

        async def fake_format(client, text, context=""):
            return text + " [FMT]", None

        with patch.object(_formatter_module, "_format_text", side_effect=fake_format):
            with patch.object(_formatter_module, "genai"):
                result, _ = await format_explainer_content("fake-api-key", data)

        assert set(result.keys()) == set(data.keys())
        assert len(result["desarrollo"]) == len(data["desarrollo"])
        for i, sec in enumerate(result["desarrollo"]):
            assert len(sec["subsecciones"]) == len(data["desarrollo"][i]["subsecciones"])
            for sub in sec["subsecciones"]:
                assert "titulo_subseccion" in sub
                assert "explicacion_detallada" in sub

    @pytest.mark.asyncio
    async def test_all_tasks_run_in_single_gather(self):
        """All format tasks are submitted to asyncio.gather in a single parallel batch."""
        data = _make_explainer_data(n_sections=2, n_subsections=3, with_conexiones=True)
        gather_call_arities: list[int] = []

        original_gather = asyncio.gather

        async def tracking_gather(*coros, **kwargs):
            gather_call_arities.append(len(coros))
            return await original_gather(*coros, **kwargs)

        async def fast_format(client, text, context=""):
            return text + " [FMT]", None

        with patch.object(_formatter_module, "_format_text", side_effect=fast_format):
            with patch.object(_formatter_module, "genai"):
                with patch("asyncio.gather", side_effect=tracking_gather):
                    await format_explainer_content("fake-api-key", data)

        # Exactly one asyncio.gather call containing ALL tasks
        assert len(gather_call_arities) == 1
        n_sections, n_subs, n_cx = 2, 3, 2
        expected_tasks = 1 + 1 + n_sections + n_sections * n_subs + n_cx  # 12
        assert gather_call_arities[0] == expected_tasks

    @pytest.mark.asyncio
    async def test_content_preserved_verbatim(self):
        """When the formatter returns content identical to input, nothing is lost."""
        data = _make_explainer_data(n_sections=1, n_subsections=1, with_conexiones=False)
        original = copy.deepcopy(data)

        async def identity_format(client, text, context=""):
            return text, None  # no change

        with patch.object(_formatter_module, "_format_text", side_effect=identity_format):
            with patch.object(_formatter_module, "genai"):
                result, _ = await format_explainer_content("fake-api-key", data)

        assert result["introduccion"] == original["introduccion"]
        assert result["conclusion"] == original["conclusion"]
        for i, sec in enumerate(result["desarrollo"]):
            assert sec["explicacion_introductoria"] == original["desarrollo"][i]["explicacion_introductoria"]
            for j, sub in enumerate(sec["subsecciones"]):
                assert sub["explicacion_detallada"] == original["desarrollo"][i]["subsecciones"][j]["explicacion_detallada"]

    @pytest.mark.asyncio
    async def test_all_exceptions_do_not_propagate(self):
        """Even if every _format_text call raises, no exception propagates from format_explainer_content."""
        data = _make_explainer_data(n_sections=1, n_subsections=2, with_conexiones=True)
        original = copy.deepcopy(data)

        async def always_fail(client, text, context=""):
            raise RuntimeError("Always fails")

        with patch.object(_formatter_module, "_format_text", side_effect=always_fail):
            with patch.object(_formatter_module, "genai"):
                result, usage_summary = await format_explainer_content("fake-api-key", data)

        # All prose fields fall back to originals
        assert result["introduccion"] == original["introduccion"]
        assert result["conclusion"] == original["conclusion"]
        # Usage summary reflects zero successful calls
        assert usage_summary["total_tokens"] == 0
        assert usage_summary["cost"] == 0.0

    @pytest.mark.asyncio
    async def test_usage_summary_aggregates_tokens(self):
        """Token counts from individual _format_text calls are aggregated in usage_summary."""
        data = _make_explainer_data(n_sections=1, n_subsections=1, with_conexiones=False)

        def _make_usage(prompt: int, candidates: int) -> MagicMock:
            u = MagicMock()
            u.prompt_token_count = prompt
            u.candidates_token_count = candidates
            return u

        call_num = 0

        async def fake_format_with_usage(client, text, context=""):
            nonlocal call_num
            call_num += 1
            # Return distinct token counts per call so we can verify aggregation
            return text + " [FMT]", _make_usage(10 * call_num, 5 * call_num)

        with patch.object(_formatter_module, "_format_text", side_effect=fake_format_with_usage):
            with patch.object(_formatter_module, "genai"):
                _, usage_summary = await format_explainer_content("fake-api-key", data)

        # n_sections=1, n_subsections=1: 1 intro + 1 conclusion + 1 sec_intro + 1 sub = 4 calls
        assert call_num == 4
        # total_input = 10+20+30+40 = 100, total_output = 5+10+15+20 = 50
        assert usage_summary["input_tokens"] == 100
        assert usage_summary["output_tokens"] == 50
        assert usage_summary["total_tokens"] == 150
        assert usage_summary["cost"] > 0.0
