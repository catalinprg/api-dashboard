import { useEffect, useMemo, useState } from 'react'
import { Copy, Check, Trash2, RefreshCw } from 'lucide-react'
import { api } from '../api.js'

export default function WebhookPanel() {
  const [webhooks, setWebhooks] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeId, setActiveId] = useState(null)

  const reload = async () => {
    try {
      setError(null)
      setWebhooks(await api.listWebhooks())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { reload() }, [])

  const create = async () => {
    const name = prompt('Webhook name (e.g. "GitHub push"):', '')
    if (name === null) return
    const w = await api.createWebhook({ name: name || '', notes: '' })
    await reload()
    setActiveId(w.id)
  }

  const remove = async (w) => {
    if (!confirm(`Delete webhook "${w.name || w.slug}" and all its recorded events?`)) return
    await api.deleteWebhook(w.id)
    if (activeId === w.id) setActiveId(null)
    await reload()
  }

  const active = useMemo(() => webhooks.find((w) => w.id === activeId), [webhooks, activeId])

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-7xl mx-auto px-4 md:px-6 py-4 md:py-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4 md:mb-6">
          <div>
            <h1 className="text-lg md:text-xl font-semibold">Webhooks</h1>
            <p className="text-xs md:text-sm text-ink-400 mt-0.5 md:mt-1">Inbound test endpoints — point Stripe, GitHub, etc. at these URLs and inspect what they send.</p>
          </div>
          <button className="btn-primary" onClick={create}>+ New webhook</button>
        </div>

        {error && <div className="text-sm text-red-700 bg-red-600/10 border border-red-600/30 rounded-md p-2 mb-3">{error}</div>}

        {loading ? (
          <div className="card p-10 text-center text-ink-400 text-sm">Loading…</div>
        ) : webhooks.length === 0 ? (
          <div className="card p-10 text-center text-ink-400 text-sm">
            No webhooks yet. <button className="underline text-accent" onClick={create}>Create the first one →</button>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-1 space-y-2 min-w-0">
              {webhooks.map((w) => (
                <WebhookRow key={w.id} w={w} active={activeId === w.id} onSelect={() => setActiveId(w.id)} onDelete={() => remove(w)} />
              ))}
            </div>
            <div className="lg:col-span-2 min-w-0">
              {active ? <WebhookDetail webhook={active} onChanged={reload} /> : <div className="card p-10 text-center text-ink-400 text-sm">Pick a webhook to see the inbound events.</div>}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function WebhookRow({ w, active, onSelect, onDelete }) {
  return (
    <div className={`card p-3 cursor-pointer transition ${active ? 'border-accent ring-1 ring-accent/40' : 'hover:border-ink-600'}`} onClick={onSelect}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-semibold truncate">{w.name || w.slug}</div>
          <div className="text-[11px] text-ink-400 font-mono truncate">/hook/{w.slug}</div>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onDelete() }}
          className="text-ink-400 hover:text-red-700 shrink-0 w-8 h-8 flex items-center justify-center"
          title="Delete webhook"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
      <div className="text-[11px] text-ink-400 mt-1 flex items-center gap-2">
        <span>{w.event_count} event{w.event_count === 1 ? '' : 's'}</span>
        {!w.enabled && <span className="pill bg-ink-700 text-ink-400">disabled</span>}
      </div>
    </div>
  )
}

function WebhookDetail({ webhook, onChanged }) {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [openId, setOpenId] = useState(null)

  const reload = async () => {
    setLoading(true)
    try {
      setEvents(await api.listWebhookEvents(webhook.id, 100))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { reload() }, [webhook.id])

  const clear = async () => {
    if (!confirm('Delete all recorded events for this webhook?')) return
    await api.clearWebhookEvents(webhook.id)
    await reload()
    await onChanged()
  }

  const fullUrl = `${window.location.origin}/hook/${webhook.slug}`

  return (
    <div className="space-y-3">
      <div className="card p-4 space-y-3">
        <div>
          <label className="label">Receiver URL</label>
          <div className="flex items-center gap-2">
            <code className="flex-1 min-w-0 truncate font-mono text-xs bg-white border border-ink-700 rounded-md px-2 py-2">{fullUrl}</code>
            <CopyBtn text={fullUrl} />
          </div>
          <p className="text-[11px] text-ink-400 mt-1">Any HTTP method works. Subpaths and query strings are captured.</p>
        </div>
      </div>

      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold">Recent events</div>
        <div className="flex gap-2">
          <button className="btn-ghost text-xs" onClick={reload} title="Refresh">
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
          {events.length > 0 && (
            <button className="btn-ghost text-xs text-red-700" onClick={clear}>Clear all</button>
          )}
        </div>
      </div>

      {loading ? (
        <div className="card p-8 text-center text-ink-400 text-sm">Loading…</div>
      ) : events.length === 0 ? (
        <div className="card p-8 text-center text-ink-400 text-sm">
          Waiting for the first request. Send one to <span className="font-mono">{fullUrl}</span>.
        </div>
      ) : (
        <div className="space-y-2">
          {events.map((e) => (
            <EventRow key={e.id} event={e} open={openId === e.id} onToggle={() => setOpenId(openId === e.id ? null : e.id)} onDeleted={() => { setEvents((xs) => xs.filter((x) => x.id !== e.id)); onChanged() }} />
          ))}
        </div>
      )}
    </div>
  )
}

function EventRow({ event, open, onToggle, onDeleted }) {
  const remove = async (ev) => {
    ev.stopPropagation()
    await api.deleteWebhookEvent(event.id)
    onDeleted()
  }
  const when = formatWhen(event.received_at)
  return (
    <div className="card overflow-hidden">
      <button className="w-full p-3 text-left hover:bg-ink-800 transition" onClick={onToggle}>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="pill bg-accent/15 text-accent">{event.method}</span>
          <span className="text-xs text-ink-400 font-mono truncate">{event.path || '/'}</span>
          {event.query_string && <span className="text-[11px] text-ink-400 font-mono">?{event.query_string}</span>}
          <button onClick={remove} className="ml-auto text-ink-400 hover:text-red-700 w-7 h-7 flex items-center justify-center" title="Delete">
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
        <div className="text-[11px] text-ink-400 mt-1 flex items-center gap-3 flex-wrap">
          <span>{when}</span>
          {event.source_ip && <span className="font-mono">{event.source_ip}</span>}
          {event.content_type && <span className="font-mono truncate">{event.content_type}</span>}
        </div>
      </button>
      {open && (
        <div className="border-t border-ink-700 p-3 space-y-2 bg-white/40">
          <Section title="Headers">
            <pre className="text-[11px] font-mono text-ink-100 bg-white border border-ink-700 rounded-md p-2 overflow-auto max-h-48 whitespace-pre-wrap break-words">
              {Object.entries(event.headers || {}).map(([k, v]) => `${k}: ${v}`).join('\n')}
            </pre>
          </Section>
          <Section title="Body">
            <pre className="text-[11px] font-mono text-ink-100 bg-white border border-ink-700 rounded-md p-2 overflow-auto max-h-80 whitespace-pre-wrap break-words">
              {formatBody(event.body, event.content_type)}
            </pre>
          </Section>
        </div>
      )}
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div>
      <div className="text-xs text-ink-400 font-medium mb-1">{title}</div>
      {children}
    </div>
  )
}

function CopyBtn({ text }) {
  const [ok, setOk] = useState(false)
  const go = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setOk(true)
      setTimeout(() => setOk(false), 1200)
    } catch {}
  }
  return (
    <button onClick={go} className="btn-secondary shrink-0 px-3" title="Copy URL">
      {ok ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
    </button>
  )
}

function formatBody(body, contentType) {
  if (!body) return '(empty)'
  if ((contentType || '').includes('json')) {
    try { return JSON.stringify(JSON.parse(body), null, 2) } catch { /* fall through */ }
  }
  return body
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
