/**
 * Theme resolution, kept out of React so the stored choice can be applied
 * before first paint (see main.jsx) rather than flashing the wrong palette.
 */
const KEY = 'afa.theme'
export const THEMES = ['system', 'light', 'dark']

export function storedTheme() {
  const value = localStorage.getItem(KEY)
  return THEMES.includes(value) ? value : 'system'
}

export function systemPrefersDark() {
  return typeof matchMedia === 'function' ? matchMedia('(prefers-color-scheme: dark)').matches : true
}

export const THEME_EVENT = 'afa:themechange'

/** 'system' leaves the attribute off so the CSS media query decides. */
export function applyTheme(theme) {
  if (theme === 'system') document.documentElement.removeAttribute('data-theme')
  else document.documentElement.setAttribute('data-theme', theme)
  localStorage.setItem(KEY, theme)
  // Charts paint to a canvas and cannot observe CSS variables, so they listen
  // for this and rebuild with the new palette.
  window.dispatchEvent(new CustomEvent(THEME_EVENT, { detail: resolvedTheme(theme) }))
  return theme
}

export const resolvedTheme = (theme) =>
  theme === 'system' ? (systemPrefersDark() ? 'dark' : 'light') : theme
