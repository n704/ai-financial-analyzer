/** Minutes of UTC offset carried in an ISO string ("...-04:00" -> -240). */
function offsetMinutes(iso) {
  const m = /([+-])(\d{2}):?(\d{2})$/.exec(iso)
  if (!m) return 0
  return (m[1] === '-' ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3]))
}

/**
 * Epoch seconds shifted so lightweight-charts — which always renders in UTC —
 * shows the exchange's wall clock. Without this a 09:30 New York bar reads
 * 13:30, and a 00:00 Tokyo bar lands on the previous calendar day.
 */
export const toUnix = (iso) =>
  Math.floor(new Date(iso).getTime() / 1000) + offsetMinutes(iso) * 60

export function fmtMoney(v, currency) {
  if (v == null || Number.isNaN(v)) return '—'
  const digits = Math.abs(v) >= 1000 ? 0 : Math.abs(v) >= 10 ? 2 : 4
  const n = v.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
  return currency ? `${symbolFor(currency)}${n}` : n
}

export function symbolFor(currency) {
  return { USD: '$', EUR: '€', GBP: '£', JPY: '¥', INR: '₹', CNY: '¥' }[currency] ?? `${currency} `
}

export const fmtPct = (v, digits = 2) =>
  v == null || Number.isNaN(v) ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`

export const fmtNum = (v, digits = 2) =>
  v == null || Number.isNaN(v) ? '—' : v.toFixed(digits)

export const fmtCompact = (v) =>
  v == null || Number.isNaN(v)
    ? '—'
    : Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(v)

/** Formats the timestamp's own wall clock (exchange time), not the viewer's. */
export const fmtDate = (iso, intraday) =>
  new Date(toUnix(iso) * 1000).toLocaleString(undefined, {
    timeZone: 'UTC',
    month: 'short',
    day: 'numeric',
    year: intraday ? undefined : 'numeric',
    hour: intraday ? '2-digit' : undefined,
    minute: intraday ? '2-digit' : undefined,
  })

export const signalTone = (action) =>
  ({ BUY: 'pos', SELL: 'neg', HOLD: 'neutral' })[action] ?? 'neutral'
