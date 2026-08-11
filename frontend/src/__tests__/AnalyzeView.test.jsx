import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({
  analyze: vi.fn(),
  listWatchlists: vi.fn(),
  createWatchlist: vi.fn(),
  addSymbol: vi.fn(),
  getSector: vi.fn(),
}))
// Charts need a canvas; this suite is about the view's states.
vi.mock('../components/PriceChart', () => ({ default: () => <div data-testid="price-chart" /> }))
vi.mock('../components/BacktestPanel', () => ({ default: () => <div data-testid="backtest" /> }))
vi.mock('../components/SectorPanel', () => ({ default: () => <div data-testid="sector" /> }))

const api = await import('../api')
const { default: AnalyzeView } = await import('../views/AnalyzeView')

const RESULT = {
  symbol: 'AAPL',
  meta: { name: 'Apple Inc.', currency: 'USD', exchange: 'NasdaqGS' },
  interval: '1d',
  interval_label: 'Daily',
  params: {
    lookback: 128, horizon: 10, paths: 24,
    history_end: '2026-08-10T00:00:00-04:00',
    forecast_end: '2026-08-24T00:00:00-04:00',
    context_start: '2026-02-10T00:00:00-05:00',
  },
  history: [
    { time: '2026-08-07T00:00:00-04:00', open: 1, high: 1, low: 1, close: 100, volume: 1 },
    { time: '2026-08-10T00:00:00-04:00', open: 1, high: 1, low: 1, close: 102, volume: 1 },
  ],
  technicals: { last_close: 102, rsi_14: 55, realized_vol_annual: 0.25 },
  forecast: { band: [], sample_paths: [] },
  signal: { action: 'BUY', confidence: 70, rationale: ['Because.'] },
  stats: {
    last_close: 102, median_close: 105, expected_return_pct: 2.1, median_return_pct: 2.0,
    prob_up: 0.68, n_paths: 24, close_p10: 98, close_p90: 110, return_p10_pct: -4,
    return_p90_pct: 8, dispersion_pct: 4, conviction: 0.5, value_at_risk_5pct: -5,
    expected_shortfall_5pct: -6, max_drawdown_pct: -2, forecast_vol_annual: 0.3,
  },
  backtest: null,
  diagnostics: { caveats: [] },
  explanations: { forecast: [{ title: 'What the fan is', body: 'Sampled futures.' }], backtest: [] },
  timings_ms: { market_data: 120, forecast: 900 },
  disclaimer: 'Nothing here is financial advice.',
}

beforeEach(() => {
  vi.clearAllMocks()
  api.analyze.mockResolvedValue(RESULT)
  api.listWatchlists.mockResolvedValue([])
})

const evaluate = () => userEvent.click(screen.getByRole('button', { name: 'Evaluate' }))

describe('AnalyzeView', () => {
  it('invites the reader in before anything has run', () => {
    render(<AnalyzeView modelState="ready" />)
    expect(screen.getByText(/Pick a ticker and hit Evaluate/)).toBeInTheDocument()
  })

  it('shows a skeleton on the very first run', async () => {
    api.analyze.mockReturnValue(new Promise(() => {}))
    render(<AnalyzeView modelState="ready" />)
    await evaluate()
    expect(screen.getByText(/Sampling 24 Kronos futures/)).toBeInTheDocument()
  })

  it('renders the result', async () => {
    render(<AnalyzeView modelState="ready" />)
    await evaluate()
    expect(await screen.findByTestId('price-chart')).toBeInTheDocument()
    expect(screen.getByText('BUY')).toBeInTheDocument()
  })

  it('shows the forecast explanation', async () => {
    render(<AnalyzeView modelState="ready" />)
    await evaluate()
    expect(await screen.findByText('Sampled futures.')).toBeInTheDocument()
  })

  it('keeps the previous result on screen while re-running', async () => {
    render(<AnalyzeView modelState="ready" />)
    await evaluate()
    await screen.findByTestId('price-chart')

    let resolve
    api.analyze.mockReturnValue(new Promise((r) => { resolve = r }))
    await evaluate()

    // Dimmed and marked busy, but still mounted — the reader keeps their place.
    expect(screen.getByTestId('price-chart')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(/Re-running AAPL/)
    expect(document.querySelector('.results')).toHaveAttribute('aria-busy', 'true')

    resolve(RESULT)
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
  })

  it('reports an error without discarding the last good result', async () => {
    render(<AnalyzeView modelState="ready" />)
    await evaluate()
    await screen.findByTestId('price-chart')

    api.analyze.mockRejectedValue(new Error('No market data returned.'))
    await evaluate()

    expect(await screen.findByRole('alert')).toHaveTextContent('No market data returned.')
    expect(screen.getByTestId('price-chart')).toBeInTheDocument()
  })

  it('passes the model state through to the button', () => {
    render(<AnalyzeView modelState="loading" />)
    expect(screen.getByRole('button', { name: /Loading model/ })).toBeDisabled()
  })

  it('reports the analysed symbol upward for the URL', async () => {
    const onSymbolChange = vi.fn()
    render(<AnalyzeView modelState="ready" onSymbolChange={onSymbolChange} />)
    await evaluate()
    expect(onSymbolChange).toHaveBeenCalledWith('AAPL')
  })

  it('takes its symbol from the prop', async () => {
    render(<AnalyzeView modelState="ready" symbol="NVDA" />)
    await waitFor(() => expect(screen.getByLabelText('Ticker')).toHaveValue('NVDA'))
  })

  it('renders the sector panel alongside the forecast', async () => {
    render(<AnalyzeView modelState="ready" />)
    await evaluate()
    expect(await screen.findByTestId('sector')).toBeInTheDocument()
  })

  it('surfaces diagnostic caveats', async () => {
    api.analyze.mockResolvedValue({
      ...RESULT,
      diagnostics: { caveats: ['The latest close sits +2.1σ from the window mean.'] },
    })
    render(<AnalyzeView modelState="ready" />)
    await evaluate()
    expect(await screen.findByText(/\+2.1σ from the window mean/)).toBeInTheDocument()
  })
})
