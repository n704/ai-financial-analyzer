import { beforeEach, describe, expect, it, vi } from 'vitest'

// lightweight-charts draws to a real canvas, which jsdom does not implement.
// Mocking it keeps these tests about *our* wiring: sizing, theming, teardown.
const chartInstance = {
  applyOptions: vi.fn(),
  addSeries: vi.fn(() => ({ setData: vi.fn() })),
  remove: vi.fn(),
  timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
  priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
}
const createChart = vi.fn(() => chartInstance)

vi.mock('lightweight-charts', () => ({
  createChart: (...args) => createChart(...args),
  ColorType: { Solid: 'solid' },
  LineSeries: 'LineSeries',
  CandlestickSeries: 'CandlestickSeries',
  HistogramSeries: 'HistogramSeries',
  LineStyle: { Dashed: 2 },
  createSeriesMarkers: vi.fn(),
}))

const { addLine, createBaseChart } = await import('../charts')

const observed = []
class SpyResizeObserver {
  constructor(cb) {
    this.cb = cb
    observed.push(this)
  }
  observe(el) {
    this.target = el
  }
  disconnect() {
    this.disconnected = true
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  observed.length = 0
  globalThis.ResizeObserver = SpyResizeObserver
})

const container = () => {
  const el = document.createElement('div')
  Object.defineProperty(el, 'clientWidth', { value: 800, configurable: true })
  document.body.appendChild(el)
  return el
}

describe('createBaseChart', () => {
  it('passes the requested height and intraday time axis through', () => {
    createBaseChart(container(), { height: 200, intraday: true })
    const options = createChart.mock.calls[0][1]
    expect(options.height).toBe(200)
    expect(options.timeScale.timeVisible).toBe(true)
  })

  it('themes the chart from the CSS tokens rather than literals', () => {
    document.documentElement.style.setProperty('--grid', '#010203')
    createBaseChart(container(), {})
    expect(createChart.mock.calls[0][1].grid.vertLines.color).toBe('#010203')
    document.documentElement.style.cssText = ''
  })

  it('keeps the background transparent so the panel shows through', () => {
    createBaseChart(container(), {})
    expect(createChart.mock.calls[0][1].layout.background.color).toBe('transparent')
  })

  it('lets callers override the defaults', () => {
    createBaseChart(container(), { rightPriceScale: { scaleMargins: { top: 0.5, bottom: 0.1 } } })
    expect(createChart.mock.calls[0][1].rightPriceScale.scaleMargins.top).toBe(0.5)
  })

  it('sizes the chart to its container immediately', () => {
    createBaseChart(container(), {})
    expect(chartInstance.applyOptions).toHaveBeenCalledWith({ width: 800 })
  })

  it('observes the container for resizes', () => {
    const el = container()
    createBaseChart(el, {})
    expect(observed[0].target).toBe(el)
  })

  it('re-applies the width when the observer fires', () => {
    const el = container()
    createBaseChart(el, {})
    chartInstance.applyOptions.mockClear()
    Object.defineProperty(el, 'clientWidth', { value: 400, configurable: true })
    observed[0].cb()
    expect(chartInstance.applyOptions).toHaveBeenCalledWith({ width: 400 })
  })

  it('dispose disconnects the observer before removing the chart', () => {
    const order = []
    chartInstance.remove.mockImplementation(() => order.push('remove'))
    const { dispose } = createBaseChart(container(), {})
    observed[0].disconnect = () => order.push('disconnect')
    dispose()
    expect(order).toEqual(['disconnect', 'remove'])
  })
})

describe('addLine', () => {
  it('applies the shared line defaults', () => {
    const { chart } = createBaseChart(container(), {})
    addLine(chart, [{ time: 1, value: 2 }])
    const [type, options] = chart.addSeries.mock.calls.at(-1)
    expect(type).toBe('LineSeries')
    expect(options).toMatchObject({ lineWidth: 2, priceLineVisible: false })
  })

  it('lets the caller override them', () => {
    const { chart } = createBaseChart(container(), {})
    addLine(chart, [], { lineWidth: 1, color: '#fff' })
    const options = chart.addSeries.mock.calls.at(-1)[1]
    expect(options).toMatchObject({ lineWidth: 1, color: '#fff' })
  })

  it('sets the data on the series it created', () => {
    const setData = vi.fn()
    chartInstance.addSeries.mockReturnValueOnce({ setData })
    const { chart } = createBaseChart(container(), {})
    const data = [{ time: 1, value: 2 }]
    addLine(chart, data)
    expect(setData).toHaveBeenCalledWith(data)
  })
})
