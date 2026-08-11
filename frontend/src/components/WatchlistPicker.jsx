import { useState } from 'react'

/** Switch between watchlists, and create, rename or delete them. */
export default function WatchlistPicker({
  watchlists,
  activeId,
  onSelect,
  onCreate,
  onRename,
  onDelete,
}) {
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const active = watchlists.find((w) => w.id === activeId)

  const submit = (e) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    onCreate(trimmed)
    setName('')
    setCreating(false)
  }

  return (
    <div className="picker">
      <div className="picker-lists">
        {watchlists.map((w) => (
          <button
            key={w.id}
            type="button"
            className={`chip ${w.id === activeId ? 'active' : ''}`}
            aria-current={w.id === activeId}
            onClick={() => onSelect(w.id)}
          >
            {w.name}
            <span className="muted count">{w.items.length}</span>
          </button>
        ))}

        {creating ? (
          <form onSubmit={submit} className="picker-new">
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onBlur={() => !name.trim() && setCreating(false)}
              placeholder="List name"
              aria-label="New watchlist name"
              maxLength={64}
            />
            <button type="submit" className="btn ghost">Create</button>
          </form>
        ) : (
          <button type="button" className="chip" onClick={() => setCreating(true)}>
            + New list
          </button>
        )}
      </div>

      {active && (
        <div className="picker-actions">
          <button
            type="button"
            className="btn ghost"
            onClick={() => {
              const next = window.prompt('Rename this watchlist', active.name)
              if (next?.trim()) onRename(active.id, next.trim())
            }}
          >
            Rename
          </button>
          <button
            type="button"
            className="btn ghost danger"
            onClick={() => {
              if (window.confirm(`Delete "${active.name}" and everything on it?`)) {
                onDelete(active.id)
              }
            }}
          >
            Delete
          </button>
        </div>
      )}
    </div>
  )
}
