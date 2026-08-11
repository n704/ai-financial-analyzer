import { useCallback, useEffect, useState } from 'react'
import * as api from '../api'
import WatchlistPicker from '../components/WatchlistPicker'
import WatchlistTable from '../components/WatchlistTable'

const REFRESH_MS = 60_000

/** Persistent symbol lists with price snapshots, backed by the server. */
export default function WatchlistView({ onAnalyze }) {
  const [watchlists, setWatchlists] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [quotes, setQuotes] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [quotesBusy, setQuotesBusy] = useState(false)
  const [symbol, setSymbol] = useState('')

  const active = watchlists.find((w) => w.id === activeId) ?? null

  /** Every mutation returns fresh state, so one helper covers them all. */
  const run = useCallback(async (action) => {
    setError(null)
    try {
      await action()
      const lists = await api.listWatchlists()
      setWatchlists(lists)
      return lists
    } catch (e) {
      setError(e.message)
      return null
    }
  }, [])

  useEffect(() => {
    api
      .listWatchlists()
      .then(setWatchlists)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  // Select the first list once they load, and follow deletions.
  useEffect(() => {
    if (!watchlists.length) setActiveId(null)
    else if (!watchlists.some((w) => w.id === activeId)) setActiveId(watchlists[0].id)
  }, [watchlists, activeId])

  // Quotes refresh on a timer as well as whenever the symbol set changes.
  const symbols = active ? active.items.map((i) => i.symbol).join(',') : ''
  useEffect(() => {
    if (!symbols) {
      setQuotes([])
      return
    }
    let cancelled = false
    const load = async () => {
      setQuotesBusy(true)
      try {
        const fresh = await api.getQuotes(symbols.split(','))
        if (!cancelled) setQuotes(fresh)
      } catch (e) {
        if (!cancelled) setError(e.message)
      } finally {
        if (!cancelled) setQuotesBusy(false)
      }
    }
    load()
    const timer = setInterval(load, REFRESH_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [symbols])

  const addSymbol = async (e) => {
    e.preventDefault()
    const ticker = symbol.trim().toUpperCase()
    if (!ticker || !active) return
    setSymbol('')
    await run(() => api.addSymbol(active.id, ticker))
  }

  const createList = async (name) => {
    const lists = await run(() => api.createWatchlist(name))
    if (lists?.length) setActiveId(lists[lists.length - 1].id)
  }

  if (loading) {
    return (
      <div className="panel">
        <div className="skeleton">
          <div className="spinner" />
          <div>Loading watchlists…</div>
        </div>
      </div>
    )
  }

  return (
    <div className="stack">
      {error && <div className="error">{error}</div>}

      <div className="panel">
        <WatchlistPicker
          watchlists={watchlists}
          activeId={activeId}
          onSelect={setActiveId}
          onCreate={createList}
          onRename={(id, name) => run(() => api.renameWatchlist(id, name))}
          onDelete={(id) => run(() => api.deleteWatchlist(id))}
        />
      </div>

      {!watchlists.length ? (
        <div className="panel">
          <div className="empty">
            <p>No watchlists yet.</p>
            <p className="muted">Create one above to start tracking a set of symbols.</p>
          </div>
        </div>
      ) : (
        <div className="panel">
          <div className="panel-head">
            <div className="panel-title" style={{ margin: 0 }}>
              {active?.name} — {active?.items.length ?? 0} symbols
            </div>
            <form className="add-symbol" onSubmit={addSymbol}>
              <label className="sr-only" htmlFor="add-symbol">Add a ticker</label>
              <input
                id="add-symbol"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                placeholder="Add ticker…"
                autoComplete="off"
                spellCheck="false"
                maxLength={24}
              />
              <button type="submit" className="btn ghost" disabled={!symbol.trim()}>
                Add
              </button>
            </form>
          </div>

          <WatchlistTable
            items={active?.items ?? []}
            quotes={quotes}
            busy={quotesBusy}
            onAnalyze={onAnalyze}
            onRemove={(s) => run(() => api.removeSymbol(active.id, s))}
          />
        </div>
      )}
    </div>
  )
}
