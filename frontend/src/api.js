// Dev goes through the Vite proxy; the production build is served by FastAPI itself.
const BASE = import.meta.env.VITE_API_BASE ?? ''

async function request(path, options) {
  const res = await fetch(`${BASE}${path}`, options)
  let body = null
  try {
    body = await res.json()
  } catch {
    /* non-JSON error page */
  }
  if (!res.ok) {
    const detail = body?.detail
    throw new Error(
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => `${d.loc?.slice(-1)}: ${d.msg}`).join('; ')
          : `Request failed (${res.status})`,
    )
  }
  return body
}

const json = (method) => (path, body) =>
  request(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

const post = json('POST')
const patch = json('PATCH')
const del = (path) => request(path, { method: 'DELETE' })

export const getConfig = () => request('/api/config')
export const getHealth = () => request('/api/health')

export const analyze = (payload) => post('/api/analyze', payload)

export const getQuotes = (symbols) =>
  symbols.length ? request(`/api/quotes?symbols=${encodeURIComponent(symbols.join(','))}`) : []

export const listWatchlists = () => request('/api/watchlists')
export const createWatchlist = (name) => post('/api/watchlists', { name })
export const renameWatchlist = (id, name) => patch(`/api/watchlists/${id}`, { name })
export const deleteWatchlist = (id) => del(`/api/watchlists/${id}`)
export const addSymbol = (id, symbol, note) => post(`/api/watchlists/${id}/symbols`, { symbol, note })
export const removeSymbol = (id, symbol) =>
  del(`/api/watchlists/${id}/symbols/${encodeURIComponent(symbol)}`)
