"""PDF utilities for page numbering and page range extraction.

Provides:
- add_page_numbers: Adds visible "— Página X / N —" watermarks to every page
- extract_page_range: Extracts a subset of pages (with optional buffer) into a new PDF
"""

from __future__ import annotations

import io
import os
import tempfile

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from backend.logging_config import get_logger

logger = get_logger("backend.pdf_utils")


def _create_page_number_overlay(page_width: float, page_height: float, page_num: int, total_pages: int) -> io.BytesIO:
    """Create a single-page transparent PDF with a page number stamp.

    The stamp is placed at the bottom-center of the page with a semi-transparent
    white background rectangle for readability against any content.

    Args:
        page_width: Width of the target page in points.
        page_height: Height of the target page in points.
        page_num: Current page number (1-indexed).
        total_pages: Total number of pages.

    Returns:
        BytesIO buffer containing the single-page overlay PDF.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_width, page_height))

    label = f"— Página {page_num} / {total_pages} —"

    # Font setup
    font_name = "Helvetica-Bold"
    font_size = 10
    c.setFont(font_name, font_size)

    # Measure text width for centering and background rectangle
    text_width = c.stringWidth(label, font_name, font_size)

    # Position: bottom-center, 8mm from bottom edge
    x = page_width / 2
    y = 8 * mm

    # Draw semi-transparent white background rectangle for readability
    padding_h = 6
    padding_v = 3
    rect_x = x - text_width / 2 - padding_h
    rect_y = y - padding_v
    rect_w = text_width + 2 * padding_h
    rect_h = font_size + 2 * padding_v

    c.saveState()
    c.setFillColorRGB(1, 1, 1, alpha=0.85)
    c.setStrokeColorRGB(0.6, 0.6, 0.6, alpha=0.5)
    c.setLineWidth(0.5)
    c.roundRect(rect_x, rect_y, rect_w, rect_h, radius=3, fill=1, stroke=1)
    c.restoreState()

    # Draw text
    c.setFillColorRGB(0.15, 0.15, 0.15)
    c.setFont(font_name, font_size)
    c.drawCentredString(x, y, label)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf


def add_page_numbers(input_path: str) -> str:
    """Add visible page number watermarks to every page of a PDF.

    Creates a new temporary PDF with "— Página X / N —" overlaid at the
    bottom-center of each page. The original file is not modified.

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

    logger.info(
        "Adding page numbers to PDF",
        extra={"input_path": input_path}
    )

    reader = PdfReader(input_path)
    writer = PdfWriter()
    total_pages = len(reader.pages)

    logger.info(
        f"PDF has {total_pages} pages",
        extra={"total_pages": total_pages}
    )

    for i, page in enumerate(reader.pages):
        page_num = i + 1

        # Get page dimensions
        media_box = page.mediabox
        page_width = float(media_box.width)
        page_height = float(media_box.height)

        # Create overlay with page number
        overlay_buf = _create_page_number_overlay(page_width, page_height, page_num, total_pages)
        overlay_reader = PdfReader(overlay_buf)
        overlay_page = overlay_reader.pages[0]

        # Merge overlay onto the original page
        page.merge_page(overlay_page)
        writer.add_page(page)

    # Write to temp file
    fd, output_path = tempfile.mkstemp(suffix="_numbered.pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            writer.write(f)
    except Exception:
        # Clean up on failure
        try:
            os.close(fd)
        except OSError:
            pass
        if os.path.isfile(output_path):
            os.unlink(output_path)
        raise

    output_size = os.path.getsize(output_path)
    logger.info(
        f"Numbered PDF created: {output_path} ({output_size} bytes)",
        extra={
            "output_path": output_path,
            "output_size_bytes": output_size,
            "total_pages": total_pages,
        }
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
