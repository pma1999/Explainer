"""Provider-neutral PDF OCR cache primitives and disk persistence."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


_PAGE_MARKER_ONLY_RE = re.compile(r"^— Página\s+\d+\s*/\s*\d+\s+—$")
_PDF_OCR_CACHE_VERSION = 1


class PdfOcrError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PdfOcrParsedPage:
    page_number: int
    markdown: str
    images: tuple[dict[str, Any], ...] = ()
    tables: tuple[dict[str, Any], ...] = ()
    hyperlinks: tuple[str, ...] = ()
    header: str | None = None
    footer: str | None = None
    dimensions: dict[str, Any] | None = None
    confidence_scores: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class PdfOcrBuildResult:
    page_index: tuple[PdfOcrParsedPage, ...]
    detected_pages: tuple[int, ...]
    missing_pages: tuple[int, ...]
    raw_response: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PdfOcrCacheEntry:
    source_sha256: str
    engine: str
    cache_path: str
    cache_hit: bool
    expected_page_numbers: tuple[int, ...] = ()
    cached_page_numbers: tuple[int, ...] = ()
    page_index: tuple[PdfOcrParsedPage, ...] = ()
    diagnostic_artifact_path: str | None = None


def normalize_expected_page_numbers(page_numbers: tuple[int, ...] | list[int] | None) -> tuple[int, ...]:
    if not page_numbers:
        return ()

    normalized_list: list[int] = []
    for page in page_numbers:
        try:
            normalized_list.append(int(page))
        except (TypeError, ValueError) as exc:
            raise PdfOcrError(
                "expected_page_numbers contiene elementos inválidos (no se pueden convertir a enteros)."
            ) from exc
    normalized = tuple(normalized_list)
    if any(page < 1 for page in normalized):
        raise PdfOcrError("expected_page_numbers contiene páginas inválidas (< 1).")
    if len(set(normalized)) != len(normalized):
        raise PdfOcrError("expected_page_numbers contiene páginas duplicadas.")
    if normalized != tuple(sorted(normalized)):
        raise PdfOcrError("expected_page_numbers debe venir en orden ascendente.")
    return normalized


def merge_page_indexes(
    existing: tuple[PdfOcrParsedPage, ...],
    updates: tuple[PdfOcrParsedPage, ...],
) -> tuple[PdfOcrParsedPage, ...]:
    merged = {page.page_number: page for page in existing}
    for page in updates:
        merged[page.page_number] = page
    return tuple(merged[page_number] for page_number in sorted(merged))


def _strip_watermark_lines(markdown: str) -> str:
    return "\n".join(
        line for line in markdown.splitlines() if not _PAGE_MARKER_ONLY_RE.fullmatch(line.strip())
    )


def _replace_table_placeholders(markdown: str, tables: tuple[dict[str, Any], ...]) -> str:
    rendered = markdown
    for table in tables:
        table_id = str(table.get("id", "")).strip()
        content = str(table.get("content", "")).strip()
        if not table_id or not content:
            continue
        placeholder = f"[{table_id}]({table_id})"
        rendered = rendered.replace(placeholder, f"[Tabla OCR {table_id}]\n{content}")
    return rendered


def _replace_image_placeholders(markdown: str, images: tuple[dict[str, Any], ...]) -> str:
    rendered = markdown
    for image in images:
        image_id = str(image.get("id", "")).strip()
        if not image_id:
            continue
        placeholder = f"![{image_id}]({image_id})"
        rendered = rendered.replace(
            placeholder,
            f"[Imagen OCR {image_id}; no se reinyecta como multimodal en esta llamada.]",
        )
    return rendered


def render_pdf_page_subset_to_text(
    *,
    cache_entry: PdfOcrCacheEntry,
    page_numbers: tuple[int, ...] | list[int],
) -> str:
    requested_pages = normalize_expected_page_numbers(page_numbers)
    page_lookup = {page.page_number: page for page in cache_entry.page_index}
    missing_pages = [page for page in requested_pages if page not in page_lookup]
    if missing_pages:
        raise PdfOcrError(
            "El subconjunto OCR solicitado contiene páginas ausentes en el cache: "
            f"{missing_pages}"
        )

    rendered_chunks: list[str] = []
    for page_number in requested_pages:
        page = page_lookup[page_number]
        page_text = _strip_watermark_lines(page.markdown)
        page_text = _replace_table_placeholders(page_text, page.tables)
        page_text = _replace_image_placeholders(page_text, page.images)
        page_text = page_text.strip()
        if page_text:
            rendered_chunks.append(page_text)

        if page.footer:
            footer = page.footer.strip()
            if footer and not _PAGE_MARKER_ONLY_RE.fullmatch(footer):
                rendered_chunks.append(f"[Footer página {page_number}]\n{footer}")

    rendered = "\n\n".join(chunk for chunk in rendered_chunks if chunk.strip()).strip()
    if not rendered:
        raise PdfOcrError("El subconjunto OCR solicitado no produjo texto reutilizable.")
    return rendered


def render_pdf_pages_with_xml_tags(
    *,
    cache_entry: PdfOcrCacheEntry,
    page_numbers: tuple[int, ...] | list[int],
) -> str:
    """Render OCR pages wrapped in XML tags for LLM consumption.

    Each page is enclosed in <pagina_N>...</pagina_N> so models always
    know the absolute page number regardless of where in the document
    the excerpt sits.
    """
    requested_pages = normalize_expected_page_numbers(page_numbers)
    if not requested_pages:
        raise PdfOcrError("No se proporcionaron páginas OCR.")
    page_lookup = {page.page_number: page for page in cache_entry.page_index}
    missing_pages = [page for page in requested_pages if page not in page_lookup]
    if missing_pages:
        raise PdfOcrError(
            "El subconjunto OCR solicitado contiene páginas ausentes en el cache: "
            f"{missing_pages}"
        )

    page_chunks: list[str] = []
    for page_number in requested_pages:
        page = page_lookup[page_number]
        page_text = _strip_watermark_lines(page.markdown)
        page_text = _replace_table_placeholders(page_text, page.tables)
        page_text = _replace_image_placeholders(page_text, page.images)
        page_text = page_text.strip()

        parts: list[str] = []
        if page_text:
            parts.append(page_text)
        if page.footer:
            footer = page.footer.strip()
            if footer and not _PAGE_MARKER_ONLY_RE.fullmatch(footer):
                parts.append(f"[Footer página {page_number}]\n{footer}")

        if parts:
            inner = "\n\n".join(parts)
            page_chunks.append(f"<pagina_{page_number}>\n{inner}\n</pagina_{page_number}>")

    if not page_chunks:
        raise PdfOcrError("El subconjunto OCR solicitado no produjo texto reutilizable.")

    return "\n\n".join(page_chunks)


def render_pdf_page_subset_to_validation_text(
    *,
    cache_entry: PdfOcrCacheEntry,
    page_numbers: tuple[int, ...] | list[int],
) -> str:
    """Render OCR pages for scope validation with XML page boundary tags."""
    requested_pages = normalize_expected_page_numbers(page_numbers)
    page_lookup = {page.page_number: page for page in cache_entry.page_index}
    missing_pages = [page for page in requested_pages if page not in page_lookup]
    if missing_pages:
        raise PdfOcrError(
            "El subconjunto OCR solicitado para validacion contiene páginas ausentes en el cache: "
            f"{missing_pages}"
        )

    rendered_chunks: list[str] = []
    for page_number in requested_pages:
        page = page_lookup[page_number]
        page_text = _strip_watermark_lines(page.markdown)
        page_text = _replace_table_placeholders(page_text, page.tables)
        page_text = _replace_image_placeholders(page_text, page.images)
        page_parts = [chunk for chunk in (page_text.strip(), (page.footer or "").strip()) if chunk]
        if page_parts:
            inner = "\n\n".join(page_parts)
            rendered_chunks.append(f"<pagina_{page_number}>\n{inner}\n</pagina_{page_number}>")

    rendered = "\n\n".join(chunk for chunk in rendered_chunks if chunk.strip()).strip()
    if not rendered:
        raise PdfOcrError("El subconjunto OCR solicitado para validacion no produjo texto reutilizable.")
    return rendered


def serialize_page_index(page_index: tuple[PdfOcrParsedPage, ...]) -> list[dict[str, Any]]:
    return [
        {
            "page_number": page.page_number,
            "markdown": page.markdown,
            "images": list(page.images),
            "tables": list(page.tables),
            "hyperlinks": list(page.hyperlinks),
            "header": page.header,
            "footer": page.footer,
            "dimensions": page.dimensions,
            "confidence_scores": page.confidence_scores,
        }
        for page in page_index
    ]


def page_index_from_serialized(raw: Any) -> tuple[PdfOcrParsedPage, ...]:
    """
    Deserialize page_index from cache JSON. Fail-closed: any malformed row or
    invalid nested shape yields an empty tuple (same spirit as OpenRouter cache).
    """
    if not isinstance(raw, list):
        return ()

    seen_pages: set[int] = set()
    pages: list[PdfOcrParsedPage] = []

    for item in raw:
        if not isinstance(item, dict):
            return ()

        page_number = item.get("page_number")
        markdown = item.get("markdown")
        # Reject bool: isinstance(True, int) is True in Python.
        if type(page_number) is not int or page_number < 1:
            return ()
        if not isinstance(markdown, str):
            return ()
        if page_number in seen_pages:
            return ()
        seen_pages.add(page_number)

        if "images" in item:
            images_raw = item["images"]
            if not isinstance(images_raw, list) or not all(isinstance(x, dict) for x in images_raw):
                return ()
            images_t: tuple[dict[str, Any], ...] = tuple(images_raw)
        else:
            images_t = ()

        if "tables" in item:
            tables_raw = item["tables"]
            if not isinstance(tables_raw, list) or not all(isinstance(x, dict) for x in tables_raw):
                return ()
            tables_t: tuple[dict[str, Any], ...] = tuple(tables_raw)
        else:
            tables_t = ()

        if "hyperlinks" in item:
            hl_raw = item["hyperlinks"]
            if not isinstance(hl_raw, list) or not all(isinstance(x, str) for x in hl_raw):
                return ()
            hyperlinks_t: tuple[str, ...] = tuple(hl_raw)
        else:
            hyperlinks_t = ()

        if "header" in item:
            header_v = item["header"]
            if header_v is not None and not isinstance(header_v, str):
                return ()
        else:
            header_v = None

        if "footer" in item:
            footer_v = item["footer"]
            if footer_v is not None and not isinstance(footer_v, str):
                return ()
        else:
            footer_v = None

        if "dimensions" in item:
            dim = item["dimensions"]
            if dim is not None and not isinstance(dim, dict):
                return ()
            dimensions_v: dict[str, Any] | None = dim
        else:
            dimensions_v = None

        if "confidence_scores" in item:
            conf = item["confidence_scores"]
            if conf is not None and not isinstance(conf, dict):
                return ()
            confidence_v: dict[str, Any] | None = conf
        else:
            confidence_v = None

        pages.append(
            PdfOcrParsedPage(
                page_number=page_number,
                markdown=markdown,
                images=images_t,
                tables=tables_t,
                hyperlinks=hyperlinks_t,
                header=header_v,
                footer=footer_v,
                dimensions=dimensions_v,
                confidence_scores=confidence_v,
            )
        )

    return tuple(sorted(pages, key=lambda page: page.page_number))


def build_pdf_ocr_payload(
    *,
    source_sha256: str,
    engine: str,
    document_page_count: int | None,
    page_index: tuple[PdfOcrParsedPage, ...],
) -> dict[str, Any]:
    return {
        "version": _PDF_OCR_CACHE_VERSION,
        "source_sha256": source_sha256,
        "engine": engine,
        "document_page_count": document_page_count,
        "page_index": serialize_page_index(page_index),
    }


def load_pdf_ocr_cache_from_mapping(
    cached: dict[str, Any] | None,
) -> tuple[tuple[PdfOcrParsedPage, ...], int | None]:
    if not isinstance(cached, dict):
        return (), None

    # Fail closed unless the payload declares the exact cache schema version we write.
    version = cached.get("version")
    if not isinstance(version, int) or version != _PDF_OCR_CACHE_VERSION:
        return (), None

    page_index = page_index_from_serialized(cached.get("page_index"))
    document_page_count = cached.get("document_page_count")
    if not isinstance(document_page_count, int) or document_page_count < 1:
        document_page_count = None
    return page_index, document_page_count


def write_pdf_ocr_cache(
    *,
    cache_path: Path,
    source_sha256: str,
    engine: str,
    document_page_count: int | None,
    page_index: tuple[PdfOcrParsedPage, ...],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_pdf_ocr_payload(
        source_sha256=source_sha256,
        engine=engine,
        document_page_count=document_page_count,
        page_index=page_index,
    )
    safe_engine = engine.replace("/", "_").replace("\\", "_")
    fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp",
        prefix=f"{source_sha256}.{safe_engine}.",
        dir=str(cache_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, cache_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def write_unresolved_pdf_ocr_artifact(
    *,
    cache_path: Path,
    source_sha256: str,
    engine: str,
    model: str,
    expected_page_numbers: tuple[int, ...],
    build_result: PdfOcrBuildResult,
) -> str:
    artifact_path = cache_path.with_suffix(cache_path.suffix + ".missing-pages.json")
    payload = {
        "source_sha256": source_sha256,
        "engine": engine,
        "model": model,
        "expected_pages": list(expected_page_numbers),
        "detected_pages": list(build_result.detected_pages),
        "missing_pages": list(build_result.missing_pages),
        "raw_response": build_result.raw_response,
    }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with open(artifact_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return str(artifact_path)
