import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import CorrelationMatrix from '../components/CorrelationMatrix'

const CORRELATIONS = {
  symbols: ['AAPL', 'MSFT', 'NVDA'],
  values: [
    [1, 0.82, 0.61],
    [0.82, 1, 0.55],
    [0.61, 0.55, 1],
  ],
}

describe('CorrelationMatrix', () => {
  it('renders an n by n grid', () => {
    render(<CorrelationMatrix correlations={CORRELATIONS} />)
    // 3 data rows + header
    expect(screen.getAllByRole('row')).toHaveLength(4)
    expect(screen.getAllByRole('columnheader')).toHaveLength(4) // + corner
  })

  it('puts 1.00 down the diagonal', () => {
    render(<CorrelationMatrix correlations={CORRELATIONS} />)
    const row = screen.getByRole('row', { name: /^AAPL/ })
    expect(within(row).getAllByRole('cell')[0]).toHaveTextContent('1.00')
  })

  it('is symmetric', () => {
    render(<CorrelationMatrix correlations={CORRELATIONS} />)
    const aapl = within(screen.getByRole('row', { name: /^AAPL/ })).getAllByRole('cell')
    const msft = within(screen.getByRole('row', { name: /^MSFT/ })).getAllByRole('cell')
    expect(aapl[1]).toHaveTextContent('0.82')
    expect(msft[0]).toHaveTextContent('0.82')
  })

  it('always prints the number, never colour alone', () => {
    render(<CorrelationMatrix correlations={CORRELATIONS} />)
    for (const cell of screen.getAllByRole('cell')) {
      expect(cell.textContent.trim()).toMatch(/^-?\d/)
    }
  })

  it('shows a dash for an undefined correlation', () => {
    render(
      <CorrelationMatrix
        correlations={{ symbols: ['A', 'B'], values: [[1, null], [null, 1]] }}
      />,
    )
    expect(screen.getAllByText('—')).toHaveLength(2)
  })

  it('renders nothing without data', () => {
    const { container } = render(<CorrelationMatrix correlations={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })
})
