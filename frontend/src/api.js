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

export const getConfig = () => request('/api/config')
export const getHealth = () => request('/api/health')

export const analyze = (payload) =>
  request('/api/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
