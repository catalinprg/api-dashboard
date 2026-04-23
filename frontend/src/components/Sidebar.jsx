import { api } from '../api.js'

export default function Sidebar({ view, setView, providerCount, navOpen, onClose, user }) {
  const logout = async () => {
    try { await api.authLogout() } catch {}
    window.location.href = '/login'
  }
  const items = [
    { id: 'playground', label: 'Playground', icon: Play, hint: 'Test APIs' },
    { id: 'history', label: 'History', icon: Clock, hint: 'Past requests' },
    { id: 'admin', label: 'Admin', icon: Cog, hint: 'Configure providers' },
  ]

  return (
    <>
      {/* Overlay for mobile drawer */}
      {navOpen && (
        <button
          aria-label="Close menu"
          onClick={onClose}
          className="md:hidden fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
        />
      )}

      <aside
        className={`
          fixed md:static inset-y-0 left-0 z-50 w-72 md:w-64 shrink-0
          bg-ink-900 border-r border-ink-700 flex flex-col
          transform transition-transform duration-200 ease-out
          ${navOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0
        `}
      >
        <div className="px-5 py-5 border-b border-ink-700 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-md bg-gradient-to-br from-accent to-purple-500 flex items-center justify-center">
              <svg viewBox="0 0 24 24" className="w-5 h-5 text-white" fill="currentColor">
                <path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" />
              </svg>
            </div>
            <div>
              <div className="font-semibold text-sm">API Dashboard</div>
              <div className="text-[11px] text-ink-400">v0.1.0</div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="md:hidden w-9 h-9 flex items-center justify-center rounded-md hover:bg-ink-800"
            aria-label="Close menu"
          >
            <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {items.map((it) => {
            const active = view === it.id
            const Icon = it.icon
            return (
              <button
                key={it.id}
                onClick={() => setView(it.id)}
                className={`w-full flex items-center gap-3 px-3 py-3 rounded-md text-sm transition ${
                  active ? 'bg-accent/15 text-accent border border-accent/30' : 'text-slate-700 hover:bg-ink-800 hover:text-slate-900 active:bg-ink-700 border border-transparent'
                }`}
              >
                <Icon className="w-4 h-4 shrink-0" />
                <div className="flex-1 text-left min-w-0">
                  <div className="font-medium">{it.label}</div>
                  <div className="text-[11px] text-ink-400 truncate">{it.hint}</div>
                </div>
              </button>
            )
          })}
        </nav>
        <div className="px-4 py-3 border-t border-ink-700 text-[11px] text-ink-400 space-y-2">
          {user && !user.auth_disabled && (
            <div className="flex items-center justify-between gap-2">
              <span className="truncate" title={user.email || user.login}>{user.login ? `@${user.login}` : user.email}</span>
              <button
                onClick={logout}
                className="text-ink-400 hover:text-red-700 underline-offset-2 hover:underline"
                title="Sign out"
              >
                sign out
              </button>
            </div>
          )}
          <div>{providerCount} provider{providerCount === 1 ? '' : 's'} configured</div>
        </div>
      </aside>
    </>
  )
}

function Play(props) {
  return <svg {...props} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3" /></svg>
}
function Clock(props) {
  return <svg {...props} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
}
function Cog(props) {
  return <svg {...props} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h0a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h0a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
}
