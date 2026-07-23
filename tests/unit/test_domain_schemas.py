"""P2.4: structured-extraction schemas — nullability, the source_page-required-
when-present rule, and validate/serialize round-tripping."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.schemas import (
    DocumentMetadata,
    FinancialMetrics,
    Guidance,
    MoneyValue,
    SegmentRevenue,
)


# --------------------------------------------------------------------------- #
# MoneyValue
# --------------------------------------------------------------------------- #
def test_money_value_defaults_to_fully_null() -> None:
    money = MoneyValue()
    assert money.value is None
    assert money.source_page is None


def test_money_value_with_value_requires_source_page() -> None:
    with pytest.raises(ValidationError, match="source_page is required"):
        MoneyValue(value=1000.0)


def test_money_value_with_value_and_page_is_valid() -> None:
    money = MoneyValue(value=1000.0, source_page=42)
    assert money.value == 1000.0
    assert money.source_page == 42


def test_money_value_source_page_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        MoneyValue(value=1.0, source_page=0)


def test_money_value_round_trips_through_json() -> None:
    money = MoneyValue(value=500.5, source_page=7)
    restored = MoneyValue.model_validate_json(money.model_dump_json())
    assert restored == money


# --------------------------------------------------------------------------- #
# Guidance
# --------------------------------------------------------------------------- #
def test_guidance_defaults_to_null() -> None:
    guidance = Guidance()
    assert guidance.text is None
    assert guidance.source_page is None


def test_guidance_with_text_requires_source_page() -> None:
    with pytest.raises(ValidationError, match="source_page is required"):
        Guidance(text="We expect revenue growth of 10-12% next quarter.")


def test_guidance_with_text_and_page_is_valid() -> None:
    guidance = Guidance(text="Verbatim guidance quote.", source_page=12)
    assert guidance.text == "Verbatim guidance quote."
    assert guidance.source_page == 12


# --------------------------------------------------------------------------- #
# SegmentRevenue
# --------------------------------------------------------------------------- #
def test_segment_revenue_requires_a_name() -> None:
    with pytest.raises(ValidationError):
        SegmentRevenue(name="")


def test_segment_revenue_defaults_revenue_to_null() -> None:
    segment = SegmentRevenue(name="Cloud")
    assert segment.revenue.value is None


def test_segment_revenue_with_value() -> None:
    segment = SegmentRevenue(name="Cloud", revenue=MoneyValue(value=100.0, source_page=5))
    assert segment.revenue.value == 100.0
    assert segment.revenue.source_page == 5


# --------------------------------------------------------------------------- #
# FinancialMetrics
# --------------------------------------------------------------------------- #
def test_financial_metrics_constructs_fully_null_by_default() -> None:
    metrics = FinancialMetrics()
    assert metrics.fiscal_period is None
    assert metrics.revenue.value is None
    assert metrics.net_income.value is None
    assert metrics.diluted_eps.value is None
    assert metrics.segment_revenues == []
    assert metrics.guidance.text is None
    assert metrics.prior_period is None


def test_financial_metrics_every_money_field_enforces_source_page() -> None:
    money_fields = [
        "revenue",
        "cost_of_revenue",
        "gross_income",
        "operating_income",
        "net_income",
        "diluted_eps",
        "operating_cash_flow",
        "free_cash_flow",
        "total_debt",
        "cash_and_equivalents",
    ]
    for field in money_fields:
        with pytest.raises(ValidationError, match="source_page is required"):
            FinancialMetrics(**{field: {"value": 1.0}})


def test_financial_metrics_full_round_trip() -> None:
    metrics = FinancialMetrics(
        fiscal_period="FY2025",
        revenue=MoneyValue(value=1_000_000.0, source_page=10),
        net_income=MoneyValue(value=200_000.0, source_page=12),
        diluted_eps=MoneyValue(value=1.23, source_page=13),
        segment_revenues=[
            SegmentRevenue(name="Cloud", revenue=MoneyValue(value=600_000.0, source_page=11)),
            SegmentRevenue(name="Devices", revenue=MoneyValue(value=400_000.0, source_page=11)),
        ],
        guidance=Guidance(text="We expect continued growth.", source_page=20),
        prior_period=FinancialMetrics(
            fiscal_period="FY2024",
            revenue=MoneyValue(value=900_000.0, source_page=45),
        ),
    )

    restored = FinancialMetrics.model_validate_json(metrics.model_dump_json())

    assert restored == metrics
    assert restored.prior_period is not None
    assert restored.prior_period.fiscal_period == "FY2024"
    assert restored.prior_period.revenue.value == 900_000.0
    assert restored.prior_period.prior_period is None
    assert len(restored.segment_revenues) == 2


def test_financial_metrics_json_schema_generation_does_not_crash() -> None:
    # Exercised because this is exactly what a `generate_structured` adapter
    # hands the provider (e.g. Gemini's `response_schema`); the recursive
    # `prior_period` self-reference resolves to a `$defs`/`$ref` pair rather
    # than an inline schema — still valid JSON Schema, just not flattened.
    schema = FinancialMetrics.model_json_schema()
    assert "$ref" in schema
    assert "properties" in schema["$defs"]["FinancialMetrics"]


# --------------------------------------------------------------------------- #
# DocumentMetadata
# --------------------------------------------------------------------------- #
def test_document_metadata_defaults() -> None:
    meta = DocumentMetadata()
    assert meta.company is None
    assert meta.ticker is None
    assert meta.report_type == "other"
    assert meta.fiscal_period is None
    assert meta.currency is None
    assert meta.fiscal_year_end is None


def test_document_metadata_full() -> None:
    meta = DocumentMetadata(
        company="Acme Corp",
        ticker="ACME",
        report_type="10-K",
        fiscal_period="FY2025",
        currency="USD",
        fiscal_year_end="12-31",
    )
    restored = DocumentMetadata.model_validate_json(meta.model_dump_json())
    assert restored == meta


def test_document_metadata_rejects_unknown_report_type() -> None:
    with pytest.raises(ValidationError):
        DocumentMetadata(report_type="8-K")  # not one of the allowed literals
