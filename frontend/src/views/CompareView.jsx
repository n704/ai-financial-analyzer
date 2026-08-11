import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '../api'
import CompareChart from '../components/CompareChart'
import CompareTable from '../components/CompareTable'
import CorrelationMatrix from '../components/CorrelationMatrix'
import ExplainPanel from '../components/ExplainPanel'
import { fmtDate } from '../utils'

const MIN_SYMBOLS = 2
const MAX_SYMBOLS = 6
const PRESETS = [
  { label: 'Megacap tech', symbols: 'AAPL,MSFT,NVDA' },
  { label: 'Index vs gold', symbols: 'SPY,GLD' },
  { label: 'EV makers', symbols: 'TSLA,RIVN,LCID' },
]

const parse = (raw) =>
  [...new Set((raw || '').toUpperCase().split(/[\s,]+/).filter(Boolean))].slice(0, MAX_SYMBOLS)

export default function CompareView({ config, symbols: initial, onNavigate }) {
  const [input, setInput] = useState(initial || 'AAPL,MSFT,NVDA')
  const [interval, setInterval] = useState('1d')
  const [bars, setBars] = useState(180)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [forecasts, setForecasts] = useState({})
  const [forecasting, setForecasting] = useState(false)
  const cancelled = useRef(false)

  useEffect(() => () => { cancelled.current = true }, [])

  const symbols = parse(input)
  const canRun = symbols.length >= MIN_SYMBOLS

  const run = useCallback(
    async (e) => {
      e?.preventDefault()
      const wanted = parse(input)
      if (wanted.length < MIN_SYMBOLS) return
      setBusy(true)
      setError(null)
      setForecasts({})
      onNavigate?.(wanted.join(','))
      try {
        setResult(await api.compare(wanted, interval, bars))
      } catch (err) {
        setError(err.message)
        setResult(null)
      } finally {
        setBusy(false)
      }
    },
    [input, interval, bars, onNavigate],
  )

  useEffect(() => {
    run()
    // Run once on mount with whatever the URL supplied.
    // eslint-disable-next-line
  }, [])

  /**
   * One request per symbol, in sequence. Inference is lock-serialised on the
   * server, so firing them together would only replace a visible progression
   * with one long silence — and each column fills in as its result lands.
   */
  const runForecasts = async () => {
    if (!result) return
    setForecasting(true)
    for (const row of result.symbols) {
      if (cancelled.current) break
      setForecasts((f) => ({ ...f, [row.symbol]: { status: 'pending' } }))
      try {
        const data = await api.compareForecast({ symbol: row.symbol, interval })
        setForecasts((f) => ({ ...f, [row.symbol]: { status: 'done', data } }))
      } catch (err) {
        setForecasts((f) => ({ ...f, [row.symbol]: { status: 'error', error: err.message } }))
      }
    }
    setForecasting(false)
  }

  const intraday = result && result.interval !== '1d'

  return (
    <div className="stack">
      <form className="panel" onSubmit={run}>
        <div className="compare-controls">
          <div className="field grow">
            <label htmlFor="compare-symbols">Symbols</label>
            <input
              id="compare-symbols"
              className="symbol"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="AAPL, MSFT, NVDA"
              autoComplete="off"
              spellCheck="false"
            />
          </div>

          <div className="field">
            <label htmlFor="compare-interval">Interval</label>
            <select
              id="compare-interval"
              value={interval}
              onChange={(e) => setInterval(e.target.value)}
            >
              {(config?.intervals ?? [{ value: '1d', label: 'Daily' }]).map((i) => (
                <option key={i.value} value={i.value}>{i.label}</option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="compare-bars">Bars</label>
            {/* No `step`: with min=32 a step of 10 would make the default 180
                fail constraint validation, and the browser silently refuses to
                submit an invalid form — the Compare button would do nothing. */}
            <input
              id="compare-bars"
              type="number"
              min="32"
              max="1000"
              value={bars}
              onChange={(e) => setBars(Number(e.target.value))}
            />
          </div>

          <button className="btn" type="submit" disabled={busy || !canRun}>
            {busy ? 'Comparing…' : 'Compare'}
          </button>
        </div>

        <div className="examples">
          <span>Try:</span>
          {PRESETS.map((p) => (
            <button
              key={p.label}
              type="button"
              className="chip"
              onClick={() => setInput(p.symbols)}
            >
              {p.label}
            </button>
          ))}
          {!canRun && <span className="muted">Enter at least two symbols.</span>}
        </div>
      </form>

      {error && <div className="error">{error}</div>}

      {busy && !result && (
        <div className="panel">
          <div className="skeleton">
            <div className="spinner" />
            <div>Fetching {symbols.length} symbols…</div>
          </div>
        </div>
      )}

      {result && (
        <>
          {result.unavailable.length > 0 && (
            <div className="notice">
              {result.unavailable.map((u) => `${u.symbol}: ${u.reason}`).join(' ')}
            </div>
          )}

          <div className="panel">
            <div className="panel-head">
              <div className="panel-title" style={{ margin: 0 }}>
                Relative performance — {result.bars} shared {result.interval_label.toLowerCase()} bars
              </div>
              <div className="muted" style={{ fontSize: 12 }}>
                {fmtDate(result.start, intraday)} → {fmtDate(result.end, intraday)}
              </div>
            </div>
            <CompareChart result={result} />
            <ExplainPanel paragraphs={result.explanations} />
          </div>

          <div className="panel">
            <div className="panel-head">
              <div className="panel-title" style={{ margin: 0 }}>
                Metrics — beta and correlation against {result.benchmark}
              </div>
              <button
                type="button"
                className="btn ghost"
                onClick={runForecasts}
                disabled={forecasting}
              >
                {forecasting ? 'Running Kronos…' : 'Run Kronos on all'}
              </button>
            </div>
            <CompareTable result={result} forecasts={forecasts} benchmark={result.benchmark} />
            <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
              Forecasts are opt-in because each one runs the model and they are served one at a
              time. Open a symbol in Analyze for its full forecast and hold-out score.
            </p>
          </div>

          <div className="panel">
            <div className="panel-title">Correlation of returns</div>
            <CorrelationMatrix correlations={result.correlations} />
          </div>
        </>
      )}
    </div>
  )
}
