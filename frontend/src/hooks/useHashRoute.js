import { useCallback, useEffect, useState } from 'react'

/**
 * Minimal hash router — `#/compare?symbols=AAPL,MSFT`.
 *
 * The app has four screens and no need for nested routes or loaders, so this
 * replaces a router dependency with ~40 lines. Keeping state in the URL means a
 * view survives a refresh and can be pasted to someone else.
 */

export const VIEWS = ['analyze', 'watchlist', 'compare']
const DEFAULT_VIEW = 'analyze'

export function parseHash(hash) {
  const raw = (hash || '').replace(/^#\/?/, '')
  const [path, query] = raw.split('?')
  const view = VIEWS.includes(path) ? path : DEFAULT_VIEW
  const params = {}
  for (const [k, v] of new URLSearchParams(query || '')) params[k] = v
  return { view, params }
}

export function buildHash(view, params = {}) {
  const query = new URLSearchParams(
    // Drop empties so the URL stays readable rather than `?symbol=&interval=`.
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''),
  ).toString()
  return `#/${view}${query ? `?${query}` : ''}`
}

export function useHashRoute() {
  const [route, setRoute] = useState(() => parseHash(window.location.hash))

  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  const navigate = useCallback((view, params = {}) => {
    const next = buildHash(view, params)
    if (next === window.location.hash) return
    window.location.hash = next
    // jsdom and some browsers fire `hashchange` asynchronously; setting state
    // here keeps the UI in step with the click that caused it.
    setRoute(parseHash(next))
  }, [])

  return { ...route, navigate }
}
