import { useEffect, useState } from 'react'
import { applyTheme, resolvedTheme, storedTheme } from '../theme'

const NEXT = { system: 'light', light: 'dark', dark: 'system' }
const ICON = { system: '🖥', light: '☀️', dark: '🌙' }
const LABEL = { system: 'Match system', light: 'Light', dark: 'Dark' }

/**
 * Cycles system → light → dark. `onChange` fires after the attribute lands so
 * charts, which read CSS variables into a canvas, can rebuild themselves.
 */
export default function ThemeToggle({ onChange }) {
  const [theme, setTheme] = useState(storedTheme)

  useEffect(() => {
    applyTheme(theme)
    onChange?.(resolvedTheme(theme))
  }, [theme, onChange])

  return (
    <button
      type="button"
      className="btn ghost icon"
      onClick={() => setTheme(NEXT[theme])}
      title={`Theme: ${LABEL[theme]} — click to change`}
      aria-label={`Theme: ${LABEL[theme]}. Click to switch to ${LABEL[NEXT[theme]]}.`}
    >
      <span aria-hidden="true">{ICON[theme]}</span>
    </button>
  )
}
