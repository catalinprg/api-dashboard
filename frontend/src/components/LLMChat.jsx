import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import ResponseView from './ResponseView.jsx'
import { Markdown } from '../utils/markdown.jsx'
import { extractUsage, estimateCost, fmtCost } from '../utils/pricing.js'

export default function LLMChat({ providers }) {
  const llmProviders = useMemo(() => providers.filter((p) => p.kind === 'llm' && p.enabled), [providers])

  const [sessions, setSessions] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [session, setSession] = useState(null) // full session w/ messages
  const [providerId, setProviderId] = useState('')
  const [model, setModel] = useState('')
  const [customModel, setCustomModel] = useState('')
  const [system, setSystem] = useState('')
  const [temperature, setTemperature] = useState(0.7)
  const [maxTokens, setMaxTokens] = useState('')
  const [tools, setTools] = useState([])
  const [toolsText, setToolsText] = useState('[]')
  const [showAdvanced, setShowAdvanced] = useState(false)

  const [input, setInput] = useState('')
  const [pendingEditId, setPendingEditId] = useState(null)
  const [attachments, setAttachments] = useState([]) // {kind: 'image'|'text', name, dataUrl?, text?}
  const [sessionsOpen, setSessionsOpen] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [streamText, setStreamText] = useState('')
  const [lastResponse, setLastResponse] = useState(null)
  const [sessionsUnavailable, setSessionsUnavailable] = useState(false)
  const [transientMsgs, setTransientMsgs] = useState([]) // used when sessions API is down
  const [sessionError, setSessionError] = useState(null)
  // Usage totals across the current chat session (LLM replies summed up)
  const [usageTotals, setUsageTotals] = useState({ input: 0, output: 0, total: 0, cost: 0 })
  const [lastUsage, setLastUsage] = useState(null)
  const fileRef = useRef(null)
  const scrollerRef = useRef(null)
  const abortRef = useRef(null)
  const toolCallsAcc = useRef({})
  // Always-latest reference to send() — so deferred callers (setTimeout) read fresh state
  const sendRef = useRef(null)

  const current = llmProviders.find((p) => p.id === Number(providerId))
  const providerModels = current?.models || []
  const effectiveModel = model === '__custom__' ? customModel : model
  const showCustomInput = model === '__custom__' || (!!model && providerModels.length > 0 && !providerModels.includes(model))

  const reloadSessions = async () => {
    try {
      const list = await api.listSessions()
      setSessions(list)
      setSessionsUnavailable(false)
      return list
    } catch (e) {
      setSessionsUnavailable(true)
      setSessionError(e.message)
      return []
    }
  }

  // On first load: remove any truly empty sessions so the sidebar isn't polluted.
  const pruneEmptySessions = async (list) => {
    const empties = list.filter((s) => (s.message_count || 0) === 0)
    if (empties.length === 0) return list
    for (const s of empties) {
      try { await api.deleteSession(s.id) } catch {}
    }
    return list.filter((s) => (s.message_count || 0) > 0)
  }

  useEffect(() => {
    (async () => {
      const list = await reloadSessions()
      if (list && list.length) {
        const pruned = await pruneEmptySessions(list)
        if (pruned.length !== list.length) setSessions(pruned)
      }
    })()
  }, [])

  // Load a session
  const loadSession = async (id) => {
    if (!id) return
    const s = await api.getSession(id)
    setSession(s)
    setSessionId(s.id)
    // Fall back to first LLM provider if the session has none stored
    let pid = s.provider_id || ''
    let mdl = s.model || ''
    if (!pid && llmProviders[0]) {
      pid = llmProviders[0].id
      if (!mdl) mdl = llmProviders[0].default_model || llmProviders[0].models?.[0] || ''
      try { await api.updateSession(s.id, { provider_id: Number(pid), model: mdl }) } catch {}
    }
    setProviderId(pid)
    setModel(mdl)
    setSystem(s.system_prompt || '')
    setTemperature(Number(s.temperature || 0.7))
    setMaxTokens(s.max_tokens != null ? String(s.max_tokens) : '')
    const ts = Array.isArray(s.tools) ? s.tools : []
    setTools(ts)
    setToolsText(JSON.stringify(ts, null, 2))
  }

  // "+ New chat" is now lazy: just resets local state. DB row is created on first send.
  const newSession = () => {
    setSession(null)
    setSessionId(null)
    setTransientMsgs([])
    setStreamText('')
    setLastResponse(null)
    setInput('')
    setAttachments([])
    setUsageTotals({ input: 0, output: 0, total: 0, cost: 0 })
    setLastUsage(null)
    const p = llmProviders[0]
    if (p) {
      setProviderId(p.id)
      setModel(p.default_model || p.models?.[0] || '')
    }
    setSystem('')
    setTemperature(0.7)
    setMaxTokens('')
    setSessionsOpen(false)
  }

  // On first load, if there are existing sessions, open the most recent. Otherwise start fresh.
  useEffect(() => {
    (async () => {
      if (llmProviders.length === 0) return
      if (!providerId) {
        const p = llmProviders[0]
        setProviderId(p.id)
        setModel(p.default_model || p.models?.[0] || '')
      }
      if (sessionId == null && !sessionsUnavailable && sessions.length > 0) {
        await loadSession(sessions[0].id)
      }
    })()
  }, [sessions.length, llmProviders.length, sessionsUnavailable])

  useEffect(() => {
    scrollerRef.current?.scrollTo({ top: scrollerRef.current.scrollHeight, behavior: 'smooth' })
  }, [session?.messages?.length, streamText, streaming])

  const persistSessionMeta = async (patch) => {
    if (!sessionId) return
    const updated = await api.updateSession(sessionId, patch)
    setSession(updated)
    setSessions((xs) => xs.map((s) => (s.id === updated.id ? { ...s, ...updated } : s)))
  }

  const onProviderChange = async (id) => {
    setProviderId(id)
    const p = llmProviders.find((x) => x.id === Number(id))
    const newModel = p?.default_model || p?.models?.[0] || ''
    setModel(newModel)
    setCustomModel('')
    await persistSessionMeta({ provider_id: Number(id) || null, model: newModel })
  }

  const onModelChange = async (v) => {
    setModel(v)
    if (v !== '__custom__') await persistSessionMeta({ model: v })
  }
  const onCustomModelBlur = async () => {
    if (model === '__custom__' && customModel) {
      await persistSessionMeta({ model: customModel })
    }
  }

  const onFilesPicked = async (e) => {
    const files = Array.from(e.target.files || [])
    const news = await Promise.all(files.map(async (f) => {
      const isImage = f.type.startsWith('image/')
      if (isImage) {
        const dataUrl = await new Promise((resolve, reject) => {
          const r = new FileReader()
          r.onload = () => resolve(r.result)
          r.onerror = reject
          r.readAsDataURL(f)
        })
        return { kind: 'image', name: f.name, dataUrl }
      } else {
        const text = await f.text()
        return { kind: 'text', name: f.name, text }
      }
    }))
    setAttachments((xs) => [...xs, ...news])
    e.target.value = ''
  }

  const removeAttachment = (i) => setAttachments((xs) => xs.filter((_, idx) => idx !== i))

  const buildMessageContent = () => {
    // If there are images, build multimodal content parts (OpenAI format)
    const hasImages = attachments.some((a) => a.kind === 'image')
    const textPieces = []
    if (input.trim()) textPieces.push(input.trim())
    for (const a of attachments) {
      if (a.kind === 'text') textPieces.push(`\n\n---\n[File: ${a.name}]\n${a.text}`)
    }
    const text = textPieces.join('')
    if (!hasImages) return text
    const parts = []
    if (text) parts.push({ type: 'text', text })
    for (const a of attachments) {
      if (a.kind === 'image') parts.push({ type: 'image_url', image_url: { url: a.dataUrl } })
    }
    return parts
  }

  const buildMessagesForRequest = (currentHistory, newUserContent) => {
    const VALID = new Set(['system', 'user', 'assistant', 'tool'])
    const msgs = []
    if (system.trim()) msgs.push({ role: 'system', content: system })
    for (const m of currentHistory) {
      if (!VALID.has(m.role)) continue // skip local-only error bubbles
      const out = { role: m.role, content: m.content }
      if (m.tool_call_id) out.tool_call_id = m.tool_call_id
      if (m.tool_calls) out.tool_calls = m.tool_calls
      msgs.push(out)
    }
    if (newUserContent != null) msgs.push({ role: 'user', content: newUserContent })
    return msgs
  }

  const send = async () => {
    if (!providerId || streaming) return
    const srcHistory = sessionId ? (session?.messages || []) : transientMsgs
    const lastRoleIsTool = srcHistory.length > 0 && srcHistory[srcHistory.length - 1].role === 'tool'
    if (!input.trim() && attachments.length === 0 && !lastRoleIsTool) return

    // If we're editing a prior user message, truncate the session to before it.
    if (pendingEditId != null) {
      const editId = pendingEditId
      setPendingEditId(null)
      const sourceHistory = sessionId ? (session?.messages || []) : transientMsgs
      const idx = sourceHistory.findIndex((m) => m.id === editId)
      if (idx !== -1) {
        const anchorBackendId = sourceHistory[idx].id
        if (sessionId && typeof anchorBackendId === 'number') {
          try {
            await api.truncateSessionAt(sessionId, anchorBackendId)
            await api.deleteSessionMessage(sessionId, anchorBackendId)
          } catch {}
        }
        const trimmed = sourceHistory.slice(0, idx)
        setSession((s) => s ? { ...s, messages: trimmed } : s)
        setTransientMsgs(() => [...trimmed])
      }
    }

    // Lazily create a DB session on first send (if sessions are available and we don't have one yet).
    let activeSessionId = sessionId
    if (!activeSessionId && !sessionsUnavailable) {
      try {
        const created = await api.createSession({
          name: 'New chat',
          provider_id: Number(providerId),
          model: effectiveModel || '',
          system_prompt: system || '',
          temperature: String(temperature),
          max_tokens: maxTokens === '' ? null : Number(maxTokens),
        })
        activeSessionId = created.id
        setSessionId(created.id)
        setSession(created)
        // Don't reload full list yet — we'll refresh after the assistant responds.
      } catch (e) {
        setSessionsUnavailable(true)
        setSessionError(e.message)
      }
    }

    const hasInputPayload = input.trim() || attachments.length > 0
    const content = hasInputPayload ? buildMessageContent() : null
    // History: from session when available, otherwise from local transient list
    const history = activeSessionId ? (session?.messages || []) : transientMsgs
    const msgs = buildMessagesForRequest(history, content)

    // Optimistic UI: append user message locally (only if there's one)
    if (content != null) {
      const userMsg = { id: `tmp-u-${Date.now()}`, role: 'user', content, created_at: new Date().toISOString() }
      if (activeSessionId) {
        setSession((s) => ({ ...(s || {}), messages: [...((s && s.messages) || []), userMsg] }))
      } else {
        setTransientMsgs((xs) => [...xs, userMsg])
      }
    }
    setInput('')
    setAttachments([])
    setStreaming(true)
    setStreamText('')
    setLastResponse(null)
    toolCallsAcc.current = {}

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const reqBody = {
        provider_id: Number(providerId),
        model: effectiveModel || undefined,
        messages: msgs,
        temperature: Number(temperature),
        max_tokens: maxTokens === '' ? undefined : Number(maxTokens),
      }
      if (tools && tools.length) reqBody.tools = tools
      if (activeSessionId) reqBody.session_id = activeSessionId
      const res = await fetch('/api/invoke/llm/stream', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify(reqBody),
      })

      // Fallback when /stream endpoint isn't live yet (old backend)
      if (res.status === 404) {
        const fallback = await api.invokeLLM(reqBody)
        const text = extractTextFromResponse(fallback.body)
        setLastResponse(fallback)
        const usage = extractUsage(fallback.body)
        if (usage) {
          setLastUsage(usage)
          const price = estimateCost(usage, effectiveModel)
          setUsageTotals((t) => ({
            input: t.input + usage.input,
            output: t.output + usage.output,
            total: t.total + usage.total,
            cost: t.cost + (price?.usd || 0),
          }))
        }
        if (text) {
          if (activeSessionId) {
            try {
              const fresh = await api.getSession(activeSessionId)
              setSession(fresh)
              await reloadSessions()
            } catch {}
          } else {
            setTransientMsgs((xs) => [...xs, { id: `tmp-a-${Date.now()}`, role: 'assistant', content: text, created_at: new Date().toISOString() }])
          }
        } else if (!fallback.ok) {
          const errMsg = typeof fallback.body === 'object' ? JSON.stringify(fallback.body) : (fallback.body || fallback.error || 'error')
          if (!activeSessionId) {
            setTransientMsgs((xs) => [...xs, { id: `tmp-e-${Date.now()}`, role: 'error', content: `${fallback.status_code}: ${errMsg}`, created_at: new Date().toISOString() }])
          }
        }
        setStreaming(false)
        return
      }

      if (!res.ok || !res.body) {
        const errText = await res.text().catch(() => '')
        setLastResponse({ ok: false, status_code: res.status, latency_ms: 0, body: errText, headers: {}, error: `${res.status}` })
        if (!activeSessionId) {
          setTransientMsgs((xs) => [...xs, { id: `tmp-e-${Date.now()}`, role: 'error', content: `${res.status}: ${errText || 'request failed'}`, created_at: new Date().toISOString() }])
        }
        setStreaming(false)
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      let collected = ''
      let finalRequest = null
      let finalStatus = 0
      let finalLatency = 0
      let finalError = null
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const events = buf.split('\n\n')
        buf = events.pop() || ''
        for (const ev of events) {
          const line = ev.split('\n').find((l) => l.startsWith('data:'))
          if (!line) continue
          try {
            const payload = JSON.parse(line.slice(5).trim())
            if (payload.type === 'delta') {
              collected += payload.text
              setStreamText(collected)
            } else if (payload.type === 'start') {
              finalRequest = payload.request
            } else if (payload.type === 'error') {
              finalError = payload.body || payload.error
              finalStatus = payload.status_code || 0
            } else if (payload.type === 'tool_calls') {
              // Accumulate chunked tool_calls — each chunk is an array of partials keyed by index
              const acc = toolCallsAcc.current
              for (const d of payload.delta || []) {
                const idx = d.index ?? 0
                const slot = acc[idx] || { id: '', type: 'function', function: { name: '', arguments: '' } }
                if (d.id) slot.id = d.id
                if (d.type) slot.type = d.type
                if (d.function) {
                  if (d.function.name) slot.function.name = (slot.function.name || '') + d.function.name
                  if (d.function.arguments) slot.function.arguments = (slot.function.arguments || '') + d.function.arguments
                }
                acc[idx] = slot
              }
            } else if (payload.type === 'usage') {
              const usage = extractUsage({ usage: payload.usage })
              if (usage) {
                setLastUsage(usage)
                const price = estimateCost(usage, effectiveModel)
                setUsageTotals((t) => ({
                  input: t.input + usage.input,
                  output: t.output + usage.output,
                  total: t.total + usage.total,
                  cost: t.cost + (price?.usd || 0),
                }))
              }
            } else if (payload.type === 'done') {
              finalStatus = payload.status_code || 200
              finalLatency = payload.latency_ms || 0
            }
          } catch {}
        }
      }

      // Finalize
      setStreamText('')
      setLastResponse({
        ok: !finalError,
        status_code: finalStatus,
        latency_ms: finalLatency,
        headers: {},
        body: finalError || { text: collected },
        error: finalError && typeof finalError === 'string' ? finalError : null,
        request: finalRequest,
      })

      if (activeSessionId) {
        // Refresh session (assistant message persisted server-side)
        try {
          const fresh = await api.getSession(activeSessionId)
          setSession(fresh)
          if (fresh && (fresh.name === 'New chat' || !fresh.name) && fresh.messages?.[0]?.role === 'user') {
            const firstText = typeof fresh.messages[0].content === 'string'
              ? fresh.messages[0].content
              : Array.isArray(fresh.messages[0].content)
                ? (fresh.messages[0].content.find((p) => p.type === 'text')?.text || '')
                : ''
            const title = (firstText || 'Chat').slice(0, 40).trim() || 'Chat'
            try { await api.updateSession(activeSessionId, { name: title }) } catch {}
          }
          await reloadSessions()
        } catch {}
      } else if (collected || Object.keys(toolCallsAcc.current).length > 0) {
        // Ephemeral mode: append assistant reply locally (and any tool_calls we accumulated)
        const toolCallsArr = Object.entries(toolCallsAcc.current)
          .sort(([a], [b]) => Number(a) - Number(b))
          .map(([, v]) => v)
        setTransientMsgs((xs) => [...xs, {
          id: `tmp-a-${Date.now()}`, role: 'assistant',
          content: collected || '',
          ...(toolCallsArr.length ? { tool_calls: toolCallsArr } : {}),
          created_at: new Date().toISOString(),
        }])
      }
    } catch (e) {
      setLastResponse({ ok: false, status_code: 0, latency_ms: 0, body: null, headers: {}, error: e.message })
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }

  const stop = () => {
    abortRef.current?.abort()
    abortRef.current = null
    setStreaming(false)
  }

  const deleteSession = async (id) => {
    if (!confirm('Delete this chat?')) return
    await api.deleteSession(id)
    const rest = sessions.filter((s) => s.id !== id)
    setSessions(rest)
    if (sessionId === id) {
      if (rest.length) await loadSession(rest[0].id)
      else {
        setSession(null); setSessionId(null)
        newSession()
      }
    }
  }

  // Resend the current chat history (optionally truncated up to/including `throughUserMessageId`).
  // - If `throughUserMessageId` is set, keeps up to that user message (inclusive) and drops later ones.
  // - `updatedUserContent` overrides that user message's content if provided.
  const resendFromHistory = async ({ throughUserMessageId = null, updatedUserContent = null } = {}) => {
    if (streaming || !providerId) return
    const sourceHistory = sessionId ? (session?.messages || []) : transientMsgs
    let history = sourceHistory
    let userContent = updatedUserContent

    if (throughUserMessageId != null) {
      const idx = sourceHistory.findIndex((m) => m.id === throughUserMessageId)
      if (idx === -1) return
      history = sourceHistory.slice(0, idx) // everything BEFORE that user msg
      userContent = updatedUserContent ?? sourceHistory[idx].content
      // Remove messages after & including the edited user msg (they'll be re-added after the API call)
      const anchorBackendId = sourceHistory[idx].id
      if (sessionId && typeof anchorBackendId === 'number') {
        try {
          await api.truncateSessionAt(sessionId, anchorBackendId)
          await api.deleteSessionMessage(sessionId, anchorBackendId)
        } catch {}
      }
      setSession((s) => s ? { ...s, messages: history } : s)
      setTransientMsgs(() => [...history])
    } else {
      // Regenerate last assistant reply: drop trailing assistants, re-send from the last user msg.
      const lastUserIdx = (() => {
        for (let i = sourceHistory.length - 1; i >= 0; i--) if (sourceHistory[i].role === 'user') return i
        return -1
      })()
      if (lastUserIdx === -1) return
      history = sourceHistory.slice(0, lastUserIdx)
      userContent = sourceHistory[lastUserIdx].content
      const anchorBackendId = sourceHistory[lastUserIdx].id
      if (sessionId && typeof anchorBackendId === 'number') {
        try {
          await api.truncateSessionAt(sessionId, anchorBackendId)
          await api.deleteSessionMessage(sessionId, anchorBackendId)
        } catch {}
      }
      setSession((s) => s ? { ...s, messages: history } : s)
      setTransientMsgs(() => [...history])
    }

    // Now inject as input and trigger send()
    if (typeof userContent === 'string') {
      setInput(userContent)
      setAttachments([])
    } else if (Array.isArray(userContent)) {
      const texts = userContent.filter((p) => p.type === 'text').map((p) => p.text).join('\n')
      const imgs = userContent.filter((p) => p.type === 'image_url').map((p, i) => ({ kind: 'image', name: `image-${i}`, dataUrl: p.image_url?.url }))
      setInput(texts || '')
      setAttachments(imgs)
    }
    // Use setTimeout to ensure state updates are flushed before send reads them
    setTimeout(() => sendRef.current?.(), 0)
  }

  const startEdit = (messageId, currentContent) => {
    // For user messages only: populate input, then on next send we truncate and re-run
    const text = typeof currentContent === 'string'
      ? currentContent
      : Array.isArray(currentContent)
        ? (currentContent.find((p) => p.type === 'text')?.text || '')
        : ''
    setInput(text)
    // Stash the edit target so the next send() treats it as a re-run from that point
    setPendingEditId(messageId)
  }

  const regenerate = () => resendFromHistory({ throughUserMessageId: null })

  const replyAsTool = async (toolCall) => {
    const result = prompt(`Result for tool "${toolCall.function?.name || 'tool'}":`, '')
    if (result == null) return
    const sourceHistory = sessionId ? (session?.messages || []) : transientMsgs
    const toolMsg = {
      id: `tmp-t-${Date.now()}`,
      role: 'tool',
      content: result,
      tool_call_id: toolCall.id,
      created_at: new Date().toISOString(),
    }
    if (sessionId) setSession((s) => s ? { ...s, messages: [...(s.messages || []), toolMsg] } : s)
    else setTransientMsgs((xs) => [...xs, toolMsg])
    // Auto-send (empty input but with the tool message now in history)
    setInput('')
    setTimeout(() => sendRef.current?.(), 0)
  }

  const clearCurrent = async () => {
    if (!confirm('Clear messages in this chat?')) return
    if (sessionId) {
      try {
        await api.clearSessionMessages(sessionId)
        await loadSession(sessionId)
      } catch {}
    }
    setTransientMsgs([])
    setStreamText('')
    setLastResponse(null)
    setUsageTotals({ input: 0, output: 0, total: 0, cost: 0 })
    setLastUsage(null)
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      send()
    }
  }

  // Keep the ref updated to the latest `send` closure each render
  sendRef.current = send

  if (llmProviders.length === 0) {
    return (
      <div className="card p-10 text-center text-ink-400">
        No enabled LLM providers yet. Add one in the Admin panel.
      </div>
    )
  }

  const sessionList = (
    <>
      <button className="btn-primary w-full" onClick={() => { newSession(); setSessionsOpen(false) }}>+ New chat</button>
      <div className="card max-h-[60vh] lg:max-h-[70vh] overflow-y-auto mt-2">
        {sessions.length === 0 && <div className="p-3 text-xs text-ink-400">No chats yet.</div>}
        {sessions.map((s) => (
          <div
            key={s.id}
            onClick={() => { loadSession(s.id); setSessionsOpen(false) }}
            className={`px-3 py-3 cursor-pointer text-sm border-b border-ink-700 last:border-b-0 transition flex items-center gap-2 ${sessionId === s.id ? 'bg-accent/10 text-accent' : 'hover:bg-ink-800 active:bg-ink-700'}`}
          >
            <div className="flex-1 min-w-0 truncate">{s.name || 'Untitled'}</div>
            <button
              onClick={(e) => { e.stopPropagation(); deleteSession(s.id) }}
              className="text-ink-400 hover:text-red-700 w-8 h-8 flex items-center justify-center"
              title="Delete"
            >✕</button>
          </div>
        ))}
      </div>
    </>
  )

  return (
    <div className="grid grid-cols-12 gap-4">
      {/* Sessions sidebar — visible on ≥lg */}
      <aside className="hidden lg:block lg:col-span-2">
        {sessionList}
      </aside>

      {/* Sessions drawer — mobile / tablet */}
      {sessionsOpen && (
        <>
          <button
            aria-label="Close chats"
            onClick={() => setSessionsOpen(false)}
            className="lg:hidden fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
          />
          <div className="lg:hidden fixed inset-y-0 left-0 z-50 w-80 max-w-[85vw] bg-ink-900 border-r border-ink-700 p-4 overflow-y-auto">
            <div className="flex items-center justify-between mb-3">
              <div className="font-semibold text-sm">Chats</div>
              <button onClick={() => setSessionsOpen(false)} className="w-9 h-9 flex items-center justify-center rounded-md hover:bg-ink-800" aria-label="Close">
                <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
              </button>
            </div>
            {sessionList}
          </div>
        </>
      )}

      {/* Chat area */}
      <div className="col-span-12 lg:col-span-7 space-y-4">
        <div className="card p-4 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="label">Provider</label>
              <select className="select" value={providerId} onChange={(e) => onProviderChange(e.target.value)}>
                <option value="">— Pick —</option>
                {llmProviders.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Model</label>
              {providerModels.length > 0 ? (
                <select
                  className="select font-mono text-xs"
                  value={providerModels.includes(model) ? model : '__custom__'}
                  onChange={(e) => {
                    const v = e.target.value
                    onModelChange(v)
                    if (v !== '__custom__') setCustomModel('')
                  }}
                >
                  {providerModels.map((m) => (
                    <option key={m} value={m}>{m}{m === current?.default_model ? '  · default' : ''}</option>
                  ))}
                  <option value="__custom__">Custom…</option>
                </select>
              ) : (
                <input
                  className="input font-mono text-xs"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  onBlur={() => persistSessionMeta({ model })}
                  placeholder="model id"
                />
              )}
              {showCustomInput && (
                <input
                  className="input font-mono text-xs mt-2"
                  value={customModel}
                  onChange={(e) => setCustomModel(e.target.value)}
                  onBlur={onCustomModelBlur}
                  placeholder="custom model id"
                />
              )}
            </div>
          </div>

          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className="text-xs text-ink-400 hover:text-slate-900 flex items-center gap-1"
          >
            <span className={`transition-transform ${showAdvanced ? 'rotate-90' : ''}`}>▸</span>
            Advanced (system prompt, temperature, max tokens)
          </button>

          {showAdvanced && (
            <div className="space-y-3 pt-2 border-t border-ink-700">
              <div>
                <label className="label">System prompt (optional)</label>
                <textarea className="textarea text-sm" rows={2} value={system} onChange={(e) => setSystem(e.target.value)} onBlur={() => persistSessionMeta({ system_prompt: system })} placeholder="You are a helpful assistant." />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="label">Temperature</label>
                  <input className="input" type="number" step="0.1" min="0" max="2" value={temperature} onChange={(e) => setTemperature(e.target.value)} onBlur={() => persistSessionMeta({ temperature: String(temperature) })} />
                </div>
                <div>
                  <label className="label">Max tokens <span className="text-ink-400 normal-case tracking-normal">(blank = model's max)</span></label>
                  <input className="input" type="number" min="1" value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} onBlur={() => persistSessionMeta({ max_tokens: maxTokens === '' ? null : Number(maxTokens) })} placeholder="unlimited" />
                </div>
              </div>
              <div className="text-[11px] text-ink-400 leading-relaxed">
                <div className="font-medium text-slate-700 mb-0.5">Temperature guide</div>
                <div><span className="font-mono">0</span> — deterministic / factual</div>
                <div><span className="font-mono">0.7</span> — balanced (default)</div>
                <div><span className="font-mono">1.0+</span> — more creative / varied</div>
              </div>
              <div>
                <label className="label">Tools / function calling (JSON array)</label>
                <textarea
                  className="textarea text-xs"
                  rows={5}
                  value={toolsText}
                  onChange={(e) => setToolsText(e.target.value)}
                  onBlur={() => {
                    try {
                      const parsed = JSON.parse(toolsText || '[]')
                      if (Array.isArray(parsed)) {
                        setTools(parsed)
                        persistSessionMeta({ tools: parsed })
                      }
                    } catch {}
                  }}
                  placeholder='[{"type":"function","function":{"name":"get_weather","description":"...","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}]'
                />
                <p className="text-[11px] text-ink-400 mt-1">OpenAI-compatible tool schemas. When the model emits <code className="font-mono text-slate-800">tool_calls</code>, you'll see them in the reply and can respond as a <code className="font-mono text-slate-800">tool</code> message.</p>
              </div>
            </div>
          )}
        </div>

        <div className="card flex flex-col" style={{ height: 'calc(100vh - 380px)', minHeight: 360 }}>
          <div className="px-3 md:px-4 py-2 border-b border-ink-700 flex items-center gap-2">
            <button
              className="lg:hidden btn-ghost px-2 py-1 text-xs shrink-0"
              onClick={() => setSessionsOpen(true)}
              aria-label="Show chats"
            >
              ☰ Chats
            </button>
            <div className="text-xs text-ink-400 truncate flex-1 min-w-0">
              <span className="font-medium text-slate-700">{session?.name || 'New chat'}</span>
              {session?.messages?.length ? ` · ${session.messages.length} msg` : ''}
            </div>
            {(usageTotals.total > 0) && (
              <span className="text-[11px] text-ink-400 font-mono shrink-0" title="Session tokens in/out and estimated cost">
                {usageTotals.input}↑ / {usageTotals.output}↓
                {usageTotals.cost > 0 && ` · ${fmtCost(usageTotals.cost)}`}
              </span>
            )}
            {((session?.messages?.length || 0) + transientMsgs.length) > 0 && (
              <button className="text-xs text-ink-400 hover:text-slate-900 shrink-0" onClick={clearCurrent}>Clear</button>
            )}
          </div>

          <div ref={scrollerRef} className="flex-1 overflow-y-auto p-4 space-y-3">
            {(sessionId ? (session?.messages || []) : transientMsgs).length === 0 && !streaming && (
              <div className="h-full flex items-center justify-center text-ink-400 text-sm text-center px-6">
                Send a message below. Press <span className="kbd ml-1">⌘ ↵</span> or click Send.
              </div>
            )}
            {(sessionId ? (session?.messages || []) : transientMsgs).map((m, i, arr) => (
              <Bubble
                key={m.id}
                msg={m}
                isLast={i === arr.length - 1}
                onEdit={m.role === 'user' && !streaming ? () => startEdit(m.id, m.content) : null}
                onRegenerate={m.role === 'assistant' && i === arr.length - 1 && !streaming ? regenerate : null}
                onReplyAsTool={m.role === 'assistant' && !streaming ? replyAsTool : null}
              />
            ))}
            {streaming && <Bubble msg={{ role: 'assistant', content: streamText || '…', _pending: true }} />}
          </div>

          {attachments.length > 0 && (
            <div className="px-3 pt-2 border-t border-ink-700 flex flex-wrap gap-2">
              {attachments.map((a, i) => (
                <div key={i} className="flex items-center gap-1 text-xs bg-ink-800 border border-ink-700 rounded-md px-2 py-1">
                  {a.kind === 'image' ? (
                    <img src={a.dataUrl} alt={a.name} className="w-8 h-8 object-cover rounded" />
                  ) : (
                    <span>📄</span>
                  )}
                  <span className="max-w-[140px] truncate">{a.name}</span>
                  <button className="text-ink-400 hover:text-red-700 ml-1" onClick={() => removeAttachment(i)}>✕</button>
                </div>
              ))}
            </div>
          )}

          <div className="p-3 border-t border-ink-700">
            <div className="flex gap-2">
              <input ref={fileRef} type="file" accept="image/*,text/*,.txt,.md,.json,.csv" multiple className="hidden" onChange={onFilesPicked} />
              <button className="btn-secondary" onClick={() => fileRef.current?.click()} title="Attach file or image">📎</button>
              <textarea
                className="textarea text-sm !font-sans flex-1"
                rows={2}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Type your message…"
                disabled={streaming}
              />
              {streaming ? (
                <button className="btn-danger self-stretch" onClick={stop}>Stop</button>
              ) : (
                <button
                  className="btn-primary self-stretch"
                  onClick={send}
                  disabled={(() => {
                    if (!providerId) return true
                    if (input.trim() || attachments.length > 0) return false
                    const list = sessionId ? (session?.messages || []) : transientMsgs
                    return !(list.length > 0 && list[list.length - 1].role === 'tool')
                  })()}
                >
                  Send
                </button>
              )}
            </div>
            {!providerId && (
              <div className="mt-2 text-xs text-amber-700 bg-amber-500/10 border border-amber-500/30 rounded-md px-2 py-1">
                Pick a provider above before sending.
              </div>
            )}
            {sessionsUnavailable && (
              <div className="mt-2 text-xs text-amber-700 bg-amber-500/10 border border-amber-500/30 rounded-md px-2 py-1 flex items-center justify-between gap-2">
                <span>Chat history isn't being saved — session endpoints weren't reachable. Restart the backend, then retry.</span>
                <button
                  className="underline text-amber-700 hover:text-amber-800 shrink-0"
                  onClick={async () => {
                    const list = await reloadSessions()
                    if (!sessionsUnavailable && list.length === 0 && llmProviders.length > 0) {
                      newSession()
                    } else if (list.length > 0 && !sessionId) {
                      await loadSession(list[0].id)
                    }
                  }}
                >Retry</button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Right: raw response — inline on desktop, collapsible on mobile */}
      <div className="col-span-12 lg:col-span-3">
        <div className="hidden lg:block">
          <ResponseView response={lastResponse} loading={streaming && !streamText} />
        </div>
        <details className="lg:hidden card">
          <summary className="px-4 py-3 cursor-pointer text-sm font-medium text-ink-400 hover:text-slate-900">
            Raw request / response {lastResponse ? `· ${lastResponse.status_code || '—'}` : ''}
          </summary>
          <div className="p-3 pt-0">
            <ResponseView response={lastResponse} loading={streaming && !streamText} />
          </div>
        </details>
      </div>
    </div>
  )
}

function Bubble({ msg, onEdit, onRegenerate, onReplyAsTool }) {
  const isUser = msg.role === 'user'
  const isTool = msg.role === 'tool'
  const isError = msg.role === 'error'
  const align = isUser ? 'justify-end' : 'justify-start'
  const bg = isError
    ? 'bg-red-100 border border-red-300 text-red-800'
    : isUser
      ? 'bg-accent text-white'
      : isTool
        ? 'bg-amber-50 border border-amber-300 text-amber-900'
        : 'bg-white border border-ink-700 text-slate-900'

  const content = msg.content
  const images = []
  let text = ''
  const toolCalls = Array.isArray(msg.tool_calls) ? msg.tool_calls : (content && typeof content === 'object' && content.tool_calls) || null
  if (typeof content === 'string') {
    text = content
  } else if (Array.isArray(content)) {
    for (const p of content) {
      if (p?.type === 'text') text += (text ? '\n\n' : '') + (p.text || '')
      if (p?.type === 'image_url' && p.image_url?.url) images.push(p.image_url.url)
    }
  } else if (content && typeof content === 'object') {
    if (typeof content.content === 'string') text = content.content
  }

  const copy = async () => {
    try { await navigator.clipboard.writeText(text) } catch {}
  }

  return (
    <div className={`group flex ${align}`}>
      <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm break-words ${bg} ${msg._pending ? 'opacity-90' : ''}`}>
        {images.length > 0 && (
          <div className="flex gap-2 flex-wrap mb-2">
            {images.map((src, i) => (
              <img key={i} src={src} alt="" className="max-w-full max-h-48 rounded border border-ink-700" />
            ))}
          </div>
        )}
        {!isUser && !isError && !isTool ? <Markdown text={text} /> : <div className="whitespace-pre-wrap">{text}</div>}
        {toolCalls && toolCalls.length > 0 && (
          <div className="mt-2 space-y-2">
            {toolCalls.map((tc, i) => (
              <div key={tc.id || i} className="rounded-md border border-ink-700 bg-ink-800/50 p-2 text-[11px] font-mono">
                <div className="text-slate-800 font-semibold">
                  🔧 {tc.function?.name || tc.name || 'tool'}
                </div>
                <div className="text-ink-400 mt-1 whitespace-pre-wrap break-words">{tc.function?.arguments || tc.arguments || ''}</div>
                {onReplyAsTool && (
                  <button
                    className="text-accent hover:underline text-[11px] mt-1"
                    onClick={() => onReplyAsTool(tc)}
                  >
                    reply as tool
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
        {!msg._pending && !isError && (onEdit || onRegenerate || text) && (
          <div className={`flex gap-2 mt-1 opacity-0 group-hover:opacity-100 transition text-[11px] ${isUser ? 'text-white/70' : 'text-ink-400'}`}>
            {text && <button onClick={copy} className="hover:underline">copy</button>}
            {onEdit && <button onClick={onEdit} className="hover:underline">edit</button>}
            {onRegenerate && <button onClick={onRegenerate} className="hover:underline">regenerate</button>}
          </div>
        )}
      </div>
    </div>
  )
}

function extractTextFromResponse(body) {
  if (!body || typeof body !== 'object') return ''
  const c = body.choices?.[0]
  if (c?.message?.content) return c.message.content
  if (typeof c?.text === 'string') return c.text
  if (Array.isArray(body.content)) {
    return body.content.filter((p) => p.type === 'text').map((p) => p.text).join('\n')
  }
  return ''
}
