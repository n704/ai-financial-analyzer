"""Static configuration for the Kronos stock-evaluation service."""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
KRONOS_REPO = PROJECT_ROOT / "vendor" / "Kronos"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
# Everything the app writes lives here; gitignored, created on first use.
DATA_DIR = PROJECT_ROOT / "data"

# Model zoo published by the Kronos authors on the Hugging Face Hub.
MODEL_PRESETS: dict[str, dict] = {
    "mini": {
        "model": "NeoQuasar/Kronos-mini",
        "tokenizer": "NeoQuasar/Kronos-Tokenizer-2k",
        "max_context": 2048,
        "params": "4.1M",
    },
    "small": {
        "model": "NeoQuasar/Kronos-small",
        "tokenizer": "NeoQuasar/Kronos-Tokenizer-base",
        "max_context": 512,
        "params": "24.7M",
    },
    "base": {
        "model": "NeoQuasar/Kronos-base",
        "tokenizer": "NeoQuasar/Kronos-Tokenizer-base",
        "max_context": 512,
        "params": "102.3M",
    },
}

DEFAULT_MODEL = os.getenv("KRONOS_MODEL", "small")
# None -> auto-detect (cuda > mps > cpu) inside KronosPredictor.
DEVICE = os.getenv("KRONOS_DEVICE") or None
# Load weights as soon as the server boots instead of on first request.
PRELOAD = os.getenv("KRONOS_PRELOAD", "1") not in {"0", "false", "False"}

# Bars of history fed to the model. The model accepts up to `max_context`, but
# walk-forward testing on daily US equities (5 tickers x 5 origins, 10-bar
# horizon) showed long windows degrade badly: median MAPE 3.6% at 64 bars and
# 4.1% at 128, against 6.7% at 256 and 6.9% at 400, with the drift bias growing
# from -1% to -7.5%. KronosPredictor z-scores each window, so a long trending
# window leaves the last price far above the window mean and the model reverts.
DEFAULT_LOOKBACK = 128
# Beyond this the mean-reversion artefact dominates; warn the user.
LOOKBACK_WARN_ABOVE = 200
# Hard ceilings that keep a single request responsive.
MAX_LOOKBACK = 512
MAX_PRED_LEN = 120
MAX_PATHS = 64

# ------------------------------------------------------------------ storage
# Which `storage.WatchlistRepository` implementation to build. Only "sqlite"
# ships today; the indirection exists so another database can replace it
# without touching any caller.
WATCHLIST_BACKEND = os.getenv("WATCHLIST_BACKEND", "sqlite")
WATCHLIST_DB = os.getenv("WATCHLIST_DB") or str(DATA_DIR / "watchlists.db")

# -------------------------------------------------------------- market data
# Comparison, sector and watchlist views fan out over many symbols, so repeated
# yfinance calls dominate latency without a cache. Bars change at most once per
# interval; names and sectors change essentially never.
OHLCV_CACHE_TTL_INTRADAY = float(os.getenv("OHLCV_CACHE_TTL_INTRADAY", "60"))
OHLCV_CACHE_TTL_DAILY = float(os.getenv("OHLCV_CACHE_TTL_DAILY", "300"))
META_CACHE_TTL = float(os.getenv("META_CACHE_TTL", "3600"))
