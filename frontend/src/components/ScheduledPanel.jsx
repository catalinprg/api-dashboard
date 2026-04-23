import { useEffect, useMemo, useState } from 'react'
import { Trash2, Play, RefreshCw, Pause, Plus } from 'lucide-react'
import { api } from '../api.js'

const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD']

const BLANK = {
  name: '',
  enabled: true,
  trigger_type: 'interval',
  interval_seconds: 900,
  cron_expr: '',
  method: 'GET',
  url: '',
  headers: '{}',
  query: '{}',
  body: '',
  body_type: 'json',
}

export default function ScheduledPanel() {
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [editing, setEditing] = useState(null) // null | 'new' | job object

  const reload = async () => {
    setLoading(true)
    try {
      setErr(null)
      setJobs(await api.listScheduledJobs())
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { reload() }, [])

  const toggle = async (j) => {
    await api.updateScheduledJob(j.id, { enabled: !j.enabled })
    reload()
  }
  const remove = async (j) => {
    if (!confirm(`Delete scheduled job "${j.name || j.url}"?`)) return
    await api.deleteScheduledJob(j.id)
    reload()
  }
  const runNow = async (j) => {
    await api.runScheduledJob(j.id)
    reload()
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-7xl mx-auto px-4 md:px-6 py-4 md:py-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4 md:mb-6">
          <div>
            <h1 className="text-lg md:text-xl font-semibold">Scheduled</h1>
            <p className="text-xs md:text-sm text-ink-400 mt-0.5 md:mt-1">Recurring HTTP requests — interval or cron. Last run status is recorded per job.</p>
          </div>
          <div className="flex gap-2">
            <button className="btn-ghost" onClick={reload} title="Refresh"><RefreshCw className="w-4 h-4" /></button>
            <button className="btn-primary" onClick={() => setEditing('new')}><Plus className="w-4 h-4" /> New job</button>
          </div>
        </div>

        {err && <div className="text-sm text-red-700 bg-red-600/10 border border-red-600/30 rounded-md p-2 mb-3">{err}</div>}

        {loading ? (
          <div className="card p-10 text-center text-ink-400 text-sm">Loading…</div>
        ) : jobs.length === 0 ? (
          <div className="card p-10 text-center text-ink-400 text-sm">
            No scheduled jobs yet. <button className="underline text-accent" onClick={() => setEditing('new')}>Create the first one →</button>
          </div>
        ) : (
          <div className="space-y-2">
            {jobs.map((j) => (
              <JobRow key={j.id} job={j} onEdit={() => setEditing(j)} onToggle={() => toggle(j)} onRun={() => runNow(j)} onDelete={() => remove(j)} />
            ))}
          </div>
        )}
      </div>

      {editing && (
        <JobEditor
          job={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); reload() }}
        />
      )}
    </div>
  )
}

function JobRow({ job, onEdit, onToggle, onRun, onDelete }) {
  const cadence = job.trigger_type === 'cron'
    ? `cron: ${job.cron_expr}`
    : `every ${formatInterval(job.interval_seconds)}`
  const lastStatus = job.last_ok === null || job.last_ok === undefined
    ? '—'
    : job.last_ok ? `● ${job.last_status_code || 'OK'}` : `✕ ${job.last_status_code || 'ERR'}`
  const lastColor = job.last_ok === true ? 'text-emerald-700' : job.last_ok === false ? 'text-red-700' : 'text-ink-400'

  return (
    <div className="card p-4 hover:border-ink-600 transition">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold">{job.name || '(unnamed)'}</span>
            <span className="pill bg-accent/15 text-accent">{job.method || 'GET'}</span>
            <span className="text-xs text-ink-400">{cadence}</span>
            {!job.enabled && <span className="pill bg-ink-700 text-ink-400">paused</span>}
          </div>
          <div className="text-xs text-ink-400 font-mono mt-1 truncate">{job.url || job.path || '(no url)'}</div>
          <div className="text-[11px] text-ink-400 mt-1 flex items-center gap-3 flex-wrap">
            <span className={`font-mono ${lastColor}`}>{lastStatus}</span>
            {job.last_latency_ms != null && <span className="font-mono">{job.last_latency_ms}ms</span>}
            {job.last_run_at && <span>last: {formatWhen(job.last_run_at)}</span>}
            {job.next_run_at && <span>next: {formatWhen(job.next_run_at)}</span>}
          </div>
          {job.last_error && <div className="text-[11px] text-red-700 mt-1 truncate">{job.last_error}</div>}
        </div>
        <div className="flex gap-1 shrink-0">
          <button className="btn-ghost" onClick={onRun} title="Run now"><Play className="w-4 h-4" /></button>
          <button className="btn-ghost" onClick={onToggle} title={job.enabled ? 'Pause' : 'Resume'}>
            {job.enabled ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
          </button>
          <button className="btn-secondary" onClick={onEdit}>Edit</button>
          <button className="btn-ghost text-red-700" onClick={onDelete}><Trash2 className="w-4 h-4" /></button>
        </div>
      </div>
    </div>
  )
}

function JobEditor({ job, onClose, onSaved }) {
  const editing = !!job
  const [form, setForm] = useState(() => {
    if (!job) return { ...BLANK }
    return {
      ...BLANK,
      ...job,
      headers: JSON.stringify(job.headers || {}, null, 2),
      query: JSON.stringify(job.query || {}, null, 2),
      body: job.body == null ? '' : (typeof job.body === 'string' ? job.body : JSON.stringify(job.body, null, 2)),
    }
  })
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState(null)
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const save = async () => {
    setSaving(true)
    setErr(null)
    try {
      let headers = {}, query = {}
      try { headers = JSON.parse(form.headers || '{}') } catch { throw new Error('Headers must be JSON') }
      try { query = JSON.parse(form.query || '{}') } catch { throw new Error('Query must be JSON') }
      let body = null
      if (form.body && form.body.trim()) {
        if (form.body_type === 'json') {
          try { body = JSON.parse(form.body) } catch { body = form.body }
        } else {
          body = form.body
        }
      }
      const payload = {
        name: form.name,
        enabled: !!form.enabled,
        trigger_type: form.trigger_type,
        interval_seconds: form.trigger_type === 'interval' ? Number(form.interval_seconds) : null,
        cron_expr: form.trigger_type === 'cron' ? form.cron_expr : '',
        method: form.method,
        url: form.url,
        headers, query, body,
        body_type: form.body_type,
      }
      if (editing) await api.updateScheduledJob(job.id, payload)
      else await api.createScheduledJob(payload)
      onSaved()
    } catch (e) {
      setErr(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="card w-full max-w-2xl h-full sm:h-auto sm:max-h-[92vh] overflow-y-auto rounded-none sm:rounded-lg sm:shadow-panel-lg">
        <div className="p-4 sm:p-5 border-b border-ink-700 flex items-center justify-between sticky top-0 bg-ink-900 z-10">
          <div>
            <div className="font-semibold">{editing ? `Edit "${job.name || 'job'}"` : 'New scheduled job'}</div>
            <div className="text-xs text-ink-400 mt-0.5">Runs an HTTP request on a schedule. Times are UTC.</div>
          </div>
          <button className="btn-ghost" onClick={onClose}>✕</button>
        </div>

        <div className="p-4 sm:p-5 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 [&>*]:min-w-0">
            <div>
              <label className="label">Name</label>
              <input className="input" value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="Heartbeat" />
            </div>
            <div>
              <label className="label">Enabled</label>
              <select className="select" value={form.enabled ? 'yes' : 'no'} onChange={(e) => set('enabled', e.target.value === 'yes')}>
                <option value="yes">Yes — run on schedule</option>
                <option value="no">No — paused</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 [&>*]:min-w-0">
            <div>
              <label className="label">Trigger</label>
              <select className="select" value={form.trigger_type} onChange={(e) => set('trigger_type', e.target.value)}>
                <option value="interval">Interval (every N seconds)</option>
                <option value="cron">Cron (5-field expression)</option>
              </select>
            </div>
            {form.trigger_type === 'interval' ? (
              <div>
                <label className="label">Interval (seconds)</label>
                <input type="number" min="10" className="input" value={form.interval_seconds} onChange={(e) => set('interval_seconds', e.target.value)} />
                <p className="text-[11px] text-ink-400 mt-1">Minimum 10 s. 900 = every 15 min, 3600 = hourly.</p>
              </div>
            ) : (
              <div>
                <label className="label">Cron expression</label>
                <input className="input font-mono text-xs" value={form.cron_expr} onChange={(e) => set('cron_expr', e.target.value)} placeholder="*/15 * * * *" />
                <p className="text-[11px] text-ink-400 mt-1">minute hour dom month dow — e.g. <code className="font-mono">0 */2 * * *</code> = every 2 h.</p>
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-[auto_1fr] gap-3 [&>*]:min-w-0">
            <div>
              <label className="label">Method</label>
              <select className="select" value={form.method} onChange={(e) => set('method', e.target.value)}>
                {METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
            <div>
              <label className="label">URL</label>
              <input className="input font-mono text-xs" value={form.url} onChange={(e) => set('url', e.target.value)} placeholder="https://api.example.com/healthcheck" />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 [&>*]:min-w-0">
            <div>
              <label className="label">Headers (JSON)</label>
              <textarea className="textarea text-xs" rows={4} value={form.headers} onChange={(e) => set('headers', e.target.value)} placeholder='{"X-Custom": "..."}' />
            </div>
            <div>
              <label className="label">Query (JSON)</label>
              <textarea className="textarea text-xs" rows={4} value={form.query} onChange={(e) => set('query', e.target.value)} placeholder='{"q": "..."}' />
            </div>
          </div>

          {!['GET', 'HEAD'].includes(form.method) && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="label !mb-0">Body</label>
                <select className="select !w-auto !py-1 text-xs" value={form.body_type} onChange={(e) => set('body_type', e.target.value)}>
                  <option value="json">JSON</option>
                  <option value="text">Text</option>
                  <option value="form">Form</option>
                </select>
              </div>
              <textarea className="textarea text-xs" rows={5} value={form.body} onChange={(e) => set('body', e.target.value)} placeholder={form.body_type === 'json' ? '{"key": "value"}' : 'raw body'} />
            </div>
          )}

          {err && <div className="text-sm text-red-700 bg-red-600/10 border border-red-600/30 rounded-md p-2">{err}</div>}
        </div>

        <div className="p-4 sm:p-5 border-t border-ink-700 flex justify-end gap-2 sticky bottom-0 bg-ink-900">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : (editing ? 'Save' : 'Create')}</button>
        </div>
      </div>
    </div>
  )
}

function formatInterval(s) {
  if (!s) return '—'
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  if (s < 86400) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

function formatWhen(iso) {
  if (!iso) return ''
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'))
  const now = new Date()
  const diff = (d - now) / 1000
  const abs = Math.abs(diff)
  const tag = diff < 0 ? 'ago' : 'from now'
  if (abs < 60) return `${Math.max(1, Math.floor(abs))}s ${tag}`
  if (abs < 3600) return `${Math.floor(abs / 60)}m ${tag}`
  if (abs < 86400) return `${Math.floor(abs / 3600)}h ${tag}`
  return d.toLocaleString()
}
