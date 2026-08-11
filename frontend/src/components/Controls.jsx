import { useState } from 'react'
import AddToWatchlist from './AddToWatchlist'
import InfoTip from './InfoTip'
import { rememberSymbol, recentSymbols } from '../recent'

const EXAMPLES = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'SPY', 'BTC-USD', 'RELIANCE.NS']

/**
 * Presets, not raw numbers, are how most people should pick a configuration.
 * The lookback values come from the walk-forward table in the README: 64 bars
 * scored best, 128 is the default, and long windows degrade badly.
 */
const PRESETS = [
  { id: 'conservative', label: 'Conservative', lookback: 64, horizon: 5, paths: 24,
    hint: 'Shortest context, which scored best in walk-forward testing.' },
  { id: 'balanced', label: 'Balanced', lookback: 128, horizon: 10, paths: 24,
    hint: 'The default: a fortnight ahead from half a year of context.' },
  { id: 'exploratory', label: 'Exploratory', lookback: 256, horizon: 20, paths: 32,
    hint: 'Long context and horizon. Expect mean-reversion artefacts.' },
]

export default function Controls({ form, setForm, onSubmit, busy, config, modelState }) {
  const [advanced, setAdvanced] = useState(false)

  const set = (k) => (e) => {
    const el = e.target
    const value = el.type === 'checkbox' ? el.checked : el.type === 'number' ? Number(el.value) : el.value
    setForm((f) => ({ ...f, [k]: value }))
  }

  const limits = config?.limits ?? { max_lookback: 512, max_horizon: 120, max_paths: 64 }
  const warnLookback = form.lookback > (config?.lookback_warn_above ?? 200) && form.interval === '1d'
  const activePreset = PRESETS.find(
    (p) => p.lookback === form.lookback && p.horizon === form.horizon,
  )
  const modelBusy = modelState === 'loading' || modelState === 'connecting'
  const recent = recentSymbols()

  const submit = (e) => {
    e.preventDefault()
    rememberSymbol(form.symbol)
    onSubmit()
  }

  return (
    <form className="panel" onSubmit={submit}>
      <div className="controls">
        <div className="field">
          <label htmlFor="symbol">Ticker</label>
          <div className="symbol-row">
            <input
              id="symbol"
              className="symbol"
              value={form.symbol}
              onChange={set('symbol')}
              placeholder="AAPL"
              autoComplete="off"
              spellCheck="false"
              list="recent-symbols"
              required
            />
            {recent.length > 0 && (
              <datalist id="recent-symbols">
                {recent.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            )}
            <AddToWatchlist symbol={form.symbol} />
          </div>
        </div>

        <div className="field">
          <label htmlFor="interval">Interval</label>
          <select id="interval" value={form.interval} onChange={set('interval')}>
            {(config?.intervals ?? [{ value: '1d', label: 'Daily' }]).map((i) => (
              <option key={i.value} value={i.value}>
                {i.label}
              </option>
            ))}
          </select>
        </div>

        <button className="btn" type="submit" disabled={busy || modelBusy}>
          {busy ? 'Forecasting…' : modelBusy ? 'Loading model…' : 'Evaluate'}
        </button>
      </div>

      <div className="examples">
        <span>Presets:</span>
        {PRESETS.map((p) => (
          <button
            key={p.id}
            type="button"
            className={`chip ${activePreset?.id === p.id ? 'active' : ''}`}
            aria-pressed={activePreset?.id === p.id}
            title={p.hint}
            onClick={() =>
              setForm((f) => ({ ...f, lookback: p.lookback, horizon: p.horizon, paths: p.paths }))
            }
          >
            {p.label}
          </button>
        ))}
        <button
          type="button"
          className="chip"
          aria-expanded={advanced}
          aria-controls="advanced-fields"
          onClick={() => setAdvanced((v) => !v)}
        >
          {advanced ? '▾' : '▸'} Advanced
        </button>

        <span className="examples-symbols">
          <span>Try:</span>
          {EXAMPLES.map((s) => (
            <button
              key={s}
              type="button"
              className="chip"
              onClick={() => setForm((f) => ({ ...f, symbol: s }))}
            >
              {s}
            </button>
          ))}
        </span>
      </div>

      {advanced && (
        <div className="advanced" id="advanced-fields">
          <div className="field">
            <label htmlFor="lookback" style={warnLookback ? { color: 'var(--warn)' } : undefined}>
              Lookback
              <InfoTip
                text="Bars of history fed to the model. Walk-forward testing on daily equities found long windows degrade badly — the model z-scores each window and mean-reverts from stretched ones."
                label="lookback"
              />
            </label>
            <input
              id="lookback"
              type="number"
              min="64"
              max={limits.max_lookback}
              value={form.lookback}
              onChange={set('lookback')}
            />
          </div>

          <div className="field">
            <label htmlFor="horizon">Horizon</label>
            <input
              id="horizon"
              type="number"
              min="1"
              max={limits.max_horizon}
              value={form.horizon}
              onChange={set('horizon')}
            />
          </div>

          <div className="field">
            <label htmlFor="paths">
              Paths
              <InfoTip
                text="How many independent futures to sample. More paths give a smoother distribution and a slower forecast."
                label="paths"
              />
            </label>
            <input
              id="paths"
              type="number"
              min="1"
              max={limits.max_paths}
              value={form.paths}
              onChange={set('paths')}
            />
          </div>

          <div className="field">
            <label htmlFor="temperature">Temperature</label>
            <input
              id="temperature"
              type="number"
              min="0.1"
              max="2"
              step="0.1"
              value={form.temperature}
              onChange={set('temperature')}
            />
          </div>

          <div className="field">
            <label htmlFor="top_p">Top-p</label>
            <input
              id="top_p"
              type="number"
              min="0.1"
              max="1"
              step="0.05"
              value={form.top_p}
              onChange={set('top_p')}
            />
          </div>

          <div className="field">
            <label htmlFor="seed">Seed</label>
            <input
              id="seed"
              type="number"
              min="0"
              value={form.seed ?? ''}
              placeholder="random"
              onChange={(e) =>
                setForm((f) => ({ ...f, seed: e.target.value === '' ? null : Number(e.target.value) }))
              }
            />
          </div>

          <div className="field checkbox">
            <label htmlFor="backtest">
              <input
                id="backtest"
                type="checkbox"
                checked={form.backtest}
                onChange={set('backtest')}
              />
              Hold-out backtest
              <InfoTip
                text="Withholds the most recent bars, forecasts them from the bars before, and scores the result against reality. Roughly doubles runtime and is the only honest check on the forecast."
                label="the hold-out backtest"
              />
            </label>
          </div>
        </div>
      )}

      {warnLookback && (
        <div className="notice" style={{ marginTop: 12 }}>
          A {form.lookback}-bar daily lookback is in the range that scored worst in walk-forward
          testing. 64–128 bars did markedly better.
        </div>
      )}
    </form>
  )
}
