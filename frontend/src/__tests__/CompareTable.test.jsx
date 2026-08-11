import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import CompareTable from '../components/CompareTable'

const row = (symbol, over = {}) => ({
  symbol,
  name: `${symbol} Inc.`,
  currency: 'USD',
  last_close: 100,
  technicals: { rsi_14: 55 },
  metrics: {
    total_return_pct: 12.5,
    annualized_vol_pct: 28.4,
    return_per_unit_risk: 0.44,
    max_drawdown_pct: -8.2,
    beta_vs_benchmark: 1.15,
    correlation_vs_benchmark: 0.82,
    ...over,
  },
})

const RESULT = { symbols: [row('AAPL'), row('MSFT', { total_return_pct: -3.1 })] }

const setup = (forecasts = {}) =>
  render(<CompareTable result={RESULT} forecasts={forecasts} benchmark="AAPL" />)

const rowFor = (symbol) => screen.getByRole('row', { name: new RegExp(symbol) })

describe('CompareTable', () => {
  it('renders one row per symbol', () => {
    setup()
    expect(screen.getAllByRole('row')).toHaveLength(3) // + header
  })

  it('marks the benchmark', () => {
    setup()
    expect(within(rowFor('AAPL')).getByText('base')).toBeInTheDocument()
    expect(within(rowFor('MSFT')).queryByText('base')).not.toBeInTheDocument()
  })

  it('colours gains and losses', () => {
    setup()
    expect(within(rowFor('AAPL')).getByText('+12.50%')).toHaveClass('pos')
    expect(within(rowFor('MSFT')).getByText('-3.10%')).toHaveClass('neg')
  })

  it('shows a dash rather than NaN for a missing metric', () => {
    render(
      <CompareTable
        result={{ symbols: [row('AAPL', { total_return_pct: null, beta_vs_benchmark: null })] }}
        forecasts={{}}
        benchmark="AAPL"
      />,
    )
    expect(within(rowFor('AAPL')).getAllByText('—').length).toBeGreaterThan(0)
  })

  it('leaves the Kronos column empty until asked', () => {
    setup()
    expect(within(rowFor('AAPL')).getByText('—')).toBeInTheDocument()
  })

  it('shows a per-symbol pending state', () => {
    setup({ AAPL: { status: 'pending' } })
    expect(within(rowFor('AAPL')).getByText('running…')).toBeInTheDocument()
  })

  it('fills in a completed forecast without waiting for the rest', () => {
    setup({
      AAPL: { status: 'done', data: { signal: { action: 'BUY' }, stats: { prob_up: 0.71 } } },
      MSFT: { status: 'pending' },
    })
    const aapl = within(rowFor('AAPL'))
    expect(aapl.getByText('BUY')).toBeInTheDocument()
    expect(aapl.getByText(/71% up/)).toBeInTheDocument()
    expect(within(rowFor('MSFT')).getByText('running…')).toBeInTheDocument()
  })

  it('reports a failed forecast for one symbol only', () => {
    setup({
      AAPL: { status: 'error', error: 'Model is not loaded' },
      MSFT: { status: 'done', data: { signal: { action: 'HOLD' }, stats: { prob_up: 0.5 } } },
    })
    expect(within(rowFor('AAPL')).getByText('failed')).toBeInTheDocument()
    expect(within(rowFor('MSFT')).getByText('HOLD')).toBeInTheDocument()
  })

  it('names the benchmark in the beta explanation', () => {
    setup()
    expect(screen.getByRole('button', { name: /What is beta/ })).toBeInTheDocument()
  })
})
