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
    explanations: dict[str, Any] = Field(default_factory=dict)
    timings_ms: dict[str, int]
    disclaimer: str


# ---------------------------------------------------------------- watchlists


class WatchlistItemOut(BaseModel):
    symbol: str
    note: str | None = None
    added_at: str | None = None


class WatchlistOut(BaseModel):
    id: int
    name: str
    created_at: str | None = None
    items: list[WatchlistItemOut] = Field(default_factory=list)

    @classmethod
    def of(cls, watchlist) -> "WatchlistOut":
        """Map a `storage.Watchlist` dataclass onto the wire format."""
        return cls(
            id=watchlist.id,
            name=watchlist.name,
            created_at=watchlist.created_at.isoformat() if watchlist.created_at else None,
            items=[
                WatchlistItemOut(
                    symbol=i.symbol,
                    note=i.note,
                    added_at=i.added_at.isoformat() if i.added_at else None,
                )
                for i in watchlist.items
            ],
        )


class WatchlistCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, examples=["Tech"])


class WatchlistRename(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class SymbolAdd(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=24, examples=["NVDA"])
    note: str | None = Field(None, max_length=280)


class Quote(BaseModel):
    symbol: str
    name: str
    currency: str | None = None
    sector: str | None = None
    price: float | None = None
    previous_close: float | None = None
    change_pct: float | None = None
    as_of: str | None = None
    error: str | None = None
