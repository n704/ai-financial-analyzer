import { useCallback, useEffect, useRef, useState } from 'react'
import { getConfig, getHealth } from './api'
import Tabs from './components/Tabs'
import ThemeToggle from './components/ThemeToggle'
import { useHashRoute } from './hooks/useHashRoute'
import AnalyzeView from './views/AnalyzeView'
import WatchlistView from './views/WatchlistView'

/**
 * Views registered here appear in the tab bar. A later PR adds compare; the
 * bar hides itself while there is only one.
 */
const VIEWS = [
  { id: 'analyze', label: 'Analyze', icon: '📈' },
  { id: 'watchlist', label: 'Watchlist', icon: '⭐' },
]

function ModelStatus({ health }) {
  const state = health?.state ?? 'connecting'
  return (
    <div className="model-status" title={health?.error ?? ''}>
      <span className={`dot ${state}`} />
      {state === 'ready' ? (
        <>
          Kronos-{health.model} · {health.params} · {health.device}
          {health.load_seconds ? ` · loaded in ${health.load_seconds}s` : ''}
        </>
      ) : state === 'loading' ? (
        'Loading model weights…'
      ) : state === 'error' ? (
        `Model error: ${health.error}`
      ) : (
        'Connecting to backend…'
      )}
    </div>
  )
}

export default function App() {
  const [config, setConfig] = useState(null)
  const [health, setHealth] = useState(null)
  const [configError, setConfigError] = useState(null)
  const { view, params, navigate } = useHashRoute()
  const timer = useRef(null)

  useEffect(() => {
    getConfig().then(setConfig).catch((e) => setConfigError(e.message))
  }, [])

  // Poll while the model is still downloading/initialising.
  useEffect(() => {
    const tick = async () => {
      try {
        const h = await getHealth()
        setHealth(h.model)
        if (h.model.state === 'ready' || h.model.state === 'error') {
          clearInterval(timer.current)
        }
      } catch {
        /* server not up yet */
      }
    }
    tick()
    timer.current = setInterval(tick, 2500)
    return () => clearInterval(timer.current)
  }, [])

  const setSymbol = useCallback(
    (symbol) => navigate('analyze', { ...params, symbol }),
    [navigate, params],
  )

  const active = VIEWS.some((v) => v.id === view) ? view : 'analyze'

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <h1>📈 AI Financial Analyzer</h1>
          <span>Kronos foundation model for financial K-lines</span>
        </div>
        <div className="header-actions">
          <ModelStatus health={health} />
          <ThemeToggle />
        </div>
      </header>

      {VIEWS.length > 1 && (
        <Tabs tabs={VIEWS} active={active} onSelect={(id) => navigate(id, params)} />
      )}

      {configError && <div className="error">{configError}</div>}

      <div role="tabpanel" id={`panel-${active}`} aria-labelledby={`tab-${active}`}>
        {active === 'analyze' && (
          <AnalyzeView config={config} symbol={params.symbol} onSymbolChange={setSymbol} />
        )}
        {active === 'watchlist' && <WatchlistView onAnalyze={setSymbol} />}
      </div>
    </div>
  )
}
