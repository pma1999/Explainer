from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import requests

from backend.deepseek_client import DeepSeekError, call_deepseek_chat


def _make_response(*, status_code: int, payload: dict | None = None, text: str | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text if text is not None else json.dumps(payload or {})
    response.json.return_value = payload or {}
    response.headers = {}
    return response


def _success_payload(content: str, *, prompt_tokens: int = 13, completion_tokens: int = 8) -> dict:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "completion_tokens_details": {"reasoning_tokens": 3},
        },
    }


def test_call_deepseek_chat_sends_thinking_max_reasoning_and_json_mode(monkeypatch):
    captured: dict = {}

    def _fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _make_response(status_code=200, payload=_success_payload('{"ok": true}'))

    monkeypatch.setattr(requests, "post", _fake_post)

    content, usage = call_deepseek_chat(
        messages=[{"role": "user", "content": "Hola"}],
        model="deepseek-v4-pro",
        system_prompt="Devuelve JSON",
        api_key="sk-deepseek-test",
        response_format="json_object",
        max_retries=1,
    )

    assert content == {"ok": True}
    assert usage.prompt_token_count == 13
    assert usage.candidates_token_count == 8
    assert usage.thoughts_token_count == 3
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-deepseek-test"
    assert captured["json"]["model"] == "deepseek-v4-pro"
    assert captured["json"]["thinking"] == {"type": "enabled"}
    assert captured["json"]["reasoning_effort"] == "max"
    assert captured["json"]["response_format"] == {"type": "json_object"}


def test_call_deepseek_chat_retries_invalid_json_conversationally(monkeypatch):
    responses = [
        _make_response(status_code=200, payload=_success_payload("not-json")),
        _make_response(status_code=200, payload=_success_payload('{"ok": true}')),
    ]
    requests_seen: list[dict] = []
    sleep_calls: list[int] = []

    def _fake_post(url, headers, json, timeout):
        requests_seen.append(json.copy())
        return responses.pop(0)

    monkeypatch.setattr(requests, "post", _fake_post)
    monkeypatch.setattr("backend.deepseek_client.time.sleep", lambda seconds: sleep_calls.append(seconds))

    content, _usage = call_deepseek_chat(
        messages=[{"role": "user", "content": "Hola"}],
        model="deepseek-v4-flash",
        system_prompt="Devuelve JSON",
        api_key="sk-deepseek-test",
        response_format="json_object",
        max_retries=2,
        json_retry_instruction='{"ok": boolean}',
    )

    assert content == {"ok": True}
    assert sleep_calls == [2]
    assert len(requests_seen) == 2
    assert requests_seen[1]["messages"][-2] == {"role": "assistant", "content": "not-json"}
    assert "respuesta anterior no ha pasado la validación" in requests_seen[1]["messages"][-1]["content"]
    assert '{"ok": boolean}' in requests_seen[1]["messages"][-1]["content"]


def test_call_deepseek_chat_executes_tool_calls_and_returns_final_json(monkeypatch):
    tool_call_payload = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "tavily_search",
                                "arguments": '{"query":"DeepSeek V4","max_results":2}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }
    responses = [
        _make_response(status_code=200, payload=tool_call_payload),
        _make_response(status_code=200, payload=_success_payload('{"ok": true}', prompt_tokens=7, completion_tokens=4)),
    ]
    requests_seen: list[dict] = []

    def _fake_post(url, headers, json, timeout):
        requests_seen.append(json.copy())
        return responses.pop(0)

    monkeypatch.setattr(requests, "post", _fake_post)

    content, usage = call_deepseek_chat(
        messages=[{"role": "user", "content": "Busca"}],
        model="deepseek-v4-flash",
        system_prompt="Devuelve JSON",
        api_key="sk-deepseek-test",
        response_format="json_object",
        tools=[{"type": "function", "function": {"name": "tavily_search", "parameters": {"type": "object"}}}],
        tool_handlers={"tavily_search": lambda args: {"query": args["query"], "results": []}},
        max_retries=1,
    )

    assert content == {"ok": True}
    assert usage.total_token_count == 23
    assert usage.server_tool_use == {"tavily_search_requests": 1}
    assert requests_seen[1]["messages"][-2]["role"] == "assistant"
    assert requests_seen[1]["messages"][-2]["tool_calls"][0]["id"] == "call_1"
    assert requests_seen[1]["messages"][-1]["role"] == "tool"
    assert requests_seen[1]["messages"][-1]["tool_call_id"] == "call_1"
    assert "DeepSeek V4" in requests_seen[1]["messages"][-1]["content"]


def test_call_deepseek_chat_forces_final_response_after_tool_round_limit(monkeypatch):
    def _tool_call_payload(call_id: str, query: str) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": "tavily_search",
                                    "arguments": json.dumps({"query": query}),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }

    responses = [
        _make_response(status_code=200, payload=_tool_call_payload("call_1", "primera")),
        _make_response(status_code=200, payload=_tool_call_payload("call_2", "segunda")),
        _make_response(status_code=200, payload=_success_payload('{"ok": true}', prompt_tokens=7, completion_tokens=4)),
    ]
    requests_seen: list[dict] = []

    def _fake_post(url, headers, json, timeout):
        requests_seen.append(json.copy())
        return responses.pop(0)

    monkeypatch.setattr(requests, "post", _fake_post)
    monkeypatch.setattr("backend.deepseek_client.time.sleep", lambda seconds: None)

    content, usage = call_deepseek_chat(
        messages=[{"role": "user", "content": "Busca"}],
        model="deepseek-v4-flash",
        system_prompt="Devuelve JSON",
        api_key="sk-deepseek-test",
        response_format="json_object",
        tools=[{"type": "function", "function": {"name": "tavily_search", "parameters": {"type": "object"}}}],
        tool_handlers={"tavily_search": lambda args: {"query": args["query"], "results": []}},
        max_retries=1,
        max_tool_rounds=1,
    )

    assert content == {"ok": True}
    assert usage.server_tool_use == {"tavily_search_requests": 1}
    assert len(requests_seen) == 3
    assert "tools" in requests_seen[1]
    assert "tools" not in requests_seen[2]
    assert "No solicites más herramientas" in requests_seen[2]["messages"][-1]["content"]


def test_call_deepseek_chat_falls_back_from_reasoning_max_to_high(monkeypatch):
    responses = [
        _make_response(
            status_code=400,
            payload={"error": {"message": "reasoning_effort max is not supported"}},
            text='{"error":{"message":"reasoning_effort max is not supported"}}',
        ),
        _make_response(status_code=200, payload=_success_payload("texto")),
    ]
    reasoning_seen: list[str] = []

    def _fake_post(url, headers, json, timeout):
        reasoning_seen.append(json["reasoning_effort"])
        return responses.pop(0)

    monkeypatch.setattr(requests, "post", _fake_post)

    content, _usage = call_deepseek_chat(
        messages=[{"role": "user", "content": "Hola"}],
        model="deepseek-v4-pro",
        system_prompt="Devuelve texto",
        api_key="sk-deepseek-test",
        max_retries=2,
    )

    assert content == "texto"
    assert reasoning_seen == ["max", "high"]


def test_call_deepseek_chat_reasoning_fallback_does_not_consume_retry_budget(monkeypatch):
    responses = [
        _make_response(
            status_code=400,
            payload={"error": {"message": "reasoning_effort max is not supported"}},
            text='{"error":{"message":"reasoning_effort max is not supported"}}',
        ),
        _make_response(status_code=200, payload=_success_payload("texto")),
    ]
    reasoning_seen: list[str] = []

    def _fake_post(url, headers, json, timeout):
        reasoning_seen.append(json["reasoning_effort"])
        return responses.pop(0)

    monkeypatch.setattr(requests, "post", _fake_post)

    content, _usage = call_deepseek_chat(
        messages=[{"role": "user", "content": "Hola"}],
        model="deepseek-v4-pro",
        system_prompt="Devuelve texto",
        api_key="sk-deepseek-test",
        max_retries=1,
    )

    assert content == "texto"
    assert reasoning_seen == ["max", "high"]


def test_call_deepseek_chat_raises_on_non_object_json(monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: _make_response(status_code=200, payload=_success_payload('["x"]')),
    )
    monkeypatch.setattr("backend.deepseek_client.time.sleep", lambda seconds: None)

    with pytest.raises(DeepSeekError, match="no un objeto JSON"):
        call_deepseek_chat(
            messages=[{"role": "user", "content": "Hola"}],
            model="deepseek-v4-flash",
            system_prompt="Devuelve JSON",
            api_key="sk-deepseek-test",
            response_format="json_object",
            max_retries=1,
        )
