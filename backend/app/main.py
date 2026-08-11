"""FastAPI entrypoint for the Kronos stock evaluator."""
from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import comparison, config, quotes as quotes_service
from .kronos_engine import ModelNotReady, engine
from .market_data import INTERVALS, MarketDataError
from .pipeline import DISCLAIMER, analyze
from .schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    CompareForecastRequest,
    CompareRequest,
    Quote,
    SymbolAdd,
    WatchlistCreate,
    WatchlistOut,
    WatchlistRename,
)
from .storage import NotFound, StorageError, get_repository

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("kronos.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if config.PRELOAD:
        # Download/initialise weights off the event loop so /api/health answers
        # immediately with state="loading".
        def _load():
            try:
                engine.load()
                engine.warmup()
            except Exception:
                logger.exception("Background model load failed")

        threading.Thread(target=_load, name="kronos-preload", daemon=True).start()
    yield


app = FastAPI(
    title="Kronos Stock Evaluator",
    version="1.0.0",
    description="Probabilistic stock forecasts from the Kronos financial foundation model.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok", "model": engine.status()}


@app.get("/api/config")
async def get_config():
    return {
        "intervals": [
            {"value": k, "label": v.label, "intraday": v.intraday} for k, v in INTERVALS.items()
        ],
        "models": [
            {"value": k, "label": f"Kronos-{k} ({v['params']})", "max_context": v["max_context"]}
            for k, v in config.MODEL_PRESETS.items()
        ],
        "defaults": {
            "interval": "1d",
            "lookback": config.DEFAULT_LOOKBACK,
            "horizon": 10,
            "paths": 24,
            "temperature": 1.0,
            "top_p": 0.9,
        },
        "lookback_warn_above": config.LOOKBACK_WARN_ABOVE,
        "limits": {
            "max_lookback": config.MAX_LOOKBACK,
            "max_horizon": config.MAX_PRED_LEN,
            "max_paths": config.MAX_PATHS,
        },
        "disclaimer": DISCLAIMER,
    }


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def post_analyze(req: AnalyzeRequest):
    if req.lookback > engine.preset["max_context"]:
        raise HTTPException(
            status_code=422,
            detail=f"lookback {req.lookback} exceeds the model context window "
            f"({engine.preset['max_context']} bars).",
        )
    try:
        # Inference is CPU/GPU-bound and lock-serialised; keep the loop free.
        return await asyncio.to_thread(analyze, req)
    except MarketDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ModelNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Analysis failed for %s", req.symbol)
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


# --------------------------------------------------------------- comparison


@app.post("/api/compare")
async def post_compare(req: CompareRequest):
    """Price and risk comparison. No model, so this returns immediately."""
    try:
        result = await asyncio.to_thread(
            comparison.compare_symbols, req.symbols, req.interval, req.bars
        )
    except MarketDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Comparison failed for %s", req.symbols)
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
    result["explanations"] = comparison.explain_comparison(result)
    return result


@app.post("/api/compare/forecast")
async def post_compare_forecast(req: CompareForecastRequest):
    """Kronos signal for a single symbol, for the compare view's opt-in column.

    Skips the hold-out backtest — it roughly doubles runtime, and the compare
    table only shows the signal.
    """
    if req.lookback > engine.preset["max_context"]:
        raise HTTPException(
            status_code=422,
            detail=f"lookback {req.lookback} exceeds the model context window "
            f"({engine.preset['max_context']} bars).",
        )
    analyze_req = AnalyzeRequest(
        symbol=req.symbol,
        interval=req.interval,
        lookback=req.lookback,
        horizon=req.horizon,
        paths=req.paths,
        seed=req.seed,
        backtest=False,
    )
    try:
        full = await asyncio.to_thread(analyze, analyze_req)
    except MarketDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ModelNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Compare forecast failed for %s", req.symbol)
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

    return {
        "symbol": full["symbol"],
        "signal": full["signal"],
        "stats": full["stats"],
        "diagnostics": full["diagnostics"],
    }


# ------------------------------------------------------------------- quotes


@app.get("/api/quotes", response_model=list[Quote])
async def get_quotes(symbols: str = Query(..., description="Comma-separated tickers")):
    """Price snapshots for watchlist rows. No model, one batched download."""
    try:
        wanted = quotes_service.parse_symbols(symbols)
        return await asyncio.to_thread(quotes_service.fetch_quotes, wanted)
    except MarketDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Quote fetch failed for %s", symbols)
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc


# --------------------------------------------------------------- watchlists


def _storage_error(exc: StorageError) -> HTTPException:
    status = 404 if isinstance(exc, NotFound) else 400
    return HTTPException(status_code=status, detail=str(exc))


@app.get("/api/watchlists", response_model=list[WatchlistOut])
async def list_watchlists():
    return [WatchlistOut.of(w) for w in get_repository().list_watchlists()]


@app.post("/api/watchlists", response_model=WatchlistOut, status_code=201)
async def create_watchlist(req: WatchlistCreate):
    try:
        return WatchlistOut.of(get_repository().create_watchlist(req.name))
    except StorageError as exc:
        raise _storage_error(exc) from exc


@app.get("/api/watchlists/{watchlist_id}", response_model=WatchlistOut)
async def get_watchlist(watchlist_id: int):
    try:
        return WatchlistOut.of(get_repository().get_watchlist(watchlist_id))
    except StorageError as exc:
        raise _storage_error(exc) from exc


@app.patch("/api/watchlists/{watchlist_id}", response_model=WatchlistOut)
async def rename_watchlist(watchlist_id: int, req: WatchlistRename):
    try:
        return WatchlistOut.of(get_repository().rename_watchlist(watchlist_id, req.name))
    except StorageError as exc:
        raise _storage_error(exc) from exc


@app.delete("/api/watchlists/{watchlist_id}", status_code=204)
async def delete_watchlist(watchlist_id: int):
    try:
        get_repository().delete_watchlist(watchlist_id)
    except StorageError as exc:
        raise _storage_error(exc) from exc


@app.post("/api/watchlists/{watchlist_id}/symbols", response_model=WatchlistOut)
async def add_symbol(watchlist_id: int, req: SymbolAdd):
    """Idempotent: adding a symbol already on the list is a no-op, not a 409."""
    try:
        return WatchlistOut.of(get_repository().add_symbol(watchlist_id, req.symbol, req.note))
    except StorageError as exc:
        raise _storage_error(exc) from exc


@app.delete("/api/watchlists/{watchlist_id}/symbols/{symbol}", response_model=WatchlistOut)
async def remove_symbol(watchlist_id: int, symbol: str):
    try:
        return WatchlistOut.of(get_repository().remove_symbol(watchlist_id, symbol))
    except StorageError as exc:
        raise _storage_error(exc) from exc


# Serve the built frontend when it exists (`npm run build` in ./frontend).
if config.FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIST), html=True), name="ui")
