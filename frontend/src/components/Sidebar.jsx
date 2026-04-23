import { useState } from 'react'
import { LayoutGrid, X, Sparkles, Globe, Braces, Webhook, Clock, Settings, RefreshCw } from 'lucide-react'
import { api } from '../api.js'

export default function Sidebar({ view, setView, providerCount, navOpen, onClose, user, onRefresh, refreshing }) {
  const [spinOnce, setSpinOnce] = useState(false)
  const logout = async () => {
    try { await api.authLogout() } catch {}
    window.location.href = '/login'
  }
  const handleRefresh = async () => {
    if (!onRefresh) return
    setSpinOnce(true)
    try { await onRefresh() } finally {
      setTimeout(() => setSpinOnce(false), 400)
    }
  }
  const items = [
    { id: 'ai', label: 'AI API', icon: Sparkles, hint: 'LLM chat & compare' },
    { id: 'http', label: 'HTTP / REST', icon: Globe, hint: 'Call any endpoint' },
    { id: 'graphql', label: 'GraphQL', icon: Braces, hint: 'Query GraphQL APIs' },
    { id: 'webhooks', label: 'Webhooks', icon: Webhook, hint: 'Inbound event capture' },
    { id: 'history', label: 'History', icon: Clock, hint: 'Past requests' },
    { id: 'admin', label: 'Admin', icon: Settings, hint: 'Configure providers' },
  ]

  const isSpinning = refreshing || spinOnce

  return (
    <>
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
          bg-ink-900 border-r border-ink-700 flex flex-col shadow-panel-lg md:shadow-none
          transform transition-transform duration-200 ease-out
          ${navOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0
        `}
      >
        <div className="px-5 py-5 border-b border-ink-700 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-md bg-gradient-to-br from-accent to-purple-500 flex items-center justify-center shadow-panel">
              <LayoutGrid className="w-4 h-4 text-white" strokeWidth={2.5} />
            </div>
            <div>
              <div className="font-semibold text-sm text-ink-100">API Dashboard</div>
              <div className="text-[11px] text-ink-400">v0.1.0</div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="md:hidden w-9 h-9 flex items-center justify-center rounded-md hover:bg-ink-800"
            aria-label="Close menu"
          >
            <X className="w-5 h-5" />
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
                  active
                    ? 'bg-accent/15 text-accent border border-accent/30 shadow-panel'
                    : 'text-ink-200 hover:bg-ink-800 hover:text-ink-100 active:bg-ink-700 border border-transparent'
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
          <div className="flex items-center justify-between gap-2">
            <span>{providerCount} provider{providerCount === 1 ? '' : 's'} configured</span>
            {onRefresh && (
              <button
                onClick={handleRefresh}
                disabled={isSpinning}
                className="w-7 h-7 flex items-center justify-center rounded-md text-ink-400 hover:text-ink-100 hover:bg-ink-800 disabled:opacity-60"
                aria-label="Refresh providers"
                title="Refresh providers"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isSpinning ? 'animate-spin' : ''}`} />
              </button>
            )}
          </div>
        </div>
      </aside>
    </>
  )
}
