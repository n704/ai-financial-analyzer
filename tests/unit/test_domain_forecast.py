"""P6.3: the pure forecast math — transforms round-trip, every metric matches a
hand-computed fixture, baselines behave on flat/trending/noisy series, the
rolling-origin backtest + skill verdict, empirical bands, and the one entry
point never yields a line without its band and scorecard."""

from __future__ import annotations

import datetime as dt
import math
import random
from collections.abc import Sequence

import pytest

from app.domain.forecast import (
    MIN_CONTEXT_POINTS,
    SKILL_BETTER,
    SKILL_NO_BETTER,
    BacktestSpec,
    InsufficientHistory,
    InvalidTicker,
    MethodScore,
    NonPositiveSeries,
    PathForecast,
    compute_input_hash,
    drift_forecast,
    empirical_quantile,
    empirical_quantile_paths,
    fix_quantile_crossing,
    forecast_with_backtest,
    future_trading_days,
    interval_coverage,
    inverse_transform_path,
    last_value_forecast,
    mae,
    mase,
    mean_pinball,
    normalize_ticker,
    pinball_loss,
    prepare_context,
    residuals,
    rolling_origins,
    season_length_for_interval,
    seasonal_naive_forecast,
    skill_verdict,
    smape,
    transform_series,
)

LEVELS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


def _spec(**overrides: object) -> BacktestSpec:
    base: dict[str, object] = {
        "horizon": 5,
        "windows": 3,
        "max_context": 64,
        "transform": "level",
        "quantile_levels": LEVELS,
    }
    base.update(overrides)
    return BacktestSpec(**base)  # type: ignore[arg-type]


def _last_value_forecaster(contexts: Sequence[Sequence[float]]) -> list[PathForecast]:
    return [PathForecast(point=tuple([c[-1]] * 5)) for c in contexts]


# --------------------------------------------------------------------------- #
# Ticker + calendar + provenance helpers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [(" brk.b ", "BRK.B"), ("aapl", "AAPL"), ("A-B", "A-B")])
def test_normalize_ticker_accepts_valid(raw: str, expected: str) -> None:
    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize("raw", ["", "123", "toolongticker", "a b", "AAPL;DROP", ".X"])
def test_normalize_ticker_rejects_invalid(raw: str) -> None:
    with pytest.raises(InvalidTicker):
        normalize_ticker(raw)


def test_future_trading_days_skips_weekends() -> None:
    friday = dt.date(2026, 9, 4)
    assert future_trading_days(friday, 3) == [
        dt.date(2026, 9, 7),
        dt.date(2026, 9, 8),
        dt.date(2026, 9, 9),
    ]
    assert future_trading_days(friday, 0) == []


def test_season_length_by_interval() -> None:
    assert season_length_for_interval("1d") == 5
    assert season_length_for_interval("1wk") == 52
    assert season_length_for_interval("unknown") == 5


def test_input_hash_is_stable_and_sensitive() -> None:
    kwargs: dict[str, object] = {
        "ticker": "ACME",
        "interval": "1d",
        "horizon": 10,
        "transform": "log",
        "provider": "naive",
        "model": "naive:drift",
        "checkpoint_revision": "n/a",
        "source": "fixture",
        "as_of": dt.date(2026, 9, 2),
        "max_context": 512,
        "quantile_levels": LEVELS,
        "backtest_windows": 8,
        "season_length": 5,
    }
    a = compute_input_hash(**kwargs)  # type: ignore[arg-type]
    b = compute_input_hash(**kwargs)  # type: ignore[arg-type]
    assert a == b and len(a) == 64
    changed = dict(kwargs, checkpoint_revision="v2")
    assert compute_input_hash(**changed) != a  # type: ignore[arg-type]
    changed = dict(kwargs, as_of=dt.date(2026, 9, 3))
    assert compute_input_hash(**changed) != a  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Transforms
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("transform", ["level", "log"])
def test_level_and_log_round_trip(transform: str) -> None:
    x = [100.0, 101.5, 99.25, 102.0, 250.0]
    y = transform_series(x, transform)  # type: ignore[arg-type]
    back = inverse_transform_path(y, transform, last_level=x[0])  # type: ignore[arg-type]
    assert back == pytest.approx(x, rel=1e-12)


def test_log_return_round_trip_from_first_level() -> None:
    x = [100.0, 101.5, 99.25, 102.0]
    r = transform_series(x, "log_return")
    assert len(r) == len(x) - 1
    assert inverse_transform_path(r, "log_return", last_level=x[0]) == pytest.approx(x[1:])


def test_log_transform_rejects_non_positive() -> None:
    with pytest.raises(NonPositiveSeries):
        transform_series([1.0, 0.0, 2.0], "log")


def test_prepare_context_takes_trailing_window() -> None:
    assert prepare_context([1.0, 2.0, 3.0, 4.0], 2) == [3.0, 4.0]
    assert prepare_context([1.0, 2.0], 10) == [1.0, 2.0]


# --------------------------------------------------------------------------- #
# Baselines
# --------------------------------------------------------------------------- #
def test_baselines_on_small_fixtures() -> None:
    assert last_value_forecast([1.0, 2.0, 3.0], 2) == [3.0, 3.0]
    assert drift_forecast([1.0, 2.0, 3.0], 2) == [4.0, 5.0]
    assert drift_forecast([5.0], 3) == [5.0, 5.0, 5.0]
    assert seasonal_naive_forecast([1, 2, 3, 4, 5, 6, 7], 3, 5) == [3, 4, 5]
    # Less than a season of context: the season clips to the context length.
    assert seasonal_naive_forecast([1.0, 2.0], 3, 5) == [1.0, 2.0, 1.0]


def test_baselines_reject_bad_inputs() -> None:
    with pytest.raises(ValueError):
        last_value_forecast([], 2)
    with pytest.raises(ValueError):
        drift_forecast([1.0], 0)


# --------------------------------------------------------------------------- #
# Metrics — each against a hand-computed value
# --------------------------------------------------------------------------- #
def test_mae_and_smape() -> None:
    assert mae([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 0.0
    assert mae([10.0, 20.0], [12.0, 18.0]) == 2.0
    # 2*2/22 and 2*2/38, averaged, in percent.
    assert smape([10.0, 20.0], [12.0, 18.0]) == pytest.approx(100 * (4 / 22 + 4 / 38) / 2)
    assert smape([0.0], [0.0]) == 0.0


def test_mase_scales_by_insample_seasonal_naive_error() -> None:
    insample = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert mase([6.0, 7.0], [6.0, 8.0], insample, 1) == pytest.approx(0.5)
    assert mase([6.0, 7.0], [6.0, 8.0], insample, 2) == pytest.approx(0.25)
    assert mase([6.0], [6.0], [3.0, 3.0, 3.0], 1) is None  # flat: no scale
    assert mase([6.0], [6.0], [3.0], 1) is None  # too short


def test_pinball_loss_is_asymmetric() -> None:
    assert pinball_loss([10.0], [8.0], 0.9) == pytest.approx(1.8)
    assert pinball_loss([10.0], [12.0], 0.9) == pytest.approx(0.2)
    with pytest.raises(ValueError):
        pinball_loss([1.0], [1.0], 1.0)


def test_mean_pinball_and_coverage() -> None:
    actual = [10.0]
    paths = [[8.0], [10.0], [12.0]]
    levels = [0.1, 0.5, 0.9]
    expected = (pinball_loss(actual, [8.0], 0.1) + 0.0 + pinball_loss(actual, [12.0], 0.9)) / 3
    assert mean_pinball(actual, paths, levels) == pytest.approx(expected)
    assert interval_coverage([1.0, 2.0, 3.0, 4.0], [0, 2, 4, 0], [2, 2, 5, 3]) == 0.5


def test_empirical_quantile_interpolates() -> None:
    xs = [4.0, 1.0, 3.0, 2.0]
    assert empirical_quantile(xs, 0.0) == 1.0
    assert empirical_quantile(xs, 1.0) == 4.0
    assert empirical_quantile(xs, 0.5) == 2.5
    assert empirical_quantile(xs, 0.25) == 1.75


def test_fix_quantile_crossing_sorts_per_step() -> None:
    fixed = fix_quantile_crossing([[3.0, 1.0], [1.0, 2.0], [2.0, 3.0]])
    assert fixed == ((1.0, 1.0), (2.0, 2.0), (3.0, 3.0))


def test_residuals_additive_and_multiplicative() -> None:
    assert residuals([10.0, 12.0], [8.0, 12.0], "additive") == [2.0, 0.0]
    assert residuals([10.0], [8.0], "multiplicative") == pytest.approx([math.log(10 / 8)])


def test_empirical_bands_wrap_the_point_path() -> None:
    point = [100.0, 100.0]
    by_step = [[-1.0, 0.0, 1.0], [-2.0, 0.0, 2.0]]
    bands = empirical_quantile_paths(point, by_step, [0.1, 0.5, 0.9], kind="additive")
    assert bands[1] == (100.0, 100.0)  # median residual is 0
    assert bands[0][1] < bands[1][1] < bands[2][1]
    assert bands[2][1] - bands[0][1] > bands[2][0] - bands[0][0]  # wider further out
    mult = empirical_quantile_paths(point, by_step, [0.1, 0.5, 0.9], kind="multiplicative")
    assert mult[0][0] == pytest.approx(100.0 * math.exp(-0.8))


# --------------------------------------------------------------------------- #
# Rolling origins + skill verdict
# --------------------------------------------------------------------------- #
def test_rolling_origins_layout() -> None:
    assert rolling_origins(100, horizon=10, windows=3) == [70, 80, 90]
    with pytest.raises(InsufficientHistory):
        rolling_origins(40, horizon=10, windows=3)  # first origin < MIN_CONTEXT_POINTS


def _score(method: str, error: float) -> MethodScore:
    return MethodScore(method=method, mae=error, mase=None, smape=0.0)


def test_skill_verdict_against_best_baseline() -> None:
    better = skill_verdict(_score("model", 0.5), [_score("a", 1.0), _score("b", 0.8)])
    assert better.verdict == SKILL_BETTER
    assert better.reference == "b"
    assert better.score == pytest.approx(1 - 0.5 / 0.8)

    noise = skill_verdict(_score("model", 0.79), [_score("a", 1.0), _score("b", 0.8)])
    assert noise.verdict == SKILL_NO_BETTER  # 1.25% edge is inside the tolerance

    perfect_naive = skill_verdict(_score("model", 0.0), [_score("a", 0.0)])
    assert perfect_naive.verdict == SKILL_NO_BETTER
    assert perfect_naive.score is None
    # Float-noise "perfect" baselines are perfect too — no minus-trillions skill.
    noise_floor = skill_verdict(_score("model", 1e-3), [_score("a", 1e-14)])
    assert noise_floor.verdict == SKILL_NO_BETTER and noise_floor.score is None


# --------------------------------------------------------------------------- #
# The one entry point
# --------------------------------------------------------------------------- #
def test_required_history_and_insufficient_history() -> None:
    spec = _spec(horizon=5, windows=3)
    assert spec.required_history() == 5 * 3 + MIN_CONTEXT_POINTS
    with pytest.raises(InsufficientHistory):
        forecast_with_backtest(
            [100.0] * (spec.required_history() - 1),
            spec=spec,
            forecaster=_last_value_forecaster,
            supports_quantiles=False,
        )


def test_flat_series_scores_zero_error_everywhere() -> None:
    levels = [100.0] * 60
    artifact = forecast_with_backtest(
        levels, spec=_spec(), forecaster=_last_value_forecaster, supports_quantiles=False
    )
    assert artifact.backtest.model.mae == 0.0
    assert all(b.mae == 0.0 for b in artifact.backtest.baselines)
    assert artifact.backtest.model.mase is None  # flat in-sample: no scale
    assert artifact.skill.verdict == SKILL_NO_BETTER  # tie with a perfect naive
    assert artifact.band_source == "empirical"
    assert all(path == artifact.point for path in artifact.quantiles)


def test_trending_series_drift_baseline_is_perfect() -> None:
    levels = [100.0 + 2.0 * t for t in range(60)]
    artifact = forecast_with_backtest(
        levels, spec=_spec(), forecaster=_last_value_forecaster, supports_quantiles=False
    )
    by_name = {b.method: b for b in artifact.backtest.baselines}
    assert by_name["drift"].mae == pytest.approx(0.0)
    assert by_name["last_value"].mae > 0.0
    assert artifact.backtest.model.mae == pytest.approx(by_name["last_value"].mae)
    assert artifact.skill.verdict == SKILL_NO_BETTER
    assert artifact.skill.reference == "drift"


def test_oracle_forecaster_beats_naive_and_batches_once() -> None:
    rng = random.Random(3)
    levels = [100.0]
    for _ in range(79):
        levels.append(max(1.0, levels[-1] + rng.gauss(0.0, 3.0)))
    spec = _spec(horizon=5, windows=3, max_context=1000)
    calls: list[int] = []

    def oracle(contexts: Sequence[Sequence[float]]) -> list[PathForecast]:
        calls.append(len(contexts))
        out: list[PathForecast] = []
        for ctx in contexts:
            origin = len(ctx)  # max_context > n, so the context is levels[:origin]
            future = levels[origin : origin + spec.horizon]
            if len(future) < spec.horizon:  # the final context: no future to peek at
                future = [ctx[-1]] * spec.horizon
            out.append(PathForecast(point=tuple(future)))
        return out

    artifact = forecast_with_backtest(
        levels, spec=spec, forecaster=oracle, supports_quantiles=False
    )
    assert calls == [spec.windows + 1]  # every origin + the final context in one batch
    assert artifact.backtest.model.mae == 0.0
    assert artifact.skill.verdict == SKILL_BETTER
    assert artifact.skill.score == 1.0
    assert artifact.backtest.origins == (65, 70, 75)


def test_provider_quantiles_become_the_band_and_are_scored() -> None:
    levels = [100.0 + math.sin(t / 3.0) * 5.0 for t in range(60)]

    def with_band(contexts: Sequence[Sequence[float]]) -> list[PathForecast]:
        out: list[PathForecast] = []
        for ctx in contexts:
            point = tuple([ctx[-1]] * 5)
            paths = tuple(tuple(p + (q - 0.5) * 40.0 for p in point) for q in LEVELS)
            out.append(PathForecast(point=point, quantile_levels=LEVELS, quantiles=paths))
        return out

    artifact = forecast_with_backtest(
        levels, spec=_spec(), forecaster=with_band, supports_quantiles=True
    )
    assert artifact.band_source == "provider"
    assert artifact.backtest.model.coverage_80 == 1.0  # +-16 band around a +-5 wiggle
    assert artifact.backtest.model.pinball is not None
    assert all(b.coverage_80 is None for b in artifact.backtest.baselines)
    assert artifact.quantile_path(0.5) == artifact.point
    for k in range(5):
        column = [path[k] for path in artifact.quantiles]
        assert column == sorted(column)


def test_quantiles_ignored_when_provider_flag_is_false() -> None:
    levels = [100.0 + t for t in range(60)]

    def with_band(contexts: Sequence[Sequence[float]]) -> list[PathForecast]:
        return [
            PathForecast(
                point=tuple([c[-1]] * 5),
                quantile_levels=LEVELS,
                quantiles=tuple(tuple([c[-1]] * 5) for _ in LEVELS),
            )
            for c in contexts
        ]

    artifact = forecast_with_backtest(
        levels, spec=_spec(), forecaster=with_band, supports_quantiles=False
    )
    assert artifact.band_source == "empirical"
    assert artifact.backtest.model.coverage_80 is None


def test_log_transform_inverts_to_levels() -> None:
    levels = [100.0 * math.exp(0.01 * t) for t in range(60)]
    spec = _spec(transform="log")

    def log_last_value(contexts: Sequence[Sequence[float]]) -> list[PathForecast]:
        return [PathForecast(point=tuple([c[-1]] * 5)) for c in contexts]

    artifact = forecast_with_backtest(
        levels, spec=spec, forecaster=log_last_value, supports_quantiles=False
    )
    assert artifact.point == pytest.approx(tuple([levels[-1]] * 5))
    assert all(v > 0 for path in artifact.quantiles for v in path)


def test_forecaster_shape_mismatch_is_an_error() -> None:
    levels = [100.0] * 60

    def wrong_horizon(contexts: Sequence[Sequence[float]]) -> list[PathForecast]:
        return [PathForecast(point=(1.0, 2.0)) for _ in contexts]

    with pytest.raises(ValueError, match="horizon"):
        forecast_with_backtest(
            levels, spec=_spec(), forecaster=wrong_horizon, supports_quantiles=False
        )


def test_spec_requires_mandatory_levels() -> None:
    with pytest.raises(ValueError, match=r"0\.5"):
        _spec(quantile_levels=(0.1, 0.9))
    with pytest.raises(ValueError, match="increasing"):
        _spec(quantile_levels=(0.9, 0.5, 0.1))
