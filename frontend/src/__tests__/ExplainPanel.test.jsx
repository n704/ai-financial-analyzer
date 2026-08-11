import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import ExplainPanel from '../components/ExplainPanel'

const PARAGRAPHS = [
  { title: 'What the fan is', body: 'The faint lines are 24 sampled futures.' },
  { title: 'Where the median lands', body: 'The median path rises 1.20%.' },
]

describe('ExplainPanel', () => {
  it('renders every paragraph the API supplied', () => {
    render(<ExplainPanel paragraphs={PARAGRAPHS} />)
    expect(screen.getByText('What the fan is')).toBeInTheDocument()
    expect(screen.getByText('The median path rises 1.20%.')).toBeInTheDocument()
  })

  it('is open by default, because the charts need explaining unprompted', () => {
    render(<ExplainPanel paragraphs={PARAGRAPHS} />)
    expect(screen.getByRole('button', { expanded: true })).toBeInTheDocument()
  })

  it('collapses and re-expands on click', async () => {
    render(<ExplainPanel paragraphs={PARAGRAPHS} />)
    const toggle = screen.getByRole('button')

    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('What the fan is')).not.toBeInTheDocument()

    await userEvent.click(toggle)
    expect(screen.getByText('What the fan is')).toBeInTheDocument()
  })

  it('can start collapsed', () => {
    render(<ExplainPanel paragraphs={PARAGRAPHS} defaultOpen={false} />)
    expect(screen.queryByText('What the fan is')).not.toBeInTheDocument()
  })

  it('takes a custom heading', () => {
    render(<ExplainPanel paragraphs={PARAGRAPHS} title="What the hold-out chart says" />)
    expect(screen.getByRole('button', { name: /hold-out chart/ })).toBeInTheDocument()
  })

  it('renders nothing at all when there is nothing to explain', () => {
    const { container } = render(<ExplainPanel paragraphs={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when the field is missing entirely', () => {
    const { container } = render(<ExplainPanel paragraphs={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })
})
