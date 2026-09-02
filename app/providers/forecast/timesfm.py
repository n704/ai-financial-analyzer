"""TimesFM adapter (P6.5): Google Research's pretrained time-series foundation
model, run zero-shot and in-process.

Everything model-specific stays here (ARCHITECTURE.md §3, "Adapter
responsibilities"): the checkpoint pin + HuggingFace download,
``from_pretrained``/``compile(ForecastConfig(...))``, device placement,
batching and context truncation, mapping the quantile head's columns onto the
requested levels, and keeping the model resident for the life of the process.
``timesfm``/``torch``/``numpy`` are imported lazily inside the constructor so
this module — and the factory that names it — import cleanly without the
``forecast`` extra installed.

Loading happens once, at construction (i.e. at process startup, from the
factory), never inside a job: a first request must not pay a checkpoint
download (SPEC.md §5, "Security & privacy").
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import structlog

from app.config import ConfigError
from app.providers.base import ForecastResult, ForecastUnavailable

log = structlog.get_logger()

# The 2.5 quantile head emits these nine levels; requests for other levels are
# refused at construction (a config error), not silently approximated.
TIMESFM_HEAD_LEVELS: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)

# Hard limits of the 2.5 architecture; config asks for a window within these.
TIMESFM_2P5_MAX_CONTEXT = 16_384
TIMESFM_2P5_MAX_HORIZON = 4_096


def quantile_columns(
    n_columns: int, requested: Sequence[float], head_levels: Sequence[float]
) -> list[int]:
    """Map requested quantile levels onto columns of the model's quantile
    output. TimesFM's quantile array has either exactly one column per head
    level, or one extra leading column carrying the mean (``[mean, q0.1, ...,
    q0.9]``); both layouts are handled by shape rather than by version sniffing.
    Pure, so it is unit-tested without torch."""
    if n_columns == len(head_levels):
        offset = 0
    elif n_columns == len(head_levels) + 1:
        offset = 1
    else:
        raise ForecastUnavailable(
            f"unexpected quantile output width {n_columns} for a head with "
            f"{len(head_levels)} levels"
        )
    columns: list[int] = []
    for q in requested:
        for i, level in enumerate(head_levels):
            if abs(level - q) < 1e-9:
                columns.append(i + offset)
                break
        else:
            raise ForecastUnavailable(f"quantile level {q} is not produced by this model")
    return columns


def _import_timesfm() -> Any:
    try:
        import timesfm
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ConfigError(
            "forecast.provider='timesfm' requires the `forecast` extra "
            "(`uv sync --extra forecast` installs timesfm[torch]); it is not importable: "
            f"{exc}"
        ) from exc
    return timesfm


class TimesFMForecastProvider:
    """Wraps ``timesfm.TimesFM_2p5_200M_torch``. ``model`` is the HuggingFace
    repo id, ``revision`` the pinned checkpoint revision (recorded on every
    artifact as provenance)."""

    def __init__(
        self,
        *,
        model: str,
        revision: str,
        device: str = "cpu",
        max_context: int = 1024,
        max_horizon: int = 256,
        quantiles: Sequence[float] = TIMESFM_HEAD_LEVELS,
        torch_compile: bool = False,
        normalize_inputs: bool = True,
        local_files_only: bool = False,
        cache_dir: str | None = None,
    ) -> None:
        if not 1 <= max_context <= TIMESFM_2P5_MAX_CONTEXT:
            raise ConfigError(
                f"forecast.max_context={max_context} outside TimesFM 2.5's range "
                f"1..{TIMESFM_2P5_MAX_CONTEXT}"
            )
        if not 1 <= max_horizon <= TIMESFM_2P5_MAX_HORIZON:
            raise ConfigError(
                f"forecast.max_horizon={max_horizon} outside TimesFM 2.5's range "
                f"1..{TIMESFM_2P5_MAX_HORIZON}"
            )
        for q in quantiles:
            if not any(abs(q - level) < 1e-9 for level in TIMESFM_HEAD_LEVELS):
                raise ConfigError(
                    f"forecast.quantiles contains {q}, which TimesFM 2.5's quantile head "
                    f"does not produce (available: {list(TIMESFM_HEAD_LEVELS)})"
                )
        self._model_id = model
        self._revision = revision
        self._device = device
        self._max_context = max_context
        self._max_horizon = max_horizon
        self._levels = tuple(float(q) for q in quantiles)

        timesfm = _import_timesfm()
        import numpy as np

        self._np = np
        try:
            loaded = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
                model,
                revision=revision,
                cache_dir=cache_dir,
                local_files_only=local_files_only,
                torch_compile=torch_compile,
            )
            _place_on_device(loaded, device)
            loaded.compile(
                timesfm.ForecastConfig(
                    max_context=max_context,
                    max_horizon=max_horizon,
                    normalize_inputs=normalize_inputs,
                    use_continuous_quantile_head=True,
                    force_flip_invariance=True,
                    # Contexts arrive in transform space (log-prices can be
                    # negative), so never clamp outputs to non-negative.
                    infer_is_positive=False,
                    fix_quantile_crossing=True,
                )
            )
        except ConfigError:
            raise
        except Exception as exc:
            raise ConfigError(
                f"could not load TimesFM checkpoint {model!r}@{revision!r}: {exc}. "
                f"Air-gapped deployments pre-seed the HuggingFace cache and set "
                f"HF_HUB_OFFLINE=1; weights are never fetched inside a request."
            ) from exc
        self._model = loaded
        log.info(
            "forecast.model_loaded",
            provider="timesfm",
            model=model,
            revision=revision,
            device=device,
            max_context=max_context,
            max_horizon=max_horizon,
        )

    @property
    def provider(self) -> str:
        return "timesfm"

    @property
    def model(self) -> str:
        return self._model_id

    @property
    def checkpoint_revision(self) -> str:
        return self._revision

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
        # 2.5 covers covariates via XReg, which this adapter does not wire yet;
        # core code passes univariate context only while this is False.
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
                f"horizon {horizon} outside the compiled range 1..{self._max_horizon}"
            )
        np = self._np
        inputs = [
            np.asarray(list(context)[-self._max_context :], dtype=np.float32)
            for context in contexts
        ]
        if any(arr.size == 0 for arr in inputs):
            raise ForecastUnavailable("empty context")
        try:
            point, quantile = self._model.forecast(horizon=horizon, inputs=inputs)
        except Exception as exc:
            raise ForecastUnavailable(f"TimesFM inference failed: {exc}") from exc

        point_arr = np.asarray(point, dtype=np.float64)
        quantile_arr = np.asarray(quantile, dtype=np.float64)
        if point_arr.ndim != 2 or quantile_arr.ndim != 3:
            raise ForecastUnavailable(
                f"unexpected TimesFM output shapes {point_arr.shape} / {quantile_arr.shape}"
            )
        columns = quantile_columns(quantile_arr.shape[-1], quantiles, TIMESFM_HEAD_LEVELS)
        points = tuple(tuple(float(v) for v in row[:horizon]) for row in point_arr)
        bands = tuple(
            tuple(tuple(float(v) for v in series[:horizon, col]) for col in columns)
            for series in quantile_arr
        )
        return ForecastResult(
            point=points, quantile_levels=tuple(float(q) for q in quantiles), quantiles=bands
        )


def _place_on_device(loaded: Any, device: str) -> None:
    """TimesFM 2.5's torch wrapper picks ``cuda:0`` when available, else CPU,
    and records the choice on its inner module's ``device`` attribute (used
    when it converts inputs to tensors). Honour ``forecast.device`` by moving
    that module and updating the attribute it reads."""
    import torch

    target = torch.device(device)
    module = getattr(loaded, "model", None)
    if module is None or not hasattr(module, "to"):
        if device != "cpu":
            raise ConfigError(
                f"forecast.device={device!r} requested but the loaded TimesFM wrapper "
                f"exposes no torch module to move; use 'cpu'"
            )
        return
    module.to(target)
    module.device = target


__all__ = [
    "TIMESFM_2P5_MAX_CONTEXT",
    "TIMESFM_2P5_MAX_HORIZON",
    "TIMESFM_HEAD_LEVELS",
    "TimesFMForecastProvider",
    "quantile_columns",
]
