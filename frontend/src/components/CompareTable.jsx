import { seriesColor } from '../chartTheme'
import { fmtMoney, fmtNum, fmtPct, signalTone } from '../utils'
import InfoTip from './InfoTip'

const pct = (v) => (v == null ? '—' : fmtPct(v))
const tone = (v) => (v == null ? 'muted' : v >= 0 ? 'pos' : 'neg')

/** Forecast cell: pending, failed, or a signal — one state per symbol. */
function ForecastCell({ state }) {
  if (!state) return <span className="muted">—</span>
  if (state.status === 'pending') return <span className="muted">running…</span>
  if (state.status === 'error') {
    return <span className="neg" title={state.error}>failed</span>
  }
  const { signal, stats } = state.data
  return (
    <span className={`badge inline ${signalTone(signal.action)}`}>
      {signal.action}
      <span className="muted"> {Math.round(stats.prob_up * 100)}% up</span>
    </span>
  )
}

export default function CompareTable({ result, forecasts, benchmark }) {
  return (
    <div className="table-scroll">
      <table className="table" aria-label="Comparison metrics">
        <thead>
          <tr>
            <th scope="col">Symbol</th>
            <th scope="col" className="num">Last</th>
            <th scope="col" className="num">Return</th>
            <th scope="col" className="num">
              Vol (ann.) <InfoTip term="realized_vol" label="annualised volatility" />
            </th>
            <th scope="col" className="num">
              Return / risk
              <InfoTip
                text="Total return divided by annualised volatility — how much move you got per unit of turbulence endured."
                label="return per unit of risk"
              />
            </th>
            <th scope="col" className="num">
              Max drawdown <InfoTip term="max_drawdown" label="max drawdown" />
            </th>
            <th scope="col" className="num">
              Beta
              <InfoTip
                text={`How far this symbol tends to move when ${benchmark} moves 1%. Above 1 means it amplifies the benchmark; below 1 means it damps it.`}
                label="beta"
              />
            </th>
            <th scope="col" className="num">
              Corr. <InfoTip
                text={`Correlation of daily returns with ${benchmark}. 1 means they move in lockstep, 0 means unrelated, −1 means opposite.`}
                label="correlation"
              />
            </th>
            <th scope="col" className="num">
              RSI <InfoTip term="rsi" label="RSI" />
            </th>
            <th scope="col">Kronos</th>
          </tr>
        </thead>
        <tbody>
          {result.symbols.map((row, i) => {
            const m = row.metrics
            return (
              <tr key={row.symbol}>
                <th scope="row" className="symbol-cell">
                  <span className="swatch-dot" style={{ background: seriesColor(i) }} />
                  {row.symbol}
                  {row.symbol === benchmark && <span className="tag">base</span>}
                  <div className="muted note">{row.name}</div>
                </th>
                <td className="num">{fmtMoney(row.last_close, row.currency)}</td>
                <td className={`num ${tone(m.total_return_pct)}`}>{pct(m.total_return_pct)}</td>
                <td className="num">{fmtNum(m.annualized_vol_pct, 1)}%</td>
                <td className={`num ${tone(m.return_per_unit_risk)}`}>
                  {fmtNum(m.return_per_unit_risk)}
                </td>
                <td className="num neg">{pct(m.max_drawdown_pct)}</td>
                <td className="num">{fmtNum(m.beta_vs_benchmark)}</td>
                <td className="num">{fmtNum(m.correlation_vs_benchmark)}</td>
                <td className="num">{fmtNum(row.technicals?.rsi_14, 0)}</td>
                <td>
                  <ForecastCell state={forecasts[row.symbol]} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
