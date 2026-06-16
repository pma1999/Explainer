"""HTTP client for Tavily Search API."""
from __future__ import annotations

import json
import math
import time
from typing import Any

import requests

from backend.logging_config import get_logger

logger = get_logger("backend.tavily_client")

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_DEFAULT_SEARCH_DEPTH = "advanced"
TAVILY_DEFAULT_MAX_RESULTS = 5
TAVILY_RESULT_CONTENT_LIMIT = 1800


class TavilyError(Exception):
    pass


class TavilyRateLimitError(TavilyError):
    pass


class TavilyServiceError(TavilyError):
    pass


def _is_retryable_requests_exception(exc: requests.exceptions.RequestException) -> bool:
    non_retryable = (
        requests.exceptions.InvalidURL,
        requests.exceptions.InvalidSchema,
        requests.exceptions.MissingSchema,
        requests.exceptions.InvalidHeader,
        requests.exceptions.URLRequired,
        requests.exceptions.TooManyRedirects,
        requests.exceptions.SSLError,
    )
    return not isinstance(exc, non_retryable)


def _retry_after_seconds(value: str | None, fallback: int) -> int:
    if not value:
        return fallback
    try:
        parsed = float(value.strip())
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(parsed) or parsed < 0:
        return fallback
    return int(min(max(parsed, 1), 120))


def _clip_text(value: Any, *, limit: int = TAVILY_RESULT_CONTENT_LIMIT) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _normalize_result(raw: Any, *, index: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    url = raw.get("url") or raw.get("link")
    title = raw.get("title")
    if not isinstance(url, str) or not url.strip():
        return None
    normalized: dict[str, Any] = {
        "position": raw.get("position") if isinstance(raw.get("position"), int) else index,
        "title": title.strip() if isinstance(title, str) and title.strip() else url.strip(),
        "url": url.strip(),
        "content": _clip_text(raw.get("content") or raw.get("snippet") or raw.get("raw_content")),
    }
    score = raw.get("score")
    if isinstance(score, (int, float)) and math.isfinite(float(score)):
        normalized["score"] = float(score)
    published_date = raw.get("published_date")
    if isinstance(published_date, str) and published_date.strip():
        normalized["published_date"] = published_date.strip()
    return normalized


def search_tavily(
    *,
    api_key: str,
    query: str,
    search_depth: str = TAVILY_DEFAULT_SEARCH_DEPTH,
    max_results: int = TAVILY_DEFAULT_MAX_RESULTS,
    include_answer: bool | str = False,
    include_raw_content: bool | str = "markdown",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    time_range: str | None = None,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Run a Tavily search and return a compact normalized payload."""
    key = (api_key or "").strip()
    if not key:
        raise TavilyError("Tavily API key no proporcionada.")
    normalized_query = (query or "").strip()
    if not normalized_query:
        raise TavilyError("Consulta Tavily vacía.")

    try:
        bounded_max_results = max(1, min(int(max_results), 10))
    except (TypeError, ValueError):
        bounded_max_results = TAVILY_DEFAULT_MAX_RESULTS

    payload: dict[str, Any] = {
        "query": normalized_query[:400],
        "search_depth": search_depth if search_depth in {"basic", "advanced"} else TAVILY_DEFAULT_SEARCH_DEPTH,
        "max_results": bounded_max_results,
        "include_answer": include_answer,
        "include_raw_content": include_raw_content,
        "include_usage": True,
    }
    if include_domains:
        payload["include_domains"] = [str(item).strip() for item in include_domains if str(item).strip()]
    if exclude_domains:
        payload["exclude_domains"] = [str(item).strip() for item in exclude_domains if str(item).strip()]
    if time_range in {"day", "week", "month", "year"}:
        payload["time_range"] = time_range

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    last_exc: Exception = TavilyError("No se realizó ningún intento Tavily.")
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(
                TAVILY_SEARCH_URL,
                headers=headers,
                json=payload,
                timeout=30,
            )

            if response.status_code == 429:
                wait = _retry_after_seconds(response.headers.get("retry-after"), min(2 ** attempt, 60))
                logger.warning(
                    "[Tavily] Rate limit 429, reintento %s/%s en %ss",
                    attempt,
                    max_retries,
                    wait,
                )
                last_exc = TavilyRateLimitError(f"Rate limit Tavily en intento {attempt}")
                if attempt < max_retries:
                    time.sleep(wait)
                    continue
                raise last_exc

            if response.status_code in (500, 502, 503, 504):
                wait = min(2 ** attempt, 60)
                logger.warning(
                    "[Tavily] Error servidor %s, reintento %s/%s en %ss",
                    response.status_code,
                    attempt,
                    max_retries,
                    wait,
                )
                last_exc = TavilyServiceError(f"Error Tavily {response.status_code} en intento {attempt}")
                if attempt < max_retries:
                    time.sleep(wait)
                    continue
                raise last_exc

            if response.status_code != 200:
                raise TavilyError(f"Tavily devolvió HTTP {response.status_code}: {response.text[:300]}")

            try:
                data = response.json()
            except ValueError as exc:
                raise TavilyServiceError(f"Tavily devolvió JSON inválido: {response.text[:300]}") from exc
            if not isinstance(data, dict):
                raise TavilyServiceError("Tavily devolvió un payload no objeto.")

            raw_results = data.get("results")
            if not isinstance(raw_results, list):
                raw_results = []
            results = [
                normalized
                for idx, raw_result in enumerate(raw_results, start=1)
                if (normalized := _normalize_result(raw_result, index=idx)) is not None
            ]
            answer = data.get("answer")
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
            logger.info(
                "[Tavily] Búsqueda completada: %d resultado(s)",
                len(results),
                extra={
                    "query_preview": normalized_query[:120],
                    "results_count": len(results),
                    "has_answer": isinstance(answer, str) and bool(answer.strip()),
                    "usage": usage or {},
                },
            )
            return {
                "query": normalized_query,
                "answer": answer.strip() if isinstance(answer, str) else "",
                "results": results,
                "usage": usage or {},
            }

        except requests.exceptions.Timeout:
            wait = min(2 ** attempt, 60)
            last_exc = TavilyError(f"Timeout Tavily en intento {attempt}")
            logger.warning("[Tavily] Timeout en intento %s/%s", attempt, max_retries)
            if attempt < max_retries:
                time.sleep(wait)
                continue
        except requests.exceptions.RequestException as exc:
            if _is_retryable_requests_exception(exc):
                wait = min(2 ** attempt, 60)
                last_exc = TavilyError(f"Error de red Tavily en intento {attempt}: {exc}")
                logger.warning(
                    "[Tavily] Error de transporte reintentable en intento %s/%s: %s",
                    attempt,
                    max_retries,
                    type(exc).__name__,
                )
                if attempt < max_retries:
                    time.sleep(wait)
                    continue
                raise last_exc from exc
            raise TavilyError(f"Error de red Tavily: {exc}") from exc

    raise last_exc


def tavily_search_tool_result(api_key: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute the DeepSeek `tavily_search` function-call payload."""
    query = str(arguments.get("query") or "").strip()
    max_results = arguments.get("max_results", TAVILY_DEFAULT_MAX_RESULTS)
    search_depth = str(arguments.get("search_depth") or TAVILY_DEFAULT_SEARCH_DEPTH)
    include_answer = arguments.get("include_answer", False)
    include_raw_content = arguments.get("include_raw_content", "markdown")
    include_domains = arguments.get("include_domains")
    exclude_domains = arguments.get("exclude_domains")
    time_range = arguments.get("time_range")
    return search_tavily(
        api_key=api_key,
        query=query,
        search_depth=search_depth,
        max_results=max_results,
        include_answer=include_answer,
        include_raw_content=include_raw_content,
        include_domains=include_domains if isinstance(include_domains, list) else None,
        exclude_domains=exclude_domains if isinstance(exclude_domains, list) else None,
        time_range=time_range if isinstance(time_range, str) else None,
    )


def serialize_tool_result(result: Any) -> str:
    try:
        return json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(result)
