"""Loads the Kronos foundation model and turns OHLCV history into forecast paths."""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from typing import Literal

import numpy as np
import pandas as pd

from . import config

logger = logging.getLogger(__name__)

# The Kronos package lives in the vendored upstream checkout, not on PyPI.
if str(config.KRONOS_REPO) not in sys.path:
    sys.path.insert(0, str(config.KRONOS_REPO))

OUTPUT_COLS = ["open", "high", "low", "close", "volume", "amount"]
State = Literal["idle", "loading", "ready", "error"]

# Batch of forecast paths pushed through the model at once.
PATH_CHUNK = 16


class ModelNotReady(RuntimeError):
    pass


def _hf_token():
    """Use an explicit HF_TOKEN if provided, otherwise download anonymously.

    A stale token in ~/.cache/huggingface/token makes public repos 401, so we
    never fall back to the ambient credential.
    """
    return os.getenv("HF_TOKEN") or False


def _resolve_device(requested: str | None) -> str:
    import torch

    if requested:
        return requested
    if torch.cuda.is_available():
        return "cuda:0"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class KronosEngine:
    """Thread-safe wrapper around a single KronosPredictor instance."""

    def __init__(self, model_key: str | None = None, device: str | None = None):
        self.model_key = model_key or config.DEFAULT_MODEL
        if self.model_key not in config.MODEL_PRESETS:
            raise ValueError(f"Unknown model '{self.model_key}'")
        self.requested_device = device if device is not None else config.DEVICE
        self.device: str | None = None
        self.state: State = "idle"
        self.error: str | None = None
        self.load_seconds: float | None = None
        self._predictor = None
        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()

    # ---------------------------------------------------------------- status

    @property
    def preset(self) -> dict:
        return config.MODEL_PRESETS[self.model_key]

    def status(self) -> dict:
        return {
            "state": self.state,
            "model": self.model_key,
            "model_repo": self.preset["model"],
            "tokenizer_repo": self.preset["tokenizer"],
            "params": self.preset["params"],
            "max_context": self.preset["max_context"],
            "device": self.device,
            "load_seconds": round(self.load_seconds, 1) if self.load_seconds else None,
            "error": self.error,
        }

    # ----------------------------------------------------------------- load

    def load(self, force_device: str | None = None) -> None:
        """Download (first run) and initialise the model. Safe to call twice."""
        with self._load_lock:
            if self.state == "ready" and force_device is None:
                return
            from model import Kronos, KronosPredictor, KronosTokenizer

            self.state = "loading"
            self.error = None
            started = time.time()
            try:
                token = _hf_token()
                tokenizer = KronosTokenizer.from_pretrained(self.preset["tokenizer"], token=token)
                net = Kronos.from_pretrained(self.preset["model"], token=token)

                # Upstream examples skip this, but these checkpoints carry
                # dropout (up to p=0.25); leaving train mode on would inject
                # noise into every forecast and MPS rejects attention dropout.
                tokenizer.eval()
                net.eval()

                device = _resolve_device(force_device or self.requested_device)
                self._predictor = KronosPredictor(
                    net, tokenizer, device=device, max_context=self.preset["max_context"]
                )
                self.device = self._predictor.device
                self.load_seconds = time.time() - started
                self.state = "ready"
                logger.info("Kronos %s ready on %s in %.1fs", self.model_key, self.device, self.load_seconds)
            except Exception as exc:  # noqa: BLE001 - surfaced through /api/health
                self.state = "error"
                self.error = f"{type(exc).__name__}: {exc}"
                logger.exception("Failed to load Kronos model")
                raise

    def ensure_ready(self) -> None:
        if self.state != "ready":
            self.load()
        if self._predictor is None:
            raise ModelNotReady(self.error or "Model is not loaded")

    # -------------------------------------------------------------- forecast

    def forecast_paths(
        self,
        df: pd.DataFrame,
        x_timestamp: pd.DatetimeIndex,
        y_timestamp: pd.DatetimeIndex,
        n_paths: int,
        temperature: float = 1.0,
        top_p: float = 0.9,
        seed: int | None = None,
    ) -> np.ndarray:
        """Return `n_paths` independent Monte-Carlo futures.

        Shape: (n_paths, pred_len, 6) over open/high/low/close/volume/amount.

        Kronos averages internally when `sample_count > 1`, which destroys the
        distribution we want. Instead we hand the same series to the batch API
        `n_paths` times with sample_count=1: one batched autoregressive pass,
        one independently sampled trajectory per batch row.
        """
        self.ensure_ready()
        pred_len = len(y_timestamp)
        x_ts = pd.Series(pd.DatetimeIndex(x_timestamp))
        y_ts = pd.Series(pd.DatetimeIndex(y_timestamp))
        frame = df[["open", "high", "low", "close", "volume"]].reset_index(drop=True)

        chunks: list[np.ndarray] = []
        with self._infer_lock:
            import torch

            if seed is not None:
                torch.manual_seed(seed)
            remaining = n_paths
            while remaining > 0:
                size = min(PATH_CHUNK, remaining)
                preds = self._run_batch(frame, x_ts, y_ts, pred_len, size, temperature, top_p)
                chunks.append(preds)
                remaining -= size
        return np.concatenate(chunks, axis=0)

    def _run_batch(self, frame, x_ts, y_ts, pred_len, size, temperature, top_p) -> np.ndarray:
        pred_dfs = self._predictor.predict_batch(
            df_list=[frame] * size,
            x_timestamp_list=[x_ts] * size,
            y_timestamp_list=[y_ts] * size,
            pred_len=pred_len,
            T=temperature,
            top_p=top_p,
            sample_count=1,
            verbose=False,
        )
        return np.stack([p[OUTPUT_COLS].to_numpy(dtype=float) for p in pred_dfs], axis=0)

    def warmup(self) -> None:
        """Run one tiny forecast so the first real request isn't paying setup."""
        self.ensure_ready()
        n = 64
        idx = pd.bdate_range("2024-01-02", periods=n)
        base = np.linspace(100.0, 105.0, n)
        df = pd.DataFrame(
            {
                "open": base,
                "high": base * 1.01,
                "low": base * 0.99,
                "close": base,
                "volume": np.full(n, 1e6),
            }
        )
        self.forecast_paths(df, idx, pd.bdate_range(idx[-1], periods=3)[1:], n_paths=1)


engine = KronosEngine()
