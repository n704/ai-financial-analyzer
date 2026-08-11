import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({ compare: vi.fn(), compareForecast: vi.fn() }))
// The chart needs a canvas; this suite is about the view's orchestration.
vi.mock('../components/CompareChart', () => ({ default: () => <div data-testid="chart" /> }))

const api = await import('../api')
const { default: CompareView } = await import('../views/CompareView')

// Both tables carry a row per symbol, so every row query is scoped to one.
const metrics = () => within(screen.getByRole('table', { name: 'Comparison metrics' }))
const metricRow = (symbol) => within(metrics().getByRole('row', { name: new RegExp(symbol) }))

const row = (symbol) => ({
  symbol,
  name: `${symbol} Inc.`,
  currency: 'USD',
  last_close: 100,
  technicals: { rsi_14: 50 },
  metrics: {
    total_return_pct: 5,
    annualized_vol_pct: 20,
    return_per_unit_risk: 0.25,
    max_drawdown_pct: -5,
    beta_vs_benchmark: 1,
    correlation_vs_benchmark: 1,
  },
  series: [{ time: '2026-01-05T00:00:00-05:00', value: 100 }],
})

const RESULT = {
  symbols: [row('AAPL'), row('MSFT')],
  benchmark: 'AAPL',
  interval: '1d',
  interval_label: 'Daily',
  bars: 120,
  start: '2026-01-05T00:00:00-05:00',
  end: '2026-06-30T00:00:00-04:00',
  correlations: { symbols: ['AAPL', 'MSFT'], values: [[1, 0.8], [0.8, 1]] },
  unavailable: [],
  explanations: [{ title: 'What the chart shows', body: 'Every line starts at 100.' }],
}

beforeEach(() => {
  vi.clearAllMocks()
  api.compare.mockResolvedValue(RESULT)
})

describe('CompareView', () => {
  it('compares on mount using the URL symbols', async () => {
    render(<CompareView symbols="TSLA,F" />)
    await waitFor(() => expect(api.compare).toHaveBeenCalledWith(['TSLA', 'F'], '1d', 180))
  })

  it('renders the chart, table and correlation matrix', async () => {
    render(<CompareView />)
    expect(await screen.findByTestId('chart')).toBeInTheDocument()
    expect(metrics().getByRole('row', { name: /AAPL/ })).toBeInTheDocument()
    expect(screen.getByRole('table', { name: 'Correlation of returns' })).toBeInTheDocument()
  })

  it('shows the explanation from the API', async () => {
    render(<CompareView />)
    expect(await screen.findByText('Every line starts at 100.')).toBeInTheDocument()
  })

  it('deduplicates and caps the symbol list', async () => {
    render(<CompareView symbols="aapl,AAPL,msft" />)
    await waitFor(() => expect(api.compare).toHaveBeenCalledWith(['AAPL', 'MSFT'], '1d', 180))
  })

  it('will not compare fewer than two symbols', async () => {
    render(<CompareView symbols="AAPL" />)
    await waitFor(() => expect(screen.getByText(/at least two symbols/)).toBeInTheDocument())
    expect(api.compare).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Compare' })).toBeDisabled()
  })

  it('records the symbols in the URL when comparing', async () => {
    const onNavigate = vi.fn()
    render(<CompareView symbols="AAPL,MSFT" onNavigate={onNavigate} />)
    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith('AAPL,MSFT'))
  })

  it('applies a preset', async () => {
    render(<CompareView symbols="AAPL,MSFT" />)
    await screen.findByTestId('chart')
    await userEvent.click(screen.getByRole('button', { name: 'Index vs gold' }))
    await userEvent.click(screen.getByRole('button', { name: 'Compare' }))
    await waitFor(() => expect(api.compare).toHaveBeenLastCalledWith(['SPY', 'GLD'], '1d', 180))
  })

  it('submits with the default bar count', async () => {
    // Regression: `min=32 step=10` made the default 180 fail HTML constraint
    // validation, and a browser silently refuses to submit an invalid form —
    // clicking Compare did nothing at all.
    render(<CompareView symbols="AAPL,MSFT" />)
    await screen.findByTestId('chart')
    expect(screen.getByLabelText('Bars')).toBeValid()

    await userEvent.click(screen.getByRole('button', { name: 'Compare' }))
    await waitFor(() => expect(api.compare).toHaveBeenCalledTimes(2))
  })

  it('honours an edited bar count', async () => {
    render(<CompareView symbols="AAPL,MSFT" />)
    await screen.findByTestId('chart')
    const bars = screen.getByLabelText('Bars')
    await userEvent.clear(bars)
    await userEvent.type(bars, '365')
    await userEvent.click(screen.getByRole('button', { name: 'Compare' }))
    await waitFor(() => expect(api.compare).toHaveBeenLastCalledWith(['AAPL', 'MSFT'], '1d', 365))
  })

  it('surfaces a failed comparison', async () => {
    api.compare.mockRejectedValue(new Error('Not enough symbols resolved to compare.'))
    render(<CompareView symbols="AAPL,ZZZZ" />)
    expect(await screen.findByText(/Not enough symbols resolved/)).toBeInTheDocument()
  })

  it('warns about symbols that were dropped', async () => {
    api.compare.mockResolvedValue({
      ...RESULT,
      unavailable: [{ symbol: 'ZZZZ', reason: 'No market data.' }],
    })
    render(<CompareView symbols="AAPL,MSFT,ZZZZ" />)
    expect(await screen.findByText(/ZZZZ: No market data./)).toBeInTheDocument()
  })

  it('does not run forecasts until asked', async () => {
    render(<CompareView />)
    await screen.findByTestId('chart')
    expect(api.compareForecast).not.toHaveBeenCalled()
  })

  it('runs forecasts one symbol at a time and fills each column in', async () => {
    const order = []
    api.compareForecast.mockImplementation(async ({ symbol }) => {
      order.push(symbol)
      return { symbol, signal: { action: 'BUY' }, stats: { prob_up: 0.7 } }
    })

    render(<CompareView />)
    await screen.findByTestId('chart')
    await userEvent.click(screen.getByRole('button', { name: /Run Kronos/ }))

    await waitFor(() => expect(order).toEqual(['AAPL', 'MSFT']))
    await waitFor(() => expect(metricRow('AAPL').getByText('BUY')).toBeInTheDocument())
  })

  it('keeps going when one symbol’s forecast fails', async () => {
    api.compareForecast.mockImplementation(async ({ symbol }) => {
      if (symbol === 'AAPL') throw new Error('Model is not loaded')
      return { symbol, signal: { action: 'HOLD' }, stats: { prob_up: 0.5 } }
    })

    render(<CompareView />)
    await screen.findByTestId('chart')
    await userEvent.click(screen.getByRole('button', { name: /Run Kronos/ }))

    await waitFor(() => expect(metricRow('AAPL').getByText('failed')).toBeInTheDocument())
    expect(metricRow('MSFT').getByText('HOLD')).toBeInTheDocument()
  })

  it('passes the chosen interval through to both endpoints', async () => {
    api.compareForecast.mockResolvedValue({ signal: { action: 'HOLD' }, stats: { prob_up: 0.5 } })
    render(
      <CompareView config={{ intervals: [{ value: '1d', label: 'Daily' }, { value: '1h', label: 'Hourly' }] }} />,
    )
    await screen.findByTestId('chart')

    await userEvent.selectOptions(screen.getByLabelText('Interval'), '1h')
    await userEvent.click(screen.getByRole('button', { name: 'Compare' }))
    await waitFor(() => expect(api.compare).toHaveBeenLastCalledWith(['AAPL', 'MSFT', 'NVDA'], '1h', 180))

    await userEvent.click(screen.getByRole('button', { name: /Run Kronos/ }))
    await waitFor(() =>
      expect(api.compareForecast).toHaveBeenCalledWith({ symbol: 'AAPL', interval: '1h' }),
    )
  })
})
