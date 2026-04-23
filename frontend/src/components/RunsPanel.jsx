import { useEffect, useMemo, useRef, useState } from 'react'
import { Play, Square, Trash2, Plus, RefreshCw, Download, Upload, Copy, Check, X } from 'lucide-react'
import { api } from '../api.js'

const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD']

const BLANK_RUN = {
  name: '',
  notes: '',
  method: 'GET',
  url: '',
  headers: '{}',
  query: '{}',
  body: '',
  body_type: 'json',
  data_format: 'csv',
  data_content: '',
  delay_ms: 0,
  stop_on_error: false,
  max_rows: null,
  assertions: {},
}

export default function RunsPanel() {
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [editing, setEditing] = useState(null) // null | 'new' | run object
  const [runningId, setRunningId] = useState(null) // run id whose execution view is open
  const [activeExecutionId, setActiveExecutionId] = useState(null)

  const reload = async () => {
    setLoading(true)
    try {
      setError(null)
      setRuns(await api.listRuns())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { reload() }, [])

  const onRemove = async (r) => {
    if (!confirm(`Delete run "${r.name || '(unnamed)'}" and all its execution history?`)) return
    await api.deleteRun(r.id)
    reload()
  }

  const onExecute = async (r) => {
    try {
      const exec = await api.executeRun(r.id)
      setRunningId(r.id)
      setActiveExecutionId(exec.id)
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-7xl mx-auto px-4 md:px-6 py-4 md:py-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4 md:mb-6">
          <div>
            <h1 className="text-lg md:text-xl font-semibold">Runs</h1>
            <p className="text-xs md:text-sm text-ink-400 mt-0.5 md:mt-1">Data-driven request runs — upload a CSV, parameterize with <code className="font-mono text-ink-200">{'{{column}}'}</code>, execute once per row.</p>
          </div>
          <div className="flex gap-2">
            <button className="btn-ghost" onClick={reload} title="Refresh"><RefreshCw className="w-4 h-4" /></button>
            <button className="btn-primary" onClick={() => setEditing('new')}><Plus className="w-4 h-4" /> New run</button>
          </div>
        </div>

        {error && <div className="text-sm text-red-700 bg-red-600/10 border border-red-600/30 rounded-md p-2 mb-3">{error}</div>}

        {loading ? (
          <div className="card p-10 text-center text-ink-400 text-sm">Loading…</div>
        ) : runs.length === 0 ? (
          <div className="card p-10 text-center text-ink-400 text-sm">
            No runs yet. <button className="underline text-accent" onClick={() => setEditing('new')}>Create the first one →</button>
          </div>
        ) : (
          <div className="space-y-2">
            {runs.map((r) => (
              <RunRow
                key={r.id}
                run={r}
                onEdit={() => setEditing(r)}
                onExecute={() => onExecute(r)}
                onDelete={() => onRemove(r)}
                onOpenHistory={() => { setRunningId(r.id); setActiveExecutionId(null) }}
              />
            ))}
          </div>
        )}
      </div>

      {editing && (
        <RunEditor
          run={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); reload() }}
        />
      )}

      {runningId && (
        <ExecutorModal
          runId={runningId}
          initialExecutionId={activeExecutionId}
          onClose={() => { setRunningId(null); setActiveExecutionId(null); reload() }}
        />
      )}
    </div>
  )
}

function RunRow({ run, onEdit, onExecute, onDelete, onOpenHistory }) {
  const lastStatus = run.last_execution_status
  const badge = lastStatus ? STATUS_BADGES[lastStatus] : null
  return (
    <div className="card p-4 hover:border-ink-600 transition">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold">{run.name || '(unnamed)'}</span>
            <span className="pill bg-accent/15 text-accent">{run.method}</span>
            {badge}
          </div>
          <div className="text-xs text-ink-400 font-mono mt-1 truncate">{run.url || run.path || '(no url)'}</div>
          <div className="text-[11px] text-ink-400 mt-1 flex items-center gap-3 flex-wrap">
            <span>{run.data_format.toUpperCase()}</span>
            <span>{countRows(run.data_content, run.data_format)} rows</span>
            {run.delay_ms > 0 && <span>{run.delay_ms}ms delay</span>}
            {run.stop_on_error && <span>stops on error</span>}
          </div>
        </div>
        <div className="flex gap-1 shrink-0">
          <button className="btn-ghost" onClick={onOpenHistory} title="History">History</button>
          <button className="btn-secondary" onClick={onEdit}>Edit</button>
          <button className="btn-primary" onClick={onExecute}><Play className="w-4 h-4" /> Run</button>
          <button className="btn-ghost text-red-700" onClick={onDelete}><Trash2 className="w-4 h-4" /></button>
        </div>
      </div>
    </div>
  )
}

const STATUS_BADGES = {
  running: <span className="pill bg-accent/15 text-accent">● running</span>,
  completed: <span className="pill bg-emerald-500/15 text-emerald-700">✓ completed</span>,
  canceled: <span className="pill bg-ink-700 text-ink-400">canceled</span>,
  failed: <span className="pill bg-red-500/15 text-red-700">✕ failed</span>,
  pending: <span className="pill bg-ink-700 text-ink-400">pending</span>,
}

function countRows(content, format) {
  if (!content) return 0
  if (format === 'json') {
    try { const v = JSON.parse(content); return Array.isArray(v) ? v.length : 0 } catch { return '?' }
  }
  const lines = content.split('\n').filter(Boolean)
  return Math.max(0, lines.length - 1) // minus header
}

function RunEditor({ run, onClose, onSaved }) {
  const editing = !!run
  const [form, setForm] = useState(() => {
    if (!run) return { ...BLANK_RUN }
    return {
      ...BLANK_RUN,
      ...run,
      headers: JSON.stringify(run.headers || {}, null, 2),
      query: JSON.stringify(run.query || {}, null, 2),
      body: run.body == null ? '' : (typeof run.body === 'string' ? run.body : JSON.stringify(run.body, null, 2)),
      assertions: run.assertions || {},
    }
  })
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState(null)
  const [preview, setPreview] = useState(null)
  const [previewErr, setPreviewErr] = useState(null)
  const fileInput = useRef(null)

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))
  const setAssertion = (k, v) => setForm((f) => ({ ...f, assertions: { ...f.assertions, [k]: v } }))

  const buildPayload = () => {
    let headers = {}, query = {}
    try { headers = JSON.parse(form.headers || '{}') } catch { throw new Error('Headers must be JSON') }
    try { query = JSON.parse(form.query || '{}') } catch { throw new Error('Query must be JSON') }
    let body = null
    if (form.body && form.body.trim()) {
      if (form.body_type === 'json') {
        try { body = JSON.parse(form.body) } catch { body = form.body }
      } else body = form.body
    }
    const assertions = { ...form.assertions }
    if (assertions.expected_status && typeof assertions.expected_status === 'string') {
      assertions.expected_status = assertions.expected_status.split(',').map((s) => parseInt(s.trim(), 10)).filter(Boolean)
    }
    if (!assertions.expected_status || assertions.expected_status.length === 0) delete assertions.expected_status
    if (!assertions.body_contains) delete assertions.body_contains
    if (!assertions.body_not_contains) delete assertions.body_not_contains
    return {
      name: form.name,
      notes: form.notes,
      method: form.method,
      url: form.url,
      path: form.path || '',
      headers, query, body,
      body_type: form.body_type,
      data_format: form.data_format,
      data_content: form.data_content,
      delay_ms: Number(form.delay_ms) || 0,
      stop_on_error: !!form.stop_on_error,
      max_rows: form.max_rows ? Number(form.max_rows) : null,
      assertions,
    }
  }

  const save = async () => {
    setSaving(true)
    setErr(null)
    try {
      const payload = buildPayload()
      if (editing) await api.updateRun(run.id, payload)
      else await api.createRun(payload)
      onSaved()
    } catch (e) {
      setErr(e.message)
    } finally {
      setSaving(false)
    }
  }

  const doPreview = async () => {
    setPreviewErr(null)
    setPreview(null)
    try {
      // Preview needs a saved run. If unsaved, save first (as draft), preview, then stay on that record.
      let id = editing ? run.id : null
      if (!id) {
        const created = await api.createRun(buildPayload())
        id = created.id
        // Nudge the parent to re-fetch later, but don't close.
      }
      const p = await api.previewRun(id)
      setPreview({ ...p, _runId: id })
    } catch (e) {
      setPreviewErr(e.message)
    }
  }

  const onFilePicked = async (e) => {
    const f = e.target.files?.[0]
    if (!f) return
    const text = await f.text()
    set('data_content', text)
    const name = f.name.toLowerCase()
    if (name.endsWith('.tsv')) set('data_format', 'tsv')
    else if (name.endsWith('.json')) set('data_format', 'json')
    else set('data_format', 'csv')
    e.target.value = ''
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="card w-full max-w-3xl h-full sm:h-auto sm:max-h-[92vh] overflow-y-auto rounded-none sm:rounded-lg sm:shadow-panel-lg">
        <div className="p-4 sm:p-5 border-b border-ink-700 flex items-center justify-between sticky top-0 bg-ink-900 z-10">
          <div>
            <div className="font-semibold">{editing ? `Edit "${run.name || 'run'}"` : 'New run'}</div>
            <div className="text-xs text-ink-400 mt-0.5">Reference columns in URL / headers / body as <code className="font-mono text-ink-200">{'{{column_name}}'}</code>.</div>
          </div>
          <button className="btn-ghost" onClick={onClose} aria-label="Close"><X className="w-4 h-4" /></button>
        </div>

        <div className="p-4 sm:p-5 space-y-5">
          <section className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 [&>*]:min-w-0">
              <div>
                <label className="label">Name</label>
                <input className="input" value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="Bulk user signup test" />
              </div>
              <div>
                <label className="label">Notes</label>
                <input className="input" value={form.notes} onChange={(e) => set('notes', e.target.value)} placeholder="optional" />
              </div>
            </div>
          </section>

          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-ink-100">Request template</h3>
            <div className="grid grid-cols-1 sm:grid-cols-[auto_1fr] gap-3 [&>*]:min-w-0">
              <div>
                <label className="label">Method</label>
                <select className="select" value={form.method} onChange={(e) => set('method', e.target.value)}>
                  {METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
              <div>
                <label className="label">URL</label>
                <input className="input font-mono text-xs" value={form.url} onChange={(e) => set('url', e.target.value)} placeholder="https://api.example.com/items/{{id}}" />
              </div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 [&>*]:min-w-0">
              <div>
                <label className="label">Headers (JSON)</label>
                <textarea className="textarea text-xs" rows={4} value={form.headers} onChange={(e) => set('headers', e.target.value)} placeholder='{"authorization": "Bearer {{token}}"}' spellCheck={false} />
              </div>
              <div>
                <label className="label">Query (JSON)</label>
                <textarea className="textarea text-xs" rows={4} value={form.query} onChange={(e) => set('query', e.target.value)} placeholder='{"q": "{{search}}"}' spellCheck={false} />
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
                <textarea className="textarea text-xs" rows={6} value={form.body} onChange={(e) => set('body', e.target.value)} placeholder={form.body_type === 'json' ? '{"email": "{{email}}", "name": "{{name}}"}' : 'raw body'} spellCheck={false} />
              </div>
            )}
          </section>

          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-ink-100">Data</h3>
              <div className="flex items-center gap-2">
                <select className="select !w-auto !py-1 text-xs" value={form.data_format} onChange={(e) => set('data_format', e.target.value)}>
                  <option value="csv">CSV</option>
                  <option value="tsv">TSV</option>
                  <option value="json">JSON</option>
                </select>
                <input type="file" ref={fileInput} className="hidden" accept=".csv,.tsv,.json,.txt" onChange={onFilePicked} />
                <button className="btn-secondary text-xs" onClick={() => fileInput.current?.click()}><Upload className="w-3.5 h-3.5" /> Upload file</button>
              </div>
            </div>
            <textarea
              className="textarea text-xs min-h-[180px]"
              value={form.data_content}
              onChange={(e) => set('data_content', e.target.value)}
              placeholder={form.data_format === 'json' ? '[{"id": 1, "email": "a@x.com"}, ...]' : 'id,email\n1,a@x.com\n2,b@x.com'}
              spellCheck={false}
            />
          </section>

          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-ink-100">Execution</h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 [&>*]:min-w-0">
              <div>
                <label className="label">Delay between iterations (ms)</label>
                <input type="number" min="0" className="input" value={form.delay_ms} onChange={(e) => set('delay_ms', e.target.value)} />
              </div>
              <div>
                <label className="label">Max rows (blank = all)</label>
                <input type="number" min="1" className="input" value={form.max_rows ?? ''} onChange={(e) => set('max_rows', e.target.value || null)} />
              </div>
              <label className="flex items-center gap-2 self-end pb-2 text-sm">
                <input type="checkbox" checked={!!form.stop_on_error} onChange={(e) => set('stop_on_error', e.target.checked)} className="accent-accent" />
                <span>Stop on first failure</span>
              </label>
            </div>
          </section>

          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-ink-100">Assertions (optional)</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 [&>*]:min-w-0">
              <div>
                <label className="label">Expected status codes</label>
                <input
                  className="input font-mono text-xs"
                  value={Array.isArray(form.assertions.expected_status) ? form.assertions.expected_status.join(', ') : (form.assertions.expected_status || '')}
                  onChange={(e) => setAssertion('expected_status', e.target.value)}
                  placeholder="200, 201"
                />
              </div>
              <div>
                <label className="label">Body contains (substring)</label>
                <input
                  className="input"
                  value={form.assertions.body_contains || ''}
                  onChange={(e) => setAssertion('body_contains', e.target.value)}
                  placeholder='"status":"ok"'
                />
              </div>
              <div className="col-span-1 sm:col-span-2">
                <label className="label">Body must NOT contain</label>
                <input
                  className="input"
                  value={form.assertions.body_not_contains || ''}
                  onChange={(e) => setAssertion('body_not_contains', e.target.value)}
                  placeholder='"error"'
                />
              </div>
            </div>
          </section>

          <section className="space-y-2">
            <div className="flex items-center gap-2">
              <button className="btn-secondary text-xs" onClick={doPreview}>Preview</button>
              <span className="text-[11px] text-ink-400">Parse the data + render the first row against the template.</span>
            </div>
            {previewErr && <div className="text-sm text-red-700 bg-red-600/10 border border-red-600/30 rounded-md p-2">{previewErr}</div>}
            {preview && (
              <div className="card p-3 space-y-2 text-xs">
                <div className="flex items-center gap-3 text-ink-400 flex-wrap">
                  <span>{preview.row_count} rows</span>
                  <span>· columns: {preview.columns.join(', ') || '(none)'}</span>
                </div>
                {preview.missing_variables?.length > 0 && (
                  <div className="text-amber-700">⚠ template references missing variables: <code className="font-mono">{preview.missing_variables.join(', ')}</code></div>
                )}
                {preview.unused_columns?.length > 0 && (
                  <div className="text-ink-400">unused columns: <code className="font-mono">{preview.unused_columns.join(', ')}</code></div>
                )}
                {preview.first_row_rendered && !preview.first_row_rendered.error && (
                  <div>
                    <div className="text-ink-400 mb-1">First row rendered:</div>
                    <pre className="font-mono text-[11px] bg-white border border-ink-700 rounded-md p-2 overflow-auto max-h-48 whitespace-pre-wrap break-words">
                      {JSON.stringify(preview.first_row_rendered, null, 2)}
                    </pre>
                  </div>
                )}
                {preview.first_row_rendered?.error && (
                  <div className="text-red-700">render error: {preview.first_row_rendered.error}</div>
                )}
              </div>
            )}
          </section>

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

function ExecutorModal({ runId, initialExecutionId, onClose }) {
  const [executions, setExecutions] = useState([])
  const [activeId, setActiveId] = useState(initialExecutionId)
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)

  const reloadList = async () => {
    try { setExecutions(await api.listRunExecutions(runId)) } catch (e) { setErr(e.message) }
  }

  useEffect(() => { reloadList() }, [runId])

  // If no active id yet and we have history, pick the most recent.
  useEffect(() => {
    if (!activeId && executions.length > 0) setActiveId(executions[0].id)
  }, [activeId, executions])

  // Poll the active execution until it reaches a terminal state.
  useEffect(() => {
    if (!activeId) { setDetail(null); setLoading(false); return }
    let alive = true
    let timer = null
    const tick = async () => {
      try {
        const d = await api.getRunExecution(runId, activeId)
        if (!alive) return
        setDetail(d)
        setLoading(false)
        if (['running', 'pending'].includes(d.status)) {
          timer = setTimeout(tick, 600)
        } else {
          // Refresh the list once so the status badge updates.
          reloadList()
        }
      } catch (e) {
        if (alive) { setErr(e.message); setLoading(false) }
      }
    }
    setLoading(true)
    tick()
    return () => { alive = false; if (timer) clearTimeout(timer) }
  }, [activeId, runId])

  const cancel = async () => {
    if (!activeId) return
    await api.cancelRunExecution(runId, activeId)
  }
  const startNew = async () => {
    const exec = await api.executeRun(runId)
    setActiveId(exec.id)
    reloadList()
  }
  const removeExec = async (id) => {
    if (!confirm('Delete this execution and all its rows?')) return
    try {
      await api.deleteRunExecution(runId, id)
      if (activeId === id) setActiveId(null)
      reloadList()
    } catch (e) { setErr(e.message) }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="card w-full max-w-5xl h-full sm:h-auto sm:max-h-[92vh] overflow-hidden rounded-none sm:rounded-lg sm:shadow-panel-lg flex flex-col">
        <div className="p-4 sm:p-5 border-b border-ink-700 flex items-center justify-between">
          <div>
            <div className="font-semibold">Run executor</div>
            <div className="text-xs text-ink-400 mt-0.5">Live progress updates every 600 ms while running.</div>
          </div>
          <div className="flex items-center gap-2">
            <button className="btn-secondary text-xs" onClick={startNew}><Play className="w-4 h-4" /> Run again</button>
            <button className="btn-ghost" onClick={onClose} aria-label="Close"><X className="w-4 h-4" /></button>
          </div>
        </div>

        <div className="flex-1 overflow-hidden flex flex-col lg:flex-row">
          <aside className="lg:w-64 lg:shrink-0 border-b lg:border-b-0 lg:border-r border-ink-700 overflow-y-auto p-2 space-y-1 max-h-48 lg:max-h-none">
            {executions.length === 0 && <div className="text-xs text-ink-400 p-2">No executions yet.</div>}
            {executions.map((e) => (
              <button
                key={e.id}
                onClick={() => setActiveId(e.id)}
                className={`w-full text-left text-xs p-2 rounded-md transition ${activeId === e.id ? 'bg-accent/15 text-accent border border-accent/30' : 'hover:bg-ink-800 border border-transparent'}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span>#{e.id}</span>
                  {STATUS_BADGES[e.status] || <span className="pill bg-ink-700 text-ink-400">{e.status}</span>}
                </div>
                <div className="text-[11px] text-ink-400 mt-0.5 flex items-center gap-2 flex-wrap">
                  <span>{e.completed_rows}/{e.total_rows} rows</span>
                  {e.succeeded > 0 && <span className="text-emerald-700">✓ {e.succeeded}</span>}
                  {e.failed > 0 && <span className="text-red-700">✕ {e.failed}</span>}
                </div>
              </button>
            ))}
          </aside>

          <div className="flex-1 overflow-y-auto p-4 space-y-3 min-w-0">
            {err && <div className="text-sm text-red-700 bg-red-600/10 border border-red-600/30 rounded-md p-2">{err}</div>}
            {loading && !detail ? (
              <div className="text-ink-400 text-sm">Loading…</div>
            ) : !detail ? (
              <div className="text-ink-400 text-sm">Pick an execution on the left.</div>
            ) : (
              <ExecutionDetail
                detail={detail}
                onCancel={cancel}
                onDelete={() => removeExec(detail.id)}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function ExecutionDetail({ detail, onCancel, onDelete }) {
  const isActive = detail.status === 'running' || detail.status === 'pending'
  const pct = detail.total_rows > 0 ? Math.round((detail.completed_rows / detail.total_rows) * 100) : 0
  const [openId, setOpenId] = useState(null)

  const exportCsv = () => {
    const head = ['row_index', 'status_code', 'latency_ms', 'ok', 'passed', 'error', 'url']
    const lines = [head.join(',')]
    for (const it of detail.iterations) {
      lines.push(head.map((h) => csvField(it[h])).join(','))
    }
    download(`${detail.run_id}-exec-${detail.id}.csv`, lines.join('\n'), 'text/csv')
  }
  const exportJson = () => {
    download(`${detail.run_id}-exec-${detail.id}.json`, JSON.stringify(detail, null, 2), 'application/json')
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        {STATUS_BADGES[detail.status] || null}
        <span className="text-xs text-ink-400">#{detail.id} · started {new Date(detail.started_at).toLocaleString()}</span>
        {isActive && (
          <button className="btn-ghost text-xs text-red-700 ml-auto" onClick={onCancel}><Square className="w-3.5 h-3.5" /> Cancel</button>
        )}
        {!isActive && (
          <div className="flex items-center gap-2 ml-auto">
            <button className="btn-ghost text-xs" onClick={exportCsv}><Download className="w-3.5 h-3.5" /> CSV</button>
            <button className="btn-ghost text-xs" onClick={exportJson}><Download className="w-3.5 h-3.5" /> JSON</button>
            <button className="btn-ghost text-xs text-red-700" onClick={onDelete}><Trash2 className="w-3.5 h-3.5" /></button>
          </div>
        )}
      </div>

      {detail.error && <div className="text-sm text-red-700 bg-red-600/10 border border-red-600/30 rounded-md p-2">{detail.error}</div>}

      <div>
        <div className="flex items-center justify-between text-xs text-ink-400 mb-1">
          <span>{detail.completed_rows}/{detail.total_rows} rows · <span className="text-emerald-700">✓ {detail.succeeded}</span> · <span className="text-red-700">✕ {detail.failed}</span></span>
          <span>{pct}%</span>
        </div>
        <div className="w-full h-2 rounded-full bg-ink-800 overflow-hidden">
          <div className="h-full bg-accent transition-all" style={{ width: `${pct}%` }} />
        </div>
      </div>

      <div className="space-y-1.5">
        {detail.iterations.map((it) => (
          <IterationRow key={it.id} it={it} open={openId === it.id} onToggle={() => setOpenId(openId === it.id ? null : it.id)} />
        ))}
        {isActive && detail.iterations.length === 0 && <div className="text-xs text-ink-400">Waiting for first result…</div>}
      </div>
    </>
  )
}

function IterationRow({ it, open, onToggle }) {
  const color = it.passed ? 'text-emerald-700' : 'text-red-700'
  return (
    <div className="card overflow-hidden">
      <button className="w-full p-2.5 text-left hover:bg-ink-800 transition" onClick={onToggle}>
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`pill ${it.passed ? 'bg-emerald-500/15 text-emerald-700' : 'bg-red-500/15 text-red-700'}`}>
            {it.passed ? '● pass' : '✕ fail'}
          </span>
          <span className="font-mono text-xs">#{it.row_index}</span>
          <span className="font-mono text-xs">{it.method}</span>
          <span className="font-mono text-[11px] text-ink-400 truncate min-w-0 flex-1">{it.url}</span>
          <span className={`font-mono text-[11px] ${color}`}>{it.status_code || 'ERR'} · {it.latency_ms}ms</span>
        </div>
        {it.error && !open && <div className="text-[11px] text-red-700 mt-1 truncate">{it.error}</div>}
      </button>
      {open && (
        <div className="border-t border-ink-700 p-3 space-y-2 bg-white/40 text-xs">
          {Object.keys(it.variables || {}).length > 0 && (
            <Detail label="Variables">
              <pre className="font-mono text-[11px] bg-white border border-ink-700 rounded-md p-2 overflow-auto max-h-40 whitespace-pre-wrap break-words">
                {JSON.stringify(it.variables, null, 2)}
              </pre>
            </Detail>
          )}
          {it.assertion_results?.length > 0 && (
            <Detail label="Assertions">
              <ul className="space-y-1">
                {it.assertion_results.map((a, i) => (
                  <li key={i} className={a.passed ? 'text-emerald-700' : 'text-red-700'}>
                    {a.passed ? '✓' : '✕'} {a.name}{a.message ? ` — ${a.message}` : ''}
                  </li>
                ))}
              </ul>
            </Detail>
          )}
          {it.error && <Detail label="Error"><div className="text-red-700 break-words">{it.error}</div></Detail>}
          {it.response_preview && (
            <Detail label="Response preview">
              <pre className="font-mono text-[11px] bg-white border border-ink-700 rounded-md p-2 overflow-auto max-h-64 whitespace-pre-wrap break-words">
                {it.response_preview}
              </pre>
            </Detail>
          )}
        </div>
      )}
    </div>
  )
}

function Detail({ label, children }) {
  return (
    <div>
      <div className="text-[11px] text-ink-400 uppercase tracking-wide mb-1">{label}</div>
      {children}
    </div>
  )
}

function csvField(v) {
  if (v === null || v === undefined) return ''
  const s = String(v)
  if (/[",\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"'
  return s
}

function download(filename, content, mime) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
