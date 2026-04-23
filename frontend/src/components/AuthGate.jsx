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
          href="/api/auth/google/start"
          className="btn-primary w-full inline-flex items-center justify-center gap-2"
        >
          <GoogleG /> Continue with Google
        </a>
        {err && <div className="mt-3 text-xs text-red-700 bg-red-100 border border-red-300 rounded-md p-2">{err}</div>}
        <div className="mt-6 text-[11px] text-ink-400">
          Access is limited to the allowlisted email configured on the server.
        </div>
      </div>
    </div>
  )
}

function GoogleG() {
  return (
    <svg width="16" height="16" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C33.6 6.3 29 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.3-.4-3.5z"/>
      <path fill="#FF3D00" d="M6.3 14.1l6.6 4.8c1.8-4 5.6-6.9 10.1-6.9 3 0 5.8 1.1 7.9 3l5.7-5.7C33.6 6.3 29 4 24 4 16.3 4 9.7 8.4 6.3 14.1z"/>
      <path fill="#4CAF50" d="M24 44c5 0 9.5-1.9 12.9-5l-6-4.9C28.9 35.5 26.6 36 24 36c-5.3 0-9.7-3.3-11.3-8l-6.5 5C9.6 39.6 16.2 44 24 44z"/>
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.2 4.3-4.1 5.8l6 4.9c-.4.4 6.8-4.9 6.8-14.7 0-1.3-.1-2.3-.4-3.5z"/>
    </svg>
  )
}
