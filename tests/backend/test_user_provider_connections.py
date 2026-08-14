"""Unit tests for the Codex (ChatGPT) provider connection storage.

Covers the frozen T01 contract:
- get_user_provider_connection / upsert_user_provider_connection / delete_user_provider_connection
- the codex fields added to get_user_api_key_status

The Supabase client is mocked (no network), following the pattern of
tests/backend/test_supabase_pdf_ocr_cache.py / test_supabase_data.py.
"""

from __future__ import annotations

import json

import pytest
from unittest.mock import MagicMock, patch

from backend.crypto import decrypt_user_api_key, encrypt_user_api_key
from backend.supabase_data import (
    PROVIDER_CODEX,
    delete_user_provider_connection,
    get_user_api_key_status,
    get_user_provider_connection,
    upsert_user_provider_connection,
)


def _result(data):
    response = MagicMock()
    response.data = data
    return response


def _table_chain(client: MagicMock) -> MagicMock:
    return client.table.return_value


class TestProviderConstant:
    def test_provider_codex_constant(self):
        assert PROVIDER_CODEX == "codex"


class TestUpsertUserProviderConnection:
    def test_upsert_passes_encrypted_blob_through_and_targets_user_id(self):
        client = MagicMock()
        encrypted = "gAAAAABfake-fernettoken-from-caller"
        with patch("backend.supabase_data._client", return_value=client):
            upsert_user_provider_connection(
                "user-123",
                status="linked",
                encrypted_credentials=encrypted,
                login_id="login-1",
                plan_type="chatgpt_plus",
                last_error=None,
            )
        call = _table_chain(client).upsert.call_args
        assert call.kwargs["on_conflict"] == "user_id"
        row = call.args[0]
        assert row["user_id"] == "user-123"
        assert row["provider"] == PROVIDER_CODEX
        assert row["status"] == "linked"
        # Contrato documentado: el caller cifra; la función acepta el blob tal cual.
        assert row["encrypted_credentials"] == encrypted
        assert row["login_id"] == "login-1"
        assert row["plan_type"] == "chatgpt_plus"
        assert row["last_error"] is None

    def test_upsert_defaults_are_none(self):
        client = MagicMock()
        with patch("backend.supabase_data._client", return_value=client):
            upsert_user_provider_connection("user-123", status="pending")
        row = _table_chain(client).upsert.call_args.args[0]
        assert row["status"] == "pending"
        assert row["encrypted_credentials"] is None
        assert row["login_id"] is None
        assert row["plan_type"] is None
        assert row["last_error"] is None

    def test_upsert_refreshes_updated_at(self):
        client = MagicMock()
        with patch("backend.supabase_data._client", return_value=client):
            with patch("backend.supabase_data._now_iso", return_value="2026-08-14T12:00:00+00:00"):
                upsert_user_provider_connection("user-123", status="pending")
        row = _table_chain(client).upsert.call_args.args[0]
        assert row["updated_at"] == "2026-08-14T12:00:00+00:00"

    def test_upsert_executes(self):
        client = MagicMock()
        with patch("backend.supabase_data._client", return_value=client):
            upsert_user_provider_connection("user-123", status="none")
        _table_chain(client).upsert.return_value.execute.assert_called_once()

    def test_upsert_propagates_supabase_errors(self):
        # Caso crítico documentado: una escritura fallida debe llegar al caller
        # (el flujo de vínculo necesita saber que nada se persistió).
        client = MagicMock()
        _table_chain(client).upsert.side_effect = RuntimeError("supabase down")
        with patch("backend.supabase_data._client", return_value=client):
            with pytest.raises(RuntimeError):
                upsert_user_provider_connection("user-123", status="linked")


class TestGetUserProviderConnection:
    def test_get_returns_full_row_when_present(self):
        client = MagicMock()
        row = {
            "user_id": "user-123",
            "provider": "codex",
            "status": "linked",
            "encrypted_credentials": "fernet-token",
            "login_id": None,
            "plan_type": "chatgpt_plus",
            "last_error": None,
            "created_at": "2026-08-14T10:00:00+00:00",
            "updated_at": "2026-08-14T12:00:00+00:00",
        }
        chain = _table_chain(client).select.return_value.eq.return_value
        chain.maybe_single.return_value.execute.return_value = _result([row])
        with patch("backend.supabase_data._client", return_value=client):
            out = get_user_provider_connection("user-123")
        assert out == row
        assert out["status"] == "linked"

    def test_get_returns_none_when_missing(self):
        client = MagicMock()
        chain = _table_chain(client).select.return_value.eq.return_value
        chain.maybe_single.return_value.execute.return_value = _result([])
        with patch("backend.supabase_data._client", return_value=client):
            out = get_user_provider_connection("user-123")
        assert out is None

    def test_get_returns_none_on_supabase_error(self):
        client = MagicMock()
        _table_chain(client).select.side_effect = RuntimeError("supabase down")
        with patch("backend.supabase_data._client", return_value=client):
            out = get_user_provider_connection("user-123")
        assert out is None


class TestDeleteUserProviderConnection:
    def test_delete_returns_true_when_row_exists(self):
        client = MagicMock()
        chain = _table_chain(client).select.return_value.eq.return_value
        chain.maybe_single.return_value.execute.return_value = _result([{"user_id": "user-123"}])
        with patch("backend.supabase_data._client", return_value=client):
            deleted = delete_user_provider_connection("user-123")
        assert deleted is True
        _table_chain(client).delete.return_value.eq.return_value.execute.assert_called_once()

    def test_delete_is_idempotent_when_missing(self):
        client = MagicMock()
        chain = _table_chain(client).select.return_value.eq.return_value
        chain.maybe_single.return_value.execute.return_value = _result([])
        with patch("backend.supabase_data._client", return_value=client):
            deleted = delete_user_provider_connection("user-123")
        assert deleted is False
        _table_chain(client).delete.return_value.eq.return_value.execute.assert_not_called()

    def test_delete_returns_false_on_supabase_error(self):
        client = MagicMock()
        _table_chain(client).select.side_effect = RuntimeError("supabase down")
        with patch("backend.supabase_data._client", return_value=client):
            deleted = delete_user_provider_connection("user-123")
        assert deleted is False


class TestEncryptionRoundTrip:
    def test_encrypt_store_read_decrypt_round_trip(self):
        """The exact round-trip the link flow (T04) will perform."""
        user_id = "user-123"
        auth_json = json.dumps({"access_token": "tok-abc", "refresh_token": "ref-xyz"})
        encrypted = encrypt_user_api_key(auth_json, user_id)
        assert encrypted != auth_json  # nunca texto plano

        client = MagicMock()
        stored: dict = {}

        def _capture(row, **kwargs):
            stored["row"] = dict(row)
            return MagicMock()

        _table_chain(client).upsert.side_effect = _capture
        with patch("backend.supabase_data._client", return_value=client):
            upsert_user_provider_connection(
                user_id,
                status="linked",
                encrypted_credentials=encrypted,
                plan_type="chatgpt_plus",
            )
            chain = _table_chain(client).select.return_value.eq.return_value
            chain.maybe_single.return_value.execute.return_value = _result([stored["row"]])
            row = get_user_provider_connection(user_id)

        assert row["encrypted_credentials"] == encrypted
        decrypted = decrypt_user_api_key(row["encrypted_credentials"], user_id)
        assert json.loads(decrypted) == json.loads(auth_json)


class TestGetUserApiKeyStatusCodexFields:
    def test_status_combines_existing_keys_and_codex_link(self):
        client = MagicMock()
        chain = _table_chain(client).select.return_value.eq.return_value
        chain.execute.return_value = _result(
            [
                {"provider": "google_gemini", "updated_at": "2026-01-01T00:00:00Z"},
                {"provider": "deepseek", "updated_at": "2026-02-01T00:00:00Z"},
            ]
        )
        chain.maybe_single.return_value.execute.return_value = _result(
            [
                {
                    "status": "linked",
                    "plan_type": "chatgpt_plus",
                    "updated_at": "2026-08-14T12:00:00Z",
                }
            ]
        )
        with patch("backend.supabase_data._client", return_value=client):
            status = get_user_api_key_status("user-123")

        # Campos existentes intactos
        assert status["has_api_key"] is True
        assert status["provider"] == "google_gemini"
        assert status["updated_at"] == "2026-01-01T00:00:00Z"
        assert status["has_deepseek_key"] is True
        assert status["deepseek_updated_at"] == "2026-02-01T00:00:00Z"
        assert status["has_openrouter_key"] is False
        assert status["has_tavily_key"] is False
        # Campos codex nuevos
        assert status["has_codex_link"] is True
        assert status["codex_status"] == "linked"
        assert status["codex_plan_type"] == "chatgpt_plus"
        assert status["codex_updated_at"] == "2026-08-14T12:00:00Z"

    def test_status_pending_means_no_active_link(self):
        client = MagicMock()
        chain = _table_chain(client).select.return_value.eq.return_value
        chain.execute.return_value = _result([])
        chain.maybe_single.return_value.execute.return_value = _result(
            [{"status": "pending", "plan_type": None, "updated_at": "2026-08-14T12:00:00Z"}]
        )
        with patch("backend.supabase_data._client", return_value=client):
            status = get_user_api_key_status("user-123")
        assert status["has_codex_link"] is False
        assert status["codex_status"] == "pending"
        assert status["codex_plan_type"] is None

    def test_status_safe_defaults_without_connection_row(self):
        client = MagicMock()
        chain = _table_chain(client).select.return_value.eq.return_value
        chain.execute.return_value = _result(
            [{"provider": "google_gemini", "updated_at": "2026-01-01T00:00:00Z"}]
        )
        chain.maybe_single.return_value.execute.return_value = _result([])
        with patch("backend.supabase_data._client", return_value=client):
            status = get_user_api_key_status("user-123")
        assert status["has_api_key"] is True
        assert status["has_codex_link"] is False
        assert status["codex_status"] == "none"
        assert status["codex_plan_type"] is None
        assert status["codex_updated_at"] is None

    def test_status_safe_defaults_on_supabase_error(self):
        client = MagicMock()
        _table_chain(client).select.side_effect = RuntimeError("supabase down")
        with patch("backend.supabase_data._client", return_value=client):
            status = get_user_api_key_status("user-123")
        assert status["has_api_key"] is False
        assert status["has_codex_link"] is False
        assert status["codex_status"] == "none"
        assert status["codex_plan_type"] is None
        assert status["codex_updated_at"] is None
        # Ningún campo existente puede faltar ni cambiar de forma
        for key in (
            "has_api_key",
            "provider",
            "updated_at",
            "has_openrouter_key",
            "openrouter_updated_at",
            "has_mistral_key",
            "mistral_updated_at",
            "has_deepseek_key",
            "deepseek_updated_at",
            "has_tavily_key",
            "tavily_updated_at",
        ):
            assert key in status
