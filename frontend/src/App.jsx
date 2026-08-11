import { useCallback, useEffect, useRef, useState } from 'react'
import { analyze, getConfig, getHealth } from './api'
import Controls from './components/Controls'
import PriceChart from './components/PriceChart'
import SignalCard from './components/SignalCard'
import BacktestPanel from './components/BacktestPanel'
import { RiskPanel, TechnicalsPanel } from './components/RiskPanel'
import { fmtDate, fmtMoney, fmtPct } from './utils'

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

export default function App() {
  const [config, setConfig] = useState(null)
  const [health, setHealth] = useState(null)
  const [form, setForm] = useState(DEFAULT_FORM)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const timer = useRef(null)

  useEffect(() => {
    getConfig()
      .then((c) => {
        setConfig(c)
        setForm((f) => ({ ...f, ...c.defaults }))
      })
      .catch((e) => setError(e.message))
  }, [])

  // Poll while the model is still downloading/initialising.
  useEffect(() => {
    const tick = async () => {
      try {
        const h = await getHealth()
        setHealth(h.model)
        if (h.model.state === 'ready' || h.model.state === 'error') {
          clearInterval(timer.current)
        }
      } catch {
        /* server not up yet */
      }
    }
    tick()
    timer.current = setInterval(tick, 2500)
    return () => clearInterval(timer.current)
  }, [])

  const run = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      const payload = { ...form, symbol: form.symbol.trim().toUpperCase() }
      setResult(await analyze(payload))
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }, [form])

  const state = health?.state ?? 'connecting'
  const intraday = result && result.interval !== '1d'
  const change = result
    ? (result.stats.last_close / result.history[result.history.length - 2].close - 1) * 100
    : null

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <h1>📈 Kronos Stock Evaluator</h1>
          <span>foundation model for financial K-lines</span>
        </div>
        <div className="model-status" title={health?.error ?? ''}>
          <span className={`dot ${state}`} />
          {state === 'ready' ? (
            <>
              Kronos-{health.model} · {health.params} · {health.device}
              {health.load_seconds ? ` · loaded in ${health.load_seconds}s` : ''}
            </>
          ) : state === 'loading' ? (
            'Loading model weights…'
          ) : state === 'error' ? (
            `Model error: ${health.error}`
          ) : (
            'Connecting to backend…'
          )}
        </div>
      </header>

      <Controls form={form} setForm={setForm} onSubmit={run} busy={busy} config={config} />

      {error && <div className="error">{error}</div>}

      {busy && !result && (
        <div className="panel" style={{ marginTop: 16 }}>
          <div className="skeleton">
            <div className="spinner" />
            <div>Sampling {form.paths} Kronos futures for {form.symbol.toUpperCase()}…</div>
          </div>
        </div>
      )}

      {result && (
        <>
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

              <BacktestPanel backtest={result.backtest} intraday={intraday} />
            </div>

            <div className="stack">
              <SignalCard result={result} />
              <RiskPanel stats={result.stats} currency={result.meta.currency} />
              <TechnicalsPanel technicals={result.technicals} currency={result.meta.currency} />
            </div>
          </div>

          <p className="disclaimer">{result.disclaimer}</p>
        </>
      )}
    </div>
  )
}
