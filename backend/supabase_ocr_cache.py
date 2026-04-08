"""OpenRouter PDF OCR parse cache rows in Supabase Postgres (jsonb + optimistic locking)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.supabase_data import _client

logger = logging.getLogger("backend.supabase_ocr_cache")

TABLE_NAME = "openrouter_pdf_ocr_cache"
MAX_WRITE_ATTEMPTS = 12


def fetch_cache(source_sha256: str, engine: str) -> tuple[dict[str, Any] | None, int | None]:
    """Return (payload dict, row_version) or (None, None) if missing."""
    client = _client()
    result = (
        client.table(TABLE_NAME)
        .select("payload, row_version")
        .eq("source_sha256", source_sha256)
        .eq("engine", engine)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return None, None
    row = rows[0]
    payload = row.get("payload")
    rv = row.get("row_version")
    if not isinstance(payload, dict):
        return None, None
    if not isinstance(rv, int):
        return None, None
    return payload, rv


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def try_write_cache(
    source_sha256: str,
    engine: str,
    payload: dict[str, Any],
    expected_row_version: int | None,
) -> tuple[bool, int | None]:
    """
    Insert or update cache row. Optimistic update requires matching expected_row_version.

    Returns (success, new_row_version on success). On conflict (insert race or stale
    version), returns (False, None) so the caller can refetch and merge.
    """
    client = _client()
    now_iso = _now_iso()

    if expected_row_version is None:
        try:
            client.table(TABLE_NAME).insert(
                {
                    "source_sha256": source_sha256,
                    "engine": engine,
                    "payload": payload,
                    "row_version": 1,
                    "updated_at": now_iso,
                }
            ).execute()
            return True, 1
        except Exception as exc:
            if _is_unique_violation(exc):
                logger.debug(
                    "OCR cache insert race; caller should refetch",
                    extra={"source_sha256": source_sha256[:16], "engine": engine},
                )
                return False, None
            raise

    res = (
        client.table(TABLE_NAME)
        .update(
            {
                "payload": payload,
                "row_version": expected_row_version + 1,
                "updated_at": now_iso,
            }
        )
        .eq("source_sha256", source_sha256)
        .eq("engine", engine)
        .eq("row_version", expected_row_version)
        .execute()
    )
    updated = res.data or []
    if not updated:
        return False, None
    new_row = updated[0]
    new_v = new_row.get("row_version")
    if isinstance(new_v, int):
        return True, new_v
    return True, expected_row_version + 1


def _is_unique_violation(exc: Exception) -> bool:
    msg = str(exc).lower()
    if "duplicate" in msg or "unique" in msg:
        return True
    if "23505" in str(exc):
        return True
    c = getattr(exc, "code", None)
    if c == "23505":
        return True
    return False


def supabase_cache_uri(source_sha256: str, engine: str) -> str:
    """Stable log/trace identifier for Supabase-backed cache entries."""
    return f"supabase:{TABLE_NAME}/{source_sha256}/{engine}"
