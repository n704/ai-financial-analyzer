import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { buildHash, parseHash, useHashRoute } from '../hooks/useHashRoute'

beforeEach(() => {
  window.location.hash = ''
})

describe('parseHash', () => {
  it('defaults to analyze when the hash is empty', () => {
    expect(parseHash('')).toEqual({ view: 'analyze', params: {} })
  })

  it('falls back to analyze for a view that does not exist', () => {
    expect(parseHash('#/nonsense').view).toBe('analyze')
  })

  it('reads the view and its query params', () => {
    expect(parseHash('#/compare?symbols=AAPL,MSFT&interval=1d')).toEqual({
      view: 'compare',
      params: { symbols: 'AAPL,MSFT', interval: '1d' },
    })
  })

  it('tolerates a hash without the leading slash', () => {
    expect(parseHash('#watchlist').view).toBe('watchlist')
  })
})

describe('buildHash', () => {
  it('omits the query string when there are no params', () => {
    expect(buildHash('analyze')).toBe('#/analyze')
  })

  it('drops empty values instead of emitting bare keys', () => {
    expect(buildHash('analyze', { symbol: 'AAPL', interval: '', seed: null })).toBe(
      '#/analyze?symbol=AAPL',
    )
  })

  it('round-trips through parseHash', () => {
    const params = { symbols: 'AAPL,MSFT' }
    expect(parseHash(buildHash('compare', params))).toEqual({ view: 'compare', params })
  })
})

describe('useHashRoute', () => {
  it('reads the initial location', () => {
    window.location.hash = '#/compare?symbols=AAPL'
    const { result } = renderHook(() => useHashRoute())
    expect(result.current.view).toBe('compare')
    expect(result.current.params.symbols).toBe('AAPL')
  })

  it('navigate updates both the URL and the returned state', () => {
    const { result } = renderHook(() => useHashRoute())
    act(() => result.current.navigate('watchlist', { symbol: 'NVDA' }))
    expect(window.location.hash).toBe('#/watchlist?symbol=NVDA')
    expect(result.current.view).toBe('watchlist')
    expect(result.current.params.symbol).toBe('NVDA')
  })

  it('follows a hashchange fired by the back button', () => {
    const { result } = renderHook(() => useHashRoute())
    act(() => {
      window.location.hash = '#/compare'
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(result.current.view).toBe('compare')
  })
})
