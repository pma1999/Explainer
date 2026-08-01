"""Tests for C2 "Repaso activo": review agent (3 providers) + endpoint + usage helper."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import main
from backend.gemini_client import GeminiError, GeminiRateLimitError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_review() -> dict:
    return {
        "preguntas": [
            {
                "numero": i,
                "pregunta": f"Pregunta {i}",
                "respuesta_razonada": f"Respuesta razonada {i}.",
                "referencia": "Sección 2.3" if i == 1 else "",
            }
            for i in range(1, 6)
        ],
        "nota": "Repasa las secciones centrales.",
    }


def _usage(**kwargs) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_token_count=kwargs.get("prompt", 10),
        tool_use_prompt_token_count=kwargs.get("tool_prompt", 0),
        candidates_token_count=kwargs.get("candidates", 5),
        thoughts_token_count=kwargs.get("thoughts", 0),
        total_token_count=kwargs.get("total", 15),
        cost_usd=kwargs.get("cost_usd", None),
    )


def _review_project(partes=None, config=None, usage=None) -> dict:
    return {
        "id": "proj-1",
        "name": "Proyecto",
        "status": "completed",
        "segmentation": {"partes": [{"numero": 1, "titulo": "Parte 1"}]},
        "partes_contenido": partes
        or {"1": {"status": "completed", "explainer": {"ok": True, "desarrollo": []}}},
        "usage": usage or {"total_tokens": 100, "total_cost": 0.001},
        "explainer_config": config,
    }


def _post_review(auth_client, project_id="proj-1", part_id="1", **json_kwargs):
    return auth_client.post(
        f"/api/projects/{project_id}/parts/{part_id}/review",
        headers={"Authorization": "Bearer fake-token"},
        **json_kwargs,
    )


# ---------------------------------------------------------------------------
# Endpoint: cache + regenerate
# ---------------------------------------------------------------------------

class TestReviewEndpointCache:
    def test_cached_review_returns_without_calling_agent(self, auth_client):
        project = _review_project(
            partes={"1": {"status": "completed", "explainer": {"ok": True}, "review": _valid_review()}}
        )
        with patch("main.get_project", return_value=project):
            with patch("main.run_review") as mock_run:
                r = _post_review(auth_client)

        assert r.status_code == 200
        data = r.json()
        assert data["cached"] is True
        assert data["review"]["preguntas"][0]["pregunta"] == "Pregunta 1"
        mock_run.assert_not_called()

    def test_regenerate_true_calls_agent_and_overwrites(self, auth_client):
        old_review = _valid_review()
        old_review["preguntas"][0]["pregunta"] = "Pregunta vieja"
        new_review = _valid_review()
        project = _review_project(
            partes={"1": {"status": "completed", "explainer": {"ok": True}, "review": old_review}},
            config={"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"},
        )
        saves = []
        with patch("main.get_project", return_value=project):
            with patch("main.has_user_api_key", return_value=True):
                with patch("main.get_user_api_key", return_value="AIzaFakeKey"):
                    with patch("main.run_review", return_value=(new_review, _usage())) as mock_run:
                        with patch(
                            "main.update_project",
                            side_effect=lambda pid, uid, payload: saves.append(payload) or {"id": pid},
                        ):
                            r = _post_review(auth_client, json={"regenerate": True})

        assert r.status_code == 200
        data = r.json()
        assert data["cached"] is False
        assert data["review"]["preguntas"][0]["pregunta"] == "Pregunta 1"
        mock_run.assert_called_once()
        assert saves[-1]["partes_contenido"]["1"]["review"] == new_review


# ---------------------------------------------------------------------------
# Endpoint: error cases (404 / 400)
# ---------------------------------------------------------------------------

class TestReviewEndpointErrors:
    def test_404_when_project_missing(self, auth_client):
        with patch("main.get_project", return_value=None):
            r = _post_review(auth_client, project_id="nope")
        assert r.status_code == 404

    def test_404_when_part_missing(self, auth_client):
        project = _review_project()
        with patch("main.get_project", return_value=project):
            r = _post_review(auth_client, part_id="99")
        assert r.status_code == 404

    @pytest.mark.parametrize("explainer", [None, {"error": "All explainer calls failed"}])
    def test_400_when_explainer_invalid(self, auth_client, explainer):
        project = _review_project(partes={"1": {"status": "completed", "explainer": explainer}})
        with patch("main.get_project", return_value=project):
            r = _post_review(auth_client)
        assert r.status_code == 400
        assert "explicación generada" in r.json()["detail"]

    def test_400_when_no_provider_determinable(self, auth_client):
        project = _review_project(config=None)
        with patch("main.get_project", return_value=project):
            r = _post_review(auth_client)
        assert r.status_code == 400
        assert "proveedor" in r.json()["detail"].lower()

    def test_400_when_no_api_key(self, auth_client):
        project = _review_project(config={"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"})
        with patch("main.get_project", return_value=project):
            with patch("main.has_user_api_key", return_value=False):
                r = _post_review(auth_client)
        assert r.status_code == 400
        assert "Gemini" in r.json()["detail"]

    def test_400_when_api_key_empty(self, auth_client):
        project = _review_project(config={"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"})
        with patch("main.get_project", return_value=project):
            with patch("main.has_user_api_key", return_value=True):
                with patch("main.get_user_api_key", return_value=None):
                    r = _post_review(auth_client)
        assert r.status_code == 400
        assert "Gemini" in r.json()["detail"]

    def test_400_unknown_provider(self, auth_client):
        project = _review_project(config={"provider": "anthropic", "model": "claude"})
        with patch("main.get_project", return_value=project):
            r = _post_review(auth_client)
        assert r.status_code == 400
        assert "no soportado" in r.json()["detail"]

    def test_502_when_persistence_fails(self, auth_client):
        project = _review_project(config={"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"})
        with patch("main.get_project", return_value=project):
            with patch("main.has_user_api_key", return_value=True):
                with patch("main.get_user_api_key", return_value="AIzaFakeKey"):
                    with patch("main.run_review", return_value=(_valid_review(), _usage())):
                        with patch("main.update_project", return_value=None):
                            r = _post_review(auth_client)
        assert r.status_code == 502
        assert "No se pudo guardar el repaso" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Endpoint: provider/model resolution + agent call + persistence
# ---------------------------------------------------------------------------

class TestReviewEndpointResolution:
    def test_uses_explainer_config_provider_and_model(self, auth_client):
        project = _review_project(
            config={
                "provider": "openrouter",
                "model": "openai/gpt-5.4-nano",
                "openrouter_model": "openai/gpt-5.4-nano",
            }
        )
        captured: dict = {}

        def _fake_or(api_key, explainer_content, part_title, target_language, model):
            captured.update(api_key=api_key, model=model, title=part_title, lang=target_language)
            return (_valid_review(), _usage(cost_usd=0.00001))

        with patch("main.get_project", return_value=project):
            with patch("main.has_user_api_key", side_effect=lambda uid, provider="google_gemini": True):
                with patch("main.get_user_api_key", return_value="sk-or-v1-test"):
                    with patch("main.run_review_or", new=_fake_or):
                        with patch("main.update_project", return_value={"id": "proj-1"}):
                            r = _post_review(auth_client)

        assert r.status_code == 200
        assert r.json()["cached"] is False
        assert captured["model"] == "openai/gpt-5.4-nano"
        assert captured["api_key"] == "sk-or-v1-test"
        assert captured["title"] == "Parte 1"
        assert captured["lang"] == "es-ES"

    def test_falls_back_to_body_provider_when_no_config(self, auth_client):
        project = _review_project(config=None)
        with patch("main.get_project", return_value=project):
            with patch(
                "main.has_user_api_key",
                side_effect=lambda uid, provider="google_gemini": provider == "google_gemini",
            ):
                with patch("main.get_user_api_key", return_value="AIzaFakeKey"):
                    with patch("main.run_review", return_value=(_valid_review(), _usage())) as mock_run:
                        with patch("main.update_project", return_value={"id": "proj-1"}):
                            r = _post_review(auth_client, json={"explainer_provider": "gemini"})

        assert r.status_code == 200
        mock_run.assert_called_once()
        assert mock_run.call_args.args[0] == "AIzaFakeKey"

    def test_accepts_markdown_string_explainer(self, auth_client):
        """Tras el formateo, el explainer almacenado es un string markdown — debe ser válido."""
        project = _review_project(
            partes={"1": {"status": "completed", "explainer": "## Introducción\n\nTexto formateado."}},
            config={"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"},
        )
        captured: dict = {}

        def _fake_run(api_key, explainer_content, part_title, target_language, model):
            captured.update(content=explainer_content, title=part_title)
            return (_valid_review(), _usage())

        with patch("main.get_project", return_value=project):
            with patch("main.has_user_api_key", return_value=True):
                with patch("main.get_user_api_key", return_value="AIzaFakeKey"):
                    with patch("main.run_review", new=_fake_run):
                        with patch("main.update_project", return_value={"id": "proj-1"}):
                            r = _post_review(auth_client)

        assert r.status_code == 200
        assert r.json()["cached"] is False
        assert captured["content"] == "## Introducción\n\nTexto formateado."
        assert captured["title"] == "Parte 1"

    def test_deepseek_provider_uses_deepseek_agent(self, auth_client):
        project = _review_project(
            config={"provider": "deepseek", "model": "deepseek-v4-pro", "deepseek_model": "deepseek-v4-pro"}
        )
        with patch("main.get_project", return_value=project):
            with patch(
                "main.has_user_api_key",
                side_effect=lambda uid, provider="google_gemini": provider == "deepseek",
            ):
                with patch("main.get_user_api_key", return_value="ds-key"):
                    with patch("main.run_review_ds", return_value=(_valid_review(), _usage())) as mock_ds:
                        with patch("main.update_project", return_value={"id": "proj-1"}):
                            r = _post_review(auth_client)

        assert r.status_code == 200
        mock_ds.assert_called_once()
        assert mock_ds.call_args.args[1] == {"ok": True, "desarrollo": []}

    def test_persists_review_and_accumulated_usage(self, auth_client):
        project = _review_project(
            config={"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"},
            usage={"total_tokens": 100, "total_cost": 0.001, "prompt_tokens": 80},
        )
        saves: list[dict] = []

        def _fake_run(api_key, explainer_content, part_title, target_language, model):
            return (_valid_review(), _usage(prompt=10, candidates=5, total=15, cost_usd=0.00001))

        with patch("main.get_project", return_value=project):
            with patch("main.has_user_api_key", return_value=True):
                with patch("main.get_user_api_key", return_value="AIzaFakeKey"):
                    with patch("main.run_review", new=_fake_run):
                        with patch(
                            "main.update_project",
                            side_effect=lambda pid, uid, payload: saves.append(payload) or {"id": pid},
                        ):
                            r = _post_review(auth_client)

        assert r.status_code == 200
        save_payload = saves[-1]
        assert save_payload["partes_contenido"]["1"]["review"]["preguntas"][0]["pregunta"] == "Pregunta 1"
        usage = save_payload["usage"]
        assert usage["prompt_tokens"] == 90
        assert usage["candidates_tokens"] == 5
        assert usage["total_tokens"] == 115
        assert usage["total_cost"] == round(0.001 + 0.00001, 6)


# ---------------------------------------------------------------------------
# Endpoint: agent failures
# ---------------------------------------------------------------------------

class TestReviewEndpointAgentFailures:
    def _patched_ok_project(self):
        return _review_project(config={"provider": "gemini", "model": "gemini-3.1-flash-lite-preview"})

    def test_502_on_agent_failure(self, auth_client):
        with patch("main.get_project", return_value=self._patched_ok_project()):
            with patch("main.has_user_api_key", return_value=True):
                with patch("main.get_user_api_key", return_value="AIzaFakeKey"):
                    with patch("main.run_review", side_effect=RuntimeError("boom")):
                        r = _post_review(auth_client)
        assert r.status_code == 502
        assert "boom" in r.json()["detail"]

    def test_429_on_gemini_rate_limit(self, auth_client):
        with patch("main.get_project", return_value=self._patched_ok_project()):
            with patch("main.has_user_api_key", return_value=True):
                with patch("main.get_user_api_key", return_value="AIzaFakeKey"):
                    with patch("main.run_review", side_effect=GeminiRateLimitError("rate limited")):
                        r = _post_review(auth_client)
        assert r.status_code == 429
        assert "429" in r.json()["detail"]

    def test_502_on_gemini_error(self, auth_client):
        with patch("main.get_project", return_value=self._patched_ok_project()):
            with patch("main.has_user_api_key", return_value=True):
                with patch("main.get_user_api_key", return_value="AIzaFakeKey"):
                    with patch("main.run_review", side_effect=GeminiError("internal failure", status_code=500)):
                        r = _post_review(auth_client)
        assert r.status_code == 502
        assert "internal failure" in r.json()["detail"]

    def test_502_on_openrouter_error_with_trimmed_message(self, auth_client):
        from backend.openrouter_client import OpenRouterError

        with patch("main.get_project", return_value=self._patched_ok_project()):
            with patch("main.has_user_api_key", return_value=True):
                with patch("main.get_user_api_key", return_value="AIzaFakeKey"):
                    with patch("main.run_review", side_effect=OpenRouterError("x" * 500)):
                        r = _post_review(auth_client)
        assert r.status_code == 502
        assert len(r.json()["detail"]) <= 200 + len("Error generando el repaso: ")


# ---------------------------------------------------------------------------
# _accumulate_review_usage helper
# ---------------------------------------------------------------------------

class TestAccumulateReviewUsage:
    def test_sums_tokens_and_uses_real_cost(self):
        usage = {"total_tokens": 100, "total_cost": 0.001, "prompt_tokens": 80, "candidates_tokens": 10, "thoughts_tokens": 5}
        main._accumulate_review_usage(usage, _usage(prompt=10, candidates=5, total=15, cost_usd=0.00001), cost_model="gemini-3.1-flash-lite-preview")
        assert usage["prompt_tokens"] == 90
        assert usage["candidates_tokens"] == 15
        assert usage["thoughts_tokens"] == 5
        assert usage["total_tokens"] == 115
        assert usage["total_cost"] == round(0.001 + 0.00001, 6)

    def test_falls_back_to_calculate_cost_without_real_cost(self):
        usage = {"total_tokens": 0, "total_cost": 0.0}
        main._accumulate_review_usage(usage, _usage(prompt=10, candidates=5, total=15, cost_usd=None), cost_model="gemini-3.1-flash-lite-preview")
        assert usage["total_tokens"] == 15
        assert usage["total_cost"] > 0

    def test_none_usage_is_noop(self):
        usage = {"total_tokens": 1, "total_cost": 0.0}
        main._accumulate_review_usage(usage, None, cost_model="x")
        assert usage == {"total_tokens": 1, "total_cost": 0.0}

    def test_negative_or_non_finite_cost_usd_ignored(self):
        usage = {"total_tokens": 0, "total_cost": 0.0}
        main._accumulate_review_usage(usage, _usage(total=5, cost_usd=-1), cost_model="gemini-3.1-flash-lite-preview")
        assert usage["total_tokens"] == 5
        assert usage["total_cost"] > 0


# ---------------------------------------------------------------------------
# Agent: Gemini
# ---------------------------------------------------------------------------

@pytest.fixture
def bypass_gemini_retry(monkeypatch):
    """Run the (decorated) gemini agent without retry/backoff sleeps."""
    from backend.agents import review

    monkeypatch.setattr(review, "gemini_retry", lambda **kwargs: (lambda fn: fn))


class TestReviewAgentGemini:
    def test_run_review_validates_and_passes_response_schema(self, bypass_gemini_retry, monkeypatch):
        from backend.agents import review

        captured: dict = {}

        def _fake_generate(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                text=json.dumps(_valid_review()),
                usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5, thoughts_token_count=0, total_token_count=15),
            )

        monkeypatch.setattr(review, "generate_content_with_retry", _fake_generate)

        result, usage = review.run_review(
            api_key="AIzaFakeKey",
            explainer_content={"ok": True, "desarrollo": []},
            part_title="Parte 1",
            model="gemini-3.1-flash-lite-preview",
        )

        assert len(result["preguntas"]) == 5
        assert result["preguntas"][0]["referencia"] == "Sección 2.3"
        assert usage.total_token_count == 15
        assert captured["model"] == "gemini-3.1-flash-lite-preview"
        schema = captured["config"].response_schema
        assert schema.properties["preguntas"].min_items == 5
        assert schema.properties["preguntas"].max_items == 5
        assert "Pregunta 1" not in captured["contents"][0].parts[0].text
        assert "Parte 1" in captured["contents"][0].parts[0].text
        assert "exactamente 5 preguntas" in captured["contents"][0].parts[0].text

    def test_run_review_rejects_invalid_question_count(self, bypass_gemini_retry, monkeypatch):
        from backend.agents import review

        def _fake_generate(**kwargs):
            bad = _valid_review()
            bad["preguntas"] = bad["preguntas"][:4]
            return SimpleNamespace(text=json.dumps(bad), usage_metadata=None)

        monkeypatch.setattr(review, "generate_content_with_retry", _fake_generate)

        with pytest.raises(Exception, match="exactamente 5"):
            review.run_review(api_key="AIzaFakeKey", explainer_content={}, part_title="P1")


# ---------------------------------------------------------------------------
# Agent: OpenRouter
# ---------------------------------------------------------------------------

class TestReviewAgentOpenRouter:
    def test_run_review_or_uses_json_contract_and_validates(self, monkeypatch):
        from backend.agents import review

        captured: dict = {}

        def _fake_call(**kwargs):
            captured.update(kwargs)
            return (_valid_review(), _usage(cost_usd=0.00001))

        monkeypatch.setattr(review, "call_openrouter_chat", _fake_call)

        result, usage = review.run_review_or(
            api_key="sk-or-v1-test",
            explainer_content={"ok": True},
            part_title="Parte 1",
        )

        assert len(result["preguntas"]) == 5
        assert usage.cost_usd == 0.00001
        assert captured["model"] == "deepseek/deepseek-v4-flash"
        assert captured["response_format"] == "json_object"
        assert "exactamente 5" in captured["system_prompt"]
        assert "preguntas" in captured["json_retry_instruction"]
        assert "respuesta_razonada" in captured["json_retry_instruction"]

    def test_run_review_or_corrects_invalid_payload_with_retry(self, monkeypatch):
        from backend.agents import review

        calls: list[dict] = []

        def _fake_call(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                bad = _valid_review()
                bad["preguntas"] = bad["preguntas"][:4]  # menos de 5 → inválido
                return (bad, _usage())
            return (_valid_review(), _usage())

        monkeypatch.setattr(review, "call_openrouter_chat", _fake_call)

        result, _ = review.run_review_or(api_key="sk-or-v1-test", explainer_content={}, part_title="P1")

        assert len(result["preguntas"]) == 5
        assert len(calls) == 2


# ---------------------------------------------------------------------------
# Agent: DeepSeek
# ---------------------------------------------------------------------------

class TestReviewAgentDeepSeek:
    def test_run_review_ds_uses_json_contract_and_validates(self, monkeypatch):
        from backend.agents import review

        captured: dict = {}

        def _fake_call(**kwargs):
            captured.update(kwargs)
            return (_valid_review(), _usage(cost_usd=0.00001))

        monkeypatch.setattr(review, "call_deepseek_chat", _fake_call)

        result, usage = review.run_review_ds(
            api_key="ds-key",
            explainer_content={"ok": True},
            part_title="Parte 1",
        )

        assert len(result["preguntas"]) == 5
        assert usage.cost_usd == 0.00001
        assert captured["response_format"] == "json_object"
        assert captured["model"] == "deepseek-v4-flash"
        assert "preguntas" in captured["json_retry_instruction"]

    def test_run_review_ds_corrects_invalid_payload_with_retry(self, monkeypatch):
        from backend.agents import review

        calls: list[dict] = []

        def _fake_call(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return ({"preguntas": "not-a-list"}, _usage())
            return (_valid_review(), _usage())

        monkeypatch.setattr(review, "call_deepseek_chat", _fake_call)

        result, _ = review.run_review_ds(api_key="ds-key", explainer_content={}, part_title="P1")

        assert len(result["preguntas"]) == 5
        assert len(calls) == 2
