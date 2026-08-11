import { useEffect, useState } from 'react'
import { THEME_EVENT } from '../theme'

/**
 * A counter that increments on every theme change. Chart effects put it in
 * their dependency array so the canvas is rebuilt with the new palette —
 * lightweight-charts reads colours once at creation and cannot follow CSS.
 */
export function useThemeVersion() {
  const [version, setVersion] = useState(0)

  useEffect(() => {
    const bump = () => setVersion((v) => v + 1)
    window.addEventListener(THEME_EVENT, bump)
    // Also follow the OS when the user is on "match system".
    const mq = typeof matchMedia === 'function' ? matchMedia('(prefers-color-scheme: dark)') : null
    mq?.addEventListener?.('change', bump)
    return () => {
      window.removeEventListener(THEME_EVENT, bump)
      mq?.removeEventListener?.('change', bump)
    }
  }, [])

  return version
}
