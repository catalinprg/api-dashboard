import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import ResponseView from './ResponseView.jsx'

export default function GenericRequest({ providers }) {
  const enabled = useMemo(() => providers.filter((p) => p.enabled && p.kind === 'http'), [providers])
  const [providerId, setProviderId] = useState('')
  const [endpointId, setEndpointId] = useState('')
  const [headersText, setHeadersText] = useState('{}')
  const [queryText, setQueryText] = useState('{}')
  const [body, setBody] = useState('')
  const [bodyType, setBodyType] = useState('json')
  const [loading, setLoading] = useState(false)
  const [response, setResponse] = useState(null)
  const [parseErr, setParseErr] = useState(null)
  const [presets, setPresets] = useState([])
  const [presetId, setPresetId] = useState('')

  const reloadPresets = async () => {
    try { setPresets(await api.listPresets()) } catch {}
  }
  useEffect(() => { reloadPresets() }, [])

  const loadPreset = async (id) => {
    setPresetId(id)
    if (!id) return
    const p = presets.find((x) => x.id === Number(id))
    if (!p) return
    skipEndpointAutoSelect.current = true
    setProviderId(p.provider_id || '')
    setEndpointId(p.endpoint_id || '')
    setHeadersText(JSON.stringify(p.headers || {}, null, 2))
    setQueryText(JSON.stringify(p.query || {}, null, 2))
    setBody(p.body != null ? (typeof p.body === 'string' ? p.body : JSON.stringify(p.body, null, 2)) : '')
    setBodyType(p.body_type || 'json')
  }

  const savePreset = async () => {
    const name = prompt('Preset name:', selectedEndpoint?.name || 'Saved request')
    if (!name) return
    let headers = {}, query = {}, bodyVal = null
    try { headers = JSON.parse(headersText || '{}') } catch {}
    try { query = JSON.parse(queryText || '{}') } catch {}
    if (body.trim()) {
      if (bodyType === 'json') { try { bodyVal = JSON.parse(body) } catch { bodyVal = body } }
      else bodyVal = body
    }
    await api.createPreset({
      name,
      provider_id: providerId ? Number(providerId) : null,
      endpoint_id: endpointId ? Number(endpointId) : null,
      method: selectedEndpoint?.method || 'GET',
      headers, query, body: bodyVal, body_type: bodyType,
    })
    await reloadPresets()
  }

  const deletePresetById = async () => {
    if (!presetId) return
    if (!confirm('Delete this preset?')) return
    await api.deletePreset(Number(presetId))
    setPresetId('')
    await reloadPresets()
  }

  const current = enabled.find((p) => p.id === Number(providerId))
  const endpoints = current?.endpoints || []
  const selectedEndpoint = endpoints.find((e) => e.id === Number(endpointId))
  const skipEndpointAutoSelect = useRef(false)

  useEffect(() => {
    if (skipEndpointAutoSelect.current) {
      skipEndpointAutoSelect.current = false
      return
    }
    if (!endpoints.find((e) => e.id === Number(endpointId))) {
      setEndpointId(endpoints[0]?.id || '')
    }
  }, [providerId])

  const previewUrl = useMemo(() => {
    if (!current || !selectedEndpoint) return ''
    const path = selectedEndpoint.path || ''
    if (path.startsWith('http://') || path.startsWith('https://')) return path
    const base = (current.base_url || '').replace(/\/$/, '')
    return `${base}${path.startsWith('/') || !path ? '' : '/'}${path}`
  }, [current, selectedEndpoint])

  const send = async () => {
    setParseErr(null)
    if (!selectedEndpoint) { setParseErr('Pick a provider + endpoint first.'); return }
    let headers = {}, query = {}
    try { headers = JSON.parse(headersText || '{}') } catch { setParseErr('Headers must be JSON'); return }
    try { query = JSON.parse(queryText || '{}') } catch { setParseErr('Query must be JSON'); return }

    let parsedBody = null
    if (body.trim() && !['GET', 'HEAD'].includes(selectedEndpoint.method)) {
      if (bodyType === 'json') {
        try { parsedBody = JSON.parse(body) } catch { setParseErr('Body must be JSON (or switch to text/form)'); return }
      } else if (bodyType === 'form') {
        try { parsedBody = JSON.parse(body) } catch { setParseErr('Form body must be JSON object'); return }
      } else {
        parsedBody = body
      }
    }

    setLoading(true)
    setResponse(null)
    try {
      const res = await api.invokeHTTP({
        endpoint_id: Number(endpointId),
        headers, query, body: parsedBody, body_type: bodyType,
      })
      setResponse(res)
    } catch (e) {
      setResponse({ ok: false, status_code: 0, latency_ms: 0, body: null, headers: {}, error: e.message })
    } finally {
      setLoading(false)
    }
  }

  if (enabled.length === 0) {
    return (
      <div className="card p-10 text-center text-ink-400">
        No enabled providers yet. Add one in the Admin panel.
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
      <div className="lg:col-span-3 space-y-4">
        {presets.length > 0 && (
          <div className="card p-3 flex flex-wrap items-center gap-2">
            <label className="label !mb-0 shrink-0">Preset</label>
            <select className="select flex-1 min-w-0" value={presetId} onChange={(e) => loadPreset(e.target.value)}>
              <option value="">— Load a saved preset —</option>
              {presets.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            <button className="btn-secondary text-xs" onClick={savePreset}>Save current</button>
            {presetId && <button className="btn-ghost text-xs text-red-700" onClick={deletePresetById}>Delete</button>}
          </div>
        )}
        {presets.length === 0 && (
          <div className="card p-3 flex items-center gap-2">
            <button className="btn-secondary text-xs" onClick={savePreset}>Save as preset</button>
            <span className="text-xs text-ink-400">Give the current method/headers/body a name so you can re-run it.</span>
          </div>
        )}
        <div className="card p-4 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="label">Provider</label>
              <select className="select" value={providerId} onChange={(e) => setProviderId(e.target.value)}>
                <option value="">— Pick a provider —</option>
                {enabled.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Endpoint</label>
              <select className="select" value={endpointId} onChange={(e) => setEndpointId(e.target.value)} disabled={!current}>
                <option value="">
                  {!current ? '— Pick a provider first —' : endpoints.length === 0 ? '— No endpoints configured —' : '— Pick an endpoint —'}
                </option>
                {endpoints.map((e) => (
                  <option key={e.id} value={e.id}>{e.method} · {e.name}</option>
                ))}
              </select>
            </div>
          </div>

          {current && endpoints.length === 0 && (
            <div className="text-xs text-amber-700 bg-amber-500/10 border border-amber-500/30 rounded-md p-2">
              This provider has no endpoints. Add one in Admin → Edit → Endpoints.
            </div>
          )}

          {selectedEndpoint && (
            <div className="text-xs text-ink-400 font-mono bg-white border border-ink-700 rounded-md p-2 break-all">
              <span className={`mr-2 font-semibold ${methodColor(selectedEndpoint.method)}`}>{selectedEndpoint.method}</span>
              <span className="text-ink-200">{previewUrl || '—'}</span>
            </div>
          )}

          <div className="flex justify-end">
            <button className="btn-primary" onClick={send} disabled={loading || !selectedEndpoint}>
              {loading ? 'Sending…' : 'Send request'}
            </button>
          </div>
        </div>

        <div className="card p-4 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="label">Extra headers (JSON)</label>
              <textarea className="textarea text-xs" rows={4} value={headersText} onChange={(e) => setHeadersText(e.target.value)} placeholder='{"accept": "application/json"}' />
            </div>
            <div>
              <label className="label">Query params (JSON)</label>
              <textarea className="textarea text-xs" rows={4} value={queryText} onChange={(e) => setQueryText(e.target.value)} placeholder='{"q": "search term"}' />
            </div>
          </div>

          {selectedEndpoint && !['GET', 'HEAD'].includes(selectedEndpoint.method) && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="label !mb-0">Body</label>
                <select className="select !w-auto !py-1 text-xs" value={bodyType} onChange={(e) => setBodyType(e.target.value)}>
                  <option value="json">JSON</option>
                  <option value="form">Form</option>
                  <option value="text">Text</option>
                </select>
              </div>
              <textarea className="textarea text-xs" rows={6} value={body} onChange={(e) => setBody(e.target.value)} placeholder={bodyType === 'json' ? '{"key": "value"}' : 'raw body'} />
            </div>
          )}

          {parseErr && <div className="text-sm text-red-700 bg-red-600/10 border border-red-600/30 rounded-md p-2">{parseErr}</div>}
        </div>
      </div>

      <div className="lg:col-span-2">
        <ResponseView response={response} loading={loading} />
      </div>
    </div>
  )
}

function methodColor(m) {
  return {
    GET: 'text-emerald-700',
    POST: 'text-blue-400',
    PUT: 'text-amber-700',
    PATCH: 'text-amber-700',
    DELETE: 'text-red-700',
    HEAD: 'text-ink-500',
  }[m] || 'text-ink-500'
}
