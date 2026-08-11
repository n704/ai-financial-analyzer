import { useEffect, useRef, useState } from 'react'
import * as api from '../api'
import { addLine, createBaseChart } from '../charts'
import { seriesColor } from '../chartTheme'
import { useThemeVersion } from '../hooks/useThemeVersion'
import { fmtNum, fmtPct, toUnix } from '../utils'
import ExplainPanel from './ExplainPanel'
import InfoTip from './InfoTip'

function RelativeStrengthChart({ points, height = 150 }) {
  const holder = useRef(null)
  const themeVersion = useThemeVersion()

  useEffect(() => {
    if (!holder.current || !points?.length) return
    const { chart, colors, dispose } = createBaseChart(holder.current, { height })
    addLine(
      chart,
      points.map((p) => ({ time: toUnix(p.time), value: p.value })),
      { color: colors.median, lineWidth: 2, lastValueVisible: true },
    )
    // 100 is the line between keeping up with the benchmark and not.
    addLine(
      chart,
      points.map((p) => ({ time: toUnix(p.time), value: 100 })),
      { color: colors.bound, lineWidth: 1, lineStyle: 2 },
    )
    chart.timeScale().fitContent()
    return dispose
  }, [points, height, themeVersion])

  return <div className="chart" ref={holder} />
}

function OverlayChart({ result, height = 240 }) {
  const holder = useRef(null)
  const themeVersion = useThemeVersion()

  useEffect(() => {
    if (!holder.current || !result?.symbols?.length) return
    const { chart, dispose } = createBaseChart(holder.current, {
      height,
      intraday: result.interval !== '1d',
    })
    result.symbols.forEach((row, i) => {
      addLine(
        chart,
        row.series.map((p) => ({ time: toUnix(p.time), value: p.value })),
        { color: seriesColor(i), lineWidth: row.symbol === result.symbol ? 2 : 1, lastValueVisible: true },
      )
    })
    chart.timeScale().fitContent()
    return dispose
  }, [result, height, themeVersion])

  return <div className="chart" ref={holder} />
}

/** How one stock has done against its sector ETF and the broad market. */
export default function SectorPanel({ symbol, interval = '1d', bars = 180 }) {
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    setBusy(true)
    setError(null)
    api
      .getSector(symbol, interval, bars)
      .then((r) => !cancelled && setResult(r))
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setBusy(false))
    return () => { cancelled = true }
  }, [symbol, interval, bars])

  if (busy && !result) {
    return (
      <div className="panel">
        <div className="panel-title">Sector comparison</div>
        <div className="skeleton" style={{ height: 140 }}>
          <div className="spinner" />
          <div>Comparing {symbol} with its sector…</div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="panel">
        <div className="panel-title">Sector comparison</div>
        <div className="notice">{error}</div>
      </div>
    )
  }

  if (!result) return null

  const rel = result.relative ?? {}
  const excess = rel.excess_return_pct
  const title = result.sector_etf
    ? `${result.symbol} vs ${result.sector} (${result.sector_etf})`
    : `${result.symbol} vs the market`

  return (
    <div className="panel">
      <div className="panel-head">
        <div className="panel-title" style={{ margin: 0 }}>{title}</div>
        <div className="muted" style={{ fontSize: 12 }}>
          {result.bars} shared {result.interval_label.toLowerCase()} bars
        </div>
      </div>

      {result.caveat && <div className="notice" style={{ marginBottom: 12 }}>{result.caveat}</div>}

      {rel.benchmark && (
        <div className="stats" style={{ marginBottom: 14 }}>
          <div className="stat">
            <div className="k">{result.symbol} return</div>
            <div className={`v ${rel.stock_return_pct >= 0 ? 'pos' : 'neg'}`}>
              {fmtPct(rel.stock_return_pct)}
            </div>
          </div>
          <div className="stat">
            <div className="k">{rel.benchmark} return</div>
            <div className={`v ${rel.benchmark_return_pct >= 0 ? 'pos' : 'neg'}`}>
              {fmtPct(rel.benchmark_return_pct)}
            </div>
          </div>
          <div className="stat">
            <div className="k">
              vs benchmark
              <InfoTip
                text={`Simple difference between the two returns. It ignores how sensitive ${result.symbol} is to ${rel.benchmark} — see alpha.`}
                label="return against the benchmark"
              />
            </div>
            <div className={`v ${excess >= 0 ? 'pos' : 'neg'}`}>{fmtPct(excess)}</div>
          </div>
          <div className="stat">
            <div className="k">
              Alpha
              <InfoTip
                text={`Return left after removing the part explained by beta. Beating a rising sector while being twice as sensitive to it is leverage, not skill — alpha is what remains.`}
                label="alpha"
              />
            </div>
            <div className={`v ${rel.alpha_pct >= 0 ? 'pos' : 'neg'}`}>{fmtPct(rel.alpha_pct)}</div>
          </div>
          <div className="stat">
            <div className="k">
              Beta
              <InfoTip
                text={`How far ${result.symbol} tends to move when ${rel.benchmark} moves 1%.`}
                label="beta"
              />
            </div>
            <div className="v">{fmtNum(rel.beta)}</div>
          </div>
          <div className="stat">
            <div className="k">Correlation</div>
            <div className="v">{fmtNum(rel.correlation)}</div>
          </div>
        </div>
      )}

      <OverlayChart result={result} />
      <div className="legend">
        {result.symbols.map((row, i) => (
          <span key={row.symbol}>
            <i className="swatch" style={{ borderTopColor: seriesColor(i) }} />
            {row.symbol}
            {row.symbol === result.sector_etf && result.sector_etf_name
              ? ` · ${result.sector_etf_name}`
              : ''}
          </span>
        ))}
        <span className="muted">Indexed to 100 at the start of the window</span>
      </div>

      {result.relative_strength?.length > 0 && (
        <>
          <div className="panel-title" style={{ marginTop: 16 }}>
            Relative strength — {result.symbol} ÷ {rel.benchmark}
            <InfoTip
              text="The ratio of the two rebased lines. Rising means the stock is gaining on its benchmark, falling means it is losing ground, flat means it is simply riding it."
              label="relative strength"
            />
          </div>
          <RelativeStrengthChart points={result.relative_strength} />
        </>
      )}

      <ExplainPanel paragraphs={result.explanations} title="What the sector comparison shows" />
    </div>
  )
}
