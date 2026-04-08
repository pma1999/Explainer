from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import requests
from pypdf import PdfWriter

from backend.openrouter_client import (
    OpenRouterError,
    OpenRouterJsonSchemaResponseFormat,
    call_openrouter_chat,
    call_openrouter_chat_full,
    get_or_prime_pdf_parse_cache,
    render_pdf_page_subset_to_text,
)


def _make_response(*, status_code: int, payload: dict | None = None, text: str | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text if text is not None else json.dumps(payload or {})
    response.json.return_value = payload or {}
    return response


def _success_payload(content: str, *, annotations: list[dict] | None = None) -> dict:
    message = {"content": content}
    if annotations is not None:
        message["annotations"] = annotations
    return {
        "choices": [
            {
                "message": message,
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 13,
            "completion_tokens": 8,
        },
    }


def _pdf_annotations_with_marked_pages(*pages: int) -> list[dict]:
    parts = [
        {
            "type": "text",
            "text": "\n\n".join(
                f"— Página {page} / 10 —\nContenido OCR de la página {page}."
                for page in pages
            ),
        }
    ]
    return [
        {
            "type": "file",
            "file": {
                "hash": "parsed-hash",
                "content": parts,
            },
        }
    ]


def _make_workspace_temp_dir() -> Path:
    base_dir = Path.cwd() / "test_output" / "pytest-openrouter-client"
    temp_dir = base_dir / uuid4().hex
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def _write_test_pdf(path: Path, *, pages: int) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    with open(path, "wb") as f:
        writer.write(f)


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


def test_call_openrouter_chat_json_schema_mode_adds_schema_and_parses_json(monkeypatch):
    captured_request: dict = {}

    def _fake_post(url, headers, json, timeout):
        captured_request["json"] = json
        return _make_response(
            status_code=200,
            payload=_success_payload('{"desarrollo": []}'),
        )

    monkeypatch.setattr(requests, "post", _fake_post)

    content, usage = call_openrouter_chat(
        messages=[{"role": "user", "content": "Hola"}],
        model="openai/gpt-5.4-nano",
        system_prompt="Devuelve JSON schema",
        api_key="sk-or-v1-test",
        response_format=OpenRouterJsonSchemaResponseFormat(
            name="subpart_explainer",
            strict=True,
            schema={
                "type": "object",
                "properties": {
                    "desarrollo": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["desarrollo"],
                "additionalProperties": False,
            },
        ),
        enable_response_healing=True,
    )

    assert content == {"desarrollo": []}
    assert usage.total_token_count == 21
    assert captured_request["json"]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "subpart_explainer",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "desarrollo": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["desarrollo"],
                "additionalProperties": False,
            },
        },
    }
    assert captured_request["json"]["plugins"] == [{"id": "response-healing"}]


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


def test_call_openrouter_chat_retries_transient_request_exception(monkeypatch):
    outcomes: list[object] = [
        requests.exceptions.ChunkedEncodingError("Response ended prematurely"),
        _make_response(status_code=200, payload=_success_payload("texto plano")),
    ]
    sleep_calls: list[int] = []

    def _fake_post(*args, **kwargs):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(requests, "post", _fake_post)
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


def test_call_openrouter_chat_does_not_retry_non_retryable_request_exception(monkeypatch):
    sleep_calls: list[int] = []

    def _fake_post(*args, **kwargs):
        raise requests.exceptions.InvalidURL("bad url")

    monkeypatch.setattr(requests, "post", _fake_post)
    monkeypatch.setattr("backend.openrouter_client.time.sleep", lambda seconds: sleep_calls.append(seconds))

    with pytest.raises(OpenRouterError, match="Error de red: bad url"):
        call_openrouter_chat(
            messages=[{"role": "user", "content": "Hola"}],
            model="test/model",
            system_prompt="Devuelve texto",
            api_key="sk-or-v1-test",
            response_format="text",
            max_retries=2,
        )

    assert sleep_calls == []


def test_call_openrouter_chat_retries_when_http_200_payload_has_no_choices(monkeypatch):
    responses = [
        _make_response(
            status_code=200,
            payload={"error": {"message": "provider timeout", "code": 502}},
        ),
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


def test_call_openrouter_chat_raises_useful_error_when_choices_are_missing(monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: _make_response(status_code=200, payload={"id": "bad-response"}),
    )
    monkeypatch.setattr("backend.openrouter_client.time.sleep", lambda seconds: None)

    with pytest.raises(OpenRouterError, match="Respuesta OpenRouter inválida: Falta choices"):
        call_openrouter_chat(
            messages=[{"role": "user", "content": "Hola"}],
            model="test/model",
            system_prompt="Devuelve texto",
            api_key="sk-or-v1-test",
            response_format="text",
            max_retries=1,
        )


def test_call_openrouter_chat_full_preserves_annotations(monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: _make_response(
            status_code=200,
            payload=_success_payload(
                "OK",
                annotations=[
                    {
                        "type": "file",
                        "file": {
                            "hash": "abc123",
                            "name": "document.pdf",
                            "content": [{"type": "text", "text": "Parsed text"}],
                        },
                    }
                ],
            ),
        ),
    )

    result = call_openrouter_chat_full(
        messages=[{"role": "user", "content": "Hola"}],
        model="test/model",
        system_prompt="Devuelve texto",
        api_key="sk-or-v1-test",
        response_format="text",
        max_retries=1,
    )

    assert result.content == "OK"
    assert result.usage.total_token_count == 21
    assert result.assistant_message.annotations == [
        {
            "type": "file",
            "file": {
                "hash": "abc123",
                "name": "document.pdf",
                "content": [{"type": "text", "text": "Parsed text"}],
            },
        }
    ]


def test_get_or_prime_pdf_parse_cache_reuses_disk_cache(monkeypatch):
    temp_dir = _make_workspace_temp_dir()
    pdf_path = temp_dir / "sample.pdf"
    _write_test_pdf(pdf_path, pages=5)
    cache_dir = temp_dir / "cache"

    call_count = {"value": 0}

    def _fake_call_full(**kwargs):
        call_count["value"] += 1
        return type(
            "FakeResult",
            (),
            {
                "content": "OK",
                "usage": type(
                    "FakeUsage",
                    (),
                    {
                        "prompt_token_count": 1,
                        "candidates_token_count": 1,
                        "total_token_count": 2,
                    },
                )(),
                "assistant_message": type(
                    "FakeAssistant",
                    (),
                    {
                        "content": "OK",
                        "annotations": _pdf_annotations_with_marked_pages(1, 2, 3, 4, 5),
                    },
                )(),
            },
        )()

    monkeypatch.setattr("backend.openrouter_client.call_openrouter_chat_full", _fake_call_full)

    try:
        first = get_or_prime_pdf_parse_cache(
            source_path=str(pdf_path),
            api_key="sk-or-v1-test",
            model="test/model",
            engine="mistral-ocr",
            cache_dir=str(cache_dir),
        )
        second = get_or_prime_pdf_parse_cache(
            source_path=str(pdf_path),
            api_key="sk-or-v1-test",
            model="test/model",
            engine="mistral-ocr",
            cache_dir=str(cache_dir),
        )

        assert call_count["value"] == 1
        assert first.cache_hit is False
        assert second.cache_hit is True
        assert first.cached_page_numbers == (1, 2, 3, 4, 5)
        assert second.cached_page_numbers == (1, 2, 3, 4, 5)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_get_or_prime_pdf_parse_cache_builds_page_index_for_expected_pages(monkeypatch):
    temp_dir = _make_workspace_temp_dir()
    pdf_path = temp_dir / "sample.pdf"
    _write_test_pdf(pdf_path, pages=5)
    cache_dir = temp_dir / "cache"

    def _fake_call_full(**kwargs):
        return type(
            "FakeResult",
            (),
            {
                "content": "OK",
                "usage": type(
                    "FakeUsage",
                    (),
                    {
                        "prompt_token_count": 1,
                        "candidates_token_count": 1,
                        "total_token_count": 2,
                    },
                )(),
                "assistant_message": type(
                    "FakeAssistant",
                    (),
                    {
                        "content": "OK",
                        "annotations": _pdf_annotations_with_marked_pages(2, 3, 4),
                    },
                )(),
            },
        )()

    monkeypatch.setattr("backend.openrouter_client.call_openrouter_chat_full", _fake_call_full)

    try:
        cache_entry = get_or_prime_pdf_parse_cache(
            source_path=str(pdf_path),
            api_key="sk-or-v1-test",
            model="test/model",
            engine="mistral-ocr",
            cache_dir=str(cache_dir),
            expected_page_numbers=(2, 3, 4),
        )

        assert cache_entry.cache_hit is False
        assert cache_entry.expected_page_numbers == (2, 3, 4)
        assert cache_entry.cached_page_numbers == (2, 3, 4)
        assert tuple(page.page_number for page in cache_entry.page_index) == (2, 3, 4)

        rendered = render_pdf_page_subset_to_text(
            cache_entry=cache_entry,
            page_numbers=(3, 4),
        )
        assert "Página 3 / 10" in rendered
        assert "Contenido OCR de la página 3." in rendered
        assert "Página 4 / 10" in rendered
        assert "Contenido OCR de la página 4." in rendered
        assert "Página 2 / 10" not in rendered
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_get_or_prime_pdf_parse_cache_only_primes_missing_pages(monkeypatch):
    temp_dir = _make_workspace_temp_dir()
    pdf_path = temp_dir / "sample.pdf"
    _write_test_pdf(pdf_path, pages=5)
    cache_dir = temp_dir / "cache"
    primed_groups: list[tuple[int, ...]] = []

    def _fake_prime_group_recursive(**kwargs):
        page_numbers = tuple(kwargs["page_numbers"])
        primed_groups.append(page_numbers)
        return tuple(
            type(
                "ParsedPage",
                (),
                {
                    "page_number": page_number,
                    "content_parts": (
                        {"type": "text", "text": f"— Página {page_number} / 10 —\nTexto {page_number}"},
                    ),
                },
            )()
            for page_number in page_numbers
        )

    monkeypatch.setattr(
        "backend.openrouter_client._prime_pdf_page_group_recursive",
        _fake_prime_group_recursive,
    )

    try:
        first = get_or_prime_pdf_parse_cache(
            source_path=str(pdf_path),
            api_key="sk-or-v1-test",
            model="test/model",
            engine="mistral-ocr",
            cache_dir=str(cache_dir),
            expected_page_numbers=(2, 4, 5),
        )
        assert first.cache_hit is False
        assert primed_groups == [(2,), (4, 5)]
        assert first.cached_page_numbers == (2, 4, 5)

        primed_groups.clear()
        second = get_or_prime_pdf_parse_cache(
            source_path=str(pdf_path),
            api_key="sk-or-v1-test",
            model="test/model",
            engine="mistral-ocr",
            cache_dir=str(cache_dir),
            expected_page_numbers=(2, 3, 4, 5),
        )
        assert second.cache_hit is False
        assert primed_groups == [(3,)]
        assert second.cached_page_numbers == (2, 3, 4, 5)

        rendered = render_pdf_page_subset_to_text(
            cache_entry=second,
            page_numbers=(2, 3, 4, 5),
        )
        assert "Texto 2" in rendered
        assert "Texto 3" in rendered
        assert "Texto 4" in rendered
        assert "Texto 5" in rendered

        primed_groups.clear()
        third = get_or_prime_pdf_parse_cache(
            source_path=str(pdf_path),
            api_key="sk-or-v1-test",
            model="test/model",
            engine="mistral-ocr",
            cache_dir=str(cache_dir),
            expected_page_numbers=(2, 3, 4, 5),
        )
        assert third.cache_hit is True
        assert primed_groups == []
        assert third.cached_page_numbers == (2, 3, 4, 5)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_render_pdf_page_subset_to_text_raises_when_page_is_missing():
    cache_entry = type(
        "CacheEntry",
        (),
        {
            "page_index": (
                type(
                    "ParsedPage",
                    (),
                    {
                        "page_number": 7,
                        "content_parts": (
                            {"type": "text", "text": "— Página 7 / 10 —\nTexto 7"},
                        ),
                    },
                )(),
            )
        },
    )()

    with pytest.raises(OpenRouterError, match="páginas ausentes"):
        render_pdf_page_subset_to_text(
            cache_entry=cache_entry,
            page_numbers=(7, 8),
        )
