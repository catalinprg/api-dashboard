import { useEffect, useState } from 'react'
import Sidebar from './components/Sidebar.jsx'
import AdminPanel from './components/AdminPanel.jsx'
import Playground from './components/Playground.jsx'
import HistoryPanel from './components/HistoryPanel.jsx'
import AuthGate from './components/AuthGate.jsx'
import { api } from './api.js'

const VIEW_LABELS = {
  playground: 'Playground',
  history: 'History',
  admin: 'Admin',
}

export default function App() {
  return <AuthGate>{(user) => <Shell user={user} />}</AuthGate>
}

function Shell({ user }) {
  const [view, setView] = useState('playground')
  const [providers, setProviders] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [navOpen, setNavOpen] = useState(false)

  const reload = async () => {
    try {
      setError(null)
      const data = await api.listProviders()
      setProviders(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { reload() }, [])
  useEffect(() => { setNavOpen(false) }, [view])

  return (
    <div className="flex flex-col md:flex-row h-screen w-screen overflow-hidden">
      {/* Mobile top bar */}
      <header className="md:hidden flex items-center gap-3 bg-ink-900 border-b border-ink-700 px-4 py-3 shrink-0">
        <button
          onClick={() => setNavOpen(true)}
          className="w-10 h-10 -ml-2 flex items-center justify-center rounded-md hover:bg-ink-800 active:bg-ink-700"
          aria-label="Open menu"
        >
          <svg viewBox="0 0 24 24" className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold truncate">{VIEW_LABELS[view] || 'API Dashboard'}</div>
        </div>
        <div className="w-7 h-7 rounded-md bg-gradient-to-br from-accent to-purple-500 flex items-center justify-center shrink-0">
          <svg viewBox="0 0 24 24" className="w-4 h-4 text-white" fill="currentColor">
            <path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" />
          </svg>
        </div>
      </header>

      {/* Sidebar — fixed column on ≥md, drawer on mobile */}
      <Sidebar
        view={view}
        setView={(v) => { setView(v); setNavOpen(false) }}
        providerCount={providers.length}
        navOpen={navOpen}
        onClose={() => setNavOpen(false)}
        user={user}
      />

      <main className="flex-1 min-w-0 overflow-hidden flex flex-col">
        {error && (
          <div className="bg-red-100 border-b border-red-300 text-red-800 px-4 md:px-6 py-2 text-sm">
            {error} <button className="underline ml-2" onClick={reload}>retry</button>
          </div>
        )}
        {loading ? (
          <div className="flex-1 flex items-center justify-center text-ink-400">Loading…</div>
        ) : view === 'admin' ? (
          <AdminPanel providers={providers} reload={reload} />
        ) : view === 'history' ? (
          <HistoryPanel />
        ) : (
          <Playground providers={providers} />
        )}
      </main>
    </div>
  )
}
