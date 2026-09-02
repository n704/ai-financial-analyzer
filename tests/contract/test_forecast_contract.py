"""P6.4/P6.5 contract suite: every ``ForecastProvider`` adapter satisfies the
same tests. ``naive`` and ``fake`` always run; ``timesfm`` runs only when the
``forecast`` extra is installed *and* ``FORECAST_CONTRACT_TIMESFM=1`` (it
downloads a 200M checkpoint). Adding an adapter = one factory entry below."""

from __future__ import annotations

import importlib.util
import math
import os
from collections.abc import Callable

import pytest

from app.providers.base import ForecastProvider, ForecastResult, ForecastUnavailable
from app.providers.forecast.fake import FakeForecastProvider
from app.providers.forecast.naive import NaiveForecastProvider

LEVELS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


def _timesfm_available() -> bool:
    return (
        importlib.util.find_spec("timesfm") is not None
        and os.environ.get("FORECAST_CONTRACT_TIMESFM") == "1"
    )


def _build_timesfm() -> ForecastProvider:
    from app.providers.forecast.timesfm import TimesFMForecastProvider

    return TimesFMForecastProvider(
        model="google/timesfm-2.5-200m-pytorch", revision="main", max_context=256, max_horizon=64
    )


FACTORIES: dict[str, Callable[[], ForecastProvider]] = {
    "naive-drift": lambda: NaiveForecastProvider(method="drift"),
    "naive-seasonal": lambda: NaiveForecastProvider(method="seasonal_naive", season_length=5),
    "fake": lambda: FakeForecastProvider(),
    "timesfm": _build_timesfm,
}

_PARAMS = [
    "naive-drift",
    "naive-seasonal",
    "fake",
    pytest.param(
        "timesfm",
        marks=pytest.mark.skipif(
            not _timesfm_available(),
            reason="needs the forecast extra and FORECAST_CONTRACT_TIMESFM=1",
        ),
    ),
]


@pytest.fixture(params=_PARAMS)
def provider(request: pytest.FixtureRequest) -> ForecastProvider:
    return FACTORIES[request.param]()


def _contexts() -> list[list[float]]:
    a = [math.log(100.0 + 0.5 * t + 3.0 * math.sin(t / 4.0)) for t in range(96)]
    b = [math.log(50.0 + 0.1 * t) for t in range(64)]
    return [a, b]


def test_satisfies_protocol_and_reports_capabilities(provider: ForecastProvider) -> None:
    assert isinstance(provider, ForecastProvider)
    assert provider.provider and provider.model and provider.checkpoint_revision
    assert provider.max_context >= 16
    assert provider.max_horizon >= 1
    assert isinstance(provider.supports_quantiles, bool)
    assert isinstance(provider.supports_covariates, bool)


def test_forecast_shapes_follow_the_request(provider: ForecastProvider) -> None:
    result = provider.forecast(_contexts(), 12, LEVELS)
    assert isinstance(result, ForecastResult)
    assert result.batch_size == 2
    assert result.horizon == 12
    assert all(math.isfinite(v) for path in result.point for v in path)
    if provider.supports_quantiles:
        assert result.quantiles is not None
        assert result.quantile_levels == LEVELS
        for per_series in result.quantiles:
            assert len(per_series) == len(LEVELS)
            for k in range(12):
                column = [path[k] for path in per_series]
                assert column == sorted(column), "quantile paths must not cross"
    else:
        assert result.quantiles is None


def test_forecast_is_deterministic(provider: ForecastProvider) -> None:
    first = provider.forecast(_contexts(), 8, LEVELS)
    second = provider.forecast(_contexts(), 8, LEVELS)
    assert first == second


def test_rejects_out_of_range_horizon_and_empty_batch(provider: ForecastProvider) -> None:
    with pytest.raises(ForecastUnavailable):
        provider.forecast(_contexts(), provider.max_horizon + 1, LEVELS)
    with pytest.raises(ForecastUnavailable):
        provider.forecast([], 4, LEVELS)


def test_single_short_context_still_forecasts(provider: ForecastProvider) -> None:
    result = provider.forecast([[1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7]], 3, LEVELS)
    assert result.batch_size == 1 and result.horizon == 3
