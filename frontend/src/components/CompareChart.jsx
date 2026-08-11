import { useEffect, useRef } from 'react'
import { addLine, createBaseChart } from '../charts'
import { seriesColor } from '../chartTheme'
import { useThemeVersion } from '../hooks/useThemeVersion'
import { toUnix } from '../utils'

/** Every symbol rebased to 100 at the first shared bar, on one axis. */
export default function CompareChart({ result, height = 340 }) {
  const holder = useRef(null)
  const themeVersion = useThemeVersion()

  useEffect(() => {
    if (!holder.current || !result?.symbols?.length) return
    const intraday = result.interval !== '1d'
    const { chart, dispose } = createBaseChart(holder.current, { height, intraday })

    result.symbols.forEach((row, i) => {
      addLine(
        chart,
        row.series.map((p) => ({ time: toUnix(p.time), value: p.value })),
        { color: seriesColor(i), lineWidth: 2, lastValueVisible: true, title: row.symbol },
      )
    })

    chart.timeScale().fitContent()
    return dispose
  }, [result, height, themeVersion])

  return (
    <>
      <div className="chart" ref={holder} />
      <div className="legend">
        {result.symbols.map((row, i) => (
          <span key={row.symbol}>
            <i className="swatch" style={{ borderTopColor: seriesColor(i) }} />
            {row.symbol}
          </span>
        ))}
        <span className="muted">Indexed to 100 at the start of the window</span>
      </div>
    </>
  )
}
