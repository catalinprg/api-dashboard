import { useEffect, useState } from 'react'
import { api } from '../api.js'

/**
 * Wraps the app. Behavior:
 *   - Calls /api/auth/status → if auth disabled on backend, render children as usual.
 *   - Otherwise calls /api/auth/me → if logged in, render children.
 *   - If not logged in, renders the login screen.
 */
export default function AuthGate({ children }) {
  const [status, setStatus] = useState('loading') // loading | disabled | authed | unauthed | error
  const [user, setUser] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    (async () => {
      try {
        const s = await api.authStatus()
        if (!s.enabled) { setStatus('disabled'); return }
        try {
          const me = await api.authMe()
          setUser(me)
          setStatus('authed')
        } catch {
          setStatus('unauthed')
        }
      } catch (e) {
        setErr(e.message)
        setStatus('error')
      }
    })()
  }, [])

  if (status === 'loading') {
    return <div className="h-screen w-screen flex items-center justify-center text-ink-400 text-sm">Loading…</div>
  }
  if (status === 'error') {
    return (
      <div className="h-screen w-screen flex items-center justify-center p-6">
        <div className="card p-6 max-w-md text-sm">
          <div className="font-semibold mb-2">Couldn't reach the backend</div>
          <div className="text-ink-400">{err}</div>
        </div>
      </div>
    )
  }
  if (status === 'unauthed') return <LoginScreen />
  return children(user)
}

function LoginScreen() {
  const [err, setErr] = useState('')
  // If the URL has ?error=..., surface it
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search)
    const e = sp.get('error') || sp.get('detail')
    if (e) setErr(e)
  }, [])
  return (
    <div className="h-screen w-screen flex items-center justify-center p-6 bg-ink-950">
      <div className="card p-8 max-w-sm w-full text-center">
        <div className="w-12 h-12 mx-auto rounded-lg bg-gradient-to-br from-accent to-purple-500 flex items-center justify-center mb-4">
          <svg viewBox="0 0 24 24" className="w-7 h-7 text-white" fill="currentColor">
            <path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" />
          </svg>
        </div>
        <div className="font-semibold text-lg mb-1">API Dashboard</div>
        <div className="text-xs text-ink-400 mb-6">Sign in to continue.</div>
        <a
          href="/api/auth/github/start"
          className="btn-primary w-full inline-flex items-center justify-center gap-2"
        >
          <GitHubMark /> Continue with GitHub
        </a>
        {err && <div className="mt-3 text-xs text-red-700 bg-red-100 border border-red-300 rounded-md p-2">{err}</div>}
        <div className="mt-6 text-[11px] text-ink-400">
          Access is limited to the allowlist configured on the server.
        </div>
      </div>
    </div>
  )
}

function GitHubMark() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/>
    </svg>
  )
}
