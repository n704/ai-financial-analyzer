import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ThemeToggle from '../components/ThemeToggle'
import { applyTheme, resolvedTheme, storedTheme, THEME_EVENT } from '../theme'

const root = () => document.documentElement

describe('theme module', () => {
  it('defaults to system when nothing is stored', () => {
    expect(storedTheme()).toBe('system')
  })

  it('ignores a stored value that is not a known theme', () => {
    localStorage.setItem('afa.theme', 'neon')
    expect(storedTheme()).toBe('system')
  })

  it('stamps the root element for an explicit choice', () => {
    applyTheme('dark')
    expect(root()).toHaveAttribute('data-theme', 'dark')
    applyTheme('light')
    expect(root()).toHaveAttribute('data-theme', 'light')
  })

  it('removes the attribute for system so the media query decides', () => {
    applyTheme('dark')
    applyTheme('system')
    expect(root().hasAttribute('data-theme')).toBe(false)
  })

  it('persists the choice', () => {
    applyTheme('light')
    expect(storedTheme()).toBe('light')
  })

  it('announces the change so charts can rebuild', () => {
    const listener = vi.fn()
    window.addEventListener(THEME_EVENT, listener)
    applyTheme('dark')
    expect(listener).toHaveBeenCalled()
    window.removeEventListener(THEME_EVENT, listener)
  })

  it('resolves system against the OS preference', () => {
    // setup.js stubs matchMedia with matches: false -> light.
    expect(resolvedTheme('system')).toBe('light')
    expect(resolvedTheme('dark')).toBe('dark')
  })
})

describe('ThemeToggle', () => {
  it('cycles system → light → dark → system', async () => {
    render(<ThemeToggle />)
    const button = screen.getByRole('button')

    expect(root().hasAttribute('data-theme')).toBe(false)
    await userEvent.click(button)
    expect(root()).toHaveAttribute('data-theme', 'light')
    await userEvent.click(button)
    expect(root()).toHaveAttribute('data-theme', 'dark')
    await userEvent.click(button)
    expect(root().hasAttribute('data-theme')).toBe(false)
  })

  it('restores the stored theme on mount', () => {
    localStorage.setItem('afa.theme', 'dark')
    render(<ThemeToggle />)
    expect(root()).toHaveAttribute('data-theme', 'dark')
  })

  it('describes the current and next theme for screen readers', () => {
    render(<ThemeToggle />)
    expect(screen.getByRole('button')).toHaveAccessibleName(/Match system.*switch to Light/)
  })

  it('reports the resolved theme to its parent', () => {
    const onChange = vi.fn()
    localStorage.setItem('afa.theme', 'dark')
    render(<ThemeToggle onChange={onChange} />)
    expect(onChange).toHaveBeenCalledWith('dark')
  })
})
