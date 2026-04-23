import { useRef, useState } from 'react'
import { api } from '../api.js'
import ProviderForm from './ProviderForm.jsx'

export default function AdminPanel({ providers, reload }) {
  const [editing, setEditing] = useState(null)
  const [creating, setCreating] = useState(false)
  const [filter, setFilter] = useState('')
  const [pings, setPings] = useState({})
  const [pinging, setPinging] = useState({})

  const ping = async (p) => {
    setPinging((x) => ({ ...x, [p.id]: true }))
    try {
      const res = await api.pingProvider(p.id)
      setPings((x) => ({ ...x, [p.id]: res }))
    } catch (e) {
      setPings((x) => ({ ...x, [p.id]: { ok: false, status_code: 0, message: e.message } }))
    } finally {
      setPinging((x) => ({ ...x, [p.id]: false }))
    }
  }

  const remove = async (p) => {
    if (!confirm(`Delete provider "${p.name}"? This cannot be undone.`)) return
    await api.deleteProvider(p.id)
    reload()
  }

  const toggle = async (p) => {
    await api.updateProvider(p.id, { enabled: !p.enabled })
    reload()
  }

  const filtered = providers.filter((p) =>
    p.name.toLowerCase().includes(filter.toLowerCase()) ||
    (p.base_url || '').toLowerCase().includes(filter.toLowerCase())
  )

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-5xl mx-auto px-4 md:px-6 py-4 md:py-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4 md:mb-6">
          <div>
            <h1 className="text-lg md:text-xl font-semibold">Providers</h1>
            <p className="text-xs md:text-sm text-ink-400 mt-0.5 md:mt-1">Configure the APIs you want to call from the HTTP and GraphQL panels.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <ExportImport reload={reload} />
            <button className="btn-primary flex-1 sm:flex-none" onClick={() => setCreating(true)}>+ Add provider</button>
          </div>
        </div>

        <div className="mb-4">
          <input
            className="input max-w-md"
            placeholder="Filter providers…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>

        <div className="space-y-2">
          {filtered.length === 0 && (
            <div className="card p-10 text-center text-ink-400 text-sm">
              No providers match. <button className="underline text-accent" onClick={() => setCreating(true)}>Add one →</button>
            </div>
          )}
          {filtered.map((p) => (
            <div key={p.id} className="card p-4 hover:border-ink-600 transition">
              <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="font-semibold">{p.name}</div>
                    <span className={`pill ${p.kind === 'graphql' ? 'bg-accent/15 text-accent' : 'bg-blue-500/15 text-blue-700'}`}>
                      {p.kind === 'graphql' ? 'GraphQL' : 'HTTP'}
                    </span>
                    {p.has_api_key ? (
                      <span className="pill bg-emerald-500/15 text-emerald-700">● key set</span>
                    ) : p.auth_type !== 'none' ? (
                      <span className="pill bg-amber-500/15 text-amber-700">no key</span>
                    ) : null}
                    {!p.enabled && <span className="pill bg-ink-700 text-ink-400">disabled</span>}
                  </div>
                  <div className="text-xs text-ink-400 font-mono mt-1 truncate">{p.base_url || '—'}</div>
                  {p.notes && <div className="text-xs text-ink-400 mt-2">{p.notes}</div>}
                  {pings[p.id] && (
                    <div className={`text-xs mt-2 font-mono ${pings[p.id].ok ? 'text-emerald-700' : 'text-red-700'}`}>
                      {pings[p.id].ok ? '● ' : '✕ '}
                      {pings[p.id].status_code || 'ERR'} · {pings[p.id].latency_ms ?? 0}ms · {pings[p.id].message}
                    </div>
                  )}
                </div>
                <div className="flex gap-1 shrink-0 w-full sm:w-auto">
                  <button className="btn-ghost flex-1 sm:flex-none" onClick={() => toggle(p)} title={p.enabled ? 'Disable' : 'Enable'}>
                    {p.enabled ? '⏸' : '▶'}
                  </button>
                  <button className="btn-secondary flex-1 sm:flex-none" onClick={() => ping(p)} disabled={pinging[p.id]}>
                    {pinging[p.id] ? '…' : 'Ping'}
                  </button>
                  <button className="btn-secondary flex-1 sm:flex-none" onClick={() => setEditing(p)}>Edit</button>
                  <button className="btn-ghost text-red-700 hover:bg-red-600/10 flex-1 sm:flex-none" onClick={() => remove(p)}>Delete</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {(creating || editing) && (
        <ProviderForm
          provider={editing}
          onClose={() => { setCreating(false); setEditing(null) }}
          onSaved={() => { setCreating(false); setEditing(null); reload() }}
        />
      )}
    </div>
  )
}

function ExportImport({ reload }) {
  const fileRef = useRef(null)
  const specRef = useRef(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const onSpecPick = async (e) => {
    const f = e.target.files?.[0]
    if (!f) return
    setBusy(true); setMsg('')
    try {
      const text = await f.text()
      const json = JSON.parse(text)
      const res = await api.importSpec(json)
      setMsg(`Imported ${res.detected}: ${res.endpoint_count} endpoint${res.endpoint_count === 1 ? '' : 's'}.`)
      reload()
    } catch (err) {
      setMsg(err.message || 'Import failed')
    } finally {
      setBusy(false); e.target.value = ''
    }
  }

  const exportNow = async (includeKeys) => {
    setBusy(true); setMsg('')
    try {
      const data = await api.exportConfig(includeKeys)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `api-dashboard-config-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(a.href)
    } catch (e) {
      setMsg(e.message)
    } finally { setBusy(false) }
  }

  const onExportClick = async () => {
    const withKeys = confirm('Include API keys in the export?\n\nOK = include (treat file as sensitive)\nCancel = structure only (no keys)')
    await exportNow(withKeys)
  }

  const onFilePick = async (e) => {
    const f = e.target.files?.[0]
    if (!f) return
    setBusy(true); setMsg('')
    try {
      const text = await f.text()
      const json = JSON.parse(text)
      const res = await api.importConfig(json)
      setMsg(`Imported ${res.created}. Skipped ${res.skipped} (name conflict).`)
      reload()
    } catch (err) {
      setMsg(err.message || 'Import failed')
    } finally {
      setBusy(false)
      e.target.value = ''
    }
  }

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <input ref={fileRef} type="file" accept="application/json" className="hidden" onChange={onFilePick} />
      <input ref={specRef} type="file" accept="application/json,.json,.har" className="hidden" onChange={onSpecPick} />
      <button className="btn-secondary" onClick={onExportClick} disabled={busy}>Export</button>
      <button className="btn-secondary" onClick={() => fileRef.current?.click()} disabled={busy}>Import config</button>
      <button className="btn-secondary" onClick={() => specRef.current?.click()} disabled={busy} title="HTTP/REST only — OpenAPI 3.x, Postman 2.1, or HAR">Import REST spec</button>
      {msg && <span className="text-xs text-ink-400">{msg}</span>}
    </div>
  )
}
