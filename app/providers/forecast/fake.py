"""Deterministic fake ``ForecastProvider`` (P6.4) — the quantile-head twin of
the naive provider, for tests and the no-model local mode.

Point path: drift. Quantile paths: the point path plus a Gaussian spread that
grows with the square root of the horizon step, scaled by the context's
step-to-step volatility — a plausible-looking fake quantile head, so the
provider-band path (``supports_quantiles=True``) is exercised end-to-end with
no torch. Fully deterministic given the inputs; ``fail_with`` injects a typed
provider error for the failure-path tests.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise
from statistics import NormalDist, pstdev

from app.domain.forecast import drift_forecast
from app.providers.base import ForecastResult, ForecastUnavailable, ProviderError

_NORMAL = NormalDist()


class FakeForecastProvider:
    def __init__(
        self,
        *,
        model: str = "fake-forecaster",
        max_context: int = 512,
        max_horizon: int = 512,
        fail_with: ProviderError | None = None,
    ) -> None:
        self._model = model
        self._max_context = max_context
        self._max_horizon = max_horizon
        self._fail_with = fail_with

    @property
    def provider(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return self._model

    @property
    def checkpoint_revision(self) -> str:
        return "fake-rev"

    @property
    def max_context(self) -> int:
        return self._max_context

    @property
    def max_horizon(self) -> int:
        return self._max_horizon

    @property
    def supports_quantiles(self) -> bool:
        return True

    @property
    def supports_covariates(self) -> bool:
        return False

    def forecast(
        self,
        contexts: Sequence[Sequence[float]],
        horizon: int,
        quantiles: Sequence[float],
    ) -> ForecastResult:
        if self._fail_with is not None:
            raise self._fail_with
        if not contexts:
            raise ForecastUnavailable("no contexts to forecast")
        if horizon < 1 or horizon > self._max_horizon:
            raise ForecastUnavailable(
                f"horizon {horizon} outside this provider's range 1..{self._max_horizon}"
            )
        levels = tuple(float(q) for q in quantiles)
        points: list[tuple[float, ...]] = []
        bands: list[tuple[tuple[float, ...], ...]] = []
        for context in contexts:
            window = list(context[-self._max_context :])
            if not window:
                raise ForecastUnavailable("empty context")
            point = drift_forecast(window, horizon)
            diffs = [b - a for a, b in pairwise(window)]
            sigma = pstdev(diffs) if len(diffs) > 1 else 0.0
            per_level: list[tuple[float, ...]] = []
            for q in levels:
                z = _NORMAL.inv_cdf(q)
                per_level.append(
                    tuple(p + z * sigma * math.sqrt(k + 1) for k, p in enumerate(point))
                )
            points.append(tuple(point))
            bands.append(tuple(per_level))
        return ForecastResult(point=tuple(points), quantile_levels=levels, quantiles=tuple(bands))


__all__ = ["FakeForecastProvider"]
