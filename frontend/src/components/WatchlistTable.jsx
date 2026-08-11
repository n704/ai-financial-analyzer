import { fmtMoney, fmtPct } from '../utils'

/** One row per symbol: live-ish price, change, and the actions on it. */
export default function WatchlistTable({ items, quotes, onAnalyze, onRemove, busy }) {
  if (!items.length) {
    return (
      <div className="empty">
        <p>Nothing on this list yet.</p>
        <p className="muted">
          Add a ticker above, or star one from the Analyze tab to keep an eye on it.
        </p>
      </div>
    )
  }

  const bySymbol = new Map(quotes.map((q) => [q.symbol, q]))

  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Symbol</th>
            <th scope="col">Name</th>
            <th scope="col" className="num">Price</th>
            <th scope="col" className="num">Change</th>
            <th scope="col" className="actions">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const quote = bySymbol.get(item.symbol)
            const change = quote?.change_pct
            return (
              <tr key={item.symbol}>
                <th scope="row" className="symbol-cell">
                  {item.symbol}
                  {item.note && <div className="muted note">{item.note}</div>}
                </th>
                <td className="muted">{quote?.name ?? '—'}</td>
                <td className="num">
                  {quote?.price == null ? (
                    <span className="muted">{busy ? '…' : '—'}</span>
                  ) : (
                    fmtMoney(quote.price, quote.currency)
                  )}
                </td>
                <td className={`num ${change == null ? 'muted' : change >= 0 ? 'pos' : 'neg'}`}>
                  {change == null ? '—' : fmtPct(change)}
                </td>
                <td className="actions">
                  <button
                    type="button"
                    className="btn ghost"
                    onClick={() => onAnalyze(item.symbol)}
                  >
                    Analyze
                  </button>
                  <button
                    type="button"
                    className="btn ghost danger"
                    onClick={() => onRemove(item.symbol)}
                    aria-label={`Remove ${item.symbol} from this watchlist`}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
