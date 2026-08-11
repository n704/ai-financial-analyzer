import { useEffect, useRef, useState } from 'react'
import * as api from '../api'

const DEFAULT_LIST = 'My watchlist'

/**
 * Star button next to the ticker input. Watchlists load on first open rather
 * than on mount, so the analyze screen costs no extra request until used.
 */
export default function AddToWatchlist({ symbol }) {
  const [open, setOpen] = useState(false)
  const [lists, setLists] = useState(null)
  const [status, setStatus] = useState(null)
  const holder = useRef(null)

  const ticker = (symbol || '').trim().toUpperCase()

  useEffect(() => {
    if (!open) return
    const onDown = (e) => !holder.current?.contains(e.target) && setOpen(false)
    const onEsc = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onEsc)
    }
  }, [open])

  const toggle = async () => {
    if (open) return setOpen(false)
    setOpen(true)
    setStatus(null)
    try {
      setLists(await api.listWatchlists())
    } catch (e) {
      setStatus(e.message)
      setLists([])
    }
  }

  const addTo = async (id) => {
    try {
      await api.addSymbol(id, ticker)
      setStatus(`${ticker} added`)
      setOpen(false)
    } catch (e) {
      setStatus(e.message)
    }
  }

  const createAndAdd = async () => {
    try {
      const created = await api.createWatchlist(DEFAULT_LIST)
      await addTo(created.id)
    } catch (e) {
      setStatus(e.message)
    }
  }

  return (
    <div className="star-holder" ref={holder}>
      <button
        type="button"
        className="btn ghost icon"
        onClick={toggle}
        disabled={!ticker}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Add ${ticker || 'this symbol'} to a watchlist`}
        title="Add to a watchlist"
      >
        <span aria-hidden="true">☆</span>
      </button>

      {open && (
        <div className="menu" role="menu">
          {lists === null ? (
            <div className="menu-note muted">Loading…</div>
          ) : lists.length === 0 ? (
            <button type="button" role="menuitem" className="menu-item" onClick={createAndAdd}>
              Create “{DEFAULT_LIST}” and add {ticker}
            </button>
          ) : (
            lists.map((list) => (
              <button
                key={list.id}
                type="button"
                role="menuitem"
                className="menu-item"
                onClick={() => addTo(list.id)}
              >
                {list.name}
                <span className="muted count">{list.items.length}</span>
              </button>
            ))
          )}
          {status && <div className="menu-note muted">{status}</div>}
        </div>
      )}

      {!open && status && (
        <span className="star-status muted" role="status">
          {status}
        </span>
      )}
    </div>
  )
}
