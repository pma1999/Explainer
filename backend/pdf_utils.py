"""PDF utilities for page numbering and page range extraction.

Provides:
- add_page_numbers: Adds visible "— Página X / N —" watermarks to every page
- extract_page_range: Extracts a subset of consecutive pages (with optional buffer)
- extract_pages: Extracts an arbitrary ordered set of pages into a new PDF
"""

from __future__ import annotations

import os
import tempfile

import fitz  # PyMuPDF
from pypdf import PdfReader, PdfWriter

from backend.logging_config import get_logger

logger = get_logger("backend.pdf_utils")

_MM_TO_PT = 2.834645669  # 1 mm in PDF points


def add_page_numbers(input_path: str) -> str:
    """Add visible page number watermarks to every page of a PDF.

    Creates a new temporary PDF with "— Página X / N —" overlaid at the
    bottom-center of each page. The original file is not modified.

    Uses PyMuPDF (fitz) to insert text directly into the page content stream
    so that OCR engines can read the watermark and the original page text is
    fully preserved (pypdf's merge_page corrupts content streams on pages that
    use compressed or form-XObject resources).

    Args:
        input_path: Path to the source PDF file.

    Returns:
        Path to the new temporary PDF with page numbers.
        Caller is responsible for deleting this file when done.

    Raises:
        FileNotFoundError: If input_path does not exist.
        Exception: If PDF reading or writing fails.
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"PDF not found: {input_path}")

    logger.info("Adding page numbers to PDF", extra={"input_path": input_path})

    doc = fitz.open(input_path)
    total_pages = len(doc)

    logger.info(f"PDF has {total_pages} pages", extra={"total_pages": total_pages})

    font_name = "hebo"  # Helvetica-Bold (built-in PDF font)
    font_size = 10
    pad_h = 6  # horizontal padding around label (points)
    pad_v = 3  # vertical padding around label (points)
    y_from_bottom = 8 * _MM_TO_PT  # baseline distance from page bottom

    for page in doc:
        label = f"— Página {page.number + 1} / {total_pages} —"
        rect = page.rect

        text_width = fitz.get_text_length(label, fontname=font_name, fontsize=font_size)
        x = (rect.width - text_width) / 2
        # In PyMuPDF y=0 is the top; insert_text point is the text baseline.
        y_baseline = rect.height - y_from_bottom

        bg = fitz.Rect(
            x - pad_h,
            y_baseline - font_size - pad_v,
            x + text_width + pad_h,
            y_baseline + pad_v,
        )
        page.draw_rect(bg, color=(0.6, 0.6, 0.6), fill=(1, 1, 1), fill_opacity=0.85, width=0.5)
        page.insert_text((x, y_baseline), label, fontname=font_name, fontsize=font_size, color=(0.15, 0.15, 0.15))

    fd, output_path = tempfile.mkstemp(suffix="_numbered.pdf")
    os.close(fd)
    try:
        doc.save(output_path)
    except Exception:
        if os.path.isfile(output_path):
            os.unlink(output_path)
        raise
    finally:
        doc.close()

    output_size = os.path.getsize(output_path)
    logger.info(
        f"Numbered PDF created: {output_path} ({output_size} bytes)",
        extra={"output_path": output_path, "output_size_bytes": output_size, "total_pages": total_pages},
    )

    return output_path


def extract_page_range(
    input_path: str,
    start_page: int,
    end_page: int,
    buffer: int = 1,
) -> str:
    """Extract a range of pages from a PDF into a new temporary file.

    Pages are 1-indexed. A buffer of extra pages is added on each side
    to ensure no content is lost at segment boundaries.

    Args:
        input_path: Path to the source PDF file.
        start_page: First page to include (1-indexed, inclusive).
        end_page: Last page to include (1-indexed, inclusive).
        buffer: Number of extra pages to include on each side (default: 1).

    Returns:
        Path to the new temporary PDF containing the extracted pages.
        Caller is responsible for deleting this file when done.

    Raises:
        FileNotFoundError: If input_path does not exist.
        ValueError: If page range is invalid.
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"PDF not found: {input_path}")

    reader = PdfReader(input_path)
    total_pages = len(reader.pages)

    if start_page < 1 or end_page < 1 or start_page > end_page:
        raise ValueError(
            f"Invalid page range: start_page={start_page}, end_page={end_page}"
        )

    # Apply buffer and clamp to valid range
    actual_start = max(1, start_page - buffer)
    actual_end = min(total_pages, end_page + buffer)

    logger.info(
        f"Extracting pages {actual_start}-{actual_end} "
        f"(requested {start_page}-{end_page}, buffer={buffer}, total={total_pages})",
        extra={
            "input_path": input_path,
            "requested_start": start_page,
            "requested_end": end_page,
            "actual_start": actual_start,
            "actual_end": actual_end,
            "buffer": buffer,
            "total_pages": total_pages,
        }
    )

    writer = PdfWriter()
    # Convert to 0-indexed for pypdf
    for i in range(actual_start - 1, actual_end):
        writer.add_page(reader.pages[i])

    # Write to temp file
    fd, output_path = tempfile.mkstemp(suffix="_segment.pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            writer.write(f)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        if os.path.isfile(output_path):
            os.unlink(output_path)
        raise

    output_size = os.path.getsize(output_path)
    num_pages = actual_end - actual_start + 1
    logger.info(
        f"Segment PDF created: {num_pages} pages, {output_size} bytes",
        extra={
            "output_path": output_path,
            "output_size_bytes": output_size,
            "num_pages": num_pages,
        }
    )

    return output_path


def extract_pages(input_path: str, pages: list[int] | tuple[int, ...]) -> str:
    """Extract an arbitrary ordered set of pages into a new temporary PDF.

    Pages are 1-indexed and copied in the exact order provided. Repeated pages
    are rejected because downstream cache keys assume a canonical, deduplicated
    document for a given page set.

    Args:
        input_path: Path to the source PDF file.
        pages: Ordered page numbers to copy (1-indexed).

    Returns:
        Path to the new temporary PDF containing exactly the requested pages.
        Caller is responsible for deleting this file when done.

    Raises:
        FileNotFoundError: If input_path does not exist.
        ValueError: If pages is empty, contains duplicates, or includes an
            out-of-range page number.
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"PDF not found: {input_path}")
    if not pages:
        raise ValueError("At least one page must be provided")

    ordered_pages = [int(page) for page in pages]
    if len(set(ordered_pages)) != len(ordered_pages):
        raise ValueError("Duplicate pages are not allowed in extract_pages")

    reader = PdfReader(input_path)
    total_pages = len(reader.pages)

    invalid_pages = [page for page in ordered_pages if page < 1 or page > total_pages]
    if invalid_pages:
        raise ValueError(
            f"Invalid page numbers for extract_pages: {invalid_pages} (total={total_pages})"
        )

    logger.info(
        "Extracting explicit page set from PDF",
        extra={
            "input_path": input_path,
            "pages_count": len(ordered_pages),
            "first_page": ordered_pages[0],
            "last_page": ordered_pages[-1],
            "total_pages": total_pages,
        },
    )

    writer = PdfWriter()
    for page_number in ordered_pages:
        writer.add_page(reader.pages[page_number - 1])

    fd, output_path = tempfile.mkstemp(suffix="_pageset.pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            writer.write(f)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        if os.path.isfile(output_path):
            os.unlink(output_path)
        raise

    output_size = os.path.getsize(output_path)
    logger.info(
        "Page-set PDF created",
        extra={
            "output_path": output_path,
            "output_size_bytes": output_size,
            "num_pages": len(ordered_pages),
        },
    )

    return output_path
