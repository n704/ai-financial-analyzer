import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import Tabs from '../components/Tabs'

const TABS = [
  { id: 'analyze', label: 'Analyze', icon: '📈' },
  { id: 'watchlist', label: 'Watchlist', icon: '⭐' },
  { id: 'compare', label: 'Compare', icon: '⚖️' },
]

const setup = (active = 'analyze') => {
  const onSelect = vi.fn()
  render(<Tabs tabs={TABS} active={active} onSelect={onSelect} />)
  return onSelect
}

describe('Tabs', () => {
  it('renders every tab', () => {
    setup()
    expect(screen.getAllByRole('tab')).toHaveLength(3)
  })

  it('marks only the active tab as selected', () => {
    setup('watchlist')
    expect(screen.getByRole('tab', { name: /Watchlist/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: /Analyze/ })).toHaveAttribute('aria-selected', 'false')
  })

  it('selects on click', async () => {
    const onSelect = setup()
    await userEvent.click(screen.getByRole('tab', { name: /Compare/ }))
    expect(onSelect).toHaveBeenCalledWith('compare')
  })

  it('moves right with the arrow key', async () => {
    const onSelect = setup('analyze')
    screen.getByRole('tab', { name: /Analyze/ }).focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(onSelect).toHaveBeenCalledWith('watchlist')
  })

  it('wraps around at the ends', async () => {
    const onSelect = setup('analyze')
    screen.getByRole('tab', { name: /Analyze/ }).focus()
    await userEvent.keyboard('{ArrowLeft}')
    expect(onSelect).toHaveBeenCalledWith('compare')
  })

  it('keeps only the active tab in the tab order', () => {
    setup('compare')
    expect(screen.getByRole('tab', { name: /Compare/ })).toHaveAttribute('tabindex', '0')
    expect(screen.getByRole('tab', { name: /Analyze/ })).toHaveAttribute('tabindex', '-1')
  })
})
