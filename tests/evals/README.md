# Evals

Regression evals that measure *behaviour*, not just code paths.

| Suite | What it measures | Runs |
|---|---|---|
| `forecast/` (P6.9) | The configured `ForecastProvider` scored against seasonal-naive, drift, and last-value on fixture series with known continuations — MASE / sMAPE / pinball / 80% coverage, the skill verdict, and a relative-skill regression guard (`expected.json`). The bar is "measures and reports skill correctly", **not** "beats the baseline". | CI on `naive` (hermetic). `FORECAST_EVAL_PROVIDER=timesfm make eval-forecast` on demand with the `forecast` extra. Regenerate expectations deliberately with `FORECAST_EVAL_WRITE=1`. |
| Q&A + extraction (P3/P2) | ≥20 Q&A pairs with expected citations + metric-extraction fixtures against a recorded-response provider fake. | Lands with P3. |
