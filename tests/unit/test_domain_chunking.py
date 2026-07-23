"""P2.3: the chunking pipeline — section-heading detection with page-group
fallback, token windowing with overlap, accurate per-chunk page attribution,
and table extraction serialized as Markdown. Fixture PDFs are built
programmatically with PyMuPDF (real text + ruled-line tables) rather than
bundling binary files, so every test's expected output is fully deterministic.
"""

from __future__ import annotations

import pymupdf
import pytest

from app.domain.chunking import Chunk, _table_to_markdown, chunk_pdf


def _filler_lines(n_words: int, *, start: int = 0, words_per_line: int = 8) -> list[str]:
    words = [f"w{start + i}" for i in range(n_words)]
    return [" ".join(words[i : i + words_per_line]) for i in range(0, len(words), words_per_line)]


def _draw_table(page: pymupdf.Page, rows: list[list[str]], *, x0: float, y0: float) -> None:
    col_w, row_h = 100, 20
    n_cols = len(rows[0])
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            page.insert_text((x0 + c * col_w + 5, y0 + r * row_h + 15), text, fontsize=10)
    total_w, total_h = col_w * n_cols, row_h * len(rows)
    for r in range(len(rows) + 1):
        y = y0 + r * row_h
        page.draw_line((x0, y), (x0 + total_w, y))
    for c in range(n_cols + 1):
        x = x0 + c * col_w
        page.draw_line((x, y0), (x, y0 + total_h))


def _build_pdf(
    pages: list[dict[str, object]],
) -> bytes:
    """Each page spec: heading (str | None), lines (list[str]), table (rows | None)."""
    doc = pymupdf.open()
    for spec in pages:
        page = doc.new_page()
        y = 50.0
        heading = spec.get("heading")
        if heading:
            page.insert_text((50, y), str(heading), fontsize=12)
            y += 25
        for line in spec.get("lines", []):  # type: ignore[union-attr]
            page.insert_text((50, y), str(line), fontsize=10)
            y += 16
        table = spec.get("table")
        if table:
            _draw_table(page, table, x0=50, y0=y + 15)  # type: ignore[arg-type]
    data = doc.tobytes()
    doc.close()
    return data


def _words_of(chunk: Chunk) -> list[str]:
    return chunk.text.split()


# --------------------------------------------------------------------------- #
# Section-heading detection + carry-forward
# --------------------------------------------------------------------------- #
def test_heading_carries_forward_to_following_pages_without_a_new_heading() -> None:
    data = _build_pdf(
        [
            {"heading": "Risk Factors", "lines": _filler_lines(40, start=0)},
            {"heading": None, "lines": _filler_lines(40, start=40)},
            {
                "heading": "Management's Discussion and Analysis",
                "lines": _filler_lines(40, start=80),
            },
        ]
    )

    chunks = chunk_pdf(data, target_tokens=1000, overlap_tokens=0)

    assert len(chunks) == 2
    risk, mdna = chunks
    assert risk.section == "Risk Factors"
    assert risk.page_start == 1
    assert risk.page_end == 2
    assert mdna.section == "MD&A"
    assert mdna.page_start == 3
    assert mdna.page_end == 3


def test_fallback_page_grouping_when_no_headings_present() -> None:
    pages = [{"heading": None, "lines": _filler_lines(10, start=i * 10)} for i in range(12)]
    data = _build_pdf(pages)

    chunks = chunk_pdf(data, target_tokens=10_000, overlap_tokens=0)

    # _FALLBACK_GROUP_PAGES=5 -> groups of pages (1-5), (6-10), (11-12).
    assert [(c.page_start, c.page_end, c.section) for c in chunks] == [
        (1, 5, None),
        (6, 10, None),
        (11, 12, None),
    ]


def test_leading_pages_before_first_heading_fall_back_then_switch_to_section() -> None:
    data = _build_pdf(
        [
            {"heading": None, "lines": _filler_lines(10, start=0)},
            {"heading": None, "lines": _filler_lines(10, start=10)},
            {"heading": "Risk Factors", "lines": _filler_lines(10, start=20)},
        ]
    )

    chunks = chunk_pdf(data, target_tokens=10_000, overlap_tokens=0)

    assert [(c.page_start, c.page_end, c.section) for c in chunks] == [
        (1, 2, None),
        (3, 3, "Risk Factors"),
    ]


def test_heading_mid_paragraph_is_not_a_false_positive() -> None:
    """A sentence merely mentioning risk factors in passing must not be
    mistaken for the section heading — only a short standalone line matches."""
    data = _build_pdf(
        [
            {
                "heading": None,
                "lines": [
                    "This filing discusses our risk factors in the following",
                    "sections along with other important disclosures for investors",
                    *_filler_lines(20, start=0),
                ],
            }
        ]
    )

    chunks = chunk_pdf(data, target_tokens=10_000, overlap_tokens=0)

    assert len(chunks) == 1
    assert chunks[0].section is None


# --------------------------------------------------------------------------- #
# Token windowing + overlap
# --------------------------------------------------------------------------- #
def test_short_section_yields_a_single_chunk() -> None:
    data = _build_pdf([{"heading": "Risk Factors", "lines": _filler_lines(10)}])
    chunks = chunk_pdf(data, target_tokens=800, overlap_tokens=100)
    assert len(chunks) == 1
    assert chunks[0].token_count == 10


def test_windowing_splits_long_section_with_overlap() -> None:
    data = _build_pdf([{"heading": "Risk Factors", "lines": _filler_lines(50)}])

    chunks = chunk_pdf(data, target_tokens=20, overlap_tokens=5)

    assert len(chunks) == 3
    assert [c.token_count for c in chunks] == [20, 20, 20]
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    # step = target - overlap = 15: chunk0 = words[0:20], chunk1 = words[15:35],
    # chunk2 = words[30:50] -> the last 5 words of chunk N are the first 5 of
    # chunk N+1.
    assert _words_of(chunks[0])[-5:] == _words_of(chunks[1])[:5]
    assert _words_of(chunks[1])[-5:] == _words_of(chunks[2])[:5]
    assert _words_of(chunks[0])[0] == "w0"
    assert _words_of(chunks[2])[-1] == "w49"


def test_windowing_with_zero_overlap_produces_disjoint_chunks() -> None:
    data = _build_pdf([{"heading": "Risk Factors", "lines": _filler_lines(40)}])
    chunks = chunk_pdf(data, target_tokens=20, overlap_tokens=0)
    assert len(chunks) == 2
    assert _words_of(chunks[0]) == [f"w{i}" for i in range(20)]
    assert _words_of(chunks[1]) == [f"w{i}" for i in range(20, 40)]


def test_chunk_index_is_global_across_sections() -> None:
    data = _build_pdf(
        [
            {"heading": "Risk Factors", "lines": _filler_lines(50, start=0)},
            {
                "heading": "Management's Discussion and Analysis",
                "lines": _filler_lines(50, start=50),
            },
        ]
    )
    chunks = chunk_pdf(data, target_tokens=20, overlap_tokens=5)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    # Confirms the running index continues into the second section rather
    # than restarting at 0.
    section_changes = {c.section for c in chunks}
    assert len(section_changes) == 2


# --------------------------------------------------------------------------- #
# Accurate per-chunk page attribution across a multi-page window
# --------------------------------------------------------------------------- #
def test_page_attribution_tracks_words_across_page_boundaries() -> None:
    data = _build_pdf(
        [
            {"heading": "Risk Factors", "lines": _filler_lines(15, start=0)},
            {"heading": None, "lines": _filler_lines(15, start=15)},
            {"heading": None, "lines": _filler_lines(15, start=30)},
        ]
    )

    chunks = chunk_pdf(data, target_tokens=20, overlap_tokens=0)

    assert len(chunks) == 3
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 2)
    assert (chunks[1].page_start, chunks[1].page_end) == (2, 3)
    assert (chunks[2].page_start, chunks[2].page_end) == (3, 3)


# --------------------------------------------------------------------------- #
# Table extraction -> Markdown
# --------------------------------------------------------------------------- #
def test_table_to_markdown_renders_header_and_rows() -> None:
    table = [["Metric", "Value"], ["Revenue", "1000"], ["Net Income", "200"]]
    md = _table_to_markdown(table)
    lines = md.splitlines()
    assert lines[0] == "| Metric | Value |"
    assert lines[1] == "| --- | --- |"
    assert "| Revenue | 1000 |" in lines
    assert "| Net Income | 200 |" in lines


def test_table_to_markdown_pads_ragged_rows() -> None:
    table = [["A", "B", "C"], ["1", "2"]]  # short row, missing trailing cell
    md = _table_to_markdown(table)
    assert "| 1 | 2 |  |" in md


def test_table_to_markdown_empty_table_returns_empty_string() -> None:
    assert _table_to_markdown([]) == ""


def test_table_to_markdown_blank_header_returns_empty_string() -> None:
    assert _table_to_markdown([[None, None], ["1", "2"]]) == ""


def test_table_survives_as_markdown_inside_chunk_text() -> None:
    table = [["Metric", "Value"], ["Revenue", "1000"], ["Net Income", "200"]]
    data = _build_pdf(
        [{"heading": "Financial Statements", "lines": _filler_lines(5), "table": table}]
    )

    chunks = chunk_pdf(data, target_tokens=10_000, overlap_tokens=0)

    assert len(chunks) == 1
    text = chunks[0].text
    assert "Metric" in text and "Value" in text
    assert "Revenue" in text and "1000" in text
    assert "Net" in text and "Income" in text and "200" in text


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #
def test_blank_page_yields_no_chunks() -> None:
    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()

    assert chunk_pdf(data) == []


@pytest.mark.parametrize("target,overlap", [(800, 100), (400, 50)])
def test_default_and_configured_windows_do_not_crash_on_realistic_sizes(
    target: int, overlap: int
) -> None:
    # Spread the filler across several pages (a page only fits so many lines
    # before running off it) — realistic anyway, since a real 10-K section
    # spans many pages, not one.
    pages = [
        {"heading": "Risk Factors" if i == 0 else None, "lines": _filler_lines(300, start=i * 300)}
        for i in range(5)
    ]
    data = _build_pdf(pages)
    chunks = chunk_pdf(data, target_tokens=target, overlap_tokens=overlap)
    assert len(chunks) > 1
    assert all(c.token_count <= target for c in chunks)
    assert sum(c.token_count for c in chunks) >= 1500 - overlap * len(chunks)
