import { afterEach, describe, expect, it } from 'vitest'
import { chartColors, cssVar, SERIES_COLORS, seriesColor } from '../chartTheme'

afterEach(() => {
  document.documentElement.style.cssText = ''
})

describe('cssVar', () => {
  it('reads a custom property off the root element', () => {
    document.documentElement.style.setProperty('--accent', '#123456')
    expect(cssVar('--accent')).toBe('#123456')
  })

  it('falls back when the property is unset', () => {
    // jsdom resolves unset custom properties to '', which is exactly the
    // first-paint case this fallback exists for.
    expect(cssVar('--accent')).toBe('#4c8dff')
  })

  it('prefers an explicit fallback over the built-in one', () => {
    expect(cssVar('--nope', '#abcdef')).toBe('#abcdef')
  })
})

describe('chartColors', () => {
  it('exposes every colour the charts reference', () => {
    const colors = chartColors()
    for (const key of [
      'text', 'grid', 'border', 'up', 'down', 'median',
      'bound', 'actual', 'path', 'volumeUp', 'volumeDown',
    ]) {
      expect(colors[key], key).toBeTruthy()
    }
  })

  it('follows the live theme tokens', () => {
    document.documentElement.style.setProperty('--pos', '#00ff00')
    expect(chartColors().up).toBe('#00ff00')
  })

  it('fades the accent into a translucent path colour', () => {
    document.documentElement.style.setProperty('--accent', '#4c8dff')
    expect(chartColors().path).toBe('rgba(76, 141, 255, 0.2)')
  })

  it('leaves a non-hex colour alone rather than emitting garbage', () => {
    document.documentElement.style.setProperty('--accent', 'rebeccapurple')
    expect(chartColors().path).toBe('rebeccapurple')
  })
})

describe('seriesColor', () => {
  it('gives the first symbols distinct colours', () => {
    const first = [0, 1, 2].map(seriesColor)
    expect(new Set(first).size).toBe(3)
  })

  it('cycles once the palette runs out', () => {
    expect(seriesColor(SERIES_COLORS.length)).toBe(SERIES_COLORS[0])
  })
})
