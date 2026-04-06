from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import requests

from backend.openrouter_client import OpenRouterError, call_openrouter_chat


def _make_response(*, status_code: int, payload: dict | None = None, text: str | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text if text is not None else json.dumps(payload or {})
    response.json.return_value = payload or {}
    return response


def _success_payload(content: str) -> dict:
    return {
        "choices": [
            {
                "message": {"content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 13,
            "completion_tokens": 8,
        },
    }


def test_call_openrouter_chat_json_object_mode_adds_response_healing_and_parses_json(monkeypatch):
    captured_request: dict = {}

    def _fake_post(url, headers, json, timeout):
        captured_request["url"] = url
        captured_request["headers"] = headers
        captured_request["json"] = json
        captured_request["timeout"] = timeout
        return _make_response(
            status_code=200,
            payload=_success_payload(
                '{"introduccion":"Intro","desarrollo":[],"conclusion":"Fin","conexiones_contextuales":[]}'
            ),
        )

    monkeypatch.setattr(requests, "post", _fake_post)

    content, usage = call_openrouter_chat(
        messages=[{"role": "user", "content": "Hola"}],
        model="test/model",
        system_prompt="Devuelve JSON",
        api_key="sk-or-v1-test",
        response_format="json_object",
        plugins=[{"id": "file-parser", "pdf": {"engine": "cloudflare-ai"}}],
        enable_response_healing=True,
    )

    assert content == {
        "introduccion": "Intro",
        "desarrollo": [],
        "conclusion": "Fin",
        "conexiones_contextuales": [],
    }
    assert usage.prompt_token_count == 13
    assert usage.candidates_token_count == 8
    assert captured_request["json"]["response_format"] == {"type": "json_object"}
    assert captured_request["json"]["plugins"] == [
        {"id": "file-parser", "pdf": {"engine": "cloudflare-ai"}},
        {"id": "response-healing"},
    ]


def test_call_openrouter_chat_retries_invalid_json_in_json_mode(monkeypatch):
    responses = [
        _make_response(status_code=200, payload=_success_payload("not-json")),
        _make_response(status_code=200, payload=_success_payload('{"ok": true}')),
    ]
    sleep_calls: list[int] = []

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr("backend.openrouter_client.time.sleep", lambda seconds: sleep_calls.append(seconds))

    content, usage = call_openrouter_chat(
        messages=[{"role": "user", "content": "Hola"}],
        model="test/model",
        system_prompt="Devuelve JSON",
        api_key="sk-or-v1-test",
        response_format="json_object",
        enable_response_healing=True,
        max_retries=2,
    )

    assert content == {"ok": True}
    assert usage.total_token_count == 21
    assert sleep_calls == [2]


def test_call_openrouter_chat_raises_on_non_object_json(monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: _make_response(status_code=200, payload=_success_payload('["x"]')),
    )
    monkeypatch.setattr("backend.openrouter_client.time.sleep", lambda seconds: None)

    with pytest.raises(OpenRouterError, match="no un objeto JSON"):
        call_openrouter_chat(
            messages=[{"role": "user", "content": "Hola"}],
            model="test/model",
            system_prompt="Devuelve JSON",
            api_key="sk-or-v1-test",
            response_format="json_object",
            max_retries=1,
        )


def test_call_openrouter_chat_retries_rate_limit(monkeypatch):
    responses = [
        _make_response(status_code=429, payload={"error": "rate_limited"}),
        _make_response(status_code=200, payload=_success_payload("texto plano")),
    ]
    sleep_calls: list[int] = []

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr("backend.openrouter_client.time.sleep", lambda seconds: sleep_calls.append(seconds))

    content, usage = call_openrouter_chat(
        messages=[{"role": "user", "content": "Hola"}],
        model="test/model",
        system_prompt="Devuelve texto",
        api_key="sk-or-v1-test",
        response_format="text",
        max_retries=2,
    )

    assert content == "texto plano"
    assert usage.total_token_count == 21
    assert sleep_calls == [2]
