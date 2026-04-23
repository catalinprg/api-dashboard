import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { toCurl } from '../utils/curl.js'

export default function HistoryPanel() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [filter, setFilter] = useState('all') // all | llm | http | ok | error
  const [openId, setOpenId] = useState(null)
  const [search, setSearch] = useState('')

  const reload = async (query = search) => {
    try {
      setErr(null)
      const data = await api.listHistory(500, query)
      setItems(data)
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { reload('') }, [])
  useEffect(() => {
    const t = setTimeout(() => reload(search), 250)
    return () => clearTimeout(t)
  }, [search])

  const filtered = useMemo(() => {
    return items.filter((it) => {
      if (filter === 'http' && it.kind !== 'http') return false
      if (filter === 'graphql' && it.kind !== 'graphql') return false
      if (filter === 'ok' && !it.ok) return false
      if (filter === 'error' && it.ok) return false
      return true
    })
  }, [items, filter])

  const onDelete = async (id, e) => {
    e.stopPropagation()
    await api.deleteHistory(id)
    setItems((xs) => xs.filter((x) => x.id !== id))
  }

  const onClear = async () => {
    if (!confirm('Delete all history entries? This cannot be undone.')) return
    await api.clearHistory()
    setItems([])
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-5xl mx-auto px-4 md:px-6 py-4 md:py-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4 md:mb-6">
          <div>
            <h1 className="text-lg md:text-xl font-semibold">History</h1>
            <p className="text-xs md:text-sm text-ink-400 mt-0.5 md:mt-1">Every request you've sent through the dashboard.</p>
          </div>
          <div className="flex gap-2">
            <button className="btn-secondary text-xs flex-1 sm:flex-none" onClick={reload}>Refresh</button>
            {items.length > 0 && <button className="btn-ghost text-xs text-red-700 hover:bg-red-600/10 flex-1 sm:flex-none" onClick={onClear}>Clear all</button>}
          </div>
        </div>

        <div className="flex flex-col sm:flex-row gap-3 mb-4">
          <input
            className="input w-full sm:max-w-sm"
            placeholder="Search by provider, model, URL…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="flex gap-1 p-1 bg-ink-900 border border-ink-700 rounded-lg overflow-x-auto">
            {[
              ['all', 'All'],
              ['http', 'HTTP'],
              ['graphql', 'GraphQL'],
              ['ok', 'Success'],
              ['error', 'Errors'],
            ].map(([v, label]) => (
              <button
                key={v}
                onClick={() => setFilter(v)}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition shrink-0 ${filter === v ? 'bg-accent text-white' : 'text-ink-400 hover:text-ink-100'}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {err && <div className="text-sm text-red-700 bg-red-600/10 border border-red-600/30 rounded-md p-2 mb-3">{err}</div>}

        {loading ? (
          <div className="card p-10 text-center text-ink-400 text-sm">Loading…</div>
        ) : filtered.length === 0 ? (
          <div className="card p-10 text-center text-ink-400 text-sm">
            {items.length === 0 ? 'No requests yet. Send one from the HTTP or GraphQL panel.' : 'Nothing matches.'}
          </div>
        ) : (
          <div className="space-y-2">
            {filtered.map((it) => (
              <HistoryRow key={it.id} item={it} open={openId === it.id} onToggle={() => setOpenId(openId === it.id ? null : it.id)} onDelete={onDelete} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function HistoryRow({ item, open, onToggle, onDelete }) {
  const when = useMemo(() => formatWhen(item.created_at), [item.created_at])
  return (
    <div className="card overflow-hidden">
      <button className="w-full p-3 md:p-4 text-left hover:bg-ink-800 transition" onClick={onToggle}>
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`pill ${item.ok ? 'bg-emerald-500/15 text-emerald-700' : 'bg-red-500/15 text-red-700'}`}>
            {item.ok ? '● OK' : '● ERR'}
          </span>
          <span className="pill bg-accent/15 text-accent">{item.kind.toUpperCase()}</span>
          <span className="text-sm font-semibold">{item.provider_name || '—'}</span>
          <button
            onClick={(e) => onDelete(item.id, e)}
            className="ml-auto text-ink-400 hover:text-red-700 w-8 h-8 flex items-center justify-center"
            title="Delete"
          >✕</button>
        </div>
        <div className="text-xs text-ink-400 font-mono mt-1 break-all line-clamp-2">{item.label}</div>
        <div className="flex items-center gap-3 text-[11px] text-ink-400 mt-1 flex-wrap">
          <span className="font-mono">status: <span className="text-ink-200">{item.status_code || '—'}</span></span>
          <span className="font-mono">{item.latency_ms}ms</span>
          <span>{when}</span>
        </div>
      </button>
      {open && (
        <div className="border-t border-ink-700 p-4 space-y-3 bg-white/40">
          <div className="flex justify-end">
            <CurlBtn request={item.request} />
          </div>
          <Section title="Request" data={item.request} />
          <Section title="Response" data={item.response} />
        </div>
      )}
    </div>
  )
}

function CurlBtn({ request }) {
  const [copied, setCopied] = useState(false)
  if (!request) return null
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(toCurl(request))
      setCopied(true)
      setTimeout(() => setCopied(false), 1400)
    } catch {}
  }
  return (
    <button onClick={copy} className="btn-secondary text-xs">
      {copied ? 'copied' : 'copy as cURL'}
    </button>
  )
}

function Section({ title, data }) {
  return (
    <details open>
      <summary className="text-xs text-ink-400 font-medium cursor-pointer hover:text-ink-100 mb-1">{title}</summary>
      <pre className="text-[11px] font-mono text-ink-100 bg-white border border-ink-700 rounded-md p-2 overflow-auto max-h-64 whitespace-pre-wrap break-words">
        {JSON.stringify(data, null, 2)}
      </pre>
    </details>
  )
}

function formatWhen(iso) {
  if (!iso) return ''
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'))
  const now = new Date()
  const diff = (now - d) / 1000
  if (diff < 60) return `${Math.max(1, Math.floor(diff))}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return d.toLocaleString()
}
