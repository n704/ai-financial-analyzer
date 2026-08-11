import { useEffect, useRef } from 'react'
import { LineStyle } from 'lightweight-charts'
import { addLine, createBaseChart } from '../charts'
import { useThemeVersion } from '../hooks/useThemeVersion'
import { toUnix, fmtNum } from '../utils'

/** Scores the model on bars it did not see: forecast vs what actually happened. */
export default function BacktestPanel({ backtest, intraday }) {
  const holder = useRef(null)
  const themeVersion = useThemeVersion()

  useEffect(() => {
    if (!holder.current || !backtest) return
    const { chart, colors, dispose } = createBaseChart(holder.current, { height: 200, intraday })

    const series = (key, options) =>
      addLine(chart, backtest.series.map((p) => ({ time: toUnix(p.time), value: p[key] })), options)

    series('p90', { color: colors.bound, lineWidth: 1, lineStyle: LineStyle.Dashed })
    series('p10', { color: colors.bound, lineWidth: 1, lineStyle: LineStyle.Dashed })
    series('predicted', { color: colors.median, lastValueVisible: true })
    series('actual', { color: colors.actual, lastValueVisible: true })
    chart.timeScale().fitContent()

    return dispose
  }, [backtest, intraday, themeVersion])

  if (!backtest) return null

  const beat = backtest.beats_naive
  return (
    <div className="panel">
      <div className="panel-title">Hold-out check — last {backtest.bars} bars withheld</div>
      <div className="verdict">
        <strong className={beat ? 'pos' : 'neg'}>
          {beat ? 'Beat the flat-price baseline' : 'Did not beat the flat-price baseline'}
        </strong>{' '}
        <span className="muted">
          — the model was given only the bars before this window, then scored against reality.
        </span>
      </div>
      <div className="stats" style={{ marginBottom: 14 }}>
        <div className="stat">
          <div className="k">Mean abs. error</div>
          <div className={`v ${beat ? 'pos' : 'neg'}`}>{fmtNum(backtest.mape_pct)}%</div>
        </div>
        <div className="stat">
          <div className="k">Baseline (no change)</div>
          <div className="v muted">{fmtNum(backtest.naive_mape_pct)}%</div>
        </div>
        <div className="stat">
          <div className="k">Bar direction hits</div>
          <div className="v">{fmtNum(backtest.directional_hit_rate_pct, 0)}%</div>
        </div>
        <div className="stat">
          <div className="k">p10–p90 coverage</div>
          <div className="v">{fmtNum(backtest.band_coverage_pct, 0)}%</div>
        </div>
        <div className="stat">
          <div className="k">End direction</div>
          <div className={`v ${backtest.terminal_direction_correct ? 'pos' : 'neg'}`}>
            {backtest.terminal_direction_correct ? 'Correct' : 'Wrong'}
          </div>
        </div>
      </div>
      <div className="chart" ref={holder} />
      <div className="legend">
        <span><i className="swatch actual" />Actual</span>
        <span><i className="swatch median" />Forecast median</span>
        <span><i className="swatch bound dashed" />p10 / p90</span>
      </div>
    </div>
  )
}
