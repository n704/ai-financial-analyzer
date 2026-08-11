"""Static configuration for the Kronos stock-evaluation service."""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
KRONOS_REPO = PROJECT_ROOT / "vendor" / "Kronos"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

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
