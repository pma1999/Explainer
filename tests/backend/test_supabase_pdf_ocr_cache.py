"""Tests for Supabase-backed provider-neutral PDF OCR cache."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.supabase_pdf_ocr_cache import fetch_cache, supabase_cache_uri, try_write_cache


def _table_chain(client: MagicMock):
    return client.table.return_value


def _result(data):
    response = MagicMock()
    response.data = data
    return response


def test_supabase_cache_uri_uses_generic_table_name():
    assert supabase_cache_uri("deadbeef", "mistral-native") == (
        "supabase:pdf_ocr_cache/deadbeef/mistral-native"
    )


def test_fetch_cache_miss():
    client = MagicMock()
    _table_chain(client).select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[])
    )
    with patch("backend.supabase_pdf_ocr_cache._client", return_value=client):
        payload, rv = fetch_cache("sha256hex", "mistral-native")
    assert payload is None
    assert rv is None


def test_fetch_cache_returns_payload_and_row_version():
    client = MagicMock()
    _table_chain(client).select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(
            data=[
                {
                    "payload": {"version": 1, "source_sha256": "sha256hex"},
                    "row_version": 7,
                }
            ]
        )
    )
    with patch("backend.supabase_pdf_ocr_cache._client", return_value=client):
        payload, rv = fetch_cache("sha256hex", "mistral-native")
    assert payload == {"version": 1, "source_sha256": "sha256hex"}
    assert rv == 7


def test_fetch_cache_invalid_payload_treated_as_miss():
    client = MagicMock()
    _table_chain(client).select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{"payload": "not-a-dict", "row_version": 1}])
    )
    with patch("backend.supabase_pdf_ocr_cache._client", return_value=client):
        payload, rv = fetch_cache("sha256hex", "mistral-native")
    assert payload is None
    assert rv is None


def test_fetch_cache_invalid_row_version_treated_as_miss():
    client = MagicMock()
    _table_chain(client).select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{"payload": {"version": 1}, "row_version": "1"}])
    )
    with patch("backend.supabase_pdf_ocr_cache._client", return_value=client):
        payload, rv = fetch_cache("sha256hex", "mistral-native")
    assert payload is None
    assert rv is None


def test_try_write_cache_insert_ok():
    client = MagicMock()
    _table_chain(client).insert.return_value.execute.return_value = MagicMock()
    payload = {"version": 2, "engine": "mistral-native"}
    with patch("backend.supabase_pdf_ocr_cache._client", return_value=client):
        ok, new_v = try_write_cache("sha256hex", "mistral-native", payload, None)
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
    with patch("backend.supabase_pdf_ocr_cache._client", return_value=client):
        ok, new_v = try_write_cache("sha256hex", "mistral-native", {"version": 2}, None)
    assert ok is False
    assert new_v is None


def test_try_write_cache_insert_reraises_unknown_error():
    client = MagicMock()
    _table_chain(client).insert.return_value.execute.side_effect = RuntimeError("network down")
    with patch("backend.supabase_pdf_ocr_cache._client", return_value=client):
        with pytest.raises(RuntimeError, match="network down"):
            try_write_cache("sha256hex", "mistral-native", {"version": 2}, None)


def test_try_write_cache_update_ok():
    client = MagicMock()
    _table_chain(client).update.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[{"row_version": 3, "payload": {}}])
    )
    payload = {"version": 2}
    with patch("backend.supabase_pdf_ocr_cache._client", return_value=client):
        ok, new_v = try_write_cache("sha256hex", "mistral-native", payload, 2)
    assert ok is True
    assert new_v == 3
    update_kw = client.table.return_value.update.call_args[0][0]
    assert update_kw["payload"] == payload
    assert update_kw["row_version"] == 3


def test_try_write_cache_update_ok_falls_back_when_row_version_missing_or_non_int():
    client = MagicMock()
    _table_chain(client).update.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[{"payload": {}}])
    )
    with patch("backend.supabase_pdf_ocr_cache._client", return_value=client):
        ok, new_v = try_write_cache("sha256hex", "mistral-native", {"version": 2}, 4)
    assert ok is True
    assert new_v == 5

    client2 = MagicMock()
    _table_chain(client2).update.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[{"row_version": "3"}])
    )
    with patch("backend.supabase_pdf_ocr_cache._client", return_value=client2):
        ok2, new_v2 = try_write_cache("sha256hex", "mistral-native", {"version": 2}, 2)
    assert ok2 is True
    assert new_v2 == 3


def test_try_write_cache_update_conflict_empty_data():
    client = MagicMock()
    _table_chain(client).update.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[])
    )
    with patch("backend.supabase_pdf_ocr_cache._client", return_value=client):
        ok, new_v = try_write_cache("sha256hex", "mistral-native", {"version": 2}, 2)
    assert ok is False
    assert new_v is None
