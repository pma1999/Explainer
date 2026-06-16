from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import requests

from backend.tavily_client import TavilyError, search_tavily, tavily_search_tool_result


def _make_response(*, status_code: int, payload: dict | None = None, text: str | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text if text is not None else json.dumps(payload or {})
    response.json.return_value = payload or {}
    response.headers = {}
    return response


def test_search_tavily_posts_bearer_token_and_normalizes_results(monkeypatch):
    captured: dict = {}

    def _fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _make_response(
            status_code=200,
            payload={
                "answer": "Respuesta",
                "results": [
                    {
                        "title": "Recurso",
                        "url": "https://example.com/recurso",
                        "content": "Contenido largo",
                        "score": 0.9,
                        "published_date": "2026-01-01",
                    }
                ],
                "usage": {"searches": 1},
            },
        )

    monkeypatch.setattr(requests, "post", _fake_post)

    result = search_tavily(api_key="tvly-test-key", query=" DeepSeek V4 recursos ", max_results=20)

    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["headers"]["Authorization"] == "Bearer tvly-test-key"
    assert captured["json"]["query"] == "DeepSeek V4 recursos"
    assert captured["json"]["search_depth"] == "advanced"
    assert captured["json"]["max_results"] == 10
    assert captured["json"]["include_usage"] is True
    assert result["answer"] == "Respuesta"
    assert result["results"] == [
        {
            "position": 1,
            "title": "Recurso",
            "url": "https://example.com/recurso",
            "content": "Contenido largo",
            "score": 0.9,
            "published_date": "2026-01-01",
        }
    ]
    assert result["usage"] == {"searches": 1}


def test_search_tavily_retries_rate_limit_with_retry_after(monkeypatch):
    responses = [
        _make_response(status_code=429, payload={"error": "rate_limited"}),
        _make_response(status_code=200, payload={"results": []}),
    ]
    sleep_calls: list[int] = []
    responses[0].headers = {"retry-after": "3"}

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr("backend.tavily_client.time.sleep", lambda seconds: sleep_calls.append(seconds))

    result = search_tavily(api_key="tvly-test-key", query="consulta", max_retries=2)

    assert result["results"] == []
    assert sleep_calls == [3]


def test_search_tavily_rejects_empty_query():
    with pytest.raises(TavilyError, match="vacía"):
        search_tavily(api_key="tvly-test-key", query="   ")


def test_tavily_search_tool_result_maps_tool_arguments(monkeypatch):
    captured: dict = {}

    def _fake_search_tavily(**kwargs):
        captured.update(kwargs)
        return {"query": kwargs["query"], "results": []}

    monkeypatch.setattr("backend.tavily_client.search_tavily", _fake_search_tavily)

    result = tavily_search_tool_result(
        "tvly-test-key",
        {
            "query": "consulta",
            "max_results": 3,
            "search_depth": "basic",
            "include_domains": ["example.com"],
        },
    )

    assert result == {"query": "consulta", "results": []}
    assert captured["api_key"] == "tvly-test-key"
    assert captured["max_results"] == 3
    assert captured["search_depth"] == "basic"
    assert captured["include_domains"] == ["example.com"]
