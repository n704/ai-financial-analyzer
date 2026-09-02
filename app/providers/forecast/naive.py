"""The naive baselines exposed *as* a ``ForecastProvider`` (P6.4).

``forecast.provider: naive`` is therefore a complete, working configuration
with zero extra dependencies — the whole F6 flow (fetch, transform, backtest,
band, verdict, persist, stream) runs end-to-end with torch absent. It is also
what CI exercises. The math lives in ``app/domain/forecast.py``; this module
only adapts it to the provider protocol.

No quantile head (``supports_quantiles=False``): the domain layer derives the
band from this provider's own backtest residuals, so the default configuration
exercises the empirical-band path rather than skipping it.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.forecast import BASELINES, DEFAULT_SEASON_LENGTH
from app.providers.base import ForecastResult, ForecastUnavailable

NAIVE_METHODS: tuple[str, ...] = tuple(BASELINES)


class NaiveForecastProvider:
    """``method`` is one of :data:`NAIVE_METHODS` (``drift`` by default — a
    random walk with drift, the strongest of the three on trending series)."""

    def __init__(
        self,
        *,
        method: str = "drift",
        season_length: int = DEFAULT_SEASON_LENGTH,
        max_context: int = 16_384,
        max_horizon: int = 4_096,
    ) -> None:
        if method not in BASELINES:
            raise ValueError(f"unknown naive method {method!r}; expected one of {NAIVE_METHODS}")
        if season_length < 1:
            raise ValueError("season_length must be >= 1")
        self._method = method
        self._season_length = season_length
        self._max_context = max_context
        self._max_horizon = max_horizon

    @property
    def provider(self) -> str:
        return "naive"

    @property
    def model(self) -> str:
        return f"naive:{self._method}"

    @property
    def checkpoint_revision(self) -> str:
        return "n/a"

    @property
    def max_context(self) -> int:
        return self._max_context

    @property
    def max_horizon(self) -> int:
        return self._max_horizon

    @property
    def supports_quantiles(self) -> bool:
        return False

    @property
    def supports_covariates(self) -> bool:
        return False

    def forecast(
        self,
        contexts: Sequence[Sequence[float]],
        horizon: int,
        quantiles: Sequence[float],
    ) -> ForecastResult:
        if not contexts:
            raise ForecastUnavailable("no contexts to forecast")
        if horizon < 1 or horizon > self._max_horizon:
            raise ForecastUnavailable(
                f"horizon {horizon} outside this provider's range 1..{self._max_horizon}"
            )
        fn = BASELINES[self._method]
        paths: list[tuple[float, ...]] = []
        for context in contexts:
            if not context:
                raise ForecastUnavailable("empty context")
            window = list(context[-self._max_context :])
            paths.append(tuple(fn(window, horizon, self._season_length)))
        return ForecastResult(
            point=tuple(paths), quantile_levels=tuple(float(q) for q in quantiles), quantiles=None
        )


__all__ = ["NAIVE_METHODS", "NaiveForecastProvider"]
