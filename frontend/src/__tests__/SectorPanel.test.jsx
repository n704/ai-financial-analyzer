import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({ getSector: vi.fn() }))
// Both charts need a canvas; this suite is about what the panel reports.
vi.mock('../charts', () => ({
  createBaseChart: () => ({
    chart: { timeScale: () => ({ fitContent: () => {} }) },
    colors: { median: '#000', bound: '#111' },
    dispose: () => {},
  }),
  addLine: () => ({}),
}))

const api = await import('../api')
const { default: SectorPanel } = await import('../components/SectorPanel')

const series = (symbol) => ({
  symbol,
  name: `${symbol} Inc.`,
  series: [{ time: '2026-01-05T00:00:00-05:00', value: 100 }],
})

const RESULT = {
  symbol: 'AAPL',
  name: 'Apple Inc.',
  sector: 'Technology',
  sector_etf: 'XLK',
  sector_etf_name: 'Technology Select Sector SPDR',
  market_etf: 'SPY',
  benchmark: 'XLK',
  caveat: null,
  interval: '1d',
  interval_label: 'Daily',
  bars: 120,
  start: '2026-01-05T00:00:00-05:00',
  end: '2026-06-30T00:00:00-04:00',
  symbols: [series('XLK'), series('AAPL'), series('SPY')],
  relative: {
    benchmark: 'XLK',
    stock_return_pct: 18.4,
    benchmark_return_pct: 11.2,
    excess_return_pct: 7.2,
    alpha_pct: 5.1,
    beta: 1.18,
    correlation: 0.83,
    stock_vol_pct: 28,
    benchmark_vol_pct: 21,
  },
  relative_strength: [{ time: '2026-01-05T00:00:00-05:00', value: 100 }],
  unavailable: [],
  explanations: [{ title: 'What is being compared', body: 'AAPL is shown against its sector.' }],
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getSector.mockResolvedValue(RESULT)
})

describe('SectorPanel', () => {
  it('fetches for the analysed symbol', async () => {
    render(<SectorPanel symbol="AAPL" interval="1d" />)
    await waitFor(() => expect(api.getSector).toHaveBeenCalledWith('AAPL', '1d', 180))
  })

  it('names the sector and its ETF in the heading', async () => {
    render(<SectorPanel symbol="AAPL" />)
    expect(await screen.findByText('AAPL vs Technology (XLK)')).toBeInTheDocument()
  })

  it('reports return, excess, alpha and beta', async () => {
    render(<SectorPanel symbol="AAPL" />)
    expect(await screen.findByText('+18.40%')).toBeInTheDocument()
    expect(screen.getByText('+11.20%')).toBeInTheDocument()
    expect(screen.getByText('+7.20%')).toBeInTheDocument()
    expect(screen.getByText('+5.10%')).toBeInTheDocument()
    expect(screen.getByText('1.18')).toBeInTheDocument()
  })

  it('distinguishes excess return from alpha for the reader', async () => {
    render(<SectorPanel symbol="AAPL" />)
    await screen.findByText('AAPL vs Technology (XLK)')
    expect(screen.getByRole('button', { name: /What is alpha/ })).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /What is return against the benchmark/ }),
    ).toBeInTheDocument()
  })

  it('shows the API explanation', async () => {
    render(<SectorPanel symbol="AAPL" />)
    expect(await screen.findByText('AAPL is shown against its sector.')).toBeInTheDocument()
  })

  it('names the ETF in the legend', async () => {
    render(<SectorPanel symbol="AAPL" />)
    expect(await screen.findByText(/Technology Select Sector SPDR/)).toBeInTheDocument()
  })

  it('shows the fallback caveat rather than inventing a sector', async () => {
    api.getSector.mockResolvedValue({
      ...RESULT,
      symbol: 'BTC-USD',
      sector: null,
      sector_etf: null,
      sector_etf_name: null,
      benchmark: 'SPY',
      caveat: 'No sector could be resolved for BTC-USD, so it is compared against SPY only.',
      relative: { ...RESULT.relative, benchmark: 'SPY' },
    })
    render(<SectorPanel symbol="BTC-USD" />)
    expect(await screen.findByText(/No sector could be resolved/)).toBeInTheDocument()
    expect(screen.getByText('BTC-USD vs the market')).toBeInTheDocument()
  })

  it('shows a loading state first', () => {
    api.getSector.mockReturnValue(new Promise(() => {}))
    render(<SectorPanel symbol="AAPL" />)
    expect(screen.getByText(/Comparing AAPL with its sector/)).toBeInTheDocument()
  })

  it('reports a failure without taking the page down', async () => {
    api.getSector.mockRejectedValue(new Error('No market data returned.'))
    render(<SectorPanel symbol="ZZZZ" />)
    expect(await screen.findByText('No market data returned.')).toBeInTheDocument()
  })

  it('refetches when the symbol changes', async () => {
    const { rerender } = render(<SectorPanel symbol="AAPL" />)
    await waitFor(() => expect(api.getSector).toHaveBeenCalledTimes(1))
    rerender(<SectorPanel symbol="MSFT" />)
    await waitFor(() => expect(api.getSector).toHaveBeenLastCalledWith('MSFT', '1d', 180))
  })

  it('renders nothing without a symbol', () => {
    const { container } = render(<SectorPanel symbol="" />)
    expect(container).toBeEmptyDOMElement()
    expect(api.getSector).not.toHaveBeenCalled()
  })

  it('omits the metric tiles when no benchmark resolved', async () => {
    api.getSector.mockResolvedValue({ ...RESULT, relative: {}, relative_strength: [] })
    render(<SectorPanel symbol="AAPL" />)
    await screen.findByText('AAPL vs Technology (XLK)')
    expect(screen.queryByText('+18.40%')).not.toBeInTheDocument()
  })
})
