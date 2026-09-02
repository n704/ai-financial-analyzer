"""Forecast eval (P6.9, SPEC.md §5 "Correctness & evaluation").

Scores the configured provider against seasonal-naive, drift, and last-value on
fixture series with known continuations, through the *same* pipeline the
service uses (``compute_forecast``). Two kinds of assertion:

1. **Metric correctness** — the scorecard agrees with what the fixture shape
   dictates (the right baseline wins; a perfect method scores zero; coverage is
   a probability; a model identical to a baseline ties it and is therefore
   reported as "no better than naive").
2. **Relative-skill regression** — the provider's skill score per fixture is
   compared against ``expected.json``. The bar is "measures and reports skill
   correctly", **not** "beats the baseline": on random-walk-like series the
   configured model usually will not, and the eval requires that to be said.

Runs in CI on ``naive`` (hermetic); ``FORECAST_EVAL_PROVIDER=timesfm`` (with
the ``forecast`` extra) scores the real model on demand. Regenerate the
expectations with ``FORECAST_EVAL_WRITE=1`` after a *deliberate* change.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path

import pytest
from tests.evals.forecast.fixtures import FIXTURES, Fixture, as_price_series

from app.config import Settings
from app.domain.forecast import SKILL_NO_BETTER
from app.providers.base import ForecastProvider
from app.providers.forecast.fake import FakeForecastProvider
from app.providers.forecast.naive import NaiveForecastProvider
from app.services.forecasting import compute_forecast

_EXPECTED = Path(__file__).with_name("expected.json")
_PROVIDER_NAME = os.environ.get("FORECAST_EVAL_PROVIDER", "naive")
_WRITE = os.environ.get("FORECAST_EVAL_WRITE") == "1"
_SERIES_LENGTH = 400
_HORIZON = 10
_WINDOWS = 8
# Skill may not drop by more than this versus the recorded expectation.
_REGRESSION_TOLERANCE = 0.02


def _settings(transform: str) -> Settings:
    return Settings.model_validate(
        {
            "llm": {"provider": "fake", "model": "fake-llm"},
            "embeddings": {"provider": "fake", "model": "fake-embedding"},
            "vector_store": {"provider": "chroma", "path": "./data/x"},
            "database": {"url": "sqlite:///:memory:"},
            "forecast": {
                "enabled": True,
                "provider": _PROVIDER_NAME,
                "max_context": 256,
                "max_horizon": 64,
                "transform": transform,
                "backtest_windows": _WINDOWS,
            },
            "limits": {"max_forecast_horizon": 60},
        }
    )


def _provider() -> ForecastProvider:
    if _PROVIDER_NAME == "naive":
        return NaiveForecastProvider(method="drift")
    if _PROVIDER_NAME == "fake":
        return FakeForecastProvider(max_context=256, max_horizon=64)
    if _PROVIDER_NAME == "timesfm":
        if importlib.util.find_spec("timesfm") is None:
            pytest.skip("FORECAST_EVAL_PROVIDER=timesfm needs the forecast extra")
        from app.providers.forecast.timesfm import TimesFMForecastProvider

        return TimesFMForecastProvider(
            model="google/timesfm-2.5-200m-pytorch",
            revision="main",
            max_context=256,
            max_horizon=64,
        )
    raise ValueError(f"unknown FORECAST_EVAL_PROVIDER {_PROVIDER_NAME!r}")


@pytest.fixture(scope="module")
def provider() -> ForecastProvider:
    return _provider()


def _load_expected() -> dict[str, dict[str, float | None]]:
    if not _EXPECTED.exists():
        return {}
    data: dict[str, dict[str, float | None]] = json.loads(_EXPECTED.read_text())
    return data


def _run(provider: ForecastProvider, fixture: Fixture, transform: str):  # type: ignore[no-untyped-def]
    series = as_price_series(fixture.name, fixture.generate(_SERIES_LENGTH))
    return compute_forecast(
        series=series, provider=provider, settings=_settings(transform), horizon=_HORIZON
    )


@pytest.mark.parametrize("fixture", FIXTURES, ids=[f.name for f in FIXTURES])
def test_scorecard_is_correct_for_the_fixture_shape(
    provider: ForecastProvider, fixture: Fixture
) -> None:
    artifact = _run(provider, fixture, "level")
    report = artifact.backtest
    by_name = {b.method: b for b in report.baselines}

    assert report.windows == _WINDOWS and report.horizon == _HORIZON
    best = min(by_name.values(), key=lambda s: s.mae)
    assert best.method == fixture.expected_best_baseline, {k: v.mae for k, v in by_name.items()}
    if fixture.name in ("trend", "seasonal"):
        assert by_name[fixture.expected_best_baseline].mae == pytest.approx(0.0, abs=1e-6)

    for score in (report.model, *report.baselines):
        assert math.isfinite(score.mae) and score.mae >= 0
        assert 0.0 <= score.smape <= 200.0
        assert score.mase is None or score.mase >= 0.0
        assert score.coverage_80 is None or 0.0 <= score.coverage_80 <= 1.0
        assert score.pinball is None or score.pinball >= 0.0

    # The band is never missing, whatever the provider.
    assert len(artifact.quantiles) == 9
    for k in range(_HORIZON):
        column = [path[k] for path in artifact.quantiles]
        assert column == sorted(column)


def test_a_model_identical_to_a_baseline_is_reported_as_no_better(
    provider: ForecastProvider,
) -> None:
    """The self-consistency check behind the honesty requirement: naive:drift in
    level space *is* the drift baseline, so it must tie it exactly and be
    labelled "no better than naive" — the verdict is measured, not assumed."""
    if not (provider.provider == "naive" and provider.model == "naive:drift"):
        pytest.skip("only meaningful for the drift provider")
    artifact = _run(provider, FIXTURES[3], "level")
    drift = next(b for b in artifact.backtest.baselines if b.method == "drift")
    assert artifact.backtest.model.mae == pytest.approx(drift.mae)
    assert artifact.skill.verdict == SKILL_NO_BETTER


@pytest.mark.parametrize("fixture", FIXTURES, ids=[f.name for f in FIXTURES])
def test_relative_skill_has_not_regressed(provider: ForecastProvider, fixture: Fixture) -> None:
    artifact = _run(provider, fixture, "log")
    score = artifact.skill.score
    expected = _load_expected()
    key = provider.model
    if _WRITE:
        expected.setdefault(key, {})[fixture.name] = score
        _EXPECTED.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
        pytest.skip("expectations written")
    recorded = expected.get(key, {}).get(fixture.name, "missing")
    if recorded == "missing":
        pytest.skip(
            f"no recorded expectation for {key}/{fixture.name}; run with FORECAST_EVAL_WRITE=1"
        )
    if recorded is None:
        assert score is None
        return
    assert score is not None
    assert score >= float(recorded) - _REGRESSION_TOLERANCE, (
        f"relative skill on {fixture.name} regressed: {score:.4f} < {float(recorded):.4f}"
    )
