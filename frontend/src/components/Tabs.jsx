/** Top-level view switcher. Arrow keys move between tabs, per the ARIA pattern. */
export default function Tabs({ tabs, active, onSelect }) {
  const onKeyDown = (e) => {
    const delta = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
    if (!delta) return
    e.preventDefault()
    const i = tabs.findIndex((t) => t.id === active)
    onSelect(tabs[(i + delta + tabs.length) % tabs.length].id)
  }

  return (
    <nav className="tabs" role="tablist" aria-label="Views" onKeyDown={onKeyDown}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          id={`tab-${tab.id}`}
          aria-selected={tab.id === active}
          aria-controls={`panel-${tab.id}`}
          tabIndex={tab.id === active ? 0 : -1}
          className={`tab ${tab.id === active ? 'active' : ''}`}
          onClick={() => onSelect(tab.id)}
        >
          {tab.icon && <span aria-hidden="true">{tab.icon}</span>}
          {tab.label}
        </button>
      ))}
    </nav>
  )
}
