import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({
  getConfig: vi.fn(),
  getHealth: vi.fn(),
  analyze: vi.fn(),
}))

const api = await import('../api')
const { default: App } = await import('../App')

const CONFIG = {
  intervals: [{ value: '1d', label: 'Daily', intraday: false }],
  defaults: { interval: '1d', lookback: 128, horizon: 10, paths: 24 },
  limits: { max_lookback: 512, max_horizon: 120, max_paths: 64 },
  lookback_warn_above: 200,
}

beforeEach(() => {
  vi.clearAllMocks()
  window.location.hash = ''
  api.getConfig.mockResolvedValue(CONFIG)
  api.getHealth.mockResolvedValue({
    model: { state: 'ready', model: 'small', params: '24.7M', device: 'mps', load_seconds: 3.2 },
  })
})

describe('App shell', () => {
  it('renders the product name', async () => {
    render(<App />)
    expect(await screen.findByRole('heading', { name: /AI Financial Analyzer/ })).toBeInTheDocument()
  })

  it('shows the model status once health resolves', async () => {
    render(<App />)
    expect(await screen.findByText(/Kronos-small/)).toBeInTheDocument()
    expect(screen.getByText(/loaded in 3.2s/)).toBeInTheDocument()
  })

  it('reports a backend that is still loading weights', async () => {
    api.getHealth.mockResolvedValue({ model: { state: 'loading' } })
    render(<App />)
    expect(await screen.findByText(/Loading model weights/)).toBeInTheDocument()
  })

  it('surfaces a config failure instead of rendering an empty page', async () => {
    api.getConfig.mockRejectedValue(new Error('backend is down'))
    render(<App />)
    expect(await screen.findByText('backend is down')).toBeInTheDocument()
  })

  it('renders the analyze view by default', async () => {
    render(<App />)
    expect(await screen.findByLabelText('Ticker')).toBeInTheDocument()
  })

  it('seeds the ticker from the URL', async () => {
    window.location.hash = '#/analyze?symbol=NVDA'
    render(<App />)
    await waitFor(() => expect(screen.getByLabelText('Ticker')).toHaveValue('NVDA'))
  })

  it('hides the tab bar while only one view is registered', async () => {
    render(<App />)
    await screen.findByLabelText('Ticker')
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument()
  })

  it('offers the theme toggle', async () => {
    render(<App />)
    expect(await screen.findByRole('button', { name: /Theme:/ })).toBeInTheDocument()
  })
})
