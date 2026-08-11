import { fmtNum } from '../utils'

/**
 * Correlation heatmap as a CSS grid — no charting library needed for an n×n of
 * at most 6. Colour encodes sign and strength; the number is always printed, so
 * the cell never depends on colour alone to be readable.
 */
export default function CorrelationMatrix({ correlations }) {
  const { symbols, values } = correlations ?? {}
  if (!symbols?.length) return null

  const shade = (v) => {
    if (v == null) return 'transparent'
    const strength = Math.min(Math.abs(v), 1) * 55
    return `color-mix(in srgb, var(${v >= 0 ? '--pos' : '--neg'}) ${strength}%, transparent)`
  }

  return (
    <div className="table-scroll">
      <table className="table matrix" aria-label="Correlation of returns">
        <caption className="sr-only">
          Correlation of returns between each pair of symbols
        </caption>
        <thead>
          <tr>
            <th scope="col"><span className="sr-only">Symbol</span></th>
            {symbols.map((s) => (
              <th scope="col" key={s} className="num">{s}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {symbols.map((row, i) => (
            <tr key={row}>
              <th scope="row">{row}</th>
              {symbols.map((col, j) => (
                <td key={col} className="num cell" style={{ background: shade(values[i][j]) }}>
                  {values[i][j] == null ? '—' : fmtNum(values[i][j])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
