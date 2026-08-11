import { fmtMoney, fmtPct, signalTone } from '../utils'

export default function SignalCard({ result }) {
  const { signal, stats, meta, params, interval_label } = result
  const tone = signalTone(signal.action)
  const currency = meta.currency

  return (
    <div className="panel">
      <div className="panel-title">
        Kronos verdict — {params.horizon} {interval_label.toLowerCase()} bars ahead
      </div>
      <div className="signal">
        <div className={`badge ${tone}`}>{signal.action}</div>
        <div className="meter">
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
            <span className="muted">Confidence</span>
            <span>{signal.confidence}%</span>
          </div>
          <div className="meter-track">
            <div className="meter-fill" style={{ width: `${signal.confidence}%` }} />
          </div>
        </div>
      </div>

      <div className="stats" style={{ marginBottom: 14 }}>
        <div className="stat">
          <div className="k">Now</div>
          <div className="v">{fmtMoney(stats.last_close, currency)}</div>
        </div>
        <div className="stat">
          <div className="k">Median target</div>
          <div className={`v ${stats.median_return_pct >= 0 ? 'pos' : 'neg'}`}>
            {fmtMoney(stats.median_close, currency)}
          </div>
        </div>
        <div className="stat">
          <div className="k">Expected move</div>
          <div className={`v ${stats.expected_return_pct >= 0 ? 'pos' : 'neg'}`}>
            {fmtPct(stats.expected_return_pct)}
          </div>
        </div>
        <div className="stat">
          <div className="k">P(up)</div>
          <div className="v">{Math.round(stats.prob_up * 100)}%</div>
        </div>
      </div>

      <ul className="rationale">
        {signal.rationale.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
    </div>
  )
}
