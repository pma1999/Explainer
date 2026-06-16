"""DeepSeek-direct retries must behave as a single growing conversation.

The goal is maximal prefix-cache reuse: across retries the system prompt and the
first user message (which carries the expensive source) stay byte-identical, and
each retry only appends the previous raw assistant turn plus a short feedback turn.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from backend.agents import completeness_validator
from backend.agents import explainer_deepseek
from backend.agents import segmentador


def _usage():
    return SimpleNamespace(
        prompt_token_count=10,
        candidates_token_count=5,
        thoughts_token_count=2,
        total_token_count=17,
        cost_usd=None,
    )


def _subpart_payload():
    return {
        "desarrollo": [
            {
                "titulo_seccion": "S1",
                "explicacion_introductoria": "Cuerpo",
                "subsecciones": [
                    {"titulo_subseccion": "SS1", "explicacion_detallada": "Detalle"}
                ],
            }
        ]
    }


def _result_for(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        content=dict(payload),
        usage=_usage(),
        assistant_message=SimpleNamespace(content=json.dumps(payload), tool_calls=None),
    )


def test_subpart_explainer_ds_retry_is_a_conversation(monkeypatch, tmp_path):
    calls: list[dict] = []
    payload = _subpart_payload()

    def _fake_full(**kwargs):
        calls.append(
            {
                "system_prompt": kwargs["system_prompt"],
                "messages": [dict(m) for m in kwargs["messages"]],
            }
        )
        return _result_for(payload)

    monkeypatch.setattr(explainer_deepseek, "call_deepseek_chat_full", _fake_full)

    reports = [
        completeness_validator.ExplainerValidationReport(
            is_complete=True,
            scope_status="violation",
            reason="Invade la subparte vecina.",
            offending_fragments=("vecino",),
            retry_instructions="Retira el desarrollo del vecino.",
        ),
        completeness_validator.ExplainerValidationReport(
            is_complete=True,
            scope_status="ok",
            reason="Corregida.",
        ),
    ]
    monkeypatch.setattr(
        completeness_validator,
        "check_explainer_validation_ds",
        lambda *a, **k: (reports.pop(0), _usage()),
    )

    source = tmp_path / "source.txt"
    source.write_text("FUENTE_UNICA_DE_PRUEBA", encoding="utf-8")

    result, usage, validator_usages = explainer_deepseek.run_subpart_explainer_ds_validated(
        str(source),
        "Identificación de prueba",
        api_key="sk-ds-test",
        validator_api_key="sk-ds-test",
        mime_type="text/plain",
    )

    assert result["desarrollo"]
    assert len(calls) == 2  # initial + 1 regeneration

    # System prompt is byte-identical across rounds (never mutated with a retry suffix).
    assert calls[0]["system_prompt"] == calls[1]["system_prompt"]

    # The first user message (with the source) is byte-identical on the retry.
    assert calls[1]["messages"][0] == calls[0]["messages"][0]
    assert calls[0]["messages"][0]["role"] == "user"
    assert "FUENTE_UNICA_DE_PRUEBA" in calls[0]["messages"][0]["content"]

    # Round 2 is a real conversation: [user0, assistant0, user_feedback].
    assert [m["role"] for m in calls[1]["messages"]] == ["user", "assistant", "user"]
    assert calls[1]["messages"][1]["content"] == json.dumps(payload)

    # The feedback turn carries the validator reason but does NOT resend the source.
    feedback = calls[1]["messages"][2]["content"]
    assert "Retira el desarrollo del vecino." in feedback
    assert "FUENTE_UNICA_DE_PRUEBA" not in feedback


def test_run_segmentador_ds_retry_appends_correction_without_resending_source(monkeypatch):
    calls: list[dict] = []
    content = {"partes": [], "decision_num_partes": 1}

    def _fake_full(**kwargs):
        calls.append(
            {
                "system_prompt": kwargs["system_prompt"],
                "messages": [dict(m) for m in kwargs["messages"]],
            }
        )
        return _result_for(content)

    monkeypatch.setattr(segmentador, "call_deepseek_chat_full", _fake_full)

    _, _, conversation = segmentador.run_segmentador_ds(
        api_key="sk-ds-test",
        source_text="<pagina_1>\nFUENTE_OCR_SEGMENTADOR\n</pagina_1>",
        description="Procesar todo",
        source_kind="pdf",
    )
    assert conversation[0]["role"] == "user"
    assert "FUENTE_OCR_SEGMENTADOR" in conversation[0]["content"]
    assert conversation[-1]["role"] == "assistant"

    _, _, conversation2 = segmentador.run_segmentador_ds(
        api_key="sk-ds-test",
        source_text="IGNORADO_EN_RETRY",
        description="IGNORADO_EN_RETRY",
        source_kind="pdf",
        conversation=conversation,
        correction="Corrige los rangos de página de las partes.",
    )

    sent = calls[1]["messages"]
    # Same system prompt + identical first user turn (source cached, not resent).
    assert calls[0]["system_prompt"] == calls[1]["system_prompt"]
    assert sent[0] == calls[0]["messages"][0]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert sent[2]["content"] == "Corrige los rangos de página de las partes."
    assert "FUENTE_OCR_SEGMENTADOR" not in sent[2]["content"]
    assert "IGNORADO_EN_RETRY" not in sent[2]["content"]
