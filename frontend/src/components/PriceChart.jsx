import { useEffect, useRef } from 'react'
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  LineStyle,
  ColorType,
  createSeriesMarkers,
} from 'lightweight-charts'
import { toUnix } from '../utils'

const COLORS = {
  up: '#26a69a',
  down: '#ef5350',
  median: '#4c8dff',
  bound: '#7a8dab',
  path: 'rgba(76, 141, 255, 0.20)',
  grid: '#1c2434',
}

/** Candlestick history + Monte-Carlo forecast fan from Kronos. */
export default function PriceChart({ result, height = 420 }) {
  const holder = useRef(null)

  useEffect(() => {
    if (!holder.current || !result) return
    const intraday = result.interval !== '1d'

    const chart = createChart(holder.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#8b9bb4',
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: COLORS.grid },
        horzLines: { color: COLORS.grid },
      },
      rightPriceScale: { borderColor: '#253044', scaleMargins: { top: 0.08, bottom: 0.26 } },
      timeScale: {
        borderColor: '#253044',
        timeVisible: intraday,
        secondsVisible: false,
        rightOffset: 4,
      },
      crosshair: { mode: 1 },
      localization: { locale: undefined },
    })

    // --- history ---
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: COLORS.up,
      downColor: COLORS.down,
      wickUpColor: COLORS.up,
      wickDownColor: COLORS.down,
      borderVisible: false,
      priceLineVisible: false,
    })
    const hist = result.history.map((c) => ({
      time: toUnix(c.time),
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }))
    candles.setData(hist)

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
        color: c.close >= c.open ? 'rgba(38,166,154,0.35)' : 'rgba(239,83,80,0.35)',
      })),
    )
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.84, bottom: 0 }, visible: false })

    // --- forecast, anchored to the last real bar so the lines connect ---
    const lastBar = result.history[result.history.length - 1]
    const anchor = { time: toUnix(lastBar.time), value: lastBar.close }
    const line = (key, options) => {
      const s = chart.addSeries(LineSeries, {
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        ...options,
      })
      s.setData([anchor, ...result.forecast.band.map((b) => ({ time: toUnix(b.time), value: b[key] }))])
      return s
    }

    for (const path of result.forecast.sample_paths) {
      const s = chart.addSeries(LineSeries, {
        color: COLORS.path,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      s.setData([anchor, ...path.map((p) => ({ time: toUnix(p.time), value: p.value }))])
    }

    line('p90', { color: COLORS.bound, lineWidth: 1, lineStyle: LineStyle.Dashed })
    line('p10', { color: COLORS.bound, lineWidth: 1, lineStyle: LineStyle.Dashed })
    line('p50', { color: COLORS.median, lineWidth: 2, lastValueVisible: true })

    createSeriesMarkers(candles, [
      {
        time: toUnix(result.params.context_start),
        position: 'belowBar',
        color: '#8b9bb4',
        shape: 'arrowUp',
        text: `context (${result.params.lookback} bars)`,
      },
      {
        time: toUnix(lastBar.time),
        position: 'aboveBar',
        color: COLORS.median,
        shape: 'arrowDown',
        text: 'forecast →',
      },
    ])

    chart.timeScale().fitContent()

    const ro = new ResizeObserver(() => chart.applyOptions({ width: holder.current.clientWidth }))
    ro.observe(holder.current)
    chart.applyOptions({ width: holder.current.clientWidth })

    return () => {
      ro.disconnect()
      chart.remove()
    }
  }, [result, height])

  return (
    <>
      <div className="chart" ref={holder} />
      <div className="legend">
        <span><i style={{ borderColor: COLORS.median }} />Median forecast (p50)</span>
        <span><i style={{ borderColor: COLORS.bound, borderTopStyle: 'dashed' }} />p10 / p90 band</span>
        <span><i style={{ borderColor: 'rgba(76,141,255,0.6)' }} />Sampled Kronos paths</span>
      </div>
    </>
  )
}
