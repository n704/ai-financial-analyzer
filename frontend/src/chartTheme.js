/**
 * Chart colours, resolved from the CSS custom properties in index.css.
 *
 * lightweight-charts draws to a canvas and cannot read CSS variables itself, so
 * the values are pulled out of the computed style at chart-creation time. That
 * keeps one palette for the whole app: change a token in index.css and both the
 * DOM and the canvases follow, including across a light/dark theme switch.
 */

/** Fallbacks matter in two places: jsdom (no layout) and the first paint. */
const FALLBACKS = {
  '--text': '#e6edf7',
  '--muted': '#8b9bb4',
  '--line': '#253044',
  '--grid': '#1c2434',
  '--accent': '#4c8dff',
  '--pos': '#26a69a',
  '--neg': '#ef5350',
  '--chart-bound': '#7a8dab',
}

export function cssVar(name, fallback) {
  if (typeof getComputedStyle !== 'function') return fallback ?? FALLBACKS[name]
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback || FALLBACKS[name]
}

/** Same hue as `--accent`, faded, for the Monte-Carlo spaghetti. */
function fade(hex, alpha) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return hex
  const n = parseInt(m[1], 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

/** Read the live palette. Call inside the effect, not at module scope. */
export function chartColors() {
  const accent = cssVar('--accent')
  return {
    text: cssVar('--muted'),
    grid: cssVar('--grid'),
    border: cssVar('--line'),
    up: cssVar('--pos'),
    down: cssVar('--neg'),
    median: accent,
    bound: cssVar('--chart-bound'),
    actual: cssVar('--text'),
    path: fade(accent, 0.2),
    pathLegend: fade(accent, 0.6),
    volumeUp: fade(cssVar('--pos'), 0.35),
    volumeDown: fade(cssVar('--neg'), 0.35),
  }
}

/**
 * Distinct series colours for multi-symbol charts. Ordered so the first three
 * — the common 2–3 symbol case — stay maximally separable, and every entry
 * clears 3:1 contrast against both the light and dark panel backgrounds.
 */
export const SERIES_COLORS = [
  '#4c8dff',
  '#f0b429',
  '#26a69a',
  '#c084fc',
  '#ef5350',
  '#38bdf8',
]

export const seriesColor = (i) => SERIES_COLORS[i % SERIES_COLORS.length]
