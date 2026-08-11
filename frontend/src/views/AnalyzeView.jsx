import { useCallback, useEffect, useState } from 'react'
import { analyze } from '../api'
import Controls from '../components/Controls'
import PriceChart from '../components/PriceChart'
import SignalCard from '../components/SignalCard'
import BacktestPanel from '../components/BacktestPanel'
import ExplainPanel from '../components/ExplainPanel'
import { RiskPanel, TechnicalsPanel } from '../components/RiskPanel'
import SectorPanel from '../components/SectorPanel'
import { fmtDate, fmtMoney, fmtPct } from '../utils'

const DEFAULT_FORM = {
  symbol: 'AAPL',
  interval: '1d',
  lookback: 128,
  horizon: 10,
  paths: 24,
  temperature: 1.0,
  top_p: 0.9,
  seed: null,
  backtest: true,
}

/** Single-symbol Kronos evaluation: forecast, signal, risk and hold-out score. */
export default function AnalyzeView({ config, symbol, onSymbolChange, modelState }) {
  const [form, setForm] = useState(() => ({ ...DEFAULT_FORM, symbol: symbol || DEFAULT_FORM.symbol }))
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (config?.defaults) setForm((f) => ({ ...f, ...config.defaults }))
  }, [config])

  // A symbol arriving from the URL (or another view) drives the form. Keyed on
  // `symbol` alone on purpose: adding `form.symbol` would fight the user's
  // typing, since every keystroke would re-run this and reset the field.
  useEffect(() => {
    setForm((f) => (symbol && symbol !== f.symbol ? { ...f, symbol } : f))
  }, [symbol])

  const run = useCallback(async () => {
    setBusy(true)
    setError(null)
    const payload = { ...form, symbol: form.symbol.trim().toUpperCase() }
    onSymbolChange?.(payload.symbol)
    try {
      setResult(await analyze(payload))
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }, [form, onSymbolChange])

  const intraday = result && result.interval !== '1d'
  const change = result
    ? (result.stats.last_close / result.history[result.history.length - 2].close - 1) * 100
    : null

  return (
    <>
      <Controls
        form={form}
        setForm={setForm}
        onSubmit={run}
        busy={busy}
        config={config}
        modelState={modelState}
      />

      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}

      {busy && !result && (
        <div className="panel" style={{ marginTop: 16 }}>
          <div className="skeleton">
            <div className="spinner" />
            <div>Sampling {form.paths} Kronos futures for {form.symbol.toUpperCase()}…</div>
          </div>
        </div>
      )}

      {!busy && !result && !error && (
        <div className="panel" style={{ marginTop: 16 }}>
          <div className="empty">
            <p>Pick a ticker and hit Evaluate.</p>
            <p className="muted">
              You will get a probabilistic forecast, a signal, a risk profile, and a hold-out score
              that says whether the model beat doing nothing on that symbol&apos;s recent bars.
            </p>
          </div>
        </div>
      )}

      {result && (
        <>
          {/* A re-run keeps the previous result mounted and dims it, rather
              than blanking the page — otherwise the screen jumps and the
              reader loses their place on every parameter tweak. */}
          <div className={`results ${busy ? 'stale' : ''}`} aria-busy={busy}>
            {busy && (
              <div className="results-overlay" role="status">
                <div className="spinner" />
                <div>Re-running {form.symbol.toUpperCase()}…</div>
              </div>
            )}
          <div className="grid main">
            <div className="stack">
              <div className="panel">
                <div className="chart-head">
                  <div>
                    <div className="price-now">
                      <span className="p">{fmtMoney(result.stats.last_close, result.meta.currency)}</span>
                      <span className={change >= 0 ? 'pos' : 'neg'}>{fmtPct(change)}</span>
                    </div>
                    <div className="muted" style={{ marginTop: 2 }}>
                      {result.meta.name} · {result.symbol}
                      {result.meta.exchange ? ` · ${result.meta.exchange}` : ''} · {result.interval_label}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right', fontSize: 12 }} className="muted">
                    <div>
                      <span className="tag">{result.params.lookback} bars in</span>
                      <span className="tag">{result.params.horizon} bars out</span>
                      <span className="tag">{result.params.paths} paths</span>
                    </div>
                    <div style={{ marginTop: 6 }}>
                      Through {fmtDate(result.params.history_end, intraday)} → {fmtDate(result.params.forecast_end, intraday)}
                    </div>
                    <div>
                      {Object.entries(result.timings_ms)
                        .map(([k, v]) => `${k} ${v}ms`)
                        .join(' · ')}
                    </div>
                  </div>
                </div>
                <PriceChart result={result} />
                <ExplainPanel paragraphs={result.explanations?.forecast} />
              </div>

              {result.diagnostics.caveats.length > 0 && (
                <div className="panel">
                  <div className="panel-title">Read this before trusting the number</div>
                  <div className="stack" style={{ gap: 8 }}>
                    {result.diagnostics.caveats.map((c) => (
                      <div className="notice" key={c}>
                        {c}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <BacktestPanel backtest={result.backtest} intraday={intraday}>
                <ExplainPanel
                  paragraphs={result.explanations?.backtest}
                  title="What the hold-out chart is telling you"
                />
              </BacktestPanel>

              {/* Keyed on the analysed symbol so it refetches on a new run,
                  not on every parameter tweak. */}
              <SectorPanel symbol={result.symbol} interval={result.interval} />
            </div>

            <div className="stack">
              <SignalCard result={result} />
              <RiskPanel stats={result.stats} currency={result.meta.currency} />
              <TechnicalsPanel technicals={result.technicals} currency={result.meta.currency} />
            </div>
          </div>
          </div>

          <p className="disclaimer">{result.disclaimer}</p>
        </>
      )}
    </>
  )
}
