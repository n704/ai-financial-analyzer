"""Fixture price series with known continuations for the forecast eval (P6.9).

Each fixture is a deterministic generator (seeded) so the eval is hermetic in
CI. They cover the shapes that separate the baselines: a clean trend (drift is
perfect), a weekly seasonal pattern (seasonal-naive is perfect), a pure random
walk (nothing beats last-value in expectation), and a noisy trend (skill is
real but small). ``known_continuation`` documents *why* each shape has the
expected winner — the eval asserts the measured scorecard agrees.
"""

from __future__ import annotations

import datetime as dt
import math
import random
from collections.abc import Callable
from dataclasses import dataclass

from app.providers.base import Bar, PriceSeries


@dataclass(frozen=True, slots=True)
class Fixture:
    name: str
    generate: Callable[[int], list[float]]
    expected_best_baseline: str
    """The naive method that should win (lowest MAE) on this shape."""


def _trend(n: int) -> list[float]:
    # Linear, so the (level-space) drift baseline reproduces it exactly.
    return [100.0 + 0.2 * t for t in range(n)]


def _seasonal(n: int) -> list[float]:
    pattern = [1.00, 1.02, 0.99, 1.03, 0.98]
    return [100.0 * pattern[t % 5] for t in range(n)]


def _random_walk(n: int) -> list[float]:
    rng = random.Random(2026)
    levels = [100.0]
    for _ in range(n - 1):
        levels.append(levels[-1] * math.exp(rng.gauss(0.0, 0.01)))
    return levels


def _noisy_trend(n: int) -> list[float]:
    rng = random.Random(7)
    return [100.0 * math.exp(0.003 * t) * (1.0 + rng.gauss(0.0, 0.004)) for t in range(n)]


FIXTURES: tuple[Fixture, ...] = (
    Fixture("trend", _trend, "drift"),
    Fixture("seasonal", _seasonal, "seasonal_naive"),
    Fixture("random_walk", _random_walk, "last_value"),
    Fixture("noisy_trend", _noisy_trend, "drift"),
)


def as_price_series(name: str, levels: list[float]) -> PriceSeries:
    """Wrap a level series in the provider-boundary type the service consumes,
    on consecutive weekdays ending 2026-06-30."""
    end = dt.date(2026, 6, 30)
    dates: list[dt.date] = []
    day = end
    while len(dates) < len(levels):
        if day.weekday() < 5:
            dates.append(day)
        day -= dt.timedelta(days=1)
    dates.reverse()
    bars = tuple(
        Bar(date=d, open=v, high=v * 1.01, low=v * 0.99, close=v, volume=1e6)
        for d, v in zip(dates, levels, strict=True)
    )
    return PriceSeries(ticker=name.upper()[:10], interval="1d", source="eval", as_of=end, bars=bars)
