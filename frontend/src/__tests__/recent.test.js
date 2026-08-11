import { describe, expect, it, vi } from 'vitest'
import { recentSymbols, rememberSymbol } from '../recent'

describe('recent symbols', () => {
  it('starts empty', () => {
    expect(recentSymbols()).toEqual([])
  })

  it('remembers upper-cased and trimmed', () => {
    rememberSymbol('  nvda ')
    expect(recentSymbols()).toEqual(['NVDA'])
  })

  it('puts the most recent first', () => {
    rememberSymbol('AAPL')
    rememberSymbol('MSFT')
    expect(recentSymbols()).toEqual(['MSFT', 'AAPL'])
  })

  it('moves a repeat to the front rather than duplicating it', () => {
    rememberSymbol('AAPL')
    rememberSymbol('MSFT')
    rememberSymbol('AAPL')
    expect(recentSymbols()).toEqual(['AAPL', 'MSFT'])
  })

  it('keeps the list short', () => {
    for (let i = 0; i < 20; i++) rememberSymbol(`SYM${i}`)
    expect(recentSymbols()).toHaveLength(8)
    expect(recentSymbols()[0]).toBe('SYM19')
  })

  it('ignores an empty ticker', () => {
    rememberSymbol('   ')
    expect(recentSymbols()).toEqual([])
  })

  it('survives corrupt storage', () => {
    localStorage.setItem('afa.recent', 'not json')
    expect(recentSymbols()).toEqual([])
    rememberSymbol('AAPL')
    expect(recentSymbols()).toEqual(['AAPL'])
  })

  it('survives a non-array payload', () => {
    localStorage.setItem('afa.recent', '{"nope":1}')
    expect(recentSymbols()).toEqual([])
  })

  it('does not throw when storage refuses to write', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })
    expect(() => rememberSymbol('AAPL')).not.toThrow()
    setItem.mockRestore()
  })
})
