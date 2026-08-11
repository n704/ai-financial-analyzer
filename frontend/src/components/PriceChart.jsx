import { useEffect, useRef } from 'react'
import {
  CandlestickSeries,
  HistogramSeries,
  LineStyle,
  createSeriesMarkers,
} from 'lightweight-charts'
import { addLine, createBaseChart } from '../charts'
import { useThemeVersion } from '../hooks/useThemeVersion'
import { toUnix } from '../utils'

/** Candlestick history + Monte-Carlo forecast fan from Kronos. */
export default function PriceChart({ result, height = 420 }) {
  const holder = useRef(null)
  const themeVersion = useThemeVersion()

  useEffect(() => {
    if (!holder.current || !result) return
    const intraday = result.interval !== '1d'

    const { chart, colors, dispose } = createBaseChart(holder.current, {
      height,
      intraday,
      rightPriceScale: { scaleMargins: { top: 0.08, bottom: 0.26 } },
      timeScale: { timeVisible: intraday, secondsVisible: false, rightOffset: 4 },
    })

    // --- history ---
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: colors.up,
      downColor: colors.down,
      wickUpColor: colors.up,
      wickDownColor: colors.down,
      borderVisible: false,
      priceLineVisible: false,
    })
    candles.setData(
      result.history.map((c) => ({
        time: toUnix(c.time),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    )

    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: 'vol',
      priceFormat: { type: 'volume' },
      priceLineVisible: false,
      lastValueVisible: false,
    })
    volume.setData(
      result.history.map((c) => ({
        time: toUnix(c.time),
        value: c.volume ?? 0,
        color: c.close >= c.open ? colors.volumeUp : colors.volumeDown,
      })),
    )
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.84, bottom: 0 }, visible: false })

    // --- forecast, anchored to the last real bar so the lines connect ---
    const lastBar = result.history[result.history.length - 1]
    const anchor = { time: toUnix(lastBar.time), value: lastBar.close }
    const band = (key, options) =>
      addLine(
        chart,
        [anchor, ...result.forecast.band.map((b) => ({ time: toUnix(b.time), value: b[key] }))],
        options,
      )

    for (const path of result.forecast.sample_paths) {
      addLine(chart, [anchor, ...path.map((p) => ({ time: toUnix(p.time), value: p.value }))], {
        color: colors.path,
        lineWidth: 1,
      })
    }

    band('p90', { color: colors.bound, lineWidth: 1, lineStyle: LineStyle.Dashed })
    band('p10', { color: colors.bound, lineWidth: 1, lineStyle: LineStyle.Dashed })
    band('p50', { color: colors.median, lineWidth: 2, lastValueVisible: true })

    createSeriesMarkers(candles, [
      {
        time: toUnix(result.params.context_start),
        position: 'belowBar',
        color: colors.text,
        shape: 'arrowUp',
        text: `context (${result.params.lookback} bars)`,
      },
      {
        time: toUnix(lastBar.time),
        position: 'aboveBar',
        color: colors.median,
        shape: 'arrowDown',
        text: 'forecast →',
      },
    ])

    chart.timeScale().fitContent()
    return dispose
  }, [result, height, themeVersion])

  return (
    <>
      <div className="chart" ref={holder} />
      <div className="legend">
        <span><i className="swatch median" />Median forecast (p50)</span>
        <span><i className="swatch bound dashed" />p10 / p90 band</span>
        <span><i className="swatch path" />Sampled Kronos paths</span>
      </div>
    </>
  )
}
