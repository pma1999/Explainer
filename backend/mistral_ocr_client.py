from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from mistralai.client import Mistral
from pypdf import PdfReader

from backend.pdf_ocr_cache import (
    PdfOcrBuildResult,
    PdfOcrCacheEntry,
    PdfOcrError,
    PdfOcrParsedPage,
    build_pdf_ocr_payload,
    load_pdf_ocr_cache_from_mapping,
    merge_page_indexes,
    normalize_expected_page_numbers,
    write_pdf_ocr_cache,
    write_unresolved_pdf_ocr_artifact,
)
import backend.supabase_pdf_ocr_cache as supabase_pdf_ocr_cache

logger = logging.getLogger("backend.mistral_ocr_client")

MISTRAL_OCR_MODEL = "mistral-ocr-latest"
MISTRAL_OCR_ENGINE = "mistral-native"


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_pdf_cache_dir() -> Path:
    configured = (
        os.environ.get("PDF_OCR_CACHE_DIR", "").strip()
        or os.environ.get("OPENROUTER_PDF_CACHE_DIR", "").strip()
    )
    if configured:
        return Path(configured)
    return Path.cwd() / "data" / "pdf_ocr_cache"


def _ocr_cache_backend_for_call(cache_dir: str | None) -> str:
    if cache_dir is not None:
        return "disk"
    raw = (
        os.environ.get("PDF_OCR_CACHE_BACKEND", "").strip().lower()
        or os.environ.get("OPENROUTER_OCR_CACHE_BACKEND", "").strip().lower()
        or "auto"
    )
    if raw == "auto":
        has_supabase = bool(os.environ.get("SUPABASE_URL", "").strip()) and bool(
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        )
        return "supabase" if has_supabase else "disk"
    if raw not in {"disk", "supabase"}:
        raise PdfOcrError(f"Backend de caché OCR no soportado: {raw}")
    return raw


def _pdf_cache_path(source_sha256: str, engine: str, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{source_sha256}.{engine.replace('/', '_')}.json"
    return cache_dir / filename


def _to_mistral_page_indexes(expected_page_numbers: tuple[int, ...]) -> list[int]:
    return [page_number - 1 for page_number in normalize_expected_page_numbers(expected_page_numbers)]


def _response_to_mapping(response: Any) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        payload = response.model_dump(mode="python")
    elif isinstance(response, dict):
        payload = response
    else:
        raise PdfOcrError("La respuesta OCR de Mistral no es serializable.")
    if not isinstance(payload, dict):
        raise PdfOcrError("La respuesta OCR de Mistral debe ser un objeto.")
    return payload


def _build_mistral_ocr_result(
    *,
    response_payload: dict[str, Any],
    expected_page_numbers: tuple[int, ...],
) -> PdfOcrBuildResult:
    expected = normalize_expected_page_numbers(expected_page_numbers)
    raw_pages = response_payload.get("pages")
    if not isinstance(raw_pages, list):
        raise PdfOcrError("La respuesta OCR de Mistral no incluye `pages`.")

    normalized_pages: list[PdfOcrParsedPage] = []
    for raw_page in raw_pages:
        if not isinstance(raw_page, dict):
            continue
        raw_index = raw_page.get("index")
        markdown = raw_page.get("markdown")
        if not isinstance(raw_index, int) or not isinstance(markdown, str):
            continue
        normalized_pages.append(
            PdfOcrParsedPage(
                page_number=raw_index + 1,
                markdown=markdown,
                images=tuple(raw_page.get("images") or ()),
                tables=tuple(raw_page.get("tables") or ()),
                hyperlinks=tuple(raw_page.get("hyperlinks") or ()),
                header=raw_page.get("header"),
                footer=raw_page.get("footer"),
                dimensions=raw_page.get("dimensions"),
                confidence_scores=raw_page.get("confidence_scores"),
            )
        )

    normalized_tuple = tuple(sorted(normalized_pages, key=lambda page: page.page_number))
    detected_pages = tuple(page.page_number for page in normalized_tuple)
    missing_pages = tuple(page for page in expected if page not in detected_pages)
    return PdfOcrBuildResult(
        page_index=normalized_tuple,
        detected_pages=detected_pages,
        missing_pages=missing_pages,
        raw_response=response_payload,
    )


def _fetch_missing_pages_once(
    *,
    source_path: str,
    api_key: str,
    model: str,
    expected_page_numbers: tuple[int, ...],
    filename: str,
) -> PdfOcrBuildResult:
    client = Mistral(api_key=api_key)
    with open(source_path, "rb") as handle:
        uploaded = client.files.upload(
            file={"file_name": filename, "content": handle},
            purpose="ocr",
        )
    try:
        signed_url = client.files.get_signed_url(file_id=uploaded.id)
        response = client.ocr.process(
            model=model,
            document={"type": "document_url", "document_url": signed_url.url},
            pages=_to_mistral_page_indexes(expected_page_numbers),
            table_format="html",
            extract_footer=True,
            include_image_base64=False,
        )
    except Exception as exc:
        raise PdfOcrError(f"Error al solicitar OCR nativo a Mistral: {exc}") from exc
    finally:
        try:
            client.files.delete(file_id=uploaded.id)
        except Exception as delete_exc:
            logger.warning("No se pudo borrar el archivo OCR remoto de Mistral: %s", delete_exc)

    return _build_mistral_ocr_result(
        response_payload=_response_to_mapping(response),
        expected_page_numbers=expected_page_numbers,
    )


def get_or_prime_mistral_pdf_ocr_cache(
    *,
    source_path: str,
    api_key: str,
    model: str,
    engine: str,
    filename: str | None = None,
    cache_dir: str | None = None,
    expected_page_numbers: tuple[int, ...] | list[int] | None = None,
) -> PdfOcrCacheEntry:
    if not os.path.isfile(source_path):
        raise PdfOcrError(f"PDF no encontrado para OCR: {source_path}")

    source_sha256 = _sha256_file(source_path)
    expected = normalize_expected_page_numbers(expected_page_numbers)
    resolved_cache_dir = Path(cache_dir) if cache_dir else _default_pdf_cache_dir()
    cache_path = _pdf_cache_path(source_sha256, engine, resolved_cache_dir)
    document_page_count = len(PdfReader(source_path).pages)

    page_index: tuple[PdfOcrParsedPage, ...] = ()
    row_version: int | None = None
    storage_ref = str(cache_path)
    backend = _ocr_cache_backend_for_call(cache_dir)
    use_supabase = backend == "supabase"

    if use_supabase:
        payload, row_version = supabase_pdf_ocr_cache.fetch_cache(source_sha256, engine)
        if payload is not None:
            page_index, cached_page_count = load_pdf_ocr_cache_from_mapping(payload)
            if cached_page_count is not None:
                document_page_count = cached_page_count
            storage_ref = supabase_pdf_ocr_cache.supabase_cache_uri(source_sha256, engine)
    elif cache_path.is_file():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        page_index, cached_page_count = load_pdf_ocr_cache_from_mapping(cached)
        if cached_page_count is not None:
            document_page_count = cached_page_count

    effective_expected = expected or tuple(range(1, document_page_count + 1))
    cached_page_numbers = tuple(page.page_number for page in page_index)
    missing_pages = tuple(page for page in effective_expected if page not in cached_page_numbers)

    diagnostic_artifact_path: str | None = None
    if missing_pages:
        build_result = _fetch_missing_pages_once(
            source_path=source_path,
            api_key=api_key,
            model=model,
            expected_page_numbers=missing_pages,
            filename=filename or os.path.basename(source_path) or "document.pdf",
        )
        page_index = merge_page_indexes(page_index, build_result.page_index)
        if build_result.missing_pages:
            diagnostic_artifact_path = write_unresolved_pdf_ocr_artifact(
                cache_path=cache_path,
                source_sha256=source_sha256,
                engine=engine,
                model=model,
                expected_page_numbers=missing_pages,
                build_result=build_result,
            )

        payload = build_pdf_ocr_payload(
            source_sha256=source_sha256,
            engine=engine,
            document_page_count=document_page_count,
            page_index=page_index,
        )
        if use_supabase:
            wrote = False
            for _ in range(supabase_pdf_ocr_cache.MAX_WRITE_ATTEMPTS):
                ok, new_row_version = supabase_pdf_ocr_cache.try_write_cache(
                    source_sha256,
                    engine,
                    payload,
                    row_version,
                )
                if ok:
                    row_version = new_row_version
                    wrote = True
                    break
                latest_payload, latest_row_version = supabase_pdf_ocr_cache.fetch_cache(source_sha256, engine)
                if latest_payload is None:
                    row_version = None
                    continue
                latest_page_index, latest_page_count = load_pdf_ocr_cache_from_mapping(latest_payload)
                if latest_page_count is not None:
                    document_page_count = latest_page_count
                page_index = merge_page_indexes(latest_page_index, build_result.page_index)
                payload = build_pdf_ocr_payload(
                    source_sha256=source_sha256,
                    engine=engine,
                    document_page_count=document_page_count,
                    page_index=page_index,
                )
                row_version = latest_row_version
            if not wrote:
                raise PdfOcrError("Conflicto persistente al guardar la caché OCR de Mistral.")
        else:
            write_pdf_ocr_cache(
                cache_path=cache_path,
                source_sha256=source_sha256,
                engine=engine,
                document_page_count=document_page_count,
                page_index=page_index,
            )

    merged_cached_pages = tuple(page.page_number for page in page_index)
    return PdfOcrCacheEntry(
        source_sha256=source_sha256,
        engine=engine,
        cache_path=storage_ref,
        cache_hit=not bool(missing_pages),
        expected_page_numbers=effective_expected,
        cached_page_numbers=merged_cached_pages,
        page_index=page_index,
        diagnostic_artifact_path=diagnostic_artifact_path,
    )
