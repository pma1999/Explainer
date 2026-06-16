"""Ensure DeepSeek explainer honors target_language like OpenRouter."""
from __future__ import annotations

from types import SimpleNamespace

from backend.agents import explainer_deepseek


def _usage():
    return SimpleNamespace(
        prompt_token_count=1,
        candidates_token_count=1,
        thoughts_token_count=0,
        total_token_count=2,
        cost_usd=None,
    )


def test_run_explainer_ds_uses_target_language_in_system_prompt(monkeypatch, tmp_path):
    captured: dict = {}
    source = tmp_path / "source.txt"
    source.write_text("Fuente de prueba.", encoding="utf-8")

    def fake_call(**kwargs):
        captured.update(kwargs)
        return (
            {
                "introduccion": "Intro",
                "desarrollo": [
                    {
                        "titulo_seccion": "S1",
                        "explicacion_introductoria": "Cuerpo",
                        "subsecciones": [
                            {
                                "titulo_subseccion": "SS1",
                                "explicacion_detallada": "Detalle",
                            }
                        ],
                    }
                ],
                "conclusion": "Fin",
                "conexiones_contextuales": [],
            },
            _usage(),
        )

    monkeypatch.setattr("backend.agents.explainer_deepseek.call_deepseek_chat", fake_call)

    explainer_deepseek.run_explainer_ds(
        str(source),
        "Identificación de prueba",
        api_key="sk-ds-test",
        mime_type="text/plain",
        target_language="en",
    )

    system_prompt = captured["system_prompt"]
    assert "English" in system_prompt
    assert "castellano de España" not in system_prompt.lower()


def test_run_subpart_explainer_ds_uses_target_language_in_system_prompt(monkeypatch, tmp_path):
    captured: dict = {}
    source = tmp_path / "source.txt"
    source.write_text("Fuente de prueba.", encoding="utf-8")

    def fake_call(**kwargs):
        captured.update(kwargs)
        return (
            {
                "desarrollo": [
                    {
                        "titulo_seccion": "S1",
                        "explicacion_introductoria": "Cuerpo",
                        "subsecciones": [
                            {
                                "titulo_subseccion": "SS1",
                                "explicacion_detallada": "Detalle",
                            }
                        ],
                    }
                ],
            },
            _usage(),
        )

    monkeypatch.setattr("backend.agents.explainer_deepseek.call_deepseek_chat", fake_call)

    explainer_deepseek.run_subpart_explainer_ds(
        str(source),
        "Identificación de prueba",
        api_key="sk-ds-test",
        mime_type="text/plain",
        target_language="fr",
    )

    system_prompt = captured["system_prompt"]
    assert "French" in system_prompt
    assert "castellano de España" not in system_prompt.lower()
