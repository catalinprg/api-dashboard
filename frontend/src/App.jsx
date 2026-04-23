import { useEffect, useState } from 'react'
import { Menu } from 'lucide-react'
import Sidebar from './components/Sidebar.jsx'
import AdminPanel from './components/AdminPanel.jsx'
import AIPanel from './components/AIPanel.jsx'
import HTTPPanel from './components/HTTPPanel.jsx'
import HistoryPanel from './components/HistoryPanel.jsx'
import AuthGate from './components/AuthGate.jsx'
import { api } from './api.js'

const VIEW_LABELS = {
  ai: 'AI API',
  http: 'HTTP / REST',
  history: 'History',
  admin: 'Admin',
}

export default function App() {
  return <AuthGate>{(user) => <Shell user={user} />}</AuthGate>
}

function Shell({ user }) {
  const [view, setView] = useState('ai')
  const [providers, setProviders] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)
  const [navOpen, setNavOpen] = useState(false)

  const reload = async () => {
    try {
      setError(null)
      setRefreshing(true)
      const data = await api.listProviders()
      setProviders(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => { reload() }, [])
  useEffect(() => { setNavOpen(false) }, [view])

  return (
    <div className="flex flex-col md:flex-row h-screen w-screen overflow-hidden">
      <header className="md:hidden flex items-center gap-2 bg-ink-900 border-b border-ink-700 px-3 py-2.5 shrink-0 shadow-panel">
        <button
          onClick={() => setNavOpen(true)}
          className="w-10 h-10 flex items-center justify-center rounded-md text-ink-200 hover:bg-ink-800 active:bg-ink-700"
          aria-label="Open menu"
        >
          <Menu className="w-5 h-5" />
        </button>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-ink-100 truncate">{VIEW_LABELS[view] || 'API Dashboard'}</div>
        </div>
      </header>

      <Sidebar
        view={view}
        setView={(v) => { setView(v); setNavOpen(false) }}
        providerCount={providers.length}
        navOpen={navOpen}
        onClose={() => setNavOpen(false)}
        user={user}
        onRefresh={reload}
        refreshing={refreshing}
      />

      <main className="flex-1 min-w-0 overflow-hidden flex flex-col bg-ink-950">
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
        ) : view === 'http' ? (
          <HTTPPanel providers={providers} />
        ) : (
          <AIPanel providers={providers} />
        )}
      </main>
    </div>
  )
}
