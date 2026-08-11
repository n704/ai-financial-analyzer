import { useEffect, useRef } from 'react'
import { createChart, LineSeries, LineStyle, ColorType } from 'lightweight-charts'
import { toUnix, fmtNum } from '../utils'

/** Scores the model on bars it did not see: forecast vs what actually happened. */
export default function BacktestPanel({ backtest, intraday }) {
  const holder = useRef(null)

  useEffect(() => {
    if (!holder.current || !backtest) return
    const chart = createChart(holder.current, {
      height: 200,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#8b9bb4',
        attributionLogo: false,
      },
      grid: { vertLines: { color: '#1c2434' }, horzLines: { color: '#1c2434' } },
      rightPriceScale: { borderColor: '#253044' },
      timeScale: { borderColor: '#253044', timeVisible: intraday, secondsVisible: false },
    })

    const add = (key, options) => {
      const s = chart.addSeries(LineSeries, { lineWidth: 2, priceLineVisible: false, ...options })
      s.setData(backtest.series.map((p) => ({ time: toUnix(p.time), value: p[key] })))
    }
    add('p90', { color: '#7a8dab', lineWidth: 1, lineStyle: LineStyle.Dashed, lastValueVisible: false })
    add('p10', { color: '#7a8dab', lineWidth: 1, lineStyle: LineStyle.Dashed, lastValueVisible: false })
    add('predicted', { color: '#4c8dff' })
    add('actual', { color: '#e6edf7' })
    chart.timeScale().fitContent()

    const ro = new ResizeObserver(() => chart.applyOptions({ width: holder.current.clientWidth }))
    ro.observe(holder.current)
    chart.applyOptions({ width: holder.current.clientWidth })
    return () => {
      ro.disconnect()
      chart.remove()
    }
  }, [backtest, intraday])

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
        <span><i style={{ borderColor: '#e6edf7' }} />Actual</span>
        <span><i style={{ borderColor: '#4c8dff' }} />Forecast median</span>
        <span><i style={{ borderColor: '#7a8dab', borderTopStyle: 'dashed' }} />p10 / p90</span>
      </div>
    </div>
  )
}
