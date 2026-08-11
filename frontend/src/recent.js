/** Recently evaluated tickers, offered as autocomplete on the ticker input. */
const KEY = 'afa.recent'
const LIMIT = 8

export function recentSymbols() {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) || '[]')
    return Array.isArray(parsed) ? parsed.filter((s) => typeof s === 'string') : []
  } catch {
    // Corrupt or unavailable storage must never break the controls.
    return []
  }
}

export function rememberSymbol(symbol) {
  const ticker = (symbol || '').trim().toUpperCase()
  if (!ticker) return recentSymbols()
  const next = [ticker, ...recentSymbols().filter((s) => s !== ticker)].slice(0, LIMIT)
  try {
    localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    /* private browsing, quota — not worth surfacing */
  }
  return next
}
