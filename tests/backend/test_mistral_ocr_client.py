from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.mistral_ocr_client import (
    MISTRAL_OCR_ENGINE,
    _build_mistral_ocr_result,
    _to_mistral_page_indexes,
    get_or_prime_mistral_pdf_ocr_cache,
)
from backend.pdf_ocr_cache import PdfOcrParsedPage, build_pdf_ocr_payload, write_pdf_ocr_cache


def test_to_mistral_page_indexes_converts_1_based_pages_to_0_based_request():
    assert _to_mistral_page_indexes((1, 3, 7)) == [0, 2, 6]


def test_build_mistral_ocr_result_maps_response_indexes_back_to_original_pages():
    response = {
        "pages": [
            {"index": 0, "markdown": "Página 1", "tables": [], "images": []},
            {"index": 3, "markdown": "Página 4", "tables": [], "images": []},
        ]
    }

    result = _build_mistral_ocr_result(
        response_payload=response,
        expected_page_numbers=(1, 4, 5),
    )

    assert tuple(page.page_number for page in result.page_index) == (1, 4)
    assert result.detected_pages == (1, 4)
    assert result.missing_pages == (5,)


def test_get_or_prime_mistral_pdf_ocr_cache_requests_only_missing_pages(tmp_path, monkeypatch):
    source_path = tmp_path / "document-numbered.pdf"
    source_path.write_bytes(b"%PDF-1.4\n%fake\n")

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    from backend.mistral_ocr_client import _sha256_file, _pdf_cache_path

    source_sha256 = _sha256_file(str(source_path))
    cache_path = _pdf_cache_path(source_sha256, MISTRAL_OCR_ENGINE, cache_dir)
    write_pdf_ocr_cache(
        cache_path=cache_path,
        source_sha256=source_sha256,
        engine=MISTRAL_OCR_ENGINE,
        document_page_count=8,
        page_index=(
            PdfOcrParsedPage(page_number=1, markdown="Página 1"),
            PdfOcrParsedPage(page_number=4, markdown="Página 4"),
        ),
    )

    captured: dict = {}

    def _fake_fetch_missing_pages_once(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            page_index=(PdfOcrParsedPage(page_number=5, markdown="Página 5"),),
            detected_pages=(5,),
            missing_pages=(),
            raw_response={"pages": [{"index": 4, "markdown": "Página 5"}]},
        )

    monkeypatch.setattr(
        "backend.mistral_ocr_client._fetch_missing_pages_once",
        _fake_fetch_missing_pages_once,
    )
    monkeypatch.setattr(
        "backend.mistral_ocr_client.PdfReader",
        lambda path: SimpleNamespace(pages=[object()] * 8),
    )

    entry = get_or_prime_mistral_pdf_ocr_cache(
        source_path=str(source_path),
        api_key="mistral-test-key",
        model="mistral-ocr-latest",
        engine=MISTRAL_OCR_ENGINE,
        filename="document.pdf",
        cache_dir=str(cache_dir),
        expected_page_numbers=(1, 4, 5),
    )

    assert captured["expected_page_numbers"] == (5,)
    assert entry.cached_page_numbers == (1, 4, 5)


def test_fetch_missing_pages_once_deletes_remote_file_even_on_ocr_failure(tmp_path, monkeypatch):
    source_path = tmp_path / "document-numbered.pdf"
    source_path.write_bytes(b"%PDF-1.4\n%fake\n")

    calls: list[tuple[str, str]] = []

    class _FakeFiles:
        def upload(self, file, purpose):
            calls.append(("upload", purpose))
            return SimpleNamespace(id="file-123")

        def get_signed_url(self, file_id):
            calls.append(("signed_url", file_id))
            return SimpleNamespace(url="https://signed.example/document.pdf")

        def delete(self, file_id):
            calls.append(("delete", file_id))

    class _FakeOcr:
        def process(self, **kwargs):
            raise RuntimeError("boom")

    class _FakeClient:
        def __init__(self, api_key, **_kwargs):
            self.files = _FakeFiles()
            self.ocr = _FakeOcr()

    monkeypatch.setattr("backend.mistral_ocr_client.Mistral", _FakeClient)

    from backend.mistral_ocr_client import _fetch_missing_pages_once, PdfOcrError

    with pytest.raises(PdfOcrError, match="boom"):
        _fetch_missing_pages_once(
            source_path=str(source_path),
            api_key="mistral-test-key",
            model="mistral-ocr-latest",
            expected_page_numbers=(2, 4),
            filename="document.pdf",
        )

    assert ("delete", "file-123") in calls
