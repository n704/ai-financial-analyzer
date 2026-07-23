"""Chunking pipeline (P2.3): per-page text (PyMuPDF) + table extraction
(pdfplumber, serialized as Markdown) -> section-heading detection with
page-group fallback -> ~800/100-token windows.

Pure over PDF bytes in, :class:`Chunk` objects out. No ``document_id``/
``user_id``/embedding is attached here — the ingestion service (P2.6)
assembles those into the provider-layer ``ChunkRecord`` for the vector store.
Both PyMuPDF and pdfplumber are parsing libraries, not vendor SDKs, so this
module stays consistent with ``domain/`` being I/O-free (everything happens
in-memory over the bytes already read from storage).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pdfplumber
import pymupdf

# --------------------------------------------------------------------------- #
# Token approximation
# --------------------------------------------------------------------------- #
# No tokenizer dependency is pulled in for chunk-sizing: a whitespace word
# count is a standard, cheap proxy for token count (real tokenizers run
# somewhat higher per word). Precision here only affects chunk *size*, never
# correctness of the text itself — a real tokenizer can replace `str.split()`
# later without changing this module's shape.

# Page-group fallback size, in pages, used for any run of pages where no
# section heading has been detected yet (front matter) or for a whole
# document that never matches a known heading (non-standard report layout).
_FALLBACK_GROUP_PAGES = 5


# --------------------------------------------------------------------------- #
# Section-heading detection
# --------------------------------------------------------------------------- #
_DASHES = "-–—"  # noqa: RUF001 - intentional: real filings use en/em dashes after "Item 1A"

_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "Risk Factors",
        re.compile(rf"^\s*(item\s+1a\.?\s*[{_DASHES}.]?\s*)?risk\s+factors\s*$", re.IGNORECASE),
    ),
    (
        "MD&A",
        re.compile(
            rf"^\s*(item\s+7\.?\s*[{_DASHES}.]?\s*)?management.?s\s+discussion\s+and\s+analysis"
            r"(\s+of\s+financial\s+condition\s+and\s+results\s+of\s+operations)?\s*$",
            re.IGNORECASE,
        ),
    ),
    (
        "Financial Statements",
        re.compile(
            rf"^\s*(item\s+8\.?\s*[{_DASHES}.]?\s*)?financial\s+statements"
            r"(\s+and\s+supplementary\s+data)?\s*$",
            re.IGNORECASE,
        ),
    ),
    (
        "Notes to Financial Statements",
        re.compile(
            r"^\s*notes\s+to\s+(the\s+)?(consolidated\s+)?financial\s+statements\s*$",
            re.IGNORECASE,
        ),
    ),
]

_MAX_HEADING_LINE_LEN = 120  # a heading is a short standalone line, never a paragraph
_HEADING_SCAN_LINES = 5  # only look at the first few lines of a page


def _detect_heading(page_text: str) -> tuple[str, str] | None:
    """Return ``(canonical_section_name, matched_line)`` if one of the first
    few non-blank lines of the page matches a known heading pattern, else
    ``None``. The matched line is returned alongside the name so the caller
    can strip exactly that line from the page's body content — the heading
    is already captured in ``Chunk.section``; leaving it in would pad every
    section's first chunk with a few duplicate tokens.

    Only short, standalone lines are checked — matching mid-paragraph text
    would produce false positives (e.g. a sentence that happens to mention
    "risk factors" in passing).
    """
    lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
    for line in lines[:_HEADING_SCAN_LINES]:
        if len(line) > _MAX_HEADING_LINE_LEN:
            continue
        for name, pattern in _SECTION_PATTERNS:
            if pattern.match(line):
                return name, line
    return None


# --------------------------------------------------------------------------- #
# Per-page text + table extraction
# --------------------------------------------------------------------------- #
def _table_to_markdown(table: list[list[str | None]]) -> str:
    """Render one pdfplumber-extracted table (rows of cell strings) as a
    GitHub-flavored Markdown table. The first row is treated as the header;
    ragged rows (pdfplumber can emit these for merged cells) are padded or
    truncated to the header width.
    """
    if not table:
        return ""
    rows = [[(cell or "").strip() for cell in row] for row in table]
    header, *body = rows
    if not any(header):
        return ""
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in body:
        cells = (row + [""] * len(header))[: len(header)]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _extract_page_texts(data: bytes) -> list[str]:
    """Per-page plain text (PyMuPDF), each page's text augmented with any
    tables on that page rendered as Markdown (pdfplumber) — so table numbers
    survive retrieval even where PyMuPDF's plain-text extraction garbles a
    ruled table's reading order.
    """
    doc = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
    try:
        # `Document` supports `__getitem__`/`__len__` (legacy sequence
        # iteration) but not `__iter__` per its stubs, so index explicitly
        # rather than `for page in doc`.
        raw_texts: list[str] = [
            doc[i].get_text()  # type: ignore[no-untyped-call]
            for i in range(doc.page_count)
        ]
    finally:
        doc.close()  # type: ignore[no-untyped-call]

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        table_blocks: list[list[str]] = [
            [md for table in page.extract_tables() if (md := _table_to_markdown(table))]
            for page in pdf.pages
        ]

    combined: list[str] = []
    for raw, tables in zip(raw_texts, table_blocks, strict=True):
        parts = [raw, *tables]
        combined.append("\n\n".join(p for p in parts if p.strip()))
    return combined


# --------------------------------------------------------------------------- #
# Section grouping (heading detection + page-group fallback)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class _PageWords:
    page: int  # 1-indexed
    words: list[str]


def _words_excluding_heading(page_text: str, detection: tuple[str, str] | None) -> list[str]:
    """The page's body words, with the detected heading's own line (if any)
    removed first — see :func:`_detect_heading` for why."""
    if detection is None:
        return page_text.split()
    _, heading_line = detection
    body = "\n".join(ln for ln in page_text.splitlines() if ln.strip() != heading_line)
    return body.split()


def _group_pages_by_section(page_texts: list[str]) -> list[tuple[str | None, list[_PageWords]]]:
    """Assign each page to a section by carrying the last detected heading
    forward (headings normally appear once, at the start of a section, not
    on every following page). Any run of pages before the first heading —
    or the whole document, if no heading is ever detected — falls back to
    fixed-size page groups (``section=None``) instead of one unstructured
    blob, which is the "page-group fallback" non-standard reports need.
    """
    detections = [_detect_heading(text) for text in page_texts]
    labels: list[str | None] = []
    current: str | None = None
    for detection in detections:
        if detection is not None:
            current = detection[0]
        labels.append(current)

    def page_words(p: int) -> list[str]:
        return _words_excluding_heading(page_texts[p], detections[p])

    groups: list[tuple[str | None, list[_PageWords]]] = []
    n = len(page_texts)
    i = 0
    while i < n:
        label = labels[i]
        if label is None:
            j = i
            while j < n and labels[j] is None:
                j += 1
            page = i
            while page < j:
                group_end = min(page + _FALLBACK_GROUP_PAGES, j)
                pages = [
                    _PageWords(page=p + 1, words=page_words(p)) for p in range(page, group_end)
                ]
                groups.append((None, pages))
                page = group_end
            i = j
        else:
            j = i
            while j < n and labels[j] == label:
                j += 1
            pages = [_PageWords(page=p + 1, words=page_words(p)) for p in range(i, j)]
            groups.append((label, pages))
            i = j
    return groups


# --------------------------------------------------------------------------- #
# Token windowing
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Chunk:
    text: str
    section: str | None
    page_start: int
    page_end: int
    token_count: int
    chunk_index: int


def _window_group(
    pages: list[_PageWords],
    *,
    section: str | None,
    target_tokens: int,
    overlap_tokens: int,
    start_index: int,
) -> tuple[list[Chunk], int]:
    """Split one section's pages into ~target_tokens windows with
    ~overlap_tokens overlap, tracking a word->page map so each chunk's
    ``page_start``/``page_end`` reflects exactly which pages its words came
    from (not the whole group's range) — citations depend on this being
    accurate, not just approximately right.
    """
    flat_words: list[str] = []
    word_pages: list[int] = []
    for pw in pages:
        for word in pw.words:
            flat_words.append(word)
            word_pages.append(pw.page)

    if not flat_words:
        return [], start_index

    step = max(target_tokens - overlap_tokens, 1)
    chunks: list[Chunk] = []
    index = start_index
    start = 0
    total = len(flat_words)
    while start < total:
        end = min(start + target_tokens, total)
        chunks.append(
            Chunk(
                text=" ".join(flat_words[start:end]),
                section=section,
                page_start=word_pages[start],
                page_end=word_pages[end - 1],
                token_count=end - start,
                chunk_index=index,
            )
        )
        index += 1
        if end == total:
            break
        start += step
    return chunks, index


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def chunk_pdf(data: bytes, *, target_tokens: int = 800, overlap_tokens: int = 100) -> list[Chunk]:
    """Run the full P2.3 pipeline over raw PDF bytes and return ordered chunks.

    ``target_tokens``/``overlap_tokens`` default to SPEC.md's ~800/~100
    window (``ChunkingConfig``'s defaults); callers normally pass the
    configured values through explicitly.
    """
    page_texts = _extract_page_texts(data)
    groups = _group_pages_by_section(page_texts)

    chunks: list[Chunk] = []
    index = 0
    for section, pages in groups:
        group_chunks, index = _window_group(
            pages,
            section=section,
            target_tokens=target_tokens,
            overlap_tokens=overlap_tokens,
            start_index=index,
        )
        chunks.extend(group_chunks)
    return chunks
