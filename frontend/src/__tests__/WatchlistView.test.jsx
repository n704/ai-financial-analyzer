import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({
  listWatchlists: vi.fn(),
  createWatchlist: vi.fn(),
  renameWatchlist: vi.fn(),
  deleteWatchlist: vi.fn(),
  addSymbol: vi.fn(),
  removeSymbol: vi.fn(),
  getQuotes: vi.fn(),
}))

const api = await import('../api')
const { default: WatchlistView } = await import('../views/WatchlistView')

const list = (over = {}) => ({ id: 1, name: 'Tech', items: [{ symbol: 'AAPL' }], ...over })

beforeEach(() => {
  vi.clearAllMocks()
  api.listWatchlists.mockResolvedValue([list()])
  api.getQuotes.mockResolvedValue([
    { symbol: 'AAPL', name: 'Apple Inc.', currency: 'USD', price: 190, change_pct: 1.0 },
  ])
})

describe('WatchlistView', () => {
  it('loads and renders the first list', async () => {
    render(<WatchlistView onAnalyze={vi.fn()} />)
    expect(await screen.findByText(/Tech — 1 symbols/)).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /AAPL/ })).toBeInTheDocument()
  })

  it('fetches quotes for the active list only', async () => {
    api.listWatchlists.mockResolvedValue([
      list(),
      list({ id: 2, name: 'Energy', items: [{ symbol: 'XOM' }] }),
    ])
    render(<WatchlistView onAnalyze={vi.fn()} />)
    await screen.findByText(/Tech — 1 symbols/)
    expect(api.getQuotes).toHaveBeenCalledWith(['AAPL'])
    expect(api.getQuotes).not.toHaveBeenCalledWith(['XOM'])
  })

  it('switches lists and refetches quotes', async () => {
    api.listWatchlists.mockResolvedValue([
      list(),
      list({ id: 2, name: 'Energy', items: [{ symbol: 'XOM' }] }),
    ])
    render(<WatchlistView onAnalyze={vi.fn()} />)
    await userEvent.click(await screen.findByRole('button', { name: /Energy/ }))
    await waitFor(() => expect(api.getQuotes).toHaveBeenCalledWith(['XOM']))
  })

  it('adds a symbol and reloads', async () => {
    render(<WatchlistView onAnalyze={vi.fn()} />)
    await screen.findByText(/Tech — 1 symbols/)

    api.addSymbol.mockResolvedValue({})
    api.listWatchlists.mockResolvedValue([
      list({ items: [{ symbol: 'AAPL' }, { symbol: 'NVDA' }] }),
    ])

    await userEvent.type(screen.getByLabelText('Add a ticker'), 'nvda')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))

    expect(api.addSymbol).toHaveBeenCalledWith(1, 'NVDA')
    expect(await screen.findByRole('row', { name: /NVDA/ })).toBeInTheDocument()
  })

  it('will not submit an empty ticker', async () => {
    render(<WatchlistView onAnalyze={vi.fn()} />)
    await screen.findByText(/Tech — 1 symbols/)
    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled()
  })

  it('removes a symbol', async () => {
    render(<WatchlistView onAnalyze={vi.fn()} />)
    await screen.findByRole('row', { name: /AAPL/ })
    api.removeSymbol.mockResolvedValue({})
    await userEvent.click(screen.getByRole('button', { name: /Remove AAPL/ }))
    expect(api.removeSymbol).toHaveBeenCalledWith(1, 'AAPL')
  })

  it('hands a symbol to the analyze view', async () => {
    const onAnalyze = vi.fn()
    render(<WatchlistView onAnalyze={onAnalyze} />)
    const row = await screen.findByRole('row', { name: /AAPL/ })
    await userEvent.click(within(row).getByRole('button', { name: 'Analyze' }))
    expect(onAnalyze).toHaveBeenCalledWith('AAPL')
  })

  it('creates a list and selects it', async () => {
    api.createWatchlist.mockResolvedValue({ id: 2, name: 'Energy', items: [] })
    render(<WatchlistView onAnalyze={vi.fn()} />)
    await screen.findByText(/Tech — 1 symbols/)

    api.listWatchlists.mockResolvedValue([list(), list({ id: 2, name: 'Energy', items: [] })])
    await userEvent.click(screen.getByRole('button', { name: /New list/ }))
    await userEvent.type(screen.getByLabelText('New watchlist name'), 'Energy')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))

    expect(api.createWatchlist).toHaveBeenCalledWith('Energy')
    expect(await screen.findByText(/Energy — 0 symbols/)).toBeInTheDocument()
  })

  it('shows the no-watchlists empty state', async () => {
    api.listWatchlists.mockResolvedValue([])
    render(<WatchlistView onAnalyze={vi.fn()} />)
    expect(await screen.findByText('No watchlists yet.')).toBeInTheDocument()
  })

  it('surfaces a load failure', async () => {
    api.listWatchlists.mockRejectedValue(new Error('backend is down'))
    render(<WatchlistView onAnalyze={vi.fn()} />)
    expect(await screen.findByText('backend is down')).toBeInTheDocument()
  })

  it('surfaces a failed mutation without losing the list', async () => {
    render(<WatchlistView onAnalyze={vi.fn()} />)
    await screen.findByText(/Tech — 1 symbols/)
    api.addSymbol.mockRejectedValue(new Error('unknown ticker'))

    await userEvent.type(screen.getByLabelText('Add a ticker'), 'ZZZZ')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))

    expect(await screen.findByText('unknown ticker')).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /AAPL/ })).toBeInTheDocument()
  })

  it('does not ask for quotes when the list is empty', async () => {
    api.listWatchlists.mockResolvedValue([list({ items: [] })])
    render(<WatchlistView onAnalyze={vi.fn()} />)
    await screen.findByText(/Tech — 0 symbols/)
    expect(api.getQuotes).not.toHaveBeenCalled()
  })
})
