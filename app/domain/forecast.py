"""Forecast math (P6.3): the pure, I/O-free numeric core of F6 (SPEC.md §3.6).

Everything numeric about a forecast happens here and nowhere else — the
transforms and their inverses, the naive baselines, the rolling-origin
backtest, the MASE/sMAPE/pinball/coverage metrics, the skill verdict, and the
empirical bands used when a provider has no quantile head. The forecasting
model itself is reached only through the :data:`BatchForecaster` callable the
service hands in, so this module imports no provider, and the LLM never sees
any of this except as a finished, read-only table to narrate (the same rule as
comparison deltas: the model never does arithmetic).

Honesty rules this module *enforces*, not merely documents (SPEC.md §3.6,
"Honesty requirements"):

- :func:`forecast_with_backtest` is the only way to produce a forecast, and it
  cannot return a point path without also returning a 10-90% band and a
  backtest scorecard. There is no function here that returns the line alone.
- The skill verdict compares the model's error against the *best* naive
  baseline on the very same origins. "no better than naive" is an ordinary,
  expected outcome on equity closes — a passing result, not an error.
- Too little history for the requested backtest raises
  :class:`InsufficientHistory` rather than silently shrinking the backtest.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #
Transform = Literal["level", "log", "log_return"]
TRANSFORMS: tuple[Transform, ...] = ("level", "log", "log_return")

SkillVerdict = Literal["better than naive", "no better than naive"]
SKILL_BETTER: SkillVerdict = "better than naive"
SKILL_NO_BETTER: SkillVerdict = "no better than naive"

BandSource = Literal["provider", "empirical"]

# A relative-MAE improvement below this is treated as noise, not skill: with a
# handful of backtest origins, a 1-2% edge over drift is well inside sampling
# error, and calling that "better than naive" would be the over-claim this
# feature exists to avoid. Conservative by design — the failure mode to guard
# against is an authoritative-looking curve, not an under-sold one.
DEFAULT_SKILL_TOLERANCE = 0.05

# A backtest MAE at or below this is a perfect forecast for all practical
# purposes (prices are quoted to cents; this is a float-noise floor). Comparing
# against a "perfect" baseline would otherwise divide by ~1e-14 and report a
# skill of minus trillions — numerically true, humanly meaningless.
PERFECT_MAE = 1e-9

# Fewer closes than this and a forecast is meaningless; it also bounds the
# earliest rolling origin so every backtest window has something to look at.
MIN_CONTEXT_POINTS = 16

# Season length (in bars) of the seasonal-naive baseline per bar interval:
# one trading week for daily bars, one year for weekly, one year for monthly.
_SEASON_BY_INTERVAL: dict[str, int] = {"1d": 5, "1wk": 52, "1mo": 12}
DEFAULT_SEASON_LENGTH = 5

DISCLAIMER_VERSION = 1
DISCLAIMER_TEXT = (
    "This forecast is a statistical measurement, not a prediction to be trusted "
    "and not investment advice. It is a distribution over possible price paths "
    "produced by a general-purpose time-series model with no knowledge of the "
    "company, shown together with its own measured error history on this series. "
    "Equity prices are close to a random walk; a model that does no better than "
    "a naive baseline is the normal case and is reported as such. No buy, sell, "
    "or hold recommendation is made or implied."
)

TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class ForecastMathError(ValueError):
    """Base for domain-level forecast failures — inputs that cannot be forecast
    honestly. The API maps each subclass to a specific 4xx."""


class InvalidTicker(ForecastMathError):
    def __init__(self, raw: str) -> None:
        super().__init__(
            f"{raw!r} is not a valid ticker symbol (expected {TICKER_PATTERN.pattern})"
        )
        self.raw = raw


class NonPositiveSeries(ForecastMathError):
    """A log-based transform was asked for on a series with a non-positive value."""


class InsufficientHistory(ForecastMathError):
    def __init__(self, available: int, required: int) -> None:
        super().__init__(
            f"series has {available} bars but the requested horizon and backtest "
            f"need at least {required}; shorten the horizon, reduce backtest windows, "
            f"or fetch more history"
        )
        self.available = available
        self.required = required


# --------------------------------------------------------------------------- #
# Ticker validation — before any symbol reaches a market-data client
# --------------------------------------------------------------------------- #
def normalize_ticker(raw: str) -> str:
    """Upper-case and validate a user- or document-supplied ticker
    (SPEC.md §3.6 step 1). Raises :class:`InvalidTicker` — the string never
    reaches a market-data adapter unless it matches the pattern."""
    ticker = raw.strip().upper()
    if not TICKER_PATTERN.fullmatch(ticker):
        raise InvalidTicker(raw)
    return ticker


def season_length_for_interval(interval: str) -> int:
    return _SEASON_BY_INTERVAL.get(interval, DEFAULT_SEASON_LENGTH)


# --------------------------------------------------------------------------- #
# Transforms and their inverses (round-trip tested)
# --------------------------------------------------------------------------- #
def _require_positive(values: Sequence[float]) -> None:
    for value in values:
        if not value > 0.0:
            raise NonPositiveSeries(
                f"log-based transforms need strictly positive values; got {value!r}"
            )


def transform_series(values: Sequence[float], transform: Transform) -> list[float]:
    """Map a level series into the space the model forecasts in.

    ``level`` is the identity; ``log`` takes natural logs (the default —
    price levels are non-stationary, log-prices forecast better and invert
    exactly); ``log_return`` differences the logs, yielding one fewer value.
    """
    if transform == "level":
        return list(values)
    _require_positive(values)
    logs = [math.log(v) for v in values]
    if transform == "log":
        return logs
    return [b - a for a, b in pairwise(logs)]


def inverse_transform_path(
    path: Sequence[float], transform: Transform, *, last_level: float
) -> list[float]:
    """Map a forecast path back to levels. ``last_level`` is the final level of
    the context the path continues from (only ``log_return`` needs it).

    For ``level`` and ``log`` the inverse is exact and, being monotone, maps a
    quantile of the transformed series to the same quantile of the level
    series. For ``log_return`` the inverse accumulates the path, so applying it
    to per-step return quantiles yields a band that assumes perfectly
    correlated steps — wider than the true quantile of the cumulative sum, i.e.
    conservative. That is one reason ``log`` is the default transform.
    """
    if transform == "level":
        return list(path)
    if transform == "log":
        return [math.exp(v) for v in path]
    out: list[float] = []
    acc = 0.0
    for r in path:
        acc += r
        out.append(last_level * math.exp(acc))
    return out


def prepare_context(values: Sequence[float], max_context: int) -> list[float]:
    """The trailing ``min(max_context, len(values))`` levels (SPEC.md §3.6 step 2)."""
    if max_context < 1:
        raise ValueError("max_context must be >= 1")
    return list(values[-max_context:])


# --------------------------------------------------------------------------- #
# Naive baselines — always available, scored on every forecast
# --------------------------------------------------------------------------- #
def last_value_forecast(context: Sequence[float], horizon: int) -> list[float]:
    """Repeat the last observed value (the random-walk forecast)."""
    _require_context(context, horizon)
    return [context[-1]] * horizon


def drift_forecast(context: Sequence[float], horizon: int) -> list[float]:
    """Extend the average historical change per step (random walk with drift).
    With a single-point context the drift is zero and this equals last-value."""
    _require_context(context, horizon)
    n = len(context)
    slope = (context[-1] - context[0]) / (n - 1) if n > 1 else 0.0
    return [context[-1] + slope * k for k in range(1, horizon + 1)]


def seasonal_naive_forecast(
    context: Sequence[float], horizon: int, season_length: int
) -> list[float]:
    """Repeat the value from one season earlier. With less than one season of
    context the season is clipped to the context length (degenerating toward
    last-value rather than failing)."""
    _require_context(context, horizon)
    if season_length < 1:
        raise ValueError("season_length must be >= 1")
    n = len(context)
    m = min(season_length, n)
    out: list[float] = []
    for k in range(1, horizon + 1):
        idx = n + k - 1 - m * math.ceil(k / m)
        out.append(context[idx])
    return out


def _require_context(context: Sequence[float], horizon: int) -> None:
    if not context:
        raise ValueError("context must not be empty")
    if horizon < 1:
        raise ValueError("horizon must be >= 1")


BaselineFn = Callable[[Sequence[float], int, int], list[float]]

BASELINES: dict[str, BaselineFn] = {
    "last_value": lambda ctx, h, _m: last_value_forecast(ctx, h),
    "drift": lambda ctx, h, _m: drift_forecast(ctx, h),
    "seasonal_naive": seasonal_naive_forecast,
}


# --------------------------------------------------------------------------- #
# Metrics — each matches its textbook definition and a hand-computed fixture
# --------------------------------------------------------------------------- #
def _check_same_length(actual: Sequence[float], predicted: Sequence[float]) -> None:
    if len(actual) != len(predicted):
        raise ValueError(f"actual ({len(actual)}) and predicted ({len(predicted)}) lengths differ")
    if not actual:
        raise ValueError("metrics need at least one point")


def mae(actual: Sequence[float], predicted: Sequence[float]) -> float:
    _check_same_length(actual, predicted)
    return sum(abs(a - p) for a, p in zip(actual, predicted, strict=True)) / len(actual)


def mase(
    actual: Sequence[float],
    predicted: Sequence[float],
    insample: Sequence[float],
    season_length: int,
) -> float | None:
    """Mean absolute scaled error: MAE divided by the in-sample one-step
    seasonal-naive MAE (Hyndman & Koehler). Below 1 means "better than the
    seasonal-naive forecaster would have been in-sample". ``None`` when the
    scale is undefined — too little in-sample data, or a perfectly flat
    series — rather than a fake number."""
    m = season_length
    if m < 1:
        raise ValueError("season_length must be >= 1")
    if len(insample) <= m:
        return None
    scale = sum(abs(insample[t] - insample[t - m]) for t in range(m, len(insample))) / (
        len(insample) - m
    )
    if scale == 0.0:
        return None
    return mae(actual, predicted) / scale


def smape(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """Symmetric MAPE in percent (0-200). A point where both values are zero
    contributes zero rather than a division by zero."""
    _check_same_length(actual, predicted)
    total = 0.0
    for a, p in zip(actual, predicted, strict=True):
        denom = abs(a) + abs(p)
        if denom > 0.0:
            total += 2.0 * abs(a - p) / denom
    return 100.0 * total / len(actual)


def pinball_loss(actual: Sequence[float], predicted: Sequence[float], q: float) -> float:
    """Quantile (pinball) loss for level ``q``: under-prediction is penalised by
    ``q``, over-prediction by ``1 - q``. Proper for the ``q``-quantile."""
    _check_same_length(actual, predicted)
    if not 0.0 < q < 1.0:
        raise ValueError("quantile level must lie strictly between 0 and 1")
    total = 0.0
    for a, p in zip(actual, predicted, strict=True):
        diff = a - p
        total += max(q * diff, (q - 1.0) * diff)
    return total / len(actual)


def mean_pinball(
    actual: Sequence[float],
    quantile_paths: Sequence[Sequence[float]],
    levels: Sequence[float],
) -> float:
    """Pinball loss averaged over all quantile levels — a single proper score
    for the whole predictive distribution."""
    if len(quantile_paths) != len(levels) or not levels:
        raise ValueError("one quantile path per level is required")
    return sum(
        pinball_loss(actual, path, q) for path, q in zip(quantile_paths, levels, strict=True)
    ) / len(levels)


def interval_coverage(
    actual: Sequence[float], lower: Sequence[float], upper: Sequence[float]
) -> float:
    """Fraction of actuals falling inside ``[lower, upper]``. For the 10-90%
    band the honest target is 0.8; well above it means the band is too wide,
    well below means it is too narrow."""
    _check_same_length(actual, lower)
    _check_same_length(actual, upper)
    inside = sum(1 for a, lo, hi in zip(actual, lower, upper, strict=True) if lo <= a <= hi)
    return inside / len(actual)


# --------------------------------------------------------------------------- #
# Empirical bands — for providers with no quantile head
# --------------------------------------------------------------------------- #
def empirical_quantile(values: Sequence[float], q: float) -> float:
    """Sample quantile with linear interpolation between order statistics."""
    if not values:
        raise ValueError("cannot take a quantile of no values")
    if not 0.0 <= q <= 1.0:
        raise ValueError("quantile level must lie in [0, 1]")
    xs = sorted(values)
    pos = q * (len(xs) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


ResidualKind = Literal["additive", "multiplicative"]


def residual_kind(transform: Transform) -> ResidualKind:
    """Residuals are measured in the space the model forecast in: additive in
    levels, multiplicative (log-ratio) for the log-based transforms, so an
    empirical band around a $500 stock is proportionally the same as around a
    $5 one."""
    return "additive" if transform == "level" else "multiplicative"


def residuals(
    actual: Sequence[float], predicted: Sequence[float], kind: ResidualKind
) -> list[float]:
    _check_same_length(actual, predicted)
    if kind == "additive":
        return [a - p for a, p in zip(actual, predicted, strict=True)]
    _require_positive(actual)
    _require_positive(predicted)
    return [math.log(a) - math.log(p) for a, p in zip(actual, predicted, strict=True)]


def fix_quantile_crossing(
    quantile_paths: Sequence[Sequence[float]],
) -> tuple[tuple[float, ...], ...]:
    """Sort the per-step values across levels so the 0.1 path never sits above
    the 0.9 path. Levels are assumed to be given in ascending order."""
    if not quantile_paths:
        return ()
    horizon = len(quantile_paths[0])
    if any(len(p) != horizon for p in quantile_paths):
        raise ValueError("quantile paths must share one horizon")
    columns = [sorted(path[k] for path in quantile_paths) for k in range(horizon)]
    return tuple(tuple(col[j] for col in columns) for j in range(len(quantile_paths)))


def empirical_quantile_paths(
    point: Sequence[float],
    residuals_by_step: Sequence[Sequence[float]],
    levels: Sequence[float],
    *,
    kind: ResidualKind,
) -> tuple[tuple[float, ...], ...]:
    """Bands from backtest residuals: at each horizon step, the requested
    quantiles of the residuals observed at that step across the backtest
    origins, applied to the point path. Coarse with few origins (the 0.1 and
    0.9 levels of eight residuals are nearly their min and max) — which is
    honest: a provider without a quantile head *has* only this much evidence
    about its own error."""
    if len(residuals_by_step) != len(point):
        raise ValueError("one residual sample per horizon step is required")
    paths: list[tuple[float, ...]] = []
    for q in levels:
        path: list[float] = []
        for k, value in enumerate(point):
            r = empirical_quantile(residuals_by_step[k], q)
            path.append(value + r if kind == "additive" else value * math.exp(r))
        paths.append(tuple(path))
    return fix_quantile_crossing(paths)


# --------------------------------------------------------------------------- #
# Structures crossing the service boundary
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class PathForecast:
    """One context's forecast in *transform space*, as returned by the
    :data:`BatchForecaster`. ``quantiles[j]`` is the path for
    ``quantile_levels[j]``; both are empty when the provider has no quantile
    head. Mirrors ``ForecastResult`` per series without importing it —
    ``domain`` imports nothing above it."""

    point: tuple[float, ...]
    quantile_levels: tuple[float, ...] = ()
    quantiles: tuple[tuple[float, ...], ...] = ()

    def __post_init__(self) -> None:
        if len(self.quantiles) != len(self.quantile_levels):
            raise ValueError("PathForecast needs one quantile path per level")
        if any(len(path) != len(self.point) for path in self.quantiles):
            raise ValueError("PathForecast quantile paths must match the point horizon")


BatchForecaster = Callable[[Sequence[Sequence[float]]], Sequence[PathForecast]]
"""Forecast a batch of transform-space contexts to a fixed horizon. The
service wraps ``ForecastProvider.forecast`` in this shape; tests pass plain
functions. Called exactly once per :func:`forecast_with_backtest` — the
backtest origins and the final context ride in one batch."""


@dataclass(frozen=True, slots=True)
class MethodScore:
    """Backtest metrics for one method, averaged over the rolling origins.
    ``pinball``/``coverage_80`` are ``None`` for methods without quantiles;
    ``mase`` is ``None`` when its scale is undefined (see :func:`mase`)."""

    method: str
    mae: float
    mase: float | None
    smape: float
    pinball: float | None = None
    coverage_80: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "mae": self.mae,
            "mase": self.mase,
            "smape": self.smape,
            "pinball": self.pinball,
            "coverage_80": self.coverage_80,
        }


@dataclass(frozen=True, slots=True)
class BacktestReport:
    """The scorecard persisted on every forecast: the provider's scores next to
    every naive baseline's, on the same origins."""

    horizon: int
    windows: int
    season_length: int
    origins: tuple[int, ...]
    model: MethodScore
    baselines: tuple[MethodScore, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "horizon": self.horizon,
            "windows": self.windows,
            "season_length": self.season_length,
            "origins": list(self.origins),
            "model": self.model.to_dict(),
            "baselines": [b.to_dict() for b in self.baselines],
        }


@dataclass(frozen=True, slots=True)
class SkillResult:
    verdict: SkillVerdict
    score: float | None
    reference: str
    """Relative-MAE skill against the best naive baseline: ``score = 1 -
    MAE_model / MAE_best_baseline`` (positive = better). ``None`` when the best
    baseline is perfect. ``reference`` names the baseline it was beaten by, or
    failed to beat."""


@dataclass(frozen=True, slots=True)
class ForecastArtifact:
    """Everything the honesty requirements demand, produced together: point
    path, quantile band (from the provider or empirical), the backtest
    scorecard, and the skill verdict. Values are levels (prices), inverse-
    transformed already."""

    point: tuple[float, ...]
    quantile_levels: tuple[float, ...]
    quantiles: tuple[tuple[float, ...], ...]
    band_source: BandSource
    backtest: BacktestReport
    skill: SkillResult
    context_length: int

    def quantile_path(self, level: float) -> tuple[float, ...]:
        for q, path in zip(self.quantile_levels, self.quantiles, strict=True):
            if abs(q - level) < 1e-9:
                return path
        raise KeyError(f"no quantile path for level {level}")


@dataclass(frozen=True, slots=True)
class BacktestSpec:
    """The knobs of one forecast run, all from config except ``horizon``."""

    horizon: int
    windows: int
    max_context: int
    transform: Transform
    quantile_levels: tuple[float, ...]
    season_length: int = DEFAULT_SEASON_LENGTH
    skill_tolerance: float = DEFAULT_SKILL_TOLERANCE

    def __post_init__(self) -> None:
        if self.horizon < 1:
            raise ValueError("horizon must be >= 1")
        if self.windows < 1:
            raise ValueError("windows must be >= 1")
        if self.max_context < 1:
            raise ValueError("max_context must be >= 1")
        if self.transform not in TRANSFORMS:
            raise ValueError(f"unknown transform {self.transform!r}")
        levels = self.quantile_levels
        if not levels or any(b <= a for a, b in pairwise(levels)):
            raise ValueError("quantile_levels must be non-empty and strictly increasing")
        for required in (0.1, 0.5, 0.9):
            if not any(abs(q - required) < 1e-9 for q in levels):
                raise ValueError(f"quantile_levels must include {required}")

    def required_history(self) -> int:
        return self.horizon * self.windows + MIN_CONTEXT_POINTS


# --------------------------------------------------------------------------- #
# Rolling-origin backtest + skill verdict + the one entry point
# --------------------------------------------------------------------------- #
def rolling_origins(n: int, *, horizon: int, windows: int) -> list[int]:
    """Forecast origins for ``windows`` non-overlapping evaluation windows of
    ``horizon`` steps, the last one ending at the series' end. Origin ``o``
    means: context is ``series[:o]``, actual is ``series[o:o + horizon]``."""
    origins = [n - horizon * (windows - i) for i in range(windows)]
    if origins[0] < MIN_CONTEXT_POINTS:
        raise InsufficientHistory(n, horizon * windows + MIN_CONTEXT_POINTS)
    return origins


def skill_verdict(
    model: MethodScore,
    baselines: Sequence[MethodScore],
    *,
    tolerance: float = DEFAULT_SKILL_TOLERANCE,
) -> SkillResult:
    """Compare the model against the *best* naive baseline on MAE (equivalent
    to comparing MASE, which shares the same scale on the same series).
    "better than naive" requires beating it by more than ``tolerance``."""
    if not baselines:
        raise ValueError("at least one baseline is required")
    best = min(baselines, key=lambda s: s.mae)
    if best.mae <= PERFECT_MAE:
        # A perfect naive forecast cannot be beaten, only tied; the ratio is undefined.
        return SkillResult(verdict=SKILL_NO_BETTER, score=None, reference=best.method)
    score = 1.0 - model.mae / best.mae
    verdict: SkillVerdict = SKILL_BETTER if score > tolerance else SKILL_NO_BETTER
    return SkillResult(verdict=verdict, score=score, reference=best.method)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _mean_or_none(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    if len(present) != len(values):
        return None
    return _mean(present)


def _aggregate(method: str, per_origin: Sequence[MethodScore]) -> MethodScore:
    return MethodScore(
        method=method,
        mae=_mean([s.mae for s in per_origin]),
        mase=_mean_or_none([s.mase for s in per_origin]),
        smape=_mean([s.smape for s in per_origin]),
        pinball=_mean_or_none([s.pinball for s in per_origin]),
        coverage_80=_mean_or_none([s.coverage_80 for s in per_origin]),
    )


def _score_point(
    method: str,
    actual: Sequence[float],
    predicted: Sequence[float],
    insample: Sequence[float],
    season_length: int,
) -> MethodScore:
    return MethodScore(
        method=method,
        mae=mae(actual, predicted),
        mase=mase(actual, predicted, insample, season_length),
        smape=smape(actual, predicted),
    )


def _score_with_band(
    base: MethodScore,
    actual: Sequence[float],
    quantile_paths: Sequence[Sequence[float]],
    levels: Sequence[float],
) -> MethodScore:
    lower = quantile_paths[_index_of(levels, 0.1)]
    upper = quantile_paths[_index_of(levels, 0.9)]
    return MethodScore(
        method=base.method,
        mae=base.mae,
        mase=base.mase,
        smape=base.smape,
        pinball=mean_pinball(actual, quantile_paths, levels),
        coverage_80=interval_coverage(actual, lower, upper),
    )


def _index_of(levels: Sequence[float], level: float) -> int:
    for i, q in enumerate(levels):
        if abs(q - level) < 1e-9:
            return i
    raise ValueError(f"quantile level {level} not present in {list(levels)}")


def _invert(
    forecast: PathForecast,
    *,
    transform: Transform,
    last_level: float,
    expected_levels: Sequence[float],
    use_quantiles: bool,
) -> tuple[list[float], tuple[tuple[float, ...], ...] | None]:
    point = inverse_transform_path(forecast.point, transform, last_level=last_level)
    if not use_quantiles or not forecast.quantiles:
        return point, None
    if tuple(forecast.quantile_levels) != tuple(expected_levels):
        raise ForecastMathError(
            f"forecaster returned quantile levels {list(forecast.quantile_levels)} "
            f"but {list(expected_levels)} were requested"
        )
    paths = [
        tuple(inverse_transform_path(path, transform, last_level=last_level))
        for path in forecast.quantiles
    ]
    return point, fix_quantile_crossing(paths)


def forecast_with_backtest(
    levels: Sequence[float],
    *,
    spec: BacktestSpec,
    forecaster: BatchForecaster,
    supports_quantiles: bool,
) -> ForecastArtifact:
    """The one entry point (SPEC.md §3.6 steps 2-4): backtest, forecast, band,
    verdict — produced together, or not at all.

    1. Rolling origins are laid out over the trailing ``horizon x windows``
       bars; the model is asked for every origin's context *and* the final
       context in a single batch (one provider call).
    2. Each origin's forecast is inverse-transformed and scored against the
       held-out actuals, alongside every naive baseline on the same context.
    3. The final forecast's band comes from the provider's quantile paths when
       it has a quantile head, otherwise from the backtest residuals — either
       way, a 10-90% band is present.
    4. The skill verdict compares the model's backtest MAE to the best
       baseline's.

    Raises :class:`InsufficientHistory` when the series can't support the
    requested backtest, and :class:`NonPositiveSeries` for a log transform
    over a non-positive series.
    """
    n = len(levels)
    if n < spec.required_history():
        raise InsufficientHistory(n, spec.required_history())
    if spec.transform != "level":
        _require_positive(levels)

    origins = rolling_origins(n, horizon=spec.horizon, windows=spec.windows)
    level_contexts = [prepare_context(levels[:o], spec.max_context) for o in origins]
    level_contexts.append(prepare_context(levels, spec.max_context))
    model_inputs = [transform_series(ctx, spec.transform) for ctx in level_contexts]

    results = forecaster(model_inputs)
    if len(results) != len(model_inputs):
        raise ForecastMathError(
            f"forecaster returned {len(results)} paths for {len(model_inputs)} contexts"
        )
    if any(len(r.point) != spec.horizon for r in results):
        raise ForecastMathError(f"forecaster returned paths of the wrong horizon ({spec.horizon})")

    kind = residual_kind(spec.transform)
    model_scores: list[MethodScore] = []
    baseline_scores: dict[str, list[MethodScore]] = {name: [] for name in BASELINES}
    residuals_by_step: list[list[float]] = [[] for _ in range(spec.horizon)]

    for i, origin in enumerate(origins):
        actual = list(levels[origin : origin + spec.horizon])
        context = level_contexts[i]
        insample = levels[:origin]
        point, bands = _invert(
            results[i],
            transform=spec.transform,
            last_level=context[-1],
            expected_levels=spec.quantile_levels,
            use_quantiles=supports_quantiles,
        )
        score = _score_point("model", actual, point, insample, spec.season_length)
        if bands is not None:
            score = _score_with_band(score, actual, bands, spec.quantile_levels)
        model_scores.append(score)
        for k, r in enumerate(residuals(actual, point, kind)):
            residuals_by_step[k].append(r)
        for name, fn in BASELINES.items():
            predicted = fn(context, spec.horizon, spec.season_length)
            baseline_scores[name].append(
                _score_point(name, actual, predicted, insample, spec.season_length)
            )

    model_score = _aggregate("model", model_scores)
    baselines = tuple(_aggregate(name, scores) for name, scores in baseline_scores.items())
    report = BacktestReport(
        horizon=spec.horizon,
        windows=spec.windows,
        season_length=spec.season_length,
        origins=tuple(origins),
        model=model_score,
        baselines=baselines,
    )

    final_context = level_contexts[-1]
    point, bands = _invert(
        results[-1],
        transform=spec.transform,
        last_level=final_context[-1],
        expected_levels=spec.quantile_levels,
        use_quantiles=supports_quantiles,
    )
    band_source: BandSource
    if bands is not None:
        band_source = "provider"
    else:
        band_source = "empirical"
        bands = empirical_quantile_paths(point, residuals_by_step, spec.quantile_levels, kind=kind)

    return ForecastArtifact(
        point=tuple(point),
        quantile_levels=tuple(spec.quantile_levels),
        quantiles=bands,
        band_source=band_source,
        backtest=report,
        skill=skill_verdict(model_score, baselines, tolerance=spec.skill_tolerance),
        context_length=len(final_context),
    )


# --------------------------------------------------------------------------- #
# Calendar + provenance helpers
# --------------------------------------------------------------------------- #
def future_trading_days(after: dt.date, count: int) -> list[dt.date]:
    """The next ``count`` weekdays after ``after``. Exchange holidays are not
    modelled: forecast steps are trading *bars*, and these dates are labels
    for them, accurate to within the handful of holidays a year."""
    if count < 0:
        raise ValueError("count must be >= 0")
    out: list[dt.date] = []
    day = after
    while len(out) < count:
        day += dt.timedelta(days=1)
        if day.weekday() < 5:
            out.append(day)
    return out


def compute_input_hash(
    *,
    ticker: str,
    interval: str,
    horizon: int,
    transform: str,
    provider: str,
    model: str,
    checkpoint_revision: str,
    source: str,
    as_of: dt.date,
    max_context: int,
    quantile_levels: Sequence[float],
    backtest_windows: int,
    season_length: int,
) -> str:
    """Stable identity of a forecast's inputs (SPEC.md §3.6 step 5): the same
    series, as of the same date, through the same model and settings, is the
    same artifact — so a repeat request returns it instead of re-running
    inference. A weights/config change is a different hash, never a silent
    re-attribution (ARCHITECTURE.md §5, "Forecast weights/config change")."""
    payload: dict[str, object] = {
        "ticker": ticker,
        "interval": interval,
        "horizon": horizon,
        "transform": transform,
        "provider": provider,
        "model": model,
        "checkpoint_revision": checkpoint_revision,
        "source": source,
        "as_of": as_of.isoformat(),
        "max_context": max_context,
        "quantile_levels": [float(q) for q in quantile_levels],
        "backtest_windows": backtest_windows,
        "season_length": season_length,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "BASELINES",
    "DEFAULT_SEASON_LENGTH",
    "DEFAULT_SKILL_TOLERANCE",
    "DISCLAIMER_TEXT",
    "DISCLAIMER_VERSION",
    "MIN_CONTEXT_POINTS",
    "PERFECT_MAE",
    "SKILL_BETTER",
    "SKILL_NO_BETTER",
    "TICKER_PATTERN",
    "TRANSFORMS",
    "BacktestReport",
    "BacktestSpec",
    "BandSource",
    "BatchForecaster",
    "ForecastArtifact",
    "ForecastMathError",
    "InsufficientHistory",
    "InvalidTicker",
    "MethodScore",
    "NonPositiveSeries",
    "PathForecast",
    "ResidualKind",
    "SkillResult",
    "SkillVerdict",
    "Transform",
    "compute_input_hash",
    "drift_forecast",
    "empirical_quantile",
    "empirical_quantile_paths",
    "fix_quantile_crossing",
    "forecast_with_backtest",
    "future_trading_days",
    "interval_coverage",
    "inverse_transform_path",
    "last_value_forecast",
    "mae",
    "mase",
    "mean_pinball",
    "normalize_ticker",
    "pinball_loss",
    "prepare_context",
    "residual_kind",
    "residuals",
    "rolling_origins",
    "season_length_for_interval",
    "seasonal_naive_forecast",
    "skill_verdict",
    "smape",
    "transform_series",
]
