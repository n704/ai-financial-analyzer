"""Request/response contracts for the API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from . import config


class AnalyzeRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=24, examples=["AAPL"])
    interval: str = Field("1d", examples=["1d", "1h", "30m", "15m"])
    lookback: int = Field(config.DEFAULT_LOOKBACK, ge=64, le=config.MAX_LOOKBACK)
    horizon: int = Field(10, ge=1, le=config.MAX_PRED_LEN)
    paths: int = Field(24, ge=1, le=config.MAX_PATHS)
    temperature: float = Field(1.0, gt=0.0, le=2.0)
    top_p: float = Field(0.9, gt=0.0, le=1.0)
    seed: int | None = Field(None, ge=0, le=2**31 - 1)
    backtest: bool = Field(True, description="Also score the model on withheld recent bars.")


class AnalyzeResponse(BaseModel):
    symbol: str
    meta: dict[str, Any]
    interval: str
    interval_label: str
    params: dict[str, Any]
    model: dict[str, Any]
    history: list[dict[str, Any]]
    technicals: dict[str, Any]
    forecast: dict[str, Any]
    signal: dict[str, Any]
    stats: dict[str, Any]
    backtest: dict[str, Any] | None
    diagnostics: dict[str, Any]
    timings_ms: dict[str, int]
    disclaimer: str
