# AI Financial Analyzer

A full-stack app that evaluates a stock with [**Kronos**](https://github.com/shiyu-coder/Kronos) — the
first open-source foundation model for financial candlesticks (AAAI 2026,
[arXiv:2508.02739](https://arxiv.org/abs/2508.02739)). Type a ticker, get a probabilistic forecast,
a BUY/HOLD/SELL call, a risk profile, and — importantly — a hold-out score that tells you whether the
model actually beat a do-nothing baseline on that symbol's recent bars.

- **Backend** — Python / FastAPI, Kronos (PyTorch) inference, Yahoo Finance data
- **Frontend** — React + Vite, TradingView `lightweight-charts`

```
Ticker ─▶ yfinance OHLCV ─▶ Kronos tokenizer ─▶ Kronos transformer ─▶ N sampled futures
                                                                          │
                        band + signal + risk + hold-out backtest ◀────────┘
```

## Quick start

```bash
git clone https://github.com/n704/ai-financial-analyzer.git
cd ai-financial-analyzer
./setup.sh     # clone Kronos, create .venv (Python 3.10+), install deps, build UI
./run.sh       # http://127.0.0.1:8000
```

First launch downloads ~100 MB of weights from Hugging Face (`NeoQuasar/Kronos-small` +
`Kronos-Tokenizer-base`) and caches them in `~/.cache/huggingface`. Loading takes ~20 s cold,
~1.5 s warm. A forecast of 24 paths × 10 bars runs in ~1–3 s on an M-series Mac (MPS) or CPU.

For frontend hot-reload use `./dev.sh` and open <http://127.0.0.1:5173>.

## How it works

1. **Data** — `yfinance` pulls OHLCV bars (daily, hourly, 30m, 15m). At least 260 bars are fetched so
   indicators stay meaningful even when the model context is short.
2. **Forecast** — the last `lookback` bars go to `KronosPredictor`. Kronos averages internally when
   `sample_count > 1`, which destroys the distribution, so instead the same series is handed to
   `predict_batch` `N` times with `sample_count=1`: one batched autoregressive pass, `N` independently
   sampled trajectories.
3. **Evaluation** — the paths become a p10/p50/p90 band, a terminal-return distribution, P(up),
   value-at-risk, expected shortfall, and a signal.
4. **Hold-out backtest** — the last `horizon` bars are withheld, the forecast is re-run from the bars
   before them, and the result is scored against reality *and* against a flat-price baseline.

### Signal rules

| Condition | Action |
|---|---|
| P(up) ≥ 0.58 **and** mean return > +0.5% | BUY |
| P(up) ≤ 0.42 **and** mean return < −0.5% | SELL |
| otherwise | HOLD (confidence capped at 55) |

Confidence blends directional agreement across paths with conviction (mean ÷ spread of returns).

## What I found while wiring this up

Two things that materially affect output quality, both verified rather than assumed:

**1. The model must run in eval mode.** `KronosPredictor` never calls `.eval()`, and the upstream
`examples/` don't either — but `Kronos-small` ships `ffn_dropout_p=0.25`, `resid_dropout_p=0.25`,
`attn_dropout_p=0.1`. Left in train mode it injects dropout noise into every forecast (and MPS refuses
attention dropout outright). Upstream's own `tests/test_kronos_regression.py` *does* call `.eval()`,
which settles the intent. This app calls it at load time; the vendored regression tests pass exactly:

```bash
cd vendor/Kronos && PYTHONPATH=. ../../.venv/bin/python -m pytest tests/ -q   # 4 passed
```

**2. Long lookbacks are harmful on daily equity bars.** `KronosPredictor` z-scores each context window,
so a long trending window leaves the last price ~2σ above the window mean and the model mean-reverts
hard — producing a confident, spurious downtrend. Walk-forward test, 5 tickers × 5 origins, 10-bar
horizon, measured with this codebase:

| lookback | MAPE | naive baseline | terminal direction | mean drift bias |
|---|---|---|---|---|
| 64  | **3.57%** | 3.54% | 60% | −1.1% |
| 128 | 4.07% | 3.54% | 48% | −0.9% |
| 256 | 6.68% | 3.54% | 52% | −5.7% |
| 400 | 6.91% | 3.54% | 52% | −7.5% |

Hence the default lookback is **128**, not the 400 used in the upstream examples, and the app warns
when the context is stretched (|z| > 1.5) or the lookback exceeds 200 daily bars.

**Read the honest conclusion in that table**: on daily US equities over this sample, Kronos-small did
not beat "assume the price doesn't change" on absolute error, and per-bar direction was near a coin
flip. That is why the hold-out panel is built into every response instead of being hidden — the app
shows you when its own forecast is not worth acting on. The model was designed and benchmarked largely
on higher-frequency K-lines; treat daily equity forecasts as exploratory.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Model state (`idle`/`loading`/`ready`/`error`), device, params |
| `GET /api/config` | Intervals, model presets, defaults, limits |
| `POST /api/analyze` | Full evaluation for one symbol |

```bash
curl -X POST localhost:8000/api/analyze -H 'Content-Type: application/json' \
  -d '{"symbol":"AAPL","interval":"1d","lookback":128,"horizon":10,"paths":24,"seed":7}'
```

| Field | Default | Notes |
|---|---|---|
| `symbol` | — | Yahoo format: `AAPL`, `BTC-USD`, `RELIANCE.NS` |
| `interval` | `1d` | `1d`, `1h`, `30m`, `15m` |
| `lookback` | `128` | 64–512 bars of context (model max is 512) |
| `horizon` | `10` | 1–120 bars to forecast |
| `paths` | `24` | 1–64 Monte-Carlo trajectories |
| `temperature` / `top_p` | `1.0` / `0.9` | Sampling controls |
| `seed` | `null` | Set for reproducible forecasts |
| `backtest` | `true` | Run the hold-out check (roughly doubles runtime) |

The response carries `history`, `forecast.band`, `forecast.sample_paths`, `signal`, `stats`,
`technicals`, `backtest`, and `diagnostics.caveats`.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `KRONOS_MODEL` | `small` | `mini` (4.1M, 2048 ctx), `small` (24.7M), `base` (102.3M) |
| `KRONOS_DEVICE` | auto | `cpu`, `mps`, `cuda:0`; auto-detects otherwise |
| `KRONOS_PRELOAD` | `1` | Load weights at startup instead of first request |
| `HF_TOKEN` | unset | Only needed for private mirrors — see note below |
| `PORT` | `8000` | API port |

> **Hugging Face auth note.** The Kronos repos are public, so the app downloads anonymously
> (`token=False`) unless `HF_TOKEN` is set. This is deliberate: a stale token in
> `~/.cache/huggingface/token` makes public repos return `401 Repository Not Found`, which is exactly
> what happened on the machine this was built on.

## Tests

```bash
.venv/bin/python -m pytest backend/tests -q                                  # 15 tests, no network
cd vendor/Kronos && PYTHONPATH=. ../../.venv/bin/python -m pytest tests/ -q  # upstream regression
```

The backend suite covers exchange vs. 24/7 calendar generation, intraday session grids, signal
thresholds, OHLC ordering of forecast candles, JSON-safety on degenerate paths, hold-out scoring, and
the diagnostic caveats.

## Layout

```
backend/app/
  main.py           FastAPI routes, static hosting, background model load
  pipeline.py       data → forecast → evaluation orchestration
  kronos_engine.py  thread-safe model wrapper, Monte-Carlo path sampling
  market_data.py    yfinance access, future-bar calendars
  analysis.py       bands, statistics, signal, hold-out scoring, caveats
frontend/src/
  App.jsx           layout and state
  components/       Controls, PriceChart, SignalCard, RiskPanel, BacktestPanel
vendor/Kronos/      upstream checkout (cloned by setup.sh)
```

## Disclaimer

Forecasts come from price history alone — no fundamentals, news, or earnings. Kronos is a
probabilistic model, not an oracle, and the hold-out numbers above show it can underperform a naive
baseline. This is a research and education tool. **Nothing here is financial advice.**
