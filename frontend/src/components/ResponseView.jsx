import { useState } from 'react'
import { toCurl } from '../utils/curl.js'

export default function ResponseView({ response, loading }) {
  if (loading) {
    return (
      <div className="card p-6 text-ink-400 text-sm flex items-center gap-2">
        <Spinner /> Sending request…
      </div>
    )
  }
  if (!response) {
    return (
      <div className="card p-6 text-ink-400 text-sm text-center">
        Response will appear here.
      </div>
    )
  }
  const { ok, status_code, latency_ms, body, headers, error, request } = response
  return (
    <div className="space-y-3">
      {request && (
        <div className="card overflow-hidden">
          <div className="px-4 py-2 border-b border-ink-700 text-xs text-ink-400 flex items-center justify-between">
            <span>Request sent</span>
            <CopyCurl request={request} />
          </div>
          <div className="p-3 text-xs font-mono space-y-1">
            <div>
              <span className="text-accent font-semibold mr-2">{request.method}</span>
              <span className="text-slate-900 break-all">{request.url}</span>
            </div>
            {Object.entries(request.headers || {}).length > 0 && (
              <div className="pt-2 border-t border-ink-700/60 mt-2">
                {Object.entries(request.headers).map(([k, v]) => (
                  <div key={k} className="text-ink-400 break-all">
                    <span className="text-slate-800">{k}</span>: {v}
                  </div>
                ))}
              </div>
            )}
            {Object.entries(request.query || {}).length > 0 && (
              <div className="pt-2 border-t border-ink-700/60 mt-2">
                <div className="text-ink-400 mb-1">Query:</div>
                {Object.entries(request.query).map(([k, v]) => (
                  <div key={k} className="text-ink-400"><span className="text-slate-800">{k}</span>={v}</div>
                ))}
              </div>
            )}
            {request.body != null && (
              <div className="pt-2 border-t border-ink-700/60 mt-2">
                <div className="text-ink-400 mb-1">Body:</div>
                <pre className="text-slate-800 whitespace-pre-wrap break-words">
                  {typeof request.body === 'string' ? request.body : JSON.stringify(request.body, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-ink-700 flex items-center gap-3 text-xs">
          <span className={`pill ${ok ? 'bg-emerald-500/15 text-emerald-700' : 'bg-red-500/15 text-red-700'}`}>
            {ok ? '● OK' : '● ERROR'}
          </span>
          <span className="text-ink-400">Status: <span className="text-slate-900 font-mono">{status_code}</span></span>
          <span className="text-ink-400">Latency: <span className="text-slate-900 font-mono">{latency_ms}ms</span></span>
        </div>
        {error && (
          <div className="px-4 py-3 text-red-700 text-sm border-b border-ink-700 font-mono">{error}</div>
        )}
        <details open={!ok}>
          <summary className="px-4 py-2 text-xs text-ink-400 cursor-pointer hover:text-slate-900 border-b border-ink-700">
            Response body {typeof body === 'object' && body !== null ? `(${Object.keys(body).length} fields)` : ''}
          </summary>
          <div className="p-4">
            <pre className="text-xs font-mono text-slate-900 overflow-auto max-h-[50vh] whitespace-pre-wrap break-words">
              {typeof body === 'string' ? body : JSON.stringify(body, null, 2)}
            </pre>
          </div>
        </details>
        <details className="border-t border-ink-700">
          <summary className="px-4 py-2 text-xs text-ink-400 cursor-pointer hover:text-slate-900">Response headers</summary>
          <pre className="px-4 py-2 text-[11px] font-mono text-ink-400 overflow-auto">
            {Object.entries(headers || {}).map(([k, v]) => `${k}: ${v}`).join('\n')}
          </pre>
        </details>
      </div>
    </div>
  )
}

function CopyCurl({ request }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(toCurl(request))
      setCopied(true)
      setTimeout(() => setCopied(false), 1400)
    } catch {}
  }
  return (
    <button onClick={copy} className="text-[11px] text-ink-400 hover:text-slate-900 px-1.5 py-0.5 rounded">
      {copied ? 'copied' : 'copy as cURL'}
    </button>
  )
}

function Spinner() {
  return (
    <svg className="animate-spin w-4 h-4 text-accent" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
      <path d="M4 12a8 8 0 0 1 8-8" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}
