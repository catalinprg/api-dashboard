import { useState } from 'react'
import { api } from '../api.js'

const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD']

const BLANK = {
  name: '',
  kind: 'http',
  base_url: '',
  auth_type: 'bearer',
  auth_header_name: 'Authorization',
  auth_prefix: 'Bearer ',
  auth_query_param: '',
  default_model: '',
  models: [],
  extra_headers: '{}',
  variables: '{}',
  oauth_client_id: '',
  oauth_token_url: '',
  oauth_scope: '',
  oauth_auth_style: 'body',
  enabled: true,
  notes: '',
  api_key: '',
}

export default function ProviderForm({ provider, onClose, onSaved }) {
  const editing = !!provider
  const [form, setForm] = useState(() => {
    const m = provider?.models || []
    const backfilled = m.length === 0 && provider?.default_model ? [provider.default_model] : m
    return {
      ...BLANK,
      ...(provider || {}),
      models: backfilled,
      api_key: '',
    }
  })
  // Local endpoint edits (create-mode only; edit-mode uses live API calls)
  const [draftEndpoints, setDraftEndpoints] = useState(
    () => (provider?.endpoints || []).map((e) => ({ ...e, _persisted: true }))
  )
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState(null)

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const [openEndpointIdx, setOpenEndpointIdx] = useState(null)

  const addEndpointRow = () =>
    setDraftEndpoints((list) => [...list, { name: '', method: 'GET', path: '', description: '', auth_mode: 'inherit', api_key: '', _new: true }])

  const updateEndpointRow = (idx, patch) =>
    setDraftEndpoints((list) => list.map((e, i) => (i === idx ? { ...e, ...patch, _dirty: e._persisted ? true : e._dirty } : e)))

  const removeEndpointRow = async (idx) => {
    const row = draftEndpoints[idx]
    if (row._persisted && row.id) {
      if (!confirm(`Delete endpoint "${row.name}"?`)) return
      await api.deleteEndpoint(row.id)
    }
    setDraftEndpoints((list) => list.filter((_, i) => i !== idx))
  }

  const save = async () => {
    setSaving(true)
    setErr(null)
    try {
      const payload = { ...form }
      // Only send api_key on edit when the user actually touched the field or hit "Clear"
      if (editing && !form._keyTouched) delete payload.api_key
      // Drop local / server-only fields that shouldn't be sent to PATCH
      ;['_keyTouched', 'id', 'has_api_key', 'api_key_preview', 'endpoints'].forEach((k) => { delete payload[k] })

      if (editing) {
        await api.updateProvider(provider.id, payload)
        // Persist endpoint changes made while editing
        for (const e of draftEndpoints) {
          if (!e.name || !e.path) continue
          const base = {
            name: e.name, method: e.method, path: e.path, description: e.description || '',
            auth_mode: e.auth_mode || 'inherit',
          }
          const body = e._keyTouched ? { ...base, api_key: e.api_key || '' } : base
          if (e._new) {
            await api.addEndpoint(provider.id, body)
          } else if ((e._dirty || e._keyTouched) && e.id) {
            await api.updateEndpoint(e.id, body)
          }
        }
      } else {
        const endpoints = draftEndpoints
          .filter((e) => e.name && e.path)
          .map((e) => ({
            name: e.name, method: e.method, path: e.path, description: e.description || '',
            auth_mode: e.auth_mode || 'inherit',
            ...(e.api_key ? { api_key: e.api_key } : {}),
          }))
        await api.createProvider({ ...payload, endpoints })
      }
      onSaved()
    } catch (e) {
      setErr(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="card w-full max-w-3xl h-full sm:h-auto sm:max-h-[92vh] overflow-y-auto rounded-none sm:rounded-lg sm:shadow-panel-lg">
        <div className="p-4 sm:p-5 border-b border-ink-700 flex items-center justify-between sticky top-0 bg-ink-900 z-10">
          <div>
            <div className="font-semibold">{editing ? `Edit ${provider.name}` : 'Add new provider'}</div>
            <div className="text-xs text-ink-400 mt-0.5">
              {editing ? 'Update config, rotate the key, or manage endpoints.' : 'Configure an API you want to call from the playground.'}
            </div>
          </div>
          <button className="btn-ghost" onClick={onClose}>✕</button>
        </div>

        <div className="p-4 sm:p-5 space-y-6">
          {/* ---- Basics ---- */}
          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-ink-100">Basics</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="label">Name</label>
                <input className="input" value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="GitHub API" />
              </div>
              <div>
                <label className="label">Kind</label>
                <select className="select" value={form.kind} onChange={(e) => set('kind', e.target.value)}>
                  <option value="http">HTTP / REST</option>
                  <option value="llm">LLM (chat completions)</option>
                </select>
              </div>
            </div>
            <div>
              <label className="label">Base URL</label>
              <input className="input font-mono text-xs" value={form.base_url} onChange={(e) => set('base_url', e.target.value)} placeholder="https://api.example.com" />
              <p className="text-[11px] text-ink-400 mt-1">Endpoint paths below are appended to this.</p>
            </div>
            {form.kind === 'llm' && (
              <ModelListEditor
                models={form.models}
                defaultModel={form.default_model}
                onChange={(models, defaultModel) => {
                  setForm((f) => ({ ...f, models, default_model: defaultModel }))
                }}
              />
            )}
            <div>
              <label className="label">Notes</label>
              <textarea className="textarea text-xs" rows={2} value={form.notes} onChange={(e) => set('notes', e.target.value)} placeholder="Where to get the API key, quirks, etc." />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.enabled} onChange={(e) => set('enabled', e.target.checked)} className="accent-accent" />
              <span>Enabled</span>
            </label>
          </section>

          {/* ---- Auth ---- */}
          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-ink-100">Authentication</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="label">Auth type</label>
                <select className="select" value={form.auth_type} onChange={(e) => set('auth_type', e.target.value)}>
                  <option value="bearer">Bearer token</option>
                  <option value="basic">Basic (username:password)</option>
                  <option value="oauth2_cc">OAuth 2.0 (client credentials)</option>
                  <option value="header">Custom header</option>
                  <option value="query">Query param</option>
                  <option value="hmac">HMAC-SHA256 (signed request)</option>
                  <option value="jwt_hs">JWT (HS256, self-minted)</option>
                  <option value="none">None</option>
                </select>
              </div>
              {form.auth_type === 'bearer' && (
                <div>
                  <label className="label">Prefix</label>
                  <input className="input" value={form.auth_prefix} onChange={(e) => set('auth_prefix', e.target.value)} placeholder="Bearer " />
                </div>
              )}
              {form.auth_type === 'header' && (
                <>
                  <div>
                    <label className="label">Header name</label>
                    <input className="input" value={form.auth_header_name} onChange={(e) => set('auth_header_name', e.target.value)} placeholder="x-api-key" />
                  </div>
                  <div className="col-span-2">
                    <label className="label">Header prefix (optional)</label>
                    <input className="input" value={form.auth_prefix} onChange={(e) => set('auth_prefix', e.target.value)} placeholder="(optional, e.g. 'Token ')" />
                  </div>
                </>
              )}
              {form.auth_type === 'query' && (
                <div>
                  <label className="label">Query param name</label>
                  <input className="input" value={form.auth_query_param} onChange={(e) => set('auth_query_param', e.target.value)} placeholder="api_key" />
                </div>
              )}
              {form.auth_type === 'basic' && (
                <div className="col-span-2 text-xs text-ink-400">
                  Enter the credentials below as <code className="font-mono text-ink-200">username:password</code>. Sent as <code className="font-mono text-ink-200">Authorization: Basic base64(user:pass)</code>.
                </div>
              )}
              {form.auth_type === 'oauth2_cc' && (
                <>
                  <div className="col-span-2">
                    <label className="label">Token URL</label>
                    <input className="input" value={form.oauth_token_url} onChange={(e) => set('oauth_token_url', e.target.value)} placeholder="https://auth.example.com/oauth/token" />
                  </div>
                  <div>
                    <label className="label">Client ID</label>
                    <input className="input font-mono text-xs" value={form.oauth_client_id} onChange={(e) => set('oauth_client_id', e.target.value)} placeholder="your-client-id" />
                  </div>
                  <div>
                    <label className="label">Scope (optional)</label>
                    <input className="input" value={form.oauth_scope} onChange={(e) => set('oauth_scope', e.target.value)} placeholder="read write" />
                  </div>
                  <div className="col-span-2">
                    <label className="label">Auth style</label>
                    <select className="select" value={form.oauth_auth_style} onChange={(e) => set('oauth_auth_style', e.target.value)}>
                      <option value="body">Credentials in request body (most servers)</option>
                      <option value="basic">HTTP Basic header (RFC-strict)</option>
                    </select>
                  </div>
                  <div className="col-span-2 text-xs text-ink-400">
                    Client secret goes in the key field below. Backend fetches + caches an access token, refreshes 30 s before expiry, and sends it as <code className="font-mono text-ink-200">Authorization: Bearer &lt;token&gt;</code>.
                  </div>
                </>
              )}
              {form.auth_type === 'hmac' && (
                <div className="col-span-2 text-xs text-ink-400">
                  HMAC-SHA256: the secret below signs <code className="font-mono text-ink-200">METHOD\npath\nsha256(body)\ntimestamp</code>. Override header names in Extra headers JSON: <code className="font-mono text-ink-200">hmac_ts_header</code>, <code className="font-mono text-ink-200">hmac_sig_header</code>, <code className="font-mono text-ink-200">hmac_sig_prefix</code>.
                </div>
              )}
              {form.auth_type === 'jwt_hs' && (
                <>
                  <div>
                    <label className="label">Header name</label>
                    <input className="input" value={form.auth_header_name} onChange={(e) => set('auth_header_name', e.target.value)} placeholder="Authorization" />
                  </div>
                  <div>
                    <label className="label">Prefix</label>
                    <input className="input" value={form.auth_prefix} onChange={(e) => set('auth_prefix', e.target.value)} placeholder="Bearer " />
                  </div>
                  <div className="col-span-2 text-xs text-ink-400">
                    Mints an HS256 JWT with the secret below. Configure claims in Extra headers JSON: <code className="font-mono text-ink-200">jwt_claims</code> (object) and <code className="font-mono text-ink-200">jwt_exp_seconds</code> (int, default 300). <code className="font-mono text-ink-200">iat</code> and <code className="font-mono text-ink-200">exp</code> are set automatically.
                  </div>
                </>
              )}
            </div>

            {form.auth_type !== 'none' && (
              <div>
                <label className="label flex items-center justify-between">
                  <span>API key</span>
                  {editing && provider?.has_api_key && !form._keyTouched && (
                    <span className="text-emerald-700 normal-case tracking-normal">
                      ● saved: <span className="font-mono">{provider.api_key_preview || '●●●●'}</span> — leave blank to keep
                    </span>
                  )}
                  {editing && form._keyTouched && form.api_key === '' && (
                    <span className="text-red-700 normal-case tracking-normal">● will clear saved key on save</span>
                  )}
                </label>
                <input
                  className="input font-mono text-xs"
                  type="password"
                  value={form.api_key}
                  onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value, _keyTouched: true }))}
                  placeholder={editing && provider?.has_api_key ? (provider.api_key_preview || '●●●●●●●●●●') : 'paste key'}
                  autoComplete="off"
                />
                {editing && provider?.has_api_key && (
                  <button
                    type="button"
                    className="text-[11px] text-red-700 hover:underline mt-1"
                    onClick={() => setForm((f) => ({ ...f, api_key: '', _keyTouched: true }))}
                  >
                    Clear saved key
                  </button>
                )}
              </div>
            )}

            <div>
              <label className="label">Extra headers (JSON)</label>
              <textarea className="textarea text-xs" rows={2} value={form.extra_headers} onChange={(e) => set('extra_headers', e.target.value)} placeholder='{"accept": "application/vnd.github+json"}' />
            </div>
            <div>
              <label className="label">Variables (JSON)</label>
              <textarea
                className="textarea text-xs"
                rows={3}
                value={form.variables}
                onChange={(e) => set('variables', e.target.value)}
                placeholder='{"base_path": "v1", "user_id": "42"}'
              />
              <p className="text-[11px] text-ink-400 mt-1">
                Reference these anywhere with <code className="font-mono text-ink-200">{'{{name}}'}</code> — in paths, headers, query, and request bodies. Substituted before the request is sent.
              </p>
            </div>
          </section>

          {/* ---- Endpoints (HTTP kind only) ---- */}
          {form.kind === 'http' && (
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-ink-100">Endpoints</h3>
              <button className="btn-secondary text-xs" onClick={addEndpointRow}>+ Add endpoint</button>
            </div>
            <p className="text-[11px] text-ink-400">Each endpoint is a named method + path you can call from the Playground.</p>

            {draftEndpoints.length === 0 && (
              <div className="text-xs text-ink-400 bg-white/50 border border-dashed border-ink-700 rounded-md p-4 text-center">
                No endpoints yet. Add one so it shows up in the Playground.
              </div>
            )}

            <div className="space-y-2">
              {draftEndpoints.map((e, i) => {
                const open = openEndpointIdx === i
                return (
                  <div key={e.id || `new-${i}`} className="border border-ink-700 rounded-md bg-white/40">
                    <div className="grid grid-cols-12 gap-2 items-center p-2">
                      <input
                        className="input col-span-12 sm:col-span-3 text-xs"
                        placeholder="Name (e.g. Get user)"
                        value={e.name}
                        onChange={(ev) => updateEndpointRow(i, { name: ev.target.value })}
                      />
                      <select
                        className="select col-span-4 sm:col-span-2 text-xs"
                        value={e.method}
                        onChange={(ev) => updateEndpointRow(i, { method: ev.target.value })}
                      >
                        {METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
                      </select>
                      <input
                        className="input col-span-8 sm:col-span-5 text-xs font-mono"
                        placeholder="/user or https://absolute.url"
                        value={e.path}
                        onChange={(ev) => updateEndpointRow(i, { path: ev.target.value })}
                      />
                      <button
                        type="button"
                        className={`col-span-6 sm:col-span-1 h-10 sm:h-9 rounded-md flex items-center justify-center transition ${authButtonClass(e)}`}
                        onClick={() => setOpenEndpointIdx(open ? null : i)}
                        title={authTooltip(e)}
                        aria-label={authTooltip(e)}
                      >
                        <KeyIcon mode={e.auth_mode || 'inherit'} hasKey={e.has_api_key || (e._keyTouched && !!e.api_key)} />
                        <span className="ml-1 text-xs sm:hidden">auth</span>
                      </button>
                      <button
                        className="col-span-6 sm:col-span-1 h-10 sm:h-9 rounded-md flex items-center justify-center text-ink-400 hover:text-red-700 hover:bg-red-600/10"
                        onClick={() => removeEndpointRow(i)}
                        aria-label="Delete endpoint"
                      >
                        <span className="sm:hidden text-xs mr-1">delete</span>✕
                      </button>
                    </div>
                    {open && (
                      <div className="border-t border-ink-700 p-3 space-y-3 bg-ink-800/40">
                        <div>
                          <label className="label">Auth for this endpoint</label>
                          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                            <ModeRadio
                              checked={(e.auth_mode || 'inherit') === 'inherit'}
                              onChange={() => updateEndpointRow(i, { auth_mode: 'inherit' })}
                              label="Use provider key"
                              hint="Default"
                            />
                            <ModeRadio
                              checked={(e.auth_mode || 'inherit') === 'override'}
                              onChange={() => updateEndpointRow(i, { auth_mode: 'override' })}
                              label="Override key"
                              hint="Set a key just for this endpoint"
                            />
                            <ModeRadio
                              checked={(e.auth_mode || 'inherit') === 'none'}
                              onChange={() => updateEndpointRow(i, { auth_mode: 'none' })}
                              label="No auth"
                              hint="Send no credentials"
                            />
                          </div>
                        </div>

                        {(e.auth_mode === 'override') && (
                          <div>
                            <label className="label flex items-center justify-between">
                              <span>API key</span>
                              {e.has_api_key && !e._keyTouched && (
                                <span className="text-emerald-700 normal-case tracking-normal">
                                  ● saved: <span className="font-mono">{e.api_key_preview || '●●●●'}</span>
                                </span>
                              )}
                            </label>
                            <input
                              type="password"
                              className="input font-mono text-xs"
                              value={e.api_key || ''}
                              placeholder={e.has_api_key ? (e.api_key_preview || '●●●●●●●●●●') + ' — leave blank to keep' : 'paste key for this endpoint'}
                              onChange={(ev) => updateEndpointRow(i, { api_key: ev.target.value, _keyTouched: true })}
                              autoComplete="off"
                            />
                            {e.has_api_key && (
                              <button
                                type="button"
                                className="text-[11px] text-red-700 hover:underline mt-1"
                                onClick={() => updateEndpointRow(i, { api_key: '', _keyTouched: true })}
                              >
                                Clear saved key
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </section>
          )}

          {err && <div className="text-sm text-red-700 bg-red-600/10 border border-red-600/30 rounded-md p-2">{err}</div>}
        </div>

        <div className="p-4 sm:p-5 border-t border-ink-700 flex flex-col-reverse sm:flex-row sm:justify-end gap-2 sticky bottom-0 bg-ink-900">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={save} disabled={saving || !form.name}>
            {saving ? 'Saving…' : editing ? 'Save changes' : 'Create provider'}
          </button>
        </div>
      </div>
    </div>
  )
}

function ModeRadio({ checked, onChange, label, hint }) {
  return (
    <button
      type="button"
      onClick={onChange}
      className={`text-left rounded-md border px-3 py-2 text-xs transition ${checked ? 'border-accent bg-accent/10 text-accent' : 'border-ink-700 bg-white text-ink-200 hover:border-ink-600'}`}
    >
      <div className="flex items-center gap-2 font-medium">
        <span className={`inline-block w-3 h-3 rounded-full border ${checked ? 'bg-accent border-accent' : 'border-ink-600'}`} />
        {label}
      </div>
      <div className="text-[11px] text-ink-400 mt-0.5">{hint}</div>
    </button>
  )
}

function authButtonClass(e) {
  const mode = e.auth_mode || 'inherit'
  const hasKey = e.has_api_key || (e._keyTouched && !!e.api_key)
  if (mode === 'none') return 'text-ink-400 hover:bg-ink-800'
  if (mode === 'override' && hasKey) return 'text-emerald-700 hover:bg-emerald-500/15'
  if (mode === 'override') return 'text-amber-700 hover:bg-amber-500/15'
  return 'text-ink-400 hover:bg-ink-800 hover:text-ink-100'
}
function authTooltip(e) {
  const mode = e.auth_mode || 'inherit'
  if (mode === 'none') return 'Auth: off — no credentials sent for this endpoint'
  if (mode === 'override') {
    return (e.has_api_key || (e._keyTouched && e.api_key))
      ? `Auth: custom key ${e.api_key_preview || '●●●●'}`
      : 'Auth: override selected, no key set yet'
  }
  return 'Auth: inherited from provider'
}

function KeyIcon({ mode, hasKey }) {
  if (mode === 'none') {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
        <line x1="3" y1="3" x2="21" y2="21" />
      </svg>
    )
  }
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill={mode === 'override' && hasKey ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
    </svg>
  )
}

function ModelListEditor({ models, defaultModel, onChange }) {
  const list = models && models.length ? models : ['']
  const update = (idx, value) => {
    const next = [...list]
    next[idx] = value
    const cleaned = next.filter((m) => m.trim())
    let newDefault = defaultModel
    if (!cleaned.includes(newDefault)) newDefault = cleaned[0] || ''
    onChange(cleaned.length ? cleaned : [], newDefault)
  }
  const remove = (idx) => {
    const next = list.filter((_, i) => i !== idx)
    const cleaned = next.filter((m) => m.trim())
    let newDefault = defaultModel
    if (!cleaned.includes(newDefault)) newDefault = cleaned[0] || ''
    onChange(cleaned, newDefault)
  }
  const add = () => onChange([...list.filter((m) => m.trim()), ''], defaultModel)

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label className="label !mb-0">Models</label>
        <button type="button" className="text-xs text-accent hover:underline" onClick={add}>+ Add model</button>
      </div>
      <p className="text-[11px] text-ink-400 mb-2">Listed here for quick switching in the Playground. One is the default.</p>
      <div className="space-y-2">
        {list.map((m, i) => {
          const isDefault = defaultModel && defaultModel === m && m.trim()
          return (
            <div key={i} className="flex items-center gap-2">
              <input
                className="input font-mono text-xs flex-1"
                value={m}
                onChange={(e) => update(i, e.target.value)}
                placeholder="openai/gpt-4o-mini"
              />
              <button
                type="button"
                onClick={() => m.trim() && onChange(list.map((x) => x.trim()).filter(Boolean), m.trim())}
                className={`text-xs px-2 py-1 rounded border ${isDefault ? 'bg-accent/15 text-accent border-accent/40' : 'border-ink-700 text-ink-400 hover:text-ink-100'}`}
                title={isDefault ? 'Default' : 'Set as default'}
                disabled={!m.trim()}
              >
                {isDefault ? '★ default' : 'Set default'}
              </button>
              <button type="button" className="btn-ghost text-ink-400 hover:text-red-700" onClick={() => remove(i)}>✕</button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
