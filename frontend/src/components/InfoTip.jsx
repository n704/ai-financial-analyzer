import { useEffect, useId, useRef, useState } from 'react'
import { define } from '../glossary'

/**
 * A small ⓘ that explains one term. Opens on hover *and* on focus, and closes
 * on Escape, so it is reachable without a mouse — a tooltip that only responds
 * to hover is invisible to keyboard and touch users.
 */
export default function InfoTip({ term, text, label }) {
  // Hover and pin are tracked separately on purpose. With one flag, a click
  // after a hover would toggle the already-open tip shut — and on touch, where
  // a tap synthesises a hover first, the tip would never open at all.
  const [hovered, setHovered] = useState(false)
  const [pinned, setPinned] = useState(false)
  const id = useId()
  const holder = useRef(null)
  const body = text ?? define(term)
  const open = hovered || pinned

  useEffect(() => {
    if (!open) return
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      setPinned(false)
      setHovered(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  if (!body) return null

  return (
    <span
      className="infotip"
      ref={holder}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <button
        type="button"
        className="infotip-trigger"
        aria-label={`What is ${label ?? term}?`}
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onFocus={() => setHovered(true)}
        onBlur={() => {
          setHovered(false)
          setPinned(false)
        }}
        onClick={() => setPinned((v) => !v)}
      >
        <span aria-hidden="true">ⓘ</span>
      </button>
      {open && (
        <span role="tooltip" id={id} className="infotip-body">
          {body}
        </span>
      )}
    </span>
  )
}
