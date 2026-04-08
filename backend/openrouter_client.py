"""Cliente HTTP para OpenRouter API."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import requests
from filelock import FileLock
from pypdf import PdfReader

from backend.logging_config import get_logger
from backend.pdf_utils import extract_pages

logger = get_logger("backend.openrouter_client")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_RESPONSE_HEALING_PLUGIN = {"id": "response-healing"}
_PDF_PAGE_MARKER_RE = re.compile(r"— Página\s+(\d+)\s*/\s*(\d+)\s+—")
_PDF_CACHE_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_PDF_CACHE_LOCKS_GUARD = threading.Lock()
_PDF_CACHE_VERSION = 2


class OpenRouterUsage:
    """Wrapper de usage con atributos compatibles con Gemini para _update_usage."""

    def __init__(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        cost_usd: float | None = None,
    ):
        self.prompt_token_count = prompt_tokens
        self.candidates_token_count = completion_tokens
        self.thoughts_token_count = 0
        self.tool_use_prompt_token_count = 0
        self.total_token_count = prompt_tokens + completion_tokens
        self.cost_usd = cost_usd


class OpenRouterError(Exception):
    pass


class OpenRouterRateLimitError(OpenRouterError):
    pass


class OpenRouterServiceError(OpenRouterError):
    pass


@dataclass(frozen=True, slots=True)
class OpenRouterAssistantMessage:
    content: str
    annotations: list[dict[str, Any]] | None = None


@dataclass(frozen=True, slots=True)
class OpenRouterChatResult:
    content: str | dict[str, Any]
    usage: OpenRouterUsage
    assistant_message: OpenRouterAssistantMessage


@dataclass(frozen=True, slots=True)
class OpenRouterJsonSchemaResponseFormat:
    name: str
    schema: dict[str, Any]
    strict: bool = True


@dataclass(frozen=True, slots=True)
class OpenRouterJsonSchemaResponseFormat:
    name: str
    schema: dict[str, Any]
    strict: bool = True


@dataclass(frozen=True, slots=True)
class OpenRouterPdfParseCacheEntry:
    source_sha256: str
    engine: str
    assistant_message: OpenRouterAssistantMessage | None
    cache_path: str
    cache_hit: bool
    expected_page_numbers: tuple[int, ...] = ()
    cached_page_numbers: tuple[int, ...] = ()
    page_index: tuple["OpenRouterPdfParsedPage", ...] = ()


@dataclass(frozen=True, slots=True)
class OpenRouterPdfParsedPage:
    page_number: int
    content_parts: tuple[dict[str, Any], ...]


def _merge_plugins(
    plugins: list[dict[str, Any]] | None,
    *,
    enable_response_healing: bool,
) -> list[dict[str, Any]] | None:
    """Merge request plugins and optionally append response-healing once."""
    merged = [dict(plugin) for plugin in (plugins or [])]
    if enable_response_healing and not any(
        plugin.get("id") == OPENROUTER_RESPONSE_HEALING_PLUGIN["id"]
        for plugin in merged
    ):
        merged.append(dict(OPENROUTER_RESPONSE_HEALING_PLUGIN))
    return merged or None


def _extract_message_content(message: dict[str, Any]) -> str:
    """Extract assistant message text from the OpenRouter response payload."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                chunks.append(text)
        return "".join(chunks)
    return ""


def _extract_message_annotations(message: dict[str, Any]) -> list[dict[str, Any]] | None:
    annotations = message.get("annotations")
    if not isinstance(annotations, list):
        return None
    normalized: list[dict[str, Any]] = []
    for item in annotations:
        if isinstance(item, dict):
            normalized.append(item)
    return normalized or None


def _extract_api_error_message(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None

    error = payload.get("error")
    if isinstance(error, str):
        normalized = error.strip()
        return normalized or None

    if isinstance(error, dict):
        message = error.get("message")
        code = error.get("code")
        normalized_message = message.strip() if isinstance(message, str) else ""
        if normalized_message and code is not None:
            return f"{normalized_message} (code={code})"
        if normalized_message:
            return normalized_message
        if code is not None:
            return f"code={code}"

    return None


def _response_preview(raw_text: str, *, limit: int = 300) -> str:
    preview = raw_text.strip()
    if not preview:
        return "<empty>"
    return preview[:limit]


def _build_invalid_response_error(
    *,
    reason: str,
    payload: Any,
    response_text: str,
) -> OpenRouterServiceError:
    details = [reason]
    error_message = _extract_api_error_message(payload)
    if error_message:
        details.append(f"error={error_message}")
    if isinstance(payload, dict):
        details.append(f"keys={list(payload.keys())}")
    else:
        details.append(f"payload_type={type(payload).__name__}")
    details.append(f"body={_response_preview(response_text)}")
    return OpenRouterServiceError(
        "Respuesta OpenRouter inválida: " + " | ".join(details)
    )


def _is_retryable_requests_exception(exc: requests.exceptions.RequestException) -> bool:
    """
    Retry transient transport failures, but fail fast on clearly local or
    configuration-level request errors where a retry cannot help.
    """
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


def _parse_json_object_content(content: str) -> dict[str, Any]:
    """Parse JSON text output and require a top-level object."""
    if not content or not content.strip():
        raise OpenRouterError("OpenRouter devolvió contenido JSON vacío.")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise OpenRouterError(
            "OpenRouter devolvió JSON inválido: "
            f"{exc.msg} (línea {exc.lineno}, columna {exc.colno})."
        ) from exc
    if not isinstance(parsed, dict):
        raise OpenRouterError(
            "OpenRouter devolvió JSON válido, pero no un objeto JSON."
        )
    return parsed


def _default_pdf_cache_dir() -> Path:
    env_value = os.environ.get("OPENROUTER_PDF_CACHE_DIR", "").strip()
    if env_value:
        return Path(env_value)
    return Path.cwd() / "data" / "openrouter_pdf_cache"


def _ensure_cache_dir(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pdf_cache_path(source_sha256: str, engine: str, cache_dir: Path) -> Path:
    safe_engine = engine.replace("/", "_")
    return cache_dir / f"{source_sha256}.{safe_engine}.json"


def _parse_cache_user_text() -> str:
    return (
        "Parsea este PDF para futuras preguntas. Responde solo con OK. "
        "No resumas el contenido."
    )


def _build_pdf_file_content(
    *,
    source_path: str,
    filename: str,
    text: str,
) -> list[dict[str, Any]]:
    with open(source_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return [
        {"type": "text", "text": text},
        {
            "type": "file",
            "file": {
                "filename": filename,
                "file_data": f"data:application/pdf;base64,{b64}",
            },
        },
    ]


def _assistant_message_to_dict(message: OpenRouterAssistantMessage | None) -> dict[str, Any] | None:
    if message is None:
        return None
    payload: dict[str, Any] = {"content": message.content}
    if message.annotations is not None:
        payload["annotations"] = message.annotations
    return payload


def _assistant_message_from_dict(payload: dict[str, Any] | None) -> OpenRouterAssistantMessage | None:
    if not isinstance(payload, dict):
        return None
    return OpenRouterAssistantMessage(
        content=str(payload.get("content", "")),
        annotations=_extract_message_annotations(payload),
    )


def _parse_cache_system_prompt() -> str:
    return (
        "Eres una respuesta de preparación para un documento PDF. "
        "Lee el archivo adjunto, permite que el sistema conserve sus annotations "
        "y responde exactamente con OK."
    )


def _get_pdf_cache_lock(source_sha256: str, engine: str) -> threading.Lock:
    key = (source_sha256, engine)
    with _PDF_CACHE_LOCKS_GUARD:
        lock = _PDF_CACHE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PDF_CACHE_LOCKS[key] = lock
        return lock


def _pdf_cache_file_lock(cache_path: Path) -> FileLock:
    return FileLock(str(cache_path) + ".lock")


def _normalize_expected_page_numbers(
    expected_page_numbers: tuple[int, ...] | list[int] | None,
) -> tuple[int, ...]:
    if not expected_page_numbers:
        return ()
    normalized = tuple(int(page) for page in expected_page_numbers)
    if any(page < 1 for page in normalized):
        raise OpenRouterError("expected_page_numbers contiene páginas inválidas (< 1).")
    if len(set(normalized)) != len(normalized):
        raise OpenRouterError("expected_page_numbers contiene páginas duplicadas.")
    if tuple(sorted(normalized)) != normalized:
        raise OpenRouterError("expected_page_numbers debe venir en orden ascendente.")
    return normalized


def _extract_pdf_annotation_content_parts(
    annotations: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not annotations:
        return []
    for annotation in annotations:
        if not isinstance(annotation, dict) or annotation.get("type") != "file":
            continue
        file_payload = annotation.get("file")
        if not isinstance(file_payload, dict):
            continue
        content = file_payload.get("content")
        if not isinstance(content, list):
            continue
        return [part for part in content if isinstance(part, dict)]
    return []


def _split_text_part_by_page_markers(part: dict[str, Any]) -> list[tuple[int | None, dict[str, Any]]]:
    text = part.get("text")
    if not isinstance(text, str) or not text:
        return []

    matches = list(_PDF_PAGE_MARKER_RE.finditer(text))
    if not matches:
        return [(None, {"type": "text", "text": text})]

    chunks: list[tuple[int | None, dict[str, Any]]] = []
    cursor = 0
    for index, match in enumerate(matches):
        prefix = text[cursor:match.start()]
        if prefix:
            chunks.append((None, {"type": "text", "text": prefix}))

        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunk_text = text[match.start():next_start]
        chunks.append((int(match.group(1)), {"type": "text", "text": chunk_text}))
        cursor = next_start

    suffix = text[cursor:]
    if suffix:
        chunks.append((None, {"type": "text", "text": suffix}))

    return chunks


def _serialize_page_index(page_index: tuple[OpenRouterPdfParsedPage, ...]) -> list[dict[str, Any]]:
    return [
        {
            "page_number": page.page_number,
            "content_parts": list(page.content_parts),
        }
        for page in page_index
    ]


def _page_index_from_serialized(raw: Any) -> tuple[OpenRouterPdfParsedPage, ...]:
    if not isinstance(raw, list):
        return ()

    pages: list[OpenRouterPdfParsedPage] = []
    for item in raw:
        if not isinstance(item, dict):
            return ()
        page_number = item.get("page_number")
        content_parts = item.get("content_parts")
        if not isinstance(page_number, int) or page_number < 1:
            return ()
        if not isinstance(content_parts, list) or not all(isinstance(part, dict) for part in content_parts):
            return ()
        pages.append(
            OpenRouterPdfParsedPage(
                page_number=page_number,
                content_parts=tuple(content_parts),
            )
        )

    return tuple(pages)


def _page_numbers_from_index(page_index: tuple[OpenRouterPdfParsedPage, ...]) -> tuple[int, ...]:
    return tuple(page.page_number for page in page_index)


def _merge_page_indexes(
    existing: tuple[OpenRouterPdfParsedPage, ...],
    updates: tuple[OpenRouterPdfParsedPage, ...],
) -> tuple[OpenRouterPdfParsedPage, ...]:
    merged = {page.page_number: page for page in existing}
    for page in updates:
        merged[page.page_number] = page
    return tuple(merged[page_number] for page_number in sorted(merged))


def _group_contiguous_pages(page_numbers: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    if not page_numbers:
        return ()

    groups: list[list[int]] = [[page_numbers[0]]]
    for page_number in page_numbers[1:]:
        current_group = groups[-1]
        if page_number == current_group[-1] + 1:
            current_group.append(page_number)
        else:
            groups.append([page_number])

    return tuple(tuple(group) for group in groups)


def _should_split_pdf_page_group(exc: OpenRouterError) -> bool:
    message = str(exc).lower()
    return (
        "failed to parse" in message
        or "marcadores de página" in message
        or "ambiguas" in message
        or "reconstruir" in message
    )


def _build_pdf_page_index(
    *,
    annotations: list[dict[str, Any]] | None,
    expected_page_numbers: tuple[int, ...] = (),
) -> tuple[OpenRouterPdfParsedPage, ...]:
    content_parts = _extract_pdf_annotation_content_parts(annotations)
    if not content_parts:
        raise OpenRouterError("Las annotations del PDF no contienen contenido reutilizable.")

    chunks: list[tuple[int | None, dict[str, Any]]] = []
    for part in content_parts:
        part_type = part.get("type")
        if part_type == "text":
            chunks.extend(_split_text_part_by_page_markers(part))
        elif part_type == "image_url":
            chunks.append((None, part))

    anchors = [(idx, page) for idx, (page, _) in enumerate(chunks) if page is not None]
    if not anchors:
        raise OpenRouterError(
            "No se pudieron localizar marcadores de página en las annotations OCR."
        )

    expected = _normalize_expected_page_numbers(expected_page_numbers)
    expected_index = {page: idx for idx, page in enumerate(expected)}
    page_map: dict[int, list[dict[str, Any]]] = {}

    def _assign(indices: list[int], page_number: int) -> None:
        bucket = page_map.setdefault(page_number, [])
        for chunk_index in indices:
            _, content_part = chunks[chunk_index]
            bucket.append(content_part)

    first_anchor_idx, first_anchor_page = anchors[0]
    prefix_indices = list(range(0, first_anchor_idx))
    if prefix_indices:
        if expected:
            expected_prefix = [page for page in expected if page < first_anchor_page]
            if len(expected_prefix) == 1:
                _assign(prefix_indices, expected_prefix[0])
            elif not expected_prefix:
                _assign(prefix_indices, first_anchor_page)
            else:
                raise OpenRouterError(
                    "Annotations OCR ambiguas antes del primer marcador de página."
                )
        else:
            _assign(prefix_indices, first_anchor_page)
    _assign([first_anchor_idx], first_anchor_page)

    for anchor_pos in range(1, len(anchors)):
        prev_chunk_idx, prev_page = anchors[anchor_pos - 1]
        current_chunk_idx, current_page = anchors[anchor_pos]
        gap_indices = list(range(prev_chunk_idx + 1, current_chunk_idx))

        if expected:
            if prev_page not in expected_index or current_page not in expected_index:
                raise OpenRouterError(
                    "Las annotations OCR contienen páginas fuera del conjunto esperado."
                )
            between_expected = [
                page
                for page in expected
                if expected_index[prev_page] < expected_index[page] < expected_index[current_page]
            ]
        else:
            between_expected = list(range(prev_page + 1, current_page))

        if not between_expected:
            if gap_indices:
                _assign(gap_indices, prev_page)
        elif len(between_expected) == 1:
            _assign(gap_indices, between_expected[0])
        elif len(gap_indices) == len(between_expected):
            for gap_index, inferred_page in zip(gap_indices, between_expected):
                _assign([gap_index], inferred_page)
        else:
            raise OpenRouterError(
                "Annotations OCR ambiguas: no se pudo reconstruir el mapeo exacto por página."
            )

        _assign([current_chunk_idx], current_page)

    last_anchor_idx, last_anchor_page = anchors[-1]
    suffix_indices = list(range(last_anchor_idx + 1, len(chunks)))
    if suffix_indices:
        if expected:
            expected_suffix = [page for page in expected if page > last_anchor_page]
            if len(expected_suffix) == 1:
                _assign(suffix_indices, expected_suffix[0])
            elif not expected_suffix:
                _assign(suffix_indices, last_anchor_page)
            elif len(suffix_indices) == len(expected_suffix):
                for suffix_index, inferred_page in zip(suffix_indices, expected_suffix):
                    _assign([suffix_index], inferred_page)
            else:
                raise OpenRouterError(
                    "Annotations OCR ambiguas después del último marcador de página."
                )
        else:
            _assign(suffix_indices, last_anchor_page)

    ordered_pages = expected or tuple(sorted(page_map.keys()))
    normalized_pages: list[OpenRouterPdfParsedPage] = []
    for page in ordered_pages:
        parts_for_page = tuple(page_map.get(page, []))
        if not parts_for_page:
            continue
        normalized_pages.append(
            OpenRouterPdfParsedPage(
                page_number=page,
                content_parts=parts_for_page,
            )
        )

    if expected:
        missing_pages = [page for page in expected if page not in page_map]
        if missing_pages:
            raise OpenRouterError(
                "No se pudieron reconstruir todas las páginas esperadas del OCR: "
                f"{missing_pages}"
            )

    return tuple(normalized_pages)


def _write_pdf_parse_cache(
    *,
    cache_path: Path,
    source_sha256: str,
    engine: str,
    assistant_message: OpenRouterAssistantMessage | None,
    document_page_count: int | None,
    page_index: tuple[OpenRouterPdfParsedPage, ...],
) -> None:
    serialized = {
        "version": _PDF_CACHE_VERSION,
        "source_sha256": source_sha256,
        "engine": engine,
        "assistant_message": _assistant_message_to_dict(assistant_message),
        "document_page_count": document_page_count,
        "page_index": _serialize_page_index(page_index),
    }

    fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp",
        prefix=f"{source_sha256}.{engine.replace('/', '_')}.",
        dir=str(cache_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(serialized, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, cache_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _load_pdf_parse_cache(
    cache_path: Path,
) -> tuple[OpenRouterAssistantMessage | None, tuple[OpenRouterPdfParsedPage, ...], int | None]:
    with open(cache_path, "r", encoding="utf-8") as f:
        cached = json.load(f)

    assistant_message = _assistant_message_from_dict(cached.get("assistant_message"))
    page_index = _page_index_from_serialized(cached.get("page_index"))
    document_page_count = cached.get("document_page_count")
    if not isinstance(document_page_count, int) or document_page_count < 1:
        document_page_count = None

    return assistant_message, page_index, document_page_count


def _prime_pdf_page_group(
    *,
    source_path: str,
    page_numbers: tuple[int, ...],
    api_key: str,
    model: str,
    engine: str,
    filename: str,
    max_retries: int,
) -> tuple[OpenRouterPdfParsedPage, ...]:
    chunk_pdf_path = extract_pages(source_path, page_numbers)
    try:
        priming_messages = [
            {
                "role": "user",
                "content": _build_pdf_file_content(
                    source_path=chunk_pdf_path,
                    filename=filename,
                    text=_parse_cache_user_text(),
                ),
            }
        ]
        priming_plugins = [{"id": "file-parser", "pdf": {"engine": engine}}]

        result = call_openrouter_chat_full(
            messages=priming_messages,
            model=model,
            system_prompt=_parse_cache_system_prompt(),
            api_key=api_key,
            response_format="text",
            plugins=priming_plugins,
            enable_response_healing=False,
            reasoning=None,
            max_retries=max_retries,
        )
        if not result.assistant_message.annotations:
            raise OpenRouterError(
                "OpenRouter no devolvió annotations reutilizables al parsear el PDF."
            )
        return _build_pdf_page_index(
            annotations=result.assistant_message.annotations,
            expected_page_numbers=page_numbers,
        )
    finally:
        try:
            os.unlink(chunk_pdf_path)
        except OSError:
            logger.warning(
                "No se pudo eliminar el PDF temporal del priming OCR incremental",
                extra={"chunk_pdf_path": chunk_pdf_path},
            )


def _prime_pdf_page_group_recursive(
    *,
    source_path: str,
    page_numbers: tuple[int, ...],
    api_key: str,
    model: str,
    engine: str,
    filename: str,
    max_retries: int,
) -> tuple[OpenRouterPdfParsedPage, ...]:
    try:
        return _prime_pdf_page_group(
            source_path=source_path,
            page_numbers=page_numbers,
            api_key=api_key,
            model=model,
            engine=engine,
            filename=filename,
            max_retries=max_retries,
        )
    except OpenRouterError as exc:
        if len(page_numbers) <= 1 or not _should_split_pdf_page_group(exc):
            raise

        split_at = len(page_numbers) // 2
        left_pages = page_numbers[:split_at]
        right_pages = page_numbers[split_at:]
        logger.warning(
            "Priming OCR incremental ambiguo; dividiendo rango en dos subgrupos",
            extra={
                "page_numbers": page_numbers,
                "left_pages": left_pages,
                "right_pages": right_pages,
                "error": str(exc),
            },
        )
        left = _prime_pdf_page_group_recursive(
            source_path=source_path,
            page_numbers=left_pages,
            api_key=api_key,
            model=model,
            engine=engine,
            filename=filename,
            max_retries=max_retries,
        )
        right = _prime_pdf_page_group_recursive(
            source_path=source_path,
            page_numbers=right_pages,
            api_key=api_key,
            model=model,
            engine=engine,
            filename=filename,
            max_retries=max_retries,
        )
        return left + right


def render_pdf_page_subset_to_text(
    *,
    cache_entry: OpenRouterPdfParseCacheEntry,
    page_numbers: tuple[int, ...] | list[int],
) -> str:
    requested_pages = _normalize_expected_page_numbers(page_numbers)
    if not requested_pages:
        raise OpenRouterError("No se proporcionaron páginas para el subconjunto OCR.")
    if not cache_entry.page_index:
        raise OpenRouterError(
            "El cache OCR no incluye índice por página y no puede reutilizarse por subrangos."
        )

    page_lookup = {page.page_number: page for page in cache_entry.page_index}
    missing_pages = [page for page in requested_pages if page not in page_lookup]
    if missing_pages:
        raise OpenRouterError(
            "El subconjunto OCR solicitado contiene páginas ausentes en el cache: "
            f"{missing_pages}"
        )

    rendered_chunks: list[str] = []
    for page_number in requested_pages:
        page = page_lookup[page_number]
        for part in page.content_parts:
            part_type = part.get("type")
            if part_type == "text":
                text = str(part.get("text", ""))
                stripped = text.strip()
                if not stripped or stripped.startswith("<file name="):
                    continue
                rendered_chunks.append(text)
            elif part_type == "image_url":
                rendered_chunks.append(
                    f"[Imagen OCR asociada a la página {page_number}; "
                    "no se reinyecta como multimodal en esta llamada.]"
                )

    rendered = "\n\n".join(chunk for chunk in rendered_chunks if chunk.strip()).strip()
    if not rendered:
        raise OpenRouterError(
            "El subconjunto OCR solicitado no produjo texto reutilizable."
        )
    return rendered


def call_openrouter_chat_full(
    messages: list[dict],
    model: str,
    system_prompt: str,
    api_key: str,
    response_format: Literal["text", "json_object"] | OpenRouterJsonSchemaResponseFormat = "text",
    plugins: list[dict] | None = None,
    enable_response_healing: bool = False,
    reasoning: dict | None = None,
    max_retries: int = 5,
) -> OpenRouterChatResult:
    """
    Igual que `call_openrouter_chat`, pero preserva el mensaje del asistente
    devuelto por OpenRouter, incluidas las annotations de archivos parseados.
    """
    if not api_key:
        raise OpenRouterError("OpenRouter API key no proporcionada.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            *messages,
        ],
    }

    uses_json_mode = response_format != "text"
    if response_format == "json_object":
        payload["response_format"] = {"type": "json_object"}
    elif isinstance(response_format, OpenRouterJsonSchemaResponseFormat):
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": response_format.name,
                "strict": response_format.strict,
                "schema": response_format.schema,
            },
        }

    merged_plugins = _merge_plugins(
        plugins,
        enable_response_healing=enable_response_healing and uses_json_mode,
    )
    if merged_plugins:
        payload["plugins"] = merged_plugins

    if reasoning:
        payload["reasoning"] = reasoning

    last_exc: Exception = OpenRouterError("No se realizó ningún intento.")
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                OPENROUTER_BASE_URL,
                headers=headers,
                json=payload,
                timeout=300,
            )

            if resp.status_code == 429:
                wait = min(2 ** attempt, 60)
                logger.warning(
                    f"[OpenRouter] Rate limit (429), reintento {attempt}/{max_retries} en {wait}s"
                )
                time.sleep(wait)
                last_exc = OpenRouterRateLimitError(f"Rate limit en intento {attempt}")
                continue

            if resp.status_code in (500, 502, 503, 504):
                wait = min(2 ** attempt, 60)
                logger.warning(
                    f"[OpenRouter] Error servidor {resp.status_code}, reintento {attempt}/{max_retries} en {wait}s"
                )
                time.sleep(wait)
                last_exc = OpenRouterServiceError(f"Error {resp.status_code} en intento {attempt}")
                continue

            if resp.status_code != 200:
                raise OpenRouterError(
                    f"OpenRouter devolvió HTTP {resp.status_code}: {resp.text[:300]}"
                )

            try:
                data = resp.json()
            except ValueError:
                wait = min(2 ** attempt, 60)
                exc = _build_invalid_response_error(
                    reason="HTTP 200 con cuerpo JSON no parseable",
                    payload=None,
                    response_text=resp.text,
                )
                logger.warning(
                    "[OpenRouter] Respuesta 200 con JSON inválido, reintento %s/%s en %ss",
                    attempt,
                    max_retries,
                    wait,
                    extra={
                        "model": model,
                        "response_preview": _response_preview(resp.text),
                    },
                )
                last_exc = exc
                if attempt < max_retries:
                    time.sleep(wait)
                    continue
                raise exc

            if not isinstance(data, dict):
                wait = min(2 ** attempt, 60)
                exc = _build_invalid_response_error(
                    reason="HTTP 200 con payload no objeto",
                    payload=data,
                    response_text=resp.text,
                )
                logger.warning(
                    "[OpenRouter] Payload 200 no es un objeto, reintento %s/%s en %ss",
                    attempt,
                    max_retries,
                    wait,
                    extra={
                        "model": model,
                        "payload_type": type(data).__name__,
                    },
                )
                last_exc = exc
                if attempt < max_retries:
                    time.sleep(wait)
                    continue
                raise exc

            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                wait = min(2 ** attempt, 60)
                exc = _build_invalid_response_error(
                    reason="Falta choices en la respuesta",
                    payload=data,
                    response_text=resp.text,
                )
                logger.warning(
                    "[OpenRouter] Respuesta sin choices, reintento %s/%s en %ss",
                    attempt,
                    max_retries,
                    wait,
                    extra={
                        "model": model,
                        "payload_keys": list(data.keys()),
                        "provider_error": _extract_api_error_message(data),
                    },
                )
                last_exc = exc
                if attempt < max_retries:
                    time.sleep(wait)
                    continue
                raise exc

            choice = choices[0]
            if not isinstance(choice, dict):
                wait = min(2 ** attempt, 60)
                exc = _build_invalid_response_error(
                    reason="choices[0] no es un objeto",
                    payload=data,
                    response_text=resp.text,
                )
                logger.warning(
                    "[OpenRouter] choices[0] inválido, reintento %s/%s en %ss",
                    attempt,
                    max_retries,
                    wait,
                    extra={
                        "model": model,
                        "choice_type": type(choice).__name__,
                    },
                )
                last_exc = exc
                if attempt < max_retries:
                    time.sleep(wait)
                    continue
                raise exc

            message = choice.get("message")
            if not isinstance(message, dict):
                wait = min(2 ** attempt, 60)
                exc = _build_invalid_response_error(
                    reason="choices[0].message no es un objeto",
                    payload=data,
                    response_text=resp.text,
                )
                logger.warning(
                    "[OpenRouter] choices[0].message inválido, reintento %s/%s en %ss",
                    attempt,
                    max_retries,
                    wait,
                    extra={
                        "model": model,
                        "choice_keys": list(choice.keys()),
                    },
                )
                last_exc = exc
                if attempt < max_retries:
                    time.sleep(wait)
                    continue
                raise exc

            content_text = _extract_message_content(message)
            annotations = _extract_message_annotations(message)
            finish_reason = choice.get("finish_reason", "unknown")

            usage_raw = data.get("usage", {})
            if not isinstance(usage_raw, dict):
                usage_raw = {}
            raw_cost = usage_raw.get("cost")
            cost_usd: float | None = None
            if isinstance(raw_cost, bool):
                cost_usd = None
            elif isinstance(raw_cost, (int, float)):
                candidate = float(raw_cost)
                if math.isfinite(candidate):
                    cost_usd = round(candidate, 6)
            elif isinstance(raw_cost, str):
                normalized = raw_cost.strip()
                if normalized and re.fullmatch(
                    r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?",
                    normalized,
                ):
                    try:
                        candidate = float(normalized)
                    except ValueError:
                        cost_usd = None
                    else:
                        if math.isfinite(candidate):
                            cost_usd = round(candidate, 6)
            usage = OpenRouterUsage(
                prompt_tokens=usage_raw.get("prompt_tokens", 0),
                completion_tokens=usage_raw.get("completion_tokens", 0),
                cost_usd=cost_usd,
            )

            if not content_text:
                logger.warning(
                    "[OpenRouter] Contenido vacío recibido",
                    extra={
                        "model": model,
                        "finish_reason": finish_reason,
                        "message_keys": list(message.keys()),
                        "full_choice": str(choice)[:500],
                        "full_data_keys": list(data.keys()),
                    },
                )
            else:
                logger.debug(
                    "[OpenRouter] Respuesta OK",
                    extra={
                        "model": model,
                        "finish_reason": finish_reason,
                        "prompt_tokens": usage.prompt_token_count,
                        "completion_tokens": usage.candidates_token_count,
                        "has_annotations": bool(annotations),
                    },
                )

            parsed_or_text: str | dict[str, Any] = content_text
            if uses_json_mode:
                try:
                    parsed_or_text = _parse_json_object_content(content_text)
                except OpenRouterError as exc:
                    wait = min(2 ** attempt, 60)
                    logger.warning(
                        "[OpenRouter] JSON estructurado inválido, reintento %s/%s en %ss",
                        attempt,
                        max_retries,
                        wait,
                        extra={
                            "model": model,
                            "finish_reason": finish_reason,
                            "response_preview": content_text[:300],
                        },
                    )
                    last_exc = exc
                    if attempt < max_retries:
                        time.sleep(wait)
                        continue
                    raise

            return OpenRouterChatResult(
                content=parsed_or_text,
                usage=usage,
                assistant_message=OpenRouterAssistantMessage(
                    content=content_text,
                    annotations=annotations,
                ),
            )

        except (OpenRouterRateLimitError, OpenRouterServiceError):
            pass
        except requests.exceptions.Timeout:
            wait = min(2 ** attempt, 60)
            logger.warning(
                f"[OpenRouter] Timeout en intento {attempt}/{max_retries}, reintentando en {wait}s"
            )
            time.sleep(wait)
            last_exc = OpenRouterError(f"Timeout en intento {attempt}")
        except requests.exceptions.RequestException as e:
            if _is_retryable_requests_exception(e):
                wait = min(2 ** attempt, 60)
                logger.warning(
                    "[OpenRouter] Error de transporte reintentable en intento %s/%s, reintentando en %ss",
                    attempt,
                    max_retries,
                    wait,
                    extra={
                        "model": model,
                        "error_type": type(e).__name__,
                        "error_message": str(e)[:300],
                    },
                )
                last_exc = OpenRouterError(f"Error de red en intento {attempt}: {e}")
                if attempt < max_retries:
                    time.sleep(wait)
                    continue
                raise last_exc from e
            raise OpenRouterError(f"Error de red: {e}") from e

    raise last_exc


def get_or_prime_pdf_parse_cache(
    *,
    source_path: str,
    api_key: str,
    model: str,
    engine: str,
    filename: str | None = None,
    cache_dir: str | None = None,
    expected_page_numbers: tuple[int, ...] | list[int] | None = None,
    max_retries: int = 5,
) -> OpenRouterPdfParseCacheEntry:
    """
    Carga el cache OCR incremental de un PDF o completa solo las páginas faltantes.
    El cache se indexa por SHA-256 del documento fuente + engine de parseo.
    """
    if not os.path.isfile(source_path):
        raise OpenRouterError(f"PDF no encontrado para cache de parseo: {source_path}")

    source_sha256 = _sha256_file(source_path)
    normalized_expected_pages = _normalize_expected_page_numbers(expected_page_numbers)
    resolved_cache_dir = Path(cache_dir) if cache_dir else _default_pdf_cache_dir()
    _ensure_cache_dir(resolved_cache_dir)
    cache_path = _pdf_cache_path(source_sha256, engine, resolved_cache_dir)
    cache_lock = _get_pdf_cache_lock(source_sha256, engine)
    cache_file_lock = _pdf_cache_file_lock(cache_path)
    file_name = filename or os.path.basename(source_path) or "document.pdf"

    with cache_file_lock:
        with cache_lock:
            assistant_message: OpenRouterAssistantMessage | None = None
            page_index: tuple[OpenRouterPdfParsedPage, ...] = ()
            document_page_count: int | None = None

            if cache_path.is_file():
                try:
                    assistant_message, page_index, document_page_count = _load_pdf_parse_cache(cache_path)
                    if not page_index and assistant_message and assistant_message.annotations:
                        try:
                            page_index = _build_pdf_page_index(
                                annotations=assistant_message.annotations,
                                expected_page_numbers=normalized_expected_pages,
                            )
                        except OpenRouterError:
                            if normalized_expected_pages:
                                raise
                            page_index = ()
                        else:
                            _write_pdf_parse_cache(
                                cache_path=cache_path,
                                source_sha256=source_sha256,
                                engine=engine,
                                assistant_message=assistant_message,
                                document_page_count=document_page_count,
                                page_index=page_index,
                            )
                except (OSError, json.JSONDecodeError, TypeError, ValueError, OpenRouterError) as exc:
                    logger.warning(
                        "Cache de parseo OpenRouter inválida; se regenerará",
                        extra={
                            "cache_path": str(cache_path),
                            "engine": engine,
                            "error": str(exc),
                        },
                    )
                    assistant_message = None
                    page_index = ()
                    document_page_count = None

            effective_expected_pages = normalized_expected_pages
            if not effective_expected_pages:
                if document_page_count is None:
                    document_page_count = len(PdfReader(source_path).pages)
                effective_expected_pages = tuple(range(1, document_page_count + 1))

            cached_page_numbers = _page_numbers_from_index(page_index)
            cached_page_lookup = {page.page_number: page for page in page_index}
            missing_pages = tuple(
                page_number
                for page_number in effective_expected_pages
                if page_number not in cached_page_lookup
            )

            if not missing_pages and page_index:
                return OpenRouterPdfParseCacheEntry(
                    source_sha256=source_sha256,
                    engine=engine,
                    assistant_message=assistant_message,
                    cache_path=str(cache_path),
                    cache_hit=True,
                    expected_page_numbers=effective_expected_pages,
                    cached_page_numbers=cached_page_numbers,
                    page_index=page_index,
                )

            if missing_pages:
                logger.info(
                    "Completando cache OCR incremental con páginas faltantes",
                    extra={
                        "cache_path": str(cache_path),
                        "engine": engine,
                        "requested_pages_count": len(effective_expected_pages),
                        "cached_pages_count": len(cached_page_numbers),
                        "missing_pages_count": len(missing_pages),
                        "missing_page_groups": _group_contiguous_pages(missing_pages),
                    },
                )
                for page_group in _group_contiguous_pages(missing_pages):
                    primed_pages = _prime_pdf_page_group_recursive(
                        source_path=source_path,
                        page_numbers=page_group,
                        api_key=api_key,
                        model=model,
                        engine=engine,
                        filename=file_name,
                        max_retries=max_retries,
                    )
                    page_index = _merge_page_indexes(page_index, primed_pages)

                cached_page_numbers = _page_numbers_from_index(page_index)
                _write_pdf_parse_cache(
                    cache_path=cache_path,
                    source_sha256=source_sha256,
                    engine=engine,
                    assistant_message=assistant_message,
                    document_page_count=document_page_count,
                    page_index=page_index,
                )

            return OpenRouterPdfParseCacheEntry(
                source_sha256=source_sha256,
                engine=engine,
                assistant_message=assistant_message,
                cache_path=str(cache_path),
                cache_hit=not missing_pages,
                expected_page_numbers=effective_expected_pages,
                cached_page_numbers=cached_page_numbers,
                page_index=page_index,
            )


def build_messages_with_cached_pdf_annotations(
    *,
    source_path: str,
    cache_entry: OpenRouterPdfParseCacheEntry,
    user_text: str,
    filename: str | None = None,
) -> list[dict[str, Any]]:
    if cache_entry.assistant_message is None or not cache_entry.assistant_message.annotations:
        raise OpenRouterError(
            "El cache OCR no incluye annotations reutilizables para reenviar el PDF completo."
        )

    file_name = filename or os.path.basename(source_path) or "document.pdf"
    return [
        {
            "role": "user",
            "content": _build_pdf_file_content(
                source_path=source_path,
                filename=file_name,
                text=_parse_cache_user_text(),
            ),
        },
        {
            "role": "assistant",
            "content": cache_entry.assistant_message.content,
            "annotations": cache_entry.assistant_message.annotations or [],
        },
        {
            "role": "user",
            "content": user_text,
        },
    ]


def call_openrouter_chat(
    messages: list[dict],
    model: str,
    system_prompt: str,
    api_key: str,
    response_format: Literal["text", "json_object"] | OpenRouterJsonSchemaResponseFormat = "text",
    plugins: list[dict] | None = None,
    enable_response_healing: bool = False,
    reasoning: dict | None = None,
    max_retries: int = 5,
) -> tuple[str | dict[str, Any], OpenRouterUsage]:
    """
    Llama a OpenRouter /chat/completions.
    Puede pedir texto libre, `json_object` o `json_schema`, según el contrato esperado.
    Retorna (content, OpenRouterUsage), donde `content` es `str` o `dict`.
    """
    result = call_openrouter_chat_full(
        messages=messages,
        model=model,
        system_prompt=system_prompt,
        api_key=api_key,
        response_format=response_format,
        plugins=plugins,
        enable_response_healing=enable_response_healing,
        reasoning=reasoning,
        max_retries=max_retries,
    )
    return result.content, result.usage
