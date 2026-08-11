import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({
  listWatchlists: vi.fn(),
  createWatchlist: vi.fn(),
  addSymbol: vi.fn(),
}))

const api = await import('../api')
const { default: AddToWatchlist } = await import('../components/AddToWatchlist')

beforeEach(() => {
  vi.clearAllMocks()
  api.listWatchlists.mockResolvedValue([{ id: 1, name: 'Tech', items: [{ symbol: 'AAPL' }] }])
  api.addSymbol.mockResolvedValue({})
})

const star = () => screen.getByRole('button', { name: /Add .* to a watchlist/ })

describe('AddToWatchlist', () => {
  it('does not fetch watchlists until it is opened', () => {
    render(<AddToWatchlist symbol="NVDA" />)
    expect(api.listWatchlists).not.toHaveBeenCalled()
  })

  it('lists the available watchlists on open', async () => {
    render(<AddToWatchlist symbol="NVDA" />)
    await userEvent.click(star())
    expect(await screen.findByRole('menuitem', { name: /Tech/ })).toBeInTheDocument()
  })

  it('adds the upper-cased symbol to the chosen list', async () => {
    render(<AddToWatchlist symbol=" nvda " />)
    await userEvent.click(star())
    await userEvent.click(await screen.findByRole('menuitem', { name: /Tech/ }))
    expect(api.addSymbol).toHaveBeenCalledWith(1, 'NVDA')
  })

  it('closes and confirms after adding', async () => {
    render(<AddToWatchlist symbol="NVDA" />)
    await userEvent.click(star())
    await userEvent.click(await screen.findByRole('menuitem', { name: /Tech/ }))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(await screen.findByRole('status')).toHaveTextContent('NVDA added')
  })

  it('offers to create a first list when none exist', async () => {
    api.listWatchlists.mockResolvedValue([])
    api.createWatchlist.mockResolvedValue({ id: 7, name: 'My watchlist', items: [] })
    render(<AddToWatchlist symbol="NVDA" />)
    await userEvent.click(star())
    await userEvent.click(await screen.findByRole('menuitem', { name: /Create/ }))
    expect(api.createWatchlist).toHaveBeenCalledWith('My watchlist')
    expect(api.addSymbol).toHaveBeenCalledWith(7, 'NVDA')
  })

  it('is disabled without a ticker', () => {
    render(<AddToWatchlist symbol="  " />)
    expect(star()).toBeDisabled()
  })

  it('closes on Escape', async () => {
    render(<AddToWatchlist symbol="NVDA" />)
    await userEvent.click(star())
    await screen.findByRole('menu')
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('reports an add failure instead of pretending it worked', async () => {
    api.addSymbol.mockRejectedValue(new Error('watchlist is gone'))
    render(<AddToWatchlist symbol="NVDA" />)
    await userEvent.click(star())
    await userEvent.click(await screen.findByRole('menuitem', { name: /Tech/ }))
    expect(await screen.findByText('watchlist is gone')).toBeInTheDocument()
    expect(screen.getByRole('menu')).toBeInTheDocument()
  })
})
