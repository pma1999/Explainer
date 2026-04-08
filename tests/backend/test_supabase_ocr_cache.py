"""Tests for Supabase-backed OpenRouter PDF OCR cache."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.supabase_ocr_cache import (
    fetch_cache,
    supabase_cache_uri,
    try_write_cache,
)


def _table_chain(client: MagicMock):
    return client.table.return_value


def test_supabase_cache_uri():
    assert supabase_cache_uri("deadbeef", "mistral-ocr") == (
        "supabase:openrouter_pdf_ocr_cache/deadbeef/mistral-ocr"
    )


def test_fetch_cache_miss():
    client = MagicMock()
    _table_chain(client).select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[])
    )
    with patch("backend.supabase_ocr_cache._client", return_value=client):
        payload, rv = fetch_cache("sha256hex", "mistral-ocr")
    assert payload is None
    assert rv is None


def test_fetch_cache_hit():
    client = MagicMock()
    _table_chain(client).select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(
            data=[
                {
                    "payload": {"version": 2, "source_sha256": "sha256hex"},
                    "row_version": 7,
                }
            ]
        )
    )
    with patch("backend.supabase_ocr_cache._client", return_value=client):
        payload, rv = fetch_cache("sha256hex", "mistral-ocr")
    assert payload == {"version": 2, "source_sha256": "sha256hex"}
    assert rv == 7


def test_fetch_cache_invalid_payload_treated_as_miss():
    client = MagicMock()
    _table_chain(client).select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{"payload": "not-a-dict", "row_version": 1}])
    )
    with patch("backend.supabase_ocr_cache._client", return_value=client):
        payload, rv = fetch_cache("sha256hex", "mistral-ocr")
    assert payload is None
    assert rv is None


def test_try_write_cache_insert_ok():
    client = MagicMock()
    _table_chain(client).insert.return_value.execute.return_value = MagicMock()
    payload = {"version": 2, "engine": "mistral-ocr"}
    with patch("backend.supabase_ocr_cache._client", return_value=client):
        ok, new_v = try_write_cache("sha256hex", "mistral-ocr", payload, None)
    assert ok is True
    assert new_v == 1
    insert_kw = client.table.return_value.insert.call_args[0][0]
    assert insert_kw["row_version"] == 1
    assert insert_kw["payload"] == payload


def test_try_write_cache_insert_duplicate_returns_false():
    client = MagicMock()

    def _raise_insert(*args, **kwargs):
        err = Exception("duplicate key value violates unique constraint")
        setattr(err, "code", "23505")
        raise err

    _table_chain(client).insert.return_value.execute.side_effect = _raise_insert
    with patch("backend.supabase_ocr_cache._client", return_value=client):
        ok, new_v = try_write_cache("sha256hex", "mistral-ocr", {"version": 2}, None)
    assert ok is False
    assert new_v is None


def test_try_write_cache_update_ok():
    client = MagicMock()
    _table_chain(client).update.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[{"row_version": 3, "payload": {}}])
    )
    payload = {"version": 2}
    with patch("backend.supabase_ocr_cache._client", return_value=client):
        ok, new_v = try_write_cache("sha256hex", "mistral-ocr", payload, 2)
    assert ok is True
    assert new_v == 3


def test_try_write_cache_update_conflict_empty_data():
    client = MagicMock()
    _table_chain(client).update.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[])
    )
    with patch("backend.supabase_ocr_cache._client", return_value=client):
        ok, new_v = try_write_cache("sha256hex", "mistral-ocr", {"version": 2}, 2)
    assert ok is False
    assert new_v is None


def test_try_write_cache_insert_reraises_unknown_error():
    client = MagicMock()
    _table_chain(client).insert.return_value.execute.side_effect = RuntimeError("network down")
    with patch("backend.supabase_ocr_cache._client", return_value=client):
        with pytest.raises(RuntimeError, match="network down"):
            try_write_cache("sha256hex", "mistral-ocr", {"version": 2}, None)
