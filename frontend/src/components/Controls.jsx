const EXAMPLES = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'SPY', 'BTC-USD', 'RELIANCE.NS']

export default function Controls({ form, setForm, onSubmit, busy, config }) {
  const set = (k) => (e) => {
    const el = e.target
    const value = el.type === 'checkbox' ? el.checked : el.type === 'number' ? Number(el.value) : el.value
    setForm((f) => ({ ...f, [k]: value }))
  }

  const limits = config?.limits ?? { max_lookback: 512, max_horizon: 120, max_paths: 64 }
  const warnLookback = form.lookback > (config?.lookback_warn_above ?? 200) && form.interval === '1d'

  return (
    <form
      className="panel"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit()
      }}
    >
      <div className="controls">
        <div className="field">
          <label htmlFor="symbol">Ticker</label>
          <input
            id="symbol"
            className="symbol"
            value={form.symbol}
            onChange={set('symbol')}
            placeholder="AAPL"
            autoComplete="off"
            spellCheck="false"
            required
          />
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

        <div className="field">
          <label htmlFor="lookback" style={warnLookback ? { color: 'var(--warn)' } : undefined}>
            Lookback
          </label>
          <input
            id="lookback"
            type="number"
            min="64"
            max={limits.max_lookback}
            step="16"
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
          <label htmlFor="paths">Paths</label>
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
          <label htmlFor="temperature">Temp</label>
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

        <button className="btn" type="submit" disabled={busy}>
          {busy ? 'Forecasting…' : 'Evaluate'}
        </button>
      </div>

      <div className="examples">
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
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 14, alignItems: 'center' }}>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}>
            <input type="checkbox" checked={form.backtest} onChange={set('backtest')} />
            Hold-out backtest
          </label>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            Seed
            <input
              type="number"
              min="0"
              value={form.seed ?? ''}
              onChange={(e) =>
                setForm((f) => ({ ...f, seed: e.target.value === '' ? null : Number(e.target.value) }))
              }
              placeholder="random"
              style={{ width: 90, padding: '4px 8px', background: 'var(--panel-2)', border: '1px solid var(--line)', borderRadius: 6 }}
            />
          </label>
        </span>
      </div>
    </form>
  )
}
