import { createChart, ColorType, LineSeries } from 'lightweight-charts'
import { chartColors } from './chartTheme'

/**
 * One lightweight-charts instance configured the way this app always wants it:
 * transparent background, themed grid and borders, and a ResizeObserver that
 * keeps the canvas the width of its container.
 *
 * Returns `{ chart, colors, dispose }`. Always call `dispose` from the effect's
 * cleanup — it tears down the observer before removing the chart, in that
 * order, so a resize can never fire against a destroyed chart.
 */
export function createBaseChart(container, { height = 320, intraday = false, ...overrides } = {}) {
  const colors = chartColors()

  const chart = createChart(container, {
    height,
    layout: {
      background: { type: ColorType.Solid, color: 'transparent' },
      textColor: colors.text,
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: colors.grid },
      horzLines: { color: colors.grid },
    },
    rightPriceScale: { borderColor: colors.border },
    timeScale: {
      borderColor: colors.border,
      timeVisible: intraday,
      secondsVisible: false,
    },
    crosshair: { mode: 1 },
    localization: { locale: undefined },
    ...overrides,
  })

  const resize = () => chart.applyOptions({ width: container.clientWidth })
  const observer = new ResizeObserver(resize)
  observer.observe(container)
  resize()

  return {
    chart,
    colors,
    dispose() {
      observer.disconnect()
      chart.remove()
    },
  }
}

/** Adds a line series with the defaults every overlay in this app wants. */
export function addLine(chart, data, options = {}) {
  const series = chart.addSeries(LineSeries, {
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
    ...options,
  })
  series.setData(data)
  return series
}
