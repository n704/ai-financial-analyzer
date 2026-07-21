"""P2.2: PDF upload validation — magic bytes, size limit, page-count limit."""

from __future__ import annotations

import pymupdf
import pytest

from app.domain.validation import NotAPdf, PdfTooLarge, PdfTooManyPages, validate_pdf


def _make_pdf(pages: int) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def test_valid_pdf_returns_page_count() -> None:
    data = _make_pdf(3)
    page_count = validate_pdf(data, max_size_bytes=10_000_000, max_pages=600)
    assert page_count == 3


def test_missing_magic_bytes_rejected() -> None:
    with pytest.raises(NotAPdf, match="magic bytes"):
        validate_pdf(b"not a pdf at all", max_size_bytes=10_000_000, max_pages=600)


def test_garbage_with_pdf_prefix_rejected() -> None:
    garbage = b"%PDF-1.4\nthis is not real pdf structure"
    with pytest.raises(NotAPdf, match="could not be parsed"):
        validate_pdf(garbage, max_size_bytes=10_000_000, max_pages=600)


def test_oversized_file_rejected() -> None:
    data = _make_pdf(1)
    with pytest.raises(PdfTooLarge) as exc_info:
        validate_pdf(data, max_size_bytes=10, max_pages=600)
    assert exc_info.value.max_bytes == 10


def test_too_many_pages_rejected() -> None:
    data = _make_pdf(5)
    with pytest.raises(PdfTooManyPages) as exc_info:
        validate_pdf(data, max_size_bytes=10_000_000, max_pages=3)
    assert exc_info.value.page_count == 5
    assert exc_info.value.max_pages == 3


def test_size_checked_before_parsing() -> None:
    """Size is the cheaper check — an oversized garbage blob should fail on
    size, not on a parse error, so the caller gets the more specific reason."""
    with pytest.raises(PdfTooLarge):
        validate_pdf(b"%PDF-" + b"x" * 100, max_size_bytes=10, max_pages=600)
