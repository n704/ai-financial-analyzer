import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import InfoTip from '../components/InfoTip'
import { GLOSSARY } from '../glossary'

describe('InfoTip', () => {
  it('stays closed until asked', () => {
    render(<InfoTip term="conviction" />)
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('opens on hover', async () => {
    render(<InfoTip term="conviction" />)
    await userEvent.hover(screen.getByRole('button'))
    expect(screen.getByRole('tooltip')).toHaveTextContent(/Mean forecast return divided/)
  })

  it('opens on keyboard focus, not just hover', async () => {
    render(<InfoTip term="conviction" />)
    await userEvent.tab()
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    render(<InfoTip term="conviction" />)
    await userEvent.click(screen.getByRole('button'))
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('stays open after a click, rather than toggling shut behind the hover', async () => {
    render(<InfoTip term="conviction" />)
    const trigger = screen.getByRole('button')
    await userEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
  })

  it('a click pins it open once the pointer leaves', async () => {
    render(<InfoTip term="conviction" />)
    const trigger = screen.getByRole('button')
    await userEvent.click(trigger)
    await userEvent.unhover(trigger)
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
  })

  it('a second click unpins it', async () => {
    render(<InfoTip term="conviction" />)
    const trigger = screen.getByRole('button')
    await userEvent.click(trigger)
    await userEvent.click(trigger)
    await userEvent.unhover(trigger)
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('closes when focus moves away', async () => {
    render(<InfoTip term="conviction" />)
    await userEvent.tab()
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
    await userEvent.tab()
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('describes the trigger for screen readers', () => {
    render(<InfoTip term="var_5" label="value at risk" />)
    expect(screen.getByRole('button')).toHaveAccessibleName('What is value at risk?')
  })

  it('points the trigger at the tooltip once open', async () => {
    render(<InfoTip term="conviction" />)
    const trigger = screen.getByRole('button')
    await userEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-describedby', screen.getByRole('tooltip').id)
  })

  it('accepts inline text instead of a glossary key', async () => {
    render(<InfoTip text="Bespoke explanation." label="this" />)
    await userEvent.hover(screen.getByRole('button'))
    expect(screen.getByRole('tooltip')).toHaveTextContent('Bespoke explanation.')
  })

  it('renders nothing for a term it does not know', () => {
    const { container } = render(<InfoTip term="not_a_real_term" />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('glossary', () => {
  it('defines every term the UI references', () => {
    // Guards against a typo in a `term` prop silently hiding a tooltip.
    for (const term of [
      'p10_p90', 'median_path', 'sampled_paths', 'prob_up', 'conviction', 'dispersion',
      'var_5', 'expected_shortfall', 'max_drawdown', 'forecast_vol', 'realized_vol',
      'mape', 'naive_baseline', 'band_coverage', 'directional_hit', 'rsi', 'sma',
    ]) {
      expect(GLOSSARY[term], term).toBeTruthy()
    }
  })

  it('keeps definitions short enough to read in a tooltip', () => {
    for (const [term, text] of Object.entries(GLOSSARY)) {
      expect(text.length, term).toBeLessThan(320)
    }
  })
})
