"""Upload validation (P2.2): pure functions over raw bytes — PDF magic-byte
check, size limit, and page-count limit. Opens the PDF in-memory only (no
filesystem/network I/O), consistent with ``domain/`` being I/O-free; PyMuPDF
is a parsing library, not a vendor SDK, so it's fine here (same reasoning as
``domain/chunking.py``, P2.3).
"""

from __future__ import annotations

import pymupdf

_PDF_MAGIC = b"%PDF-"


class InvalidPdfError(Exception):
    """Base class for upload validation failures — the API maps each subclass
    to a specific, clear 4xx response."""


class NotAPdf(InvalidPdfError):
    """Missing PDF magic bytes, or the parser couldn't open it at all."""


class PdfTooLarge(InvalidPdfError):
    def __init__(self, size_bytes: int, max_bytes: int) -> None:
        super().__init__(f"file is {size_bytes} bytes, exceeds the {max_bytes}-byte limit")
        self.size_bytes = size_bytes
        self.max_bytes = max_bytes


class PdfTooManyPages(InvalidPdfError):
    def __init__(self, page_count: int, max_pages: int) -> None:
        super().__init__(f"PDF has {page_count} pages, exceeds the {max_pages}-page limit")
        self.page_count = page_count
        self.max_pages = max_pages


def validate_pdf(data: bytes, *, max_size_bytes: int, max_pages: int) -> int:
    """Validate ``data`` as an acceptable upload; return its page count.

    Checks run cheapest-first so a bad upload fails with a specific, clear
    reason rather than a generic parse error: magic bytes -> size -> actually
    parseable -> page count.
    """
    if not data.startswith(_PDF_MAGIC):
        raise NotAPdf("file does not start with the PDF magic bytes (%PDF-)")
    if len(data) > max_size_bytes:
        raise PdfTooLarge(len(data), max_size_bytes)

    # pymupdf's stubs leave `Document` itself untyped despite shipping
    # py.typed, so its constructor/methods read as untyped calls under mypy
    # strict; the explicit `int` annotation below is what keeps that
    # untyped-ness from leaking into this function's own (checked) return type.
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
    except Exception as exc:
        raise NotAPdf(f"file could not be parsed as a PDF: {exc}") from exc
    try:
        page_count: int = doc.page_count
    finally:
        doc.close()  # type: ignore[no-untyped-call]

    if page_count > max_pages:
        raise PdfTooManyPages(page_count, max_pages)
    return page_count
