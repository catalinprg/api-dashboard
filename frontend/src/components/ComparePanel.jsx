import { useMemo, useState } from 'react'
import { api } from '../api.js'
import { Markdown } from '../utils/markdown.jsx'
import { extractUsage, estimateCost, fmtCost } from '../utils/pricing.js'

// Compare the same prompt across multiple provider+model pairs.
export default function ComparePanel({ providers }) {
  const llmProviders = useMemo(() => providers.filter((p) => p.kind === 'llm' && p.enabled), [providers])
  const [rows, setRows] = useState([
    { providerId: '', model: '' },
    { providerId: '', model: '' },
  ])
  const [system, setSystem] = useState('')
  const [prompt, setPrompt] = useState('Say hi in one short sentence.')
  const [temperature, setTemperature] = useState(0.7)
  const [results, setResults] = useState({}) // keyed by row index
  const [running, setRunning] = useState(false)

  const setRow = (i, patch) => setRows((xs) => xs.map((r, idx) => idx === i ? { ...r, ...patch } : r))
  const addRow = () => setRows((xs) => [...xs, { providerId: '', model: '' }])
  const removeRow = (i) => setRows((xs) => xs.filter((_, idx) => idx !== i))

  const runAll = async () => {
    if (!prompt.trim()) return
    setRunning(true)
    setResults({})
    const targets = rows.filter((r) => r.providerId)
    const msgs = []
    if (system.trim()) msgs.push({ role: 'system', content: system })
    msgs.push({ role: 'user', content: prompt })

    await Promise.all(targets.map(async (r, i) => {
      const started = performance.now()
      setResults((x) => ({ ...x, [i]: { loading: true } }))
      try {
        const res = await api.invokeLLM({
          provider_id: Number(r.providerId),
          model: r.model || undefined,
          messages: msgs,
          temperature: Number(temperature),
        })
        const text = extractText(res.body)
        const usage = extractUsage(res.body)
        const price = estimateCost(usage, r.model)
        setResults((x) => ({
          ...x,
          [i]: {
            ok: res.ok,
            status: res.status_code,
            latency: Math.round(performance.now() - started),
            text: text || (typeof res.body === 'string' ? res.body : JSON.stringify(res.body, null, 2)),
            usage,
            cost: price?.usd ?? null,
          },
        }))
      } catch (e) {
        setResults((x) => ({ ...x, [i]: { ok: false, status: 0, latency: 0, text: e.message } }))
      }
    }))
    setRunning(false)
  }

  if (llmProviders.length === 0) {
    return <div className="card p-10 text-center text-ink-400">No LLM providers yet.</div>
  }

  return (
    <div className="space-y-4">
      <div className="card p-4 space-y-3">
        <div>
          <label className="label">System prompt (optional)</label>
          <textarea className="textarea text-sm" rows={2} value={system} onChange={(e) => setSystem(e.target.value)} />
        </div>
        <div>
          <label className="label">User prompt</label>
          <textarea className="textarea text-sm" rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="label">Temperature</label>
            <input className="input" type="number" step="0.1" min="0" max="2" value={temperature} onChange={(e) => setTemperature(e.target.value)} />
          </div>
        </div>
        <div className="flex justify-end">
          <button className="btn-primary" onClick={runAll} disabled={running || !prompt.trim()}>
            {running ? 'Running…' : 'Run all'}
          </button>
        </div>
      </div>

      <div className="card p-4 space-y-3">
        <div className="flex items-center justify-between">
          <label className="label !mb-0">Targets</label>
          <button className="btn-secondary text-xs" onClick={addRow}>+ Add</button>
        </div>
        {rows.map((r, i) => {
          const prov = llmProviders.find((p) => p.id === Number(r.providerId))
          const models = prov?.models || []
          return (
            <div key={i} className="grid grid-cols-12 gap-2 items-center">
              <select className="select col-span-12 sm:col-span-5 text-xs" value={r.providerId} onChange={(e) => setRow(i, { providerId: e.target.value, model: (llmProviders.find((p) => p.id === Number(e.target.value))?.default_model) || '' })}>
                <option value="">— Provider —</option>
                {llmProviders.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              {models.length > 0 ? (
                <select className="select col-span-11 sm:col-span-6 text-xs font-mono" value={r.model} onChange={(e) => setRow(i, { model: e.target.value })}>
                  {models.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              ) : (
                <input className="input col-span-11 sm:col-span-6 text-xs font-mono" value={r.model} onChange={(e) => setRow(i, { model: e.target.value })} placeholder="model id" />
              )}
              <button className="btn-ghost col-span-1 text-ink-400 hover:text-red-700" onClick={() => removeRow(i)}>✕</button>
            </div>
          )
        })}
      </div>

      <div className={`grid grid-cols-1 ${rows.length >= 3 ? 'xl:grid-cols-3' : ''} md:grid-cols-2 gap-4`}>
        {rows.map((r, i) => {
          const prov = llmProviders.find((p) => p.id === Number(r.providerId))
          const res = results[i]
          return (
            <div key={i} className="card overflow-hidden">
              <div className="px-3 py-2 border-b border-ink-700 flex items-center justify-between">
                <div className="text-xs text-ink-200 truncate">
                  <span className="font-semibold">{prov?.name || '—'}</span>
                  <span className="text-ink-400"> · </span>
                  <span className="font-mono">{r.model || '—'}</span>
                </div>
                {res && !res.loading && (
                  <div className="text-[11px] text-ink-400 font-mono shrink-0">
                    {res.status} · {res.latency}ms
                    {res.usage && ` · ${res.usage.input}↑/${res.usage.output}↓`}
                    {res.cost != null && res.cost > 0 && ` · ${fmtCost(res.cost)}`}
                  </div>
                )}
              </div>
              <div className="p-3 min-h-[120px]">
                {!res && <div className="text-xs text-ink-400">Click Run all to see the response.</div>}
                {res?.loading && <div className="text-xs text-ink-400">Running…</div>}
                {res && !res.loading && (
                  res.ok ? <Markdown text={res.text || ''} /> : <div className="text-xs font-mono text-red-700 whitespace-pre-wrap">{res.text}</div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function extractText(body) {
  if (!body || typeof body !== 'object') return ''
  const c = body.choices?.[0]
  if (c?.message?.content) return c.message.content
  if (Array.isArray(body.content)) return body.content.filter((p) => p.type === 'text').map((p) => p.text).join('\n')
  return ''
}
