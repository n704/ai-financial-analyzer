import { useState } from 'react'

/**
 * Collapsible prose describing the chart above it.
 *
 * Open by default: the charts are dense and the whole point of this panel is
 * that a reader who does not already know what a p10/p90 fan is gets told
 * without having to go looking.
 */
export default function ExplainPanel({
  paragraphs,
  title = 'What this chart is telling you',
  defaultOpen = true,
}) {
  const [open, setOpen] = useState(defaultOpen)
  if (!paragraphs?.length) return null

  return (
    <section className="explain">
      <button
        type="button"
        className="explain-head"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="explain-caret" aria-hidden="true">{open ? '▾' : '▸'}</span>
        {title}
      </button>

      {open && (
        <div className="explain-body">
          {paragraphs.map((p) => (
            <div className="explain-para" key={p.title}>
              <h4>{p.title}</h4>
              <p>{p.body}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
