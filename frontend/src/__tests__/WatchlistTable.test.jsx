import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import WatchlistTable from '../components/WatchlistTable'

const ITEMS = [{ symbol: 'AAPL' }, { symbol: 'MSFT' }]
const QUOTES = [
  { symbol: 'AAPL', name: 'Apple Inc.', currency: 'USD', price: 189.5, change_pct: 1.24 },
  { symbol: 'MSFT', name: 'Microsoft', currency: 'USD', price: 402.1, change_pct: -0.87 },
]

const setup = (props = {}) => {
  const onAnalyze = vi.fn()
  const onRemove = vi.fn()
  render(
    <WatchlistTable
      items={ITEMS}
      quotes={QUOTES}
      onAnalyze={onAnalyze}
      onRemove={onRemove}
      {...props}
    />,
  )
  return { onAnalyze, onRemove }
}

const rowFor = (symbol) => screen.getByRole('row', { name: new RegExp(`^${symbol}`) })

describe('WatchlistTable', () => {
  it('renders one row per symbol', () => {
    setup()
    // +1 for the header row.
    expect(screen.getAllByRole('row')).toHaveLength(3)
  })

  it('shows price and name from the matching quote', () => {
    setup()
    const row = rowFor('AAPL')
    expect(within(row).getByText('Apple Inc.')).toBeInTheDocument()
    expect(within(row).getByText('$189.50')).toBeInTheDocument()
  })

  it('colours a gain and a loss differently', () => {
    setup()
    expect(within(rowFor('AAPL')).getByText('+1.24%')).toHaveClass('pos')
    expect(within(rowFor('MSFT')).getByText('-0.87%')).toHaveClass('neg')
  })

  it('falls back to a dash when a quote is missing', () => {
    setup({ quotes: [] })
    const row = rowFor('AAPL')
    expect(within(row).getAllByText('—').length).toBeGreaterThan(0)
  })

  it('shows a placeholder while quotes are in flight', () => {
    setup({ quotes: [], busy: true })
    expect(within(rowFor('AAPL')).getByText('…')).toBeInTheDocument()
  })

  it('renders a note under the symbol', () => {
    setup({ items: [{ symbol: 'AAPL', note: 'earnings 30 Oct' }] })
    expect(screen.getByText('earnings 30 Oct')).toBeInTheDocument()
  })

  it('asks to analyze the symbol that was clicked', async () => {
    const { onAnalyze } = setup()
    await userEvent.click(within(rowFor('MSFT')).getByRole('button', { name: 'Analyze' }))
    expect(onAnalyze).toHaveBeenCalledWith('MSFT')
  })

  it('removes the symbol that was clicked', async () => {
    const { onRemove } = setup()
    await userEvent.click(screen.getByRole('button', { name: /Remove AAPL/ }))
    expect(onRemove).toHaveBeenCalledWith('AAPL')
  })

  it('shows an empty state instead of a bare table', () => {
    setup({ items: [] })
    expect(screen.getByText(/Nothing on this list yet/)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})
