import { fmtMoney, fmtNum, fmtPct } from '../utils'

const Row = ({ k, v, tone }) => (
  <div className="row">
    <span className="k">{k}</span>
    <span className={`v ${tone ?? ''}`}>{v}</span>
  </div>
)

export function RiskPanel({ stats, currency }) {
  return (
    <div className="panel">
      <div className="panel-title">Distribution & risk</div>
      <div className="rows">
        <Row k="Outcome range (p10–p90)" v={`${fmtMoney(stats.close_p10, currency)} – ${fmtMoney(stats.close_p90, currency)}`} />
        <Row k="Return range (p10–p90)" v={`${fmtPct(stats.return_p10_pct)} … ${fmtPct(stats.return_p90_pct)}`} />
        <Row k="Path dispersion (1σ)" v={`${fmtNum(stats.dispersion_pct)}%`} />
        <Row k="Conviction (μ/σ)" v={fmtNum(stats.conviction)} tone={stats.conviction >= 0 ? 'pos' : 'neg'} />
        <Row k="Value at risk (5%)" v={fmtPct(stats.value_at_risk_5pct)} tone="neg" />
        <Row k="Expected shortfall (5%)" v={fmtPct(stats.expected_shortfall_5pct)} tone="neg" />
        <Row k="Max drawdown of median path" v={fmtPct(stats.max_drawdown_pct)} tone="neg" />
        <Row k="Forecast volatility (ann.)" v={`${fmtNum(stats.forecast_vol_annual * 100, 1)}%`} />
        <Row k="Paths simulated" v={stats.n_paths} />
      </div>
    </div>
  )
}

export function TechnicalsPanel({ technicals: t, currency }) {
  const rsiTone = t.rsi_14 == null ? '' : t.rsi_14 >= 70 ? 'neg' : t.rsi_14 <= 30 ? 'pos' : ''
  return (
    <div className="panel">
      <div className="panel-title">Price context</div>
      <div className="rows">
        <Row k="Last close" v={fmtMoney(t.last_close, currency)} />
        <Row k="SMA 20 / 50" v={`${fmtMoney(t.sma_20, currency)} / ${fmtMoney(t.sma_50, currency)}`} />
        <Row k="SMA 200" v={fmtMoney(t.sma_200, currency)} />
        <Row k="RSI (14)" v={fmtNum(t.rsi_14, 1)} tone={rsiTone} />
        <Row k="Realized vol (ann.)" v={t.realized_vol_annual == null ? '—' : `${fmtNum(t.realized_vol_annual * 100, 1)}%`} />
        <Row k="Period high / low" v={`${fmtMoney(t.period_high, currency)} / ${fmtMoney(t.period_low, currency)}`} />
        <Row k="From high / low" v={`${fmtPct(t.pct_from_high, 1)} / ${fmtPct(t.pct_from_low, 1)}`} />
      </div>
    </div>
  )
}
