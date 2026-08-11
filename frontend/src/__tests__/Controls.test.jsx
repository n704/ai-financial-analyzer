import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({ listWatchlists: vi.fn(), createWatchlist: vi.fn(), addSymbol: vi.fn() }))

const { default: Controls } = await import('../components/Controls')

const FORM = {
  symbol: 'AAPL',
  interval: '1d',
  lookback: 128,
  horizon: 10,
  paths: 24,
  temperature: 1.0,
  top_p: 0.9,
  seed: null,
  backtest: true,
}

const CONFIG = {
  intervals: [
    { value: '1d', label: 'Daily' },
    { value: '1h', label: 'Hourly' },
  ],
  limits: { max_lookback: 512, max_horizon: 120, max_paths: 64 },
  lookback_warn_above: 200,
}

function setup(over = {}) {
  const setForm = vi.fn()
  const onSubmit = vi.fn()
  const props = { form: FORM, setForm, onSubmit, busy: false, config: CONFIG, ...over }
  const view = render(<Controls {...props} />)
  return { setForm, onSubmit, view, props }
}

/** setForm is called with an updater; apply it to see the resulting form. */
const applied = (setForm, form = FORM) => setForm.mock.calls.at(-1)[0](form)

/**
 * Controls is a controlled component, so a mocked setForm leaves its inputs
 * frozen and typing accumulates against a stale value. Anything that types
 * into a field needs real state behind it.
 */
function Stateful({ initial = FORM, onForm, ...props }) {
  const [form, setForm] = useState(initial)
  onForm.current = form
  return <Controls form={form} setForm={setForm} onSubmit={() => {}} busy={false} config={CONFIG} {...props} />
}

function setupStateful(initial = FORM) {
  const onForm = { current: initial }
  render(<Stateful initial={initial} onForm={onForm} />)
  return onForm
}

beforeEach(() => vi.clearAllMocks())

describe('Controls — primary row', () => {
  it('shows only ticker, interval and Evaluate up front', () => {
    setup()
    expect(screen.getByLabelText('Ticker')).toBeInTheDocument()
    expect(screen.getByLabelText('Interval')).toBeInTheDocument()
    expect(screen.queryByRole('spinbutton', { name: /Lookback/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('spinbutton', { name: /Top-p/ })).not.toBeInTheDocument()
  })

  it('submits the form', async () => {
    const { onSubmit } = setup()
    await userEvent.click(screen.getByRole('button', { name: 'Evaluate' }))
    expect(onSubmit).toHaveBeenCalled()
  })

  it('is disabled while the model is still loading', () => {
    setup({ modelState: 'loading' })
    const button = screen.getByRole('button', { name: /Loading model/ })
    expect(button).toBeDisabled()
  })

  it('is disabled before the backend answers', () => {
    setup({ modelState: 'connecting' })
    expect(screen.getByRole('button', { name: /Loading model/ })).toBeDisabled()
  })

  it('is enabled once the model is ready', () => {
    setup({ modelState: 'ready' })
    expect(screen.getByRole('button', { name: 'Evaluate' })).toBeEnabled()
  })

  it('reports its own in-flight request', () => {
    setup({ busy: true, modelState: 'ready' })
    expect(screen.getByRole('button', { name: 'Forecasting…' })).toBeDisabled()
  })
})

describe('Controls — presets', () => {
  it('offers three presets', () => {
    setup()
    for (const label of ['Conservative', 'Balanced', 'Exploratory']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
    }
  })

  it('sets lookback, horizon and paths together', async () => {
    const { setForm } = setup()
    await userEvent.click(screen.getByRole('button', { name: 'Conservative' }))
    expect(applied(setForm)).toMatchObject({ lookback: 64, horizon: 5, paths: 24 })
  })

  it('marks the preset matching the current form', () => {
    setup()
    expect(screen.getByRole('button', { name: 'Balanced' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Conservative' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
  })

  it('marks none when the form matches no preset', () => {
    setup({ form: { ...FORM, lookback: 300, horizon: 7 } })
    for (const label of ['Conservative', 'Balanced', 'Exploratory']) {
      expect(screen.getByRole('button', { name: label })).toHaveAttribute('aria-pressed', 'false')
    }
  })

  it('sets the ticker from an example chip', async () => {
    const { setForm } = setup()
    await userEvent.click(screen.getByRole('button', { name: 'BTC-USD' }))
    expect(applied(setForm)).toMatchObject({ symbol: 'BTC-USD' })
  })
})

describe('Controls — advanced disclosure', () => {
  it('starts collapsed', () => {
    setup()
    expect(screen.getByRole('button', { name: /Advanced/ })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
  })

  it('reveals every remaining parameter', async () => {
    setup()
    await userEvent.click(screen.getByRole('button', { name: /Advanced/ }))
    for (const name of [/Lookback/, /Horizon/, /Paths/, /Temperature/, /Top-p/, /Seed/]) {
      expect(screen.getByRole('spinbutton', { name })).toBeInTheDocument()
    }
    expect(screen.getByRole('checkbox', { name: /Hold-out backtest/ })).toBeInTheDocument()
  })

  it('collapses again', async () => {
    setup()
    const toggle = screen.getByRole('button', { name: /Advanced/ })
    await userEvent.click(toggle)
    await userEvent.click(toggle)
    expect(screen.queryByRole('spinbutton', { name: /Lookback/ })).not.toBeInTheDocument()
  })

  it('edits a parameter', async () => {
    const form = setupStateful()
    await userEvent.click(screen.getByRole('button', { name: /Advanced/ }))
    const horizon = screen.getByRole('spinbutton', { name: /Horizon/ })
    await userEvent.clear(horizon)
    await userEvent.type(horizon, '20')
    expect(horizon).toHaveValue(20)
    expect(form.current.horizon).toBe(20)
  })

  it('sets a seed for a reproducible forecast', async () => {
    const form = setupStateful()
    await userEvent.click(screen.getByRole('button', { name: /Advanced/ }))
    await userEvent.type(screen.getByRole('spinbutton', { name: /Seed/ }), '7')
    expect(form.current.seed).toBe(7)
  })

  it('clears the seed back to random', async () => {
    const form = setupStateful({ ...FORM, seed: 7 })
    await userEvent.click(screen.getByRole('button', { name: /Advanced/ }))
    await userEvent.clear(screen.getByRole('spinbutton', { name: /Seed/ }))
    expect(form.current.seed).toBeNull()
  })

  it('toggles the hold-out backtest', async () => {
    const form = setupStateful()
    await userEvent.click(screen.getByRole('button', { name: /Advanced/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: /Hold-out backtest/ }))
    expect(form.current.backtest).toBe(false)
  })

  it('respects the limits the backend reports', async () => {
    setup()
    await userEvent.click(screen.getByRole('button', { name: /Advanced/ }))
    expect(screen.getByRole('spinbutton', { name: /Lookback/ })).toHaveAttribute('max', '512')
    expect(screen.getByRole('spinbutton', { name: /Paths/ })).toHaveAttribute('max', '64')
  })
})

describe('Controls — lookback warning', () => {
  it('warns above the threshold on daily bars', () => {
    setup({ form: { ...FORM, lookback: 400 } })
    expect(screen.getByText(/scored worst in walk-forward testing/)).toBeInTheDocument()
  })

  it('stays quiet at the default', () => {
    setup()
    expect(screen.queryByText(/scored worst/)).not.toBeInTheDocument()
  })

  it('does not warn on intraday bars, where the finding does not apply', () => {
    setup({ form: { ...FORM, lookback: 400, interval: '1h' } })
    expect(screen.queryByText(/scored worst/)).not.toBeInTheDocument()
  })
})

describe('Controls — recent symbols', () => {
  it('offers nothing before anything has been evaluated', () => {
    const { view } = setup()
    expect(view.container.querySelector('#recent-symbols')).toBeNull()
  })

  it('remembers the ticker on submit and offers it next time', async () => {
    const { onSubmit } = setup({ form: { ...FORM, symbol: 'nvda' } })
    await userEvent.click(screen.getByRole('button', { name: 'Evaluate' }))
    expect(onSubmit).toHaveBeenCalled()

    const { view } = setup()
    expect(view.container.querySelector('#recent-symbols option[value="NVDA"]')).not.toBeNull()
  })
})
