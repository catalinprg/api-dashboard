import { useMemo, useState } from 'react'
import { api } from '../api.js'
import ResponseView from './ResponseView.jsx'

const SAMPLE_QUERY = `# Write a query here, e.g.:
# query { viewer { login } }
`

export default function GraphQLPanel({ providers }) {
  const graphqlProviders = useMemo(
    () => providers.filter((p) => p.enabled && p.kind === 'graphql'),
    [providers],
  )
  const [providerId, setProviderId] = useState(() => graphqlProviders[0]?.id ?? '')
  const [query, setQuery] = useState(SAMPLE_QUERY)
  const [variables, setVariables] = useState('{}')
  const [operationName, setOperationName] = useState('')
  const [loading, setLoading] = useState(false)
  const [response, setResponse] = useState(null)
  const [parseErr, setParseErr] = useState(null)

  const send = async () => {
    setParseErr(null)
    if (!providerId) { setParseErr('Pick a GraphQL provider first.'); return }
    if (!query.trim() || query.trim().startsWith('#')) { setParseErr('Write a query first.'); return }
    let vars = undefined
    if (variables.trim()) {
      try {
        const parsed = JSON.parse(variables)
        if (parsed && typeof parsed === 'object') vars = parsed
      } catch {
        setParseErr('Variables must be valid JSON.')
        return
      }
    }
    setLoading(true)
    setResponse(null)
    try {
      const body = {
        provider_id: Number(providerId),
        query,
        ...(vars ? { variables: vars } : {}),
        ...(operationName.trim() ? { operation_name: operationName.trim() } : {}),
      }
      const res = await api.invokeGraphQL(body)
      setResponse(res)
    } catch (e) {
      setResponse({ ok: false, status_code: 0, latency_ms: 0, body: null, headers: {}, error: e.message })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-7xl mx-auto px-4 md:px-6 py-4 md:py-6">
        <div className="mb-4 md:mb-6">
          <h1 className="text-lg md:text-xl font-semibold">GraphQL</h1>
          <p className="text-xs md:text-sm text-ink-400 mt-0.5 md:mt-1">Send queries + variables to any configured GraphQL endpoint.</p>
        </div>

        {graphqlProviders.length === 0 ? (
          <div className="card p-10 text-center text-ink-400 text-sm">
            No GraphQL providers configured yet. Go to Admin → Add provider → Kind: GraphQL.
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
            <div className="lg:col-span-3 space-y-3 min-w-0">
              <div className="card p-3 [&>*]:min-w-0">
                <label className="label">Provider</label>
                <select className="select" value={providerId} onChange={(e) => setProviderId(e.target.value)}>
                  {graphqlProviders.map((p) => (
                    <option key={p.id} value={p.id}>{p.name} — {p.base_url}</option>
                  ))}
                </select>
              </div>

              <div className="card p-3 space-y-2">
                <label className="label !mb-0">Query</label>
                <textarea
                  className="textarea text-xs min-h-[260px]"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  spellCheck={false}
                />
              </div>

              <div className="card p-3 grid grid-cols-1 sm:grid-cols-2 gap-3 [&>*]:min-w-0">
                <div>
                  <label className="label">Variables (JSON)</label>
                  <textarea className="textarea text-xs" rows={5} value={variables} onChange={(e) => setVariables(e.target.value)} placeholder='{"id": "123"}' spellCheck={false} />
                </div>
                <div>
                  <label className="label">Operation name (optional)</label>
                  <input className="input" value={operationName} onChange={(e) => setOperationName(e.target.value)} placeholder="GetUser" />
                  <p className="text-[11px] text-ink-400 mt-1">Only needed if your document defines more than one operation.</p>
                </div>
              </div>

              {parseErr && <div className="text-sm text-red-700 bg-red-600/10 border border-red-600/30 rounded-md p-2">{parseErr}</div>}

              <div className="flex justify-end">
                <button className="btn-primary" onClick={send} disabled={loading}>
                  {loading ? 'Sending…' : 'Run query'}
                </button>
              </div>
            </div>

            <div className="lg:col-span-2 min-w-0">
              <ResponseView response={response} loading={loading} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
