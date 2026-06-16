"""Web URL extraction and text block normalization helpers."""
from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

try:
    from curl_cffi import requests as curl_requests
except ImportError:  # pragma: no cover - optional dependency fallback
    curl_requests = None

import requests

from backend.gemini_client import generate_content_with_retry
from backend.logging_config import get_logger

logger = get_logger("backend.url_extraction")

DEFAULT_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "text/plain;q=0.8,application/json;q=0.7,*/*;q=0.5"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}

FETCH_TIMEOUT = (8, 25)
IMPERSONATED_FETCH_TIMEOUT = 45
MAX_RESPONSE_BYTES = 3 * 1024 * 1024
MAX_TEXT_FILE_CHARS = 2_000_000
MAX_BLOCK_CHARS = 1_800
MIN_ACCEPTABLE_CHARS = 200
MIN_ACCEPTABLE_WORDS = 30
MAX_META_REFRESH_REDIRECTS = 2
BROWSER_RENDER_TIMEOUT_SECONDS = 75

SUPPORTED_MIME_PREFIXES = ("text/",)
SUPPORTED_MIME_TYPES = {
    "application/xhtml+xml",
    "application/xml",
    "application/json",
}
UNSUPPORTED_MIME_PREFIXES = ("image/", "video/", "audio/")
UNSUPPORTED_MIME_TYPES = {
    "application/pdf",
    "application/octet-stream",
    "application/zip",
}

_BLOCK_HEADING_RE = re.compile(r"^=== BLOQUE (\d+) ===$", re.MULTILINE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_WHITESPACE_RE = re.compile(r"\s+")
_TITLE_META_PATTERNS = [
    re.compile(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\'](.*?)["\']',
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL),
]
_META_REFRESH_RE = re.compile(
    r"""<meta[^>]+http-equiv=["']refresh["'][^>]+content=["'][^"']*url=([^"';]+)""",
    re.IGNORECASE,
)
_ACCESS_CHALLENGE_PATTERNS = (
    "enable javascript and cookies to continue",
    "just a moment",
    "checking your browser before accessing",
    "verify you are human",
    "attention required",
    "access denied",
    "captcha",
    "/cdn-cgi/challenge-platform",
)
_EXTRACTOR_METHOD_BONUS = {
    "plain_text": 12_000,
    "json": 12_000,
    "raw_text": 4_000,
    "trafilatura": 9_000,
    "readability": 7_000,
    "goose3": 5_500,
    "justext": 3_500,
    "visible_html_text": 0,
}


class WebExtractionError(Exception):
    """Raised when a web URL cannot be extracted safely or reliably."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        allow_gemini_fallback: bool = False,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.allow_gemini_fallback = allow_gemini_fallback


@dataclass(frozen=True)
class FetchedWebPage:
    requested_url: str
    resolved_url: str
    content_type: str
    status_code: int
    body_text: str
    title: str
    fetch_method: str = "http"
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExtractedWebContent:
    requested_url: str
    resolved_url: str
    title: str
    text: str
    content_type: str
    extraction_method: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class TextBlock:
    number: int
    text: str


@dataclass(frozen=True)
class ExtractionCandidate:
    method: str
    text: str
    score: int


def normalize_public_web_url(url: str) -> str:
    """Validate a public HTTP(S) URL and return a normalized form."""
    candidate = (url or "").strip()
    if not candidate:
        raise WebExtractionError("Debes proporcionar una URL web.")

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise WebExtractionError("La URL web debe empezar por http:// o https://")
    if not parsed.netloc:
        raise WebExtractionError("La URL web no es válida.")
    if parsed.username or parsed.password:
        raise WebExtractionError("La URL web no puede incluir credenciales.")

    hostname = parsed.hostname
    if not hostname:
        raise WebExtractionError("La URL web no es válida.")

    _ensure_public_hostname(hostname)

    normalized = parsed._replace(fragment="")
    return urlunparse(normalized)


def extract_web_content(url: str, api_key: str | None, model: str) -> tuple[ExtractedWebContent, Any | None]:
    """Extract the readable text from a public web URL."""
    normalized_url = normalize_public_web_url(url)
    fetched: FetchedWebPage | None = None
    fallback_title = ""
    content_type = "text/html"

    try:
        fetched = _fetch_web_page(normalized_url)
    except WebExtractionError as exc:
        if not exc.allow_gemini_fallback:
            raise
    else:
        deterministic_text, deterministic_method = _extract_deterministically(
            fetched.body_text,
            fetched.content_type,
            fetched.resolved_url,
        )
        if _is_sufficient_text(deterministic_text):
            normalized_text = _normalize_extracted_text(deterministic_text)
            return (
                ExtractedWebContent(
                    requested_url=normalized_url,
                    resolved_url=fetched.resolved_url,
                    title=fetched.title or _derive_title_from_url(fetched.resolved_url),
                    text=_clip_text(normalized_text),
                    content_type=fetched.content_type,
                    extraction_method=deterministic_method,
                    metadata={
                        "http_status": fetched.status_code,
                        "deterministic": True,
                        "fetch_method": fetched.fetch_method,
                        "browser_rendered": False,
                    },
                ),
                None,
            )
        fallback_title = fetched.title
        content_type = fetched.content_type

    browser_fallback = _render_web_page_in_browser(fetched.resolved_url if fetched else normalized_url)
    if browser_fallback:
        browser_text, browser_method = _extract_deterministically(
            browser_fallback.body_text,
            browser_fallback.content_type,
            browser_fallback.resolved_url,
        )
        if _is_sufficient_text(browser_text):
            normalized_text = _normalize_extracted_text(browser_text)
            return (
                ExtractedWebContent(
                    requested_url=normalized_url,
                    resolved_url=browser_fallback.resolved_url,
                    title=browser_fallback.title or fallback_title or _derive_title_from_url(browser_fallback.resolved_url),
                    text=_clip_text(normalized_text),
                    content_type=browser_fallback.content_type,
                    extraction_method=f"{browser_method}_browser_render",
                    metadata={
                        "http_status": browser_fallback.status_code,
                        "deterministic": True,
                        "fetch_method": browser_fallback.fetch_method,
                        "browser_rendered": True,
                    },
                ),
                None,
            )

    if api_key and api_key.strip():
        gemini_result, usage_meta = _extract_with_gemini_url_context(
            api_key=api_key,
            model=model,
            url=(fetched.resolved_url if fetched else normalized_url),
            fallback_title=fallback_title,
            content_type=content_type,
        )
        if gemini_result:
            return gemini_result, usage_meta

    raise WebExtractionError(
        "No se pudo extraer texto utilizable de esa URL pública. "
        "No se procesará para evitar gasto innecesario de tokens."
    )


def build_text_blocks(text: str, max_chars: int = MAX_BLOCK_CHARS) -> list[TextBlock]:
    """Split normalized text into stable, numbered blocks without losing content."""
    normalized = _normalize_extracted_text(text)
    paragraphs = [paragraph for paragraph in normalized.split("\n\n") if paragraph.strip()]
    blocks: list[TextBlock] = []
    current_parts: list[str] = []
    current_length = 0

    def flush() -> None:
        nonlocal current_parts, current_length
        if not current_parts:
            return
        block_text = "\n\n".join(current_parts).strip()
        if block_text:
            blocks.append(TextBlock(number=len(blocks) + 1, text=block_text))
        current_parts = []
        current_length = 0

    for paragraph in paragraphs:
        for piece in _split_paragraph(paragraph, max_chars=max_chars):
            piece_length = len(piece)
            separator = 2 if current_parts else 0
            if current_parts and current_length + separator + piece_length > max_chars:
                flush()
            current_parts.append(piece)
            current_length += separator + piece_length

    flush()

    if not blocks and normalized.strip():
        blocks.append(TextBlock(number=1, text=normalized.strip()))

    return blocks


def render_block_marked_document(
    *,
    title: str,
    source_url: str,
    blocks: list[TextBlock],
) -> str:
    """Render numbered text blocks into a Gemini-friendly plain-text document."""
    header_lines = [
        f"TÍTULO: {title or 'Sin título'}",
        f"URL: {source_url}",
        "",
        "Cada bloque empieza con un marcador visible en el formato === BLOQUE X ===.",
        "Debes usar esos marcadores para identificar con precisión dónde empieza y termina cada parte.",
        "",
    ]
    body_parts = []
    for block in blocks:
        body_parts.append(f"=== BLOQUE {block.number} ===\n{block.text}")
    return "\n\n".join(header_lines + body_parts).strip()


def slice_block_range(blocks: list[TextBlock], start_block: int, end_block: int) -> list[TextBlock]:
    """Return the exact block subset for a requested range."""
    if start_block < 1 or end_block < start_block:
        raise WebExtractionError("El rango de bloques generado por el segmentador no es válido.")

    indexed = {block.number: block for block in blocks}
    selected = [indexed[number] for number in range(start_block, end_block + 1) if number in indexed]
    if len(selected) != (end_block - start_block + 1):
        raise WebExtractionError("Faltan bloques del texto extraído. Se aborta el procesamiento por seguridad.")
    return selected


def write_text_document_temp(document_text: str) -> str:
    """Persist a plain-text document to a temporary file for Gemini upload."""
    fd, path = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(document_text)
    return path


def block_markers_present(text: str) -> bool:
    """Check whether a text document still contains block markers."""
    return _BLOCK_HEADING_RE.search(text or "") is not None


def _ensure_public_hostname(hostname: str) -> None:
    normalized = hostname.strip().strip(".").lower()
    if not normalized:
        raise WebExtractionError("La URL web no es válida.")
    if normalized in {"localhost", "0.0.0.0"} or normalized.endswith(".local"):
        raise WebExtractionError("No se permiten URLs locales o de red privada.")

    try:
        ip_value = ipaddress.ip_address(normalized)
    except ValueError:
        ip_value = None

    if ip_value is not None:
        _ensure_public_ip(ip_value)
        return

    try:
        address_info = socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        # DNS resolution can legitimately fail temporarily here. Let the real fetch decide.
        return

    for entry in address_info:
        ip_text = entry[4][0]
        try:
            _ensure_public_ip(ipaddress.ip_address(ip_text))
        except ValueError:
            continue


def _ensure_public_ip(ip_value: Any) -> None:
    if (
        ip_value.is_private
        or ip_value.is_loopback
        or ip_value.is_link_local
        or ip_value.is_multicast
        or ip_value.is_reserved
        or ip_value.is_unspecified
    ):
        raise WebExtractionError("La URL apunta a una red privada o no pública.")


def _fetch_web_page(url: str) -> FetchedWebPage:
    response_payload = _fetch_with_impersonation(url)
    if response_payload is None:
        return _fetch_with_requests(url)
    return response_payload


def _fetch_with_impersonation(url: str, *, redirect_depth: int = 0) -> FetchedWebPage | None:
    if curl_requests is None:
        return None

    try:
        response = curl_requests.get(
            url,
            headers=DEFAULT_REQUEST_HEADERS,
            impersonate="chrome",
            timeout=IMPERSONATED_FETCH_TIMEOUT,
            allow_redirects=True,
        )
    except Exception as exc:  # pragma: no cover - library-specific network failures
        logger.warning("curl_cffi falló al descargar %s: %s", url, exc)
        return None

    if response.status_code >= 400:
        if response.status_code in {401, 403, 406, 429}:
            raise WebExtractionError(
                f"La URL devolvió un error HTTP {response.status_code} al fetch directo. "
                "Se intentará la recuperación con un navegador real y, si no basta, con URL context.",
                status_code=response.status_code,
                allow_gemini_fallback=True,
            )
        raise WebExtractionError(
            f"La URL devolvió un error HTTP {response.status_code}. "
            "No se procesará para evitar gasto innecesario.",
            status_code=response.status_code,
        )

    content_type = _normalize_content_type(response.headers.get("Content-Type"))
    if content_type and _is_unsupported_content_type(content_type):
        raise WebExtractionError("La URL no apunta a contenido textual compatible.")

    raw_bytes = bytes(response.content or b"")
    if len(raw_bytes) > MAX_RESPONSE_BYTES:
        raise WebExtractionError("La página es demasiado grande para extraerla de forma fiable.")

    encoding = response.encoding or "utf-8"
    body_text = raw_bytes.decode(encoding, errors="replace")

    if not content_type:
        content_type = "text/html" if "<html" in body_text.lower() else "text/plain"
    if not _is_supported_content_type(content_type):
        raise WebExtractionError("La URL no apunta a contenido textual compatible.")

    meta_refresh_url = _extract_meta_refresh_url(body_text, base_url=str(response.url))
    if meta_refresh_url and redirect_depth < MAX_META_REFRESH_REDIRECTS:
        return _fetch_with_impersonation(meta_refresh_url, redirect_depth=redirect_depth + 1) or _fetch_with_requests(meta_refresh_url)

    return FetchedWebPage(
        requested_url=url,
        resolved_url=str(response.url),
        content_type=content_type,
        status_code=response.status_code,
        body_text=body_text,
        title=_extract_html_title(body_text) if _looks_like_html(content_type, body_text) else _derive_title_from_url(str(response.url)),
        fetch_method="curl_impersonation",
    )


def _fetch_with_requests(url: str, *, redirect_depth: int = 0) -> FetchedWebPage:
    try:
        response = requests.get(
            url,
            headers=DEFAULT_REQUEST_HEADERS,
            timeout=FETCH_TIMEOUT,
            allow_redirects=True,
            stream=True,
        )
    except requests.RequestException as exc:
        raise WebExtractionError("No se pudo acceder a la URL indicada.") from exc

    if response.status_code >= 400:
        if response.status_code in {401, 403, 406, 429}:
            raise WebExtractionError(
                f"La URL devolvió un error HTTP {response.status_code} al fetch directo. "
                "Se intentará la recuperación con un navegador real antes de abortar.",
                status_code=response.status_code,
                allow_gemini_fallback=True,
            )
        raise WebExtractionError(
            f"La URL devolvió un error HTTP {response.status_code}. "
            "No se procesará para evitar gasto innecesario.",
            status_code=response.status_code,
        )

    content_type = _normalize_content_type(response.headers.get("Content-Type"))
    if content_type and _is_unsupported_content_type(content_type):
        raise WebExtractionError("La URL no apunta a contenido textual compatible.")

    chunks: list[bytes] = []
    total_size = 0
    try:
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            total_size += len(chunk)
            if total_size > MAX_RESPONSE_BYTES:
                raise WebExtractionError("La página es demasiado grande para extraerla de forma fiable.")
            chunks.append(chunk)
    finally:
        response.close()

    raw_bytes = b"".join(chunks)
    encoding = response.encoding or "utf-8"
    body_text = raw_bytes.decode(encoding, errors="replace")

    if not content_type:
        content_type = "text/html" if "<html" in body_text.lower() else "text/plain"
    if not _is_supported_content_type(content_type):
        raise WebExtractionError("La URL no apunta a contenido textual compatible.")

    meta_refresh_url = _extract_meta_refresh_url(body_text, base_url=response.url)
    if meta_refresh_url and redirect_depth < MAX_META_REFRESH_REDIRECTS:
        try:
            return _fetch_with_impersonation(meta_refresh_url, redirect_depth=redirect_depth + 1) or _fetch_with_requests(
                meta_refresh_url,
                redirect_depth=redirect_depth + 1,
            )
        except WebExtractionError:
            raise

    return FetchedWebPage(
        requested_url=url,
        resolved_url=response.url,
        content_type=content_type,
        status_code=response.status_code,
        body_text=body_text,
        title=_extract_html_title(body_text) if _looks_like_html(content_type, body_text) else _derive_title_from_url(response.url),
        fetch_method="requests",
    )


def _normalize_content_type(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def _is_supported_content_type(content_type: str) -> bool:
    return content_type.startswith(SUPPORTED_MIME_PREFIXES) or content_type in SUPPORTED_MIME_TYPES


def _is_unsupported_content_type(content_type: str) -> bool:
    return content_type.startswith(UNSUPPORTED_MIME_PREFIXES) or content_type in UNSUPPORTED_MIME_TYPES


def _looks_like_html(content_type: str, body_text: str) -> bool:
    if "html" in content_type or "xml" in content_type:
        return True
    lowered = body_text[:500].lower()
    return "<html" in lowered or "<body" in lowered or "<article" in lowered or "<div" in lowered


def _extract_deterministically(body_text: str, content_type: str, url: str) -> tuple[str, str]:
    normalized_type = content_type.lower()
    if normalized_type == "text/plain":
        return body_text, "plain_text"

    if normalized_type == "application/json":
        return _pretty_json(body_text), "json"

    if not _looks_like_html(normalized_type, body_text):
        return body_text, "raw_text"

    html_text = body_text
    candidates: list[ExtractionCandidate] = []
    _append_candidate(candidates, "trafilatura", _extract_with_trafilatura(html_text, url))
    _append_candidate(candidates, "readability", _extract_with_readability(html_text))
    _append_candidate(candidates, "goose3", _extract_with_goose3(html_text))
    _append_candidate(candidates, "justext", _extract_with_justext(html_text))
    _append_candidate(candidates, "visible_html_text", _extract_visible_text_from_html(html_text))
    if not candidates:
        return "", "none"

    best_candidate = max(candidates, key=lambda candidate: candidate.score)
    if not _is_sufficient_text(best_candidate.text):
        return "", "none"
    return best_candidate.text, best_candidate.method


def _append_candidate(candidates: list[ExtractionCandidate], method: str, raw_text: str) -> None:
    normalized = _normalize_extracted_text(raw_text)
    if not normalized:
        return
    candidates.append(
        ExtractionCandidate(
            method=method,
            text=normalized,
            score=_score_extracted_text(method, normalized),
        )
    )


def _score_extracted_text(method: str, text: str) -> int:
    paragraph_list = [paragraph for paragraph in text.split("\n\n") if paragraph.strip()]
    paragraphs = len(paragraph_list)
    words = len(re.findall(r"\S+", text))
    unique_lines = {
        line.strip().lower()
        for line in text.splitlines()
        if line.strip()
    }
    total_lines = len([line for line in text.splitlines() if line.strip()])
    short_paragraphs = len([paragraph for paragraph in paragraph_list if len(paragraph) < 35])
    duplicate_penalty = max(0, total_lines - len(unique_lines)) * 35
    boilerplate_penalty = short_paragraphs * 80
    challenge_penalty = 250_000 if _looks_like_access_challenge(text) else 0
    return (
        _EXTRACTOR_METHOD_BONUS.get(method, 0)
        + min(len(text), 50_000)
        + min(words, 8_000)
        + min(paragraphs, 200) * 45
        - duplicate_penalty
        - boilerplate_penalty
        - challenge_penalty
    )


def _extract_with_trafilatura(html_text: str, url: str) -> str:
    try:
        import trafilatura
    except ImportError:
        logger.warning("Trafilatura no está instalada; se omite extracción determinista primaria.")
        return ""

    try:
        extracted = trafilatura.extract(
            html_text,
            url=url,
            favor_recall=True,
            include_comments=False,
            include_tables=True,
            include_links=False,
            include_images=False,
        )
    except Exception as exc:  # pragma: no cover - defensive against library internals
        logger.warning("Trafilatura falló: %s", exc)
        return ""
    return extracted or ""


def _extract_with_readability(html_text: str) -> str:
    try:
        from readability import Document
    except ImportError:
        logger.warning("readability-lxml no está instalada; se omite fallback readability.")
        return ""

    try:
        document = Document(html_text)
        summary_html = document.summary()
    except Exception as exc:  # pragma: no cover - defensive against library internals
        logger.warning("Readability falló: %s", exc)
        return ""

    return _extract_visible_text_from_html(summary_html)


def _extract_with_goose3(html_text: str) -> str:
    try:
        from goose3 import Goose
    except ImportError:
        logger.warning("goose3 no está instalada; se omite fallback Goose.")
        return ""

    try:
        article = Goose().extract(raw_html=html_text)
    except Exception as exc:  # pragma: no cover - defensive against library internals
        logger.warning("Goose3 falló: %s", exc)
        return ""
    return article.cleaned_text or ""


def _extract_with_justext(html_text: str) -> str:
    try:
        import justext
    except ImportError:
        logger.warning("jusText no está instalada; se omite fallback jusText.")
        return ""

    stoplist_name = _guess_justext_stoplist(html_text)
    try:
        paragraphs = justext.justext(html_text, justext.get_stoplist(stoplist_name))
    except Exception as exc:  # pragma: no cover - defensive against library internals
        logger.warning("jusText falló: %s", exc)
        return ""
    return "\n\n".join(
        paragraph.text.strip()
        for paragraph in paragraphs
        if not paragraph.is_boilerplate and paragraph.text.strip()
    )


def _guess_justext_stoplist(html_text: str) -> str:
    match = re.search(r"""<html[^>]+lang=["']([a-zA-Z-]+)["']""", html_text, re.IGNORECASE)
    language = (match.group(1).split("-", 1)[0].lower() if match else "")
    return {
        "es": "Spanish",
        "en": "English",
        "fr": "French",
        "de": "German",
        "it": "Italian",
        "pt": "Portuguese",
        "nl": "Dutch",
    }.get(language, "English")


def _extract_visible_text_from_html(html_text: str) -> str:
    try:
        from lxml import etree
        from lxml import html as lxml_html
    except ImportError:
        return _strip_html_tags(html_text)

    try:
        root = lxml_html.fromstring(html_text)
        etree.strip_elements(
            root,
            "script",
            "style",
            "noscript",
            "template",
            "svg",
            "canvas",
            "iframe",
            with_tail=False,
        )
        return root.text_content()
    except Exception as exc:  # pragma: no cover - defensive against parser internals
        logger.warning("No se pudo extraer texto visible con lxml: %s", exc)
        return _strip_html_tags(html_text)


def _strip_html_tags(html_text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html_text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return unescape(text)


def _extract_html_title(html_text: str) -> str:
    for pattern in _TITLE_META_PATTERNS:
        match = pattern.search(html_text)
        if not match:
            continue
        title = unescape(_WHITESPACE_RE.sub(" ", match.group(1))).strip()
        if title:
            return title
    return ""


def _derive_title_from_url(url: str) -> str:
    parsed = urlparse(url)
    hostname = parsed.hostname or url
    path = (parsed.path or "").rstrip("/")
    if path:
        last_segment = path.split("/")[-1]
        if last_segment:
            return f"{hostname} · {last_segment}"
    return hostname


def _pretty_json(body_text: str) -> str:
    try:
        return json.dumps(json.loads(body_text), ensure_ascii=False, indent=2)
    except Exception:
        return body_text


def _normalize_extracted_text(text: str) -> str:
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ").replace("\u200b", "")
    lines = [line.strip() for line in cleaned.split("\n")]
    paragraphs: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        paragraphs.append(" ".join(part for part in buffer if part).strip())
        buffer = []

    for line in lines:
        if line:
            buffer.append(line)
        else:
            flush()
    flush()

    normalized = "\n\n".join(paragraph for paragraph in paragraphs if paragraph)
    return normalized.strip()


def _split_paragraph(paragraph: str, max_chars: int) -> list[str]:
    text = paragraph.strip()
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    current: list[str] = []
    current_len = 0
    sentences = [segment.strip() for segment in _SENTENCE_SPLIT_RE.split(text) if segment.strip()]

    def flush() -> None:
        nonlocal current, current_len
        if current:
            pieces.append(" ".join(current).strip())
            current = []
            current_len = 0

    for sentence in sentences or [text]:
        sentence_len = len(sentence)
        separator = 1 if current else 0
        if sentence_len > max_chars:
            flush()
            pieces.extend(_split_long_token(sentence, max_chars=max_chars))
            continue
        if current and current_len + separator + sentence_len > max_chars:
            flush()
        current.append(sentence)
        current_len += separator + sentence_len

    flush()
    return pieces


def _split_long_token(text: str, max_chars: int) -> list[str]:
    words = text.split()
    if not words:
        return [text[:max_chars]]

    pieces: list[str] = []
    current_words: list[str] = []
    current_len = 0
    for word in words:
        word_len = len(word)
        separator = 1 if current_words else 0
        if current_words and current_len + separator + word_len > max_chars:
            pieces.append(" ".join(current_words))
            current_words = [word]
            current_len = word_len
            continue
        if word_len > max_chars:
            if current_words:
                pieces.append(" ".join(current_words))
                current_words = []
                current_len = 0
            pieces.extend(word[index:index + max_chars] for index in range(0, len(word), max_chars))
            continue
        current_words.append(word)
        current_len += separator + word_len

    if current_words:
        pieces.append(" ".join(current_words))
    return pieces


def _is_sufficient_text(text: str) -> bool:
    normalized = _normalize_extracted_text(text)
    if len(normalized) < MIN_ACCEPTABLE_CHARS:
        return False
    words = len(re.findall(r"\S+", normalized))
    if _looks_like_access_challenge(normalized) and words < 400:
        return False
    return words >= MIN_ACCEPTABLE_WORDS


def _clip_text(text: str) -> str:
    clipped = text[:MAX_TEXT_FILE_CHARS]
    return clipped.strip()


def _looks_like_access_challenge(text: str) -> bool:
    lowered = _WHITESPACE_RE.sub(" ", (text or "").lower())
    return any(marker in lowered for marker in _ACCESS_CHALLENGE_PATTERNS)


def _extract_meta_refresh_url(html_text: str, *, base_url: str) -> str | None:
    match = _META_REFRESH_RE.search(html_text or "")
    if not match:
        return None
    candidate = match.group(1).strip()
    if not candidate:
        return None
    return urljoin(base_url, candidate)


def _render_web_page_in_browser(url: str) -> FetchedWebPage | None:
    node_executable = shutil.which("node")
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "render-url.mjs"
    if not node_executable or not script_path.exists():
        return None

    try:
        completed = subprocess.run(
            [node_executable, str(script_path), url],
            capture_output=True,
            text=True,
            cwd=script_path.parent.parent,
            timeout=BROWSER_RENDER_TIMEOUT_SECONDS,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("No se pudo renderizar la URL en navegador: %s", exc)
        return None

    stdout = (completed.stdout or "").strip()
    if not stdout:
        return None

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        logger.warning("La salida del renderizado Playwright no era JSON válido.")
        return None

    html_text = payload.get("html") or ""
    if not html_text or len(html_text.encode("utf-8")) > MAX_RESPONSE_BYTES:
        return None

    content_type = _normalize_content_type(payload.get("contentType")) or "text/html"
    if not _is_supported_content_type(content_type):
        return None

    resolved_url = payload.get("resolvedUrl") or url
    title = (payload.get("title") or "").strip()
    status_code = int(payload.get("statusCode") or 200)
    return FetchedWebPage(
        requested_url=url,
        resolved_url=resolved_url,
        content_type=content_type,
        status_code=status_code,
        body_text=html_text,
        title=title or _derive_title_from_url(resolved_url),
        fetch_method="browser_render",
    )


def _extract_with_gemini_url_context(
    *,
    api_key: str,
    model: str,
    url: str,
    fallback_title: str,
    content_type: str,
) -> tuple[ExtractedWebContent | None, Any | None]:
    from google import genai
    from google.genai import types

    schema = types.Schema(
        type=types.Type.OBJECT,
        required=["title", "full_text", "quality"],
        properties={
            "title": types.Schema(type=types.Type.STRING),
            "full_text": types.Schema(type=types.Type.STRING),
            "quality": types.Schema(
                type=types.Type.STRING,
                enum=["sufficient", "insufficient"],
            ),
        },
    )

    prompt = (
        "Accede exclusivamente al contenido principal de la URL proporcionada. "
        "Devuelve el texto legible completo para estudio posterior, preservando el orden de títulos, "
        "subtítulos y párrafos. Excluye navegación, anuncios, cookies y elementos repetitivos. "
        "No resumas ni añadas información. Si el contenido no es accesible públicamente o no puedes "
        "extraer texto suficiente de forma fiable, devuelve quality='insufficient' y full_text vacío.\n\n"
        f"URL objetivo: {url}"
    )

    client = genai.Client(api_key=api_key)
    response = generate_content_with_retry(
        client=client,
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[{"url_context": {}}],
            response_mime_type="application/json",
            response_schema=schema,
        ),
        max_retries=5,
        operation_context={"agent": "url_context_extract"},
    )

    candidate = response.candidates[0] if getattr(response, "candidates", None) else None
    url_context_metadata = getattr(candidate, "url_context_metadata", None) if candidate else None
    url_metadata = getattr(url_context_metadata, "url_metadata", None) or []
    statuses = [getattr(item, "url_retrieval_status", "") for item in url_metadata]
    if not statuses or any(status != "URL_RETRIEVAL_STATUS_SUCCESS" for status in statuses):
        return None, response.usage_metadata

    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError:
        logger.warning("Gemini URL context devolvió una respuesta no JSON.")
        return None, response.usage_metadata

    if payload.get("quality") != "sufficient":
        return None, response.usage_metadata

    text = _normalize_extracted_text(payload.get("full_text", ""))
    if not _is_sufficient_text(text):
        return None, response.usage_metadata

    title = (payload.get("title") or "").strip() or fallback_title or _derive_title_from_url(url)
    return (
        ExtractedWebContent(
            requested_url=url,
            resolved_url=url,
            title=title,
            text=_clip_text(text),
            content_type=content_type,
            extraction_method="gemini_url_context",
            metadata={"url_retrieval_statuses": statuses, "deterministic": False},
        ),
        response.usage_metadata,
    )

