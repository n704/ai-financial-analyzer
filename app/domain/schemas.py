"""Structured-extraction schemas (P2.4): the shapes ``LLMProvider.
generate_structured()`` is asked to fill during ingestion — document metadata
detection (SPEC.md §3.2 stage 2) and financial metric extraction (§3.3).

The correctness rule these schemas exist to enforce: **the model must never
invent a number**. Every metric value is nullable, and whenever a value is
actually present it must carry a ``source_page`` — enforced by validators
here, not left to prompting alone, so a schema-violating response is rejected
before it ever reaches a user as a fabricated figure.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

ReportType = Literal["10-K", "10-Q", "annual", "earnings", "other"]


class MoneyValue(BaseModel):
    """A single nullable numeric figure (a dollar amount, a per-share
    number, …) tied to the page it was read from. ``value is None`` is how
    the model says "not found" — it must never guess; when it *is* found,
    ``source_page`` is mandatory, since an uncited number can't be trusted or
    checked.
    """

    value: float | None = None
    source_page: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _source_page_required_when_value_present(self) -> MoneyValue:
        if self.value is not None and self.source_page is None:
            raise ValueError("source_page is required whenever value is not null")
        return self


class SegmentRevenue(BaseModel):
    """One named business segment's revenue. Segments the model can't find
    are simply absent from ``FinancialMetrics.segment_revenues`` — there is
    no null-named placeholder entry."""

    name: str = Field(min_length=1)
    revenue: MoneyValue = Field(default_factory=MoneyValue)


class Guidance(BaseModel):
    """Verbatim forward-looking guidance, quoted from the filing rather than
    summarized — paraphrasing a number here would be the model inventing
    figures by another name."""

    text: str | None = None
    source_page: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _source_page_required_when_text_present(self) -> Guidance:
        if self.text is not None and self.source_page is None:
            raise ValueError("source_page is required whenever text is not null")
        return self


class FinancialMetrics(BaseModel):
    """One document's extracted financial metrics (SPEC.md §3.3).

    Every numeric field is a :class:`MoneyValue` container (always present,
    its inner ``value`` nullable) rather than an optional field, so callers
    never need a null-check on the field itself — only on ``.value``.
    ``prior_period`` nests the same shape for period-over-period comparatives
    (e.g. the prior year's figures quoted in this filing); it is ``None``
    when the filing offers no comparative period (a first-ever filing).
    """

    fiscal_period: str | None = None

    revenue: MoneyValue = Field(default_factory=MoneyValue)
    cost_of_revenue: MoneyValue = Field(default_factory=MoneyValue)
    gross_income: MoneyValue = Field(default_factory=MoneyValue)
    operating_income: MoneyValue = Field(default_factory=MoneyValue)
    net_income: MoneyValue = Field(default_factory=MoneyValue)
    diluted_eps: MoneyValue = Field(default_factory=MoneyValue)
    operating_cash_flow: MoneyValue = Field(default_factory=MoneyValue)
    free_cash_flow: MoneyValue = Field(default_factory=MoneyValue)
    total_debt: MoneyValue = Field(default_factory=MoneyValue)
    cash_and_equivalents: MoneyValue = Field(default_factory=MoneyValue)

    segment_revenues: list[SegmentRevenue] = Field(default_factory=list)
    guidance: Guidance = Field(default_factory=Guidance)

    prior_period: FinancialMetrics | None = None


class DocumentMetadata(BaseModel):
    """Auto-detected document metadata (SPEC.md §3.2 stage 2), presented to
    the user for confirmation/edit via ``PATCH /documents/{id}`` (P2.5).
    Every field but ``report_type`` is nullable — a report the model can't
    confidently place still parses, ready for the user to fill in by hand,
    rather than failing the whole detection call.
    """

    company: str | None = None
    ticker: str | None = None
    report_type: ReportType = "other"
    fiscal_period: str | None = None
    currency: str | None = None
    fiscal_year_end: str | None = None
