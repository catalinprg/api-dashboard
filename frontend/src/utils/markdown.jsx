// Minimal, dependency-free markdown renderer for assistant replies.
// Supports: fenced code blocks (```lang), inline code (`x`), bold (**x**),
// italic (*x*), links ([t](u)), headings (# / ## / ###), lists (- / 1.), paragraphs.

import { useMemo, useState } from 'react'

export function Markdown({ text }) {
  const blocks = useMemo(() => parseBlocks(text || ''), [text])
  return (
    <div className="md-body space-y-2 text-sm">
      {blocks.map((b, i) => renderBlock(b, i))}
    </div>
  )
}

function parseBlocks(src) {
  const lines = src.replace(/\r\n/g, '\n').split('\n')
  const out = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const fence = line.match(/^```(\w+)?\s*$/)
    if (fence) {
      const lang = fence[1] || ''
      const code = []
      i++
      while (i < lines.length && !/^```\s*$/.test(lines[i])) {
        code.push(lines[i])
        i++
      }
      i++
      out.push({ type: 'code', lang, content: code.join('\n') })
      continue
    }
    if (/^#{1,3}\s+/.test(line)) {
      const level = line.match(/^(#{1,3})/)[1].length
      out.push({ type: 'heading', level, content: line.replace(/^#{1,3}\s+/, '') })
      i++
      continue
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items = []
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ''))
        i++
      }
      out.push({ type: 'ul', items })
      continue
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const items = []
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ''))
        i++
      }
      out.push({ type: 'ol', items })
      continue
    }
    if (line.trim() === '') {
      i++
      continue
    }
    // paragraph (merge consecutive non-empty lines)
    const para = [line]
    i++
    while (i < lines.length && lines[i].trim() !== '' && !/^```/.test(lines[i]) && !/^#{1,3}\s+/.test(lines[i]) && !/^\s*[-*]\s+/.test(lines[i]) && !/^\s*\d+\.\s+/.test(lines[i])) {
      para.push(lines[i])
      i++
    }
    out.push({ type: 'p', content: para.join('\n') })
  }
  return out
}

function renderBlock(b, key) {
  if (b.type === 'code') return <CodeBlock key={key} lang={b.lang} code={b.content} />
  if (b.type === 'heading') {
    const size = b.level === 1 ? 'text-lg' : b.level === 2 ? 'text-base' : 'text-sm'
    return <div key={key} className={`font-semibold ${size} mt-1`}>{renderInline(b.content)}</div>
  }
  if (b.type === 'ul') return (
    <ul key={key} className="list-disc pl-5 space-y-0.5">
      {b.items.map((it, i) => <li key={i}>{renderInline(it)}</li>)}
    </ul>
  )
  if (b.type === 'ol') return (
    <ol key={key} className="list-decimal pl-5 space-y-0.5">
      {b.items.map((it, i) => <li key={i}>{renderInline(it)}</li>)}
    </ol>
  )
  return <p key={key} className="whitespace-pre-wrap">{renderInline(b.content)}</p>
}

function CodeBlock({ lang, code }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch {}
  }
  return (
    <div className="relative group">
      <div className="flex items-center justify-between bg-ink-800 border border-ink-700 border-b-0 rounded-t-md px-3 py-1 text-[11px] text-ink-400">
        <span>{lang || 'code'}</span>
        <button className="hover:text-ink-100 transition" onClick={copy}>{copied ? 'copied' : 'copy'}</button>
      </div>
      <pre className="bg-white border border-ink-700 rounded-b-md p-3 overflow-auto text-xs font-mono text-ink-100 whitespace-pre-wrap break-words">
        {code}
      </pre>
    </div>
  )
}

function renderInline(text) {
  // tokenize: `code`, **bold**, *italic*, [text](url)
  const nodes = []
  let i = 0
  let buf = ''
  const flush = () => {
    if (buf) {
      nodes.push(buf)
      buf = ''
    }
  }
  while (i < text.length) {
    const ch = text[i]
    if (ch === '`') {
      const end = text.indexOf('`', i + 1)
      if (end > i) {
        flush()
        nodes.push(<code key={nodes.length} className="bg-ink-800 px-1 py-0.5 rounded text-[0.85em] font-mono">{text.slice(i + 1, end)}</code>)
        i = end + 1
        continue
      }
    }
    if (ch === '*' && text[i + 1] === '*') {
      const end = text.indexOf('**', i + 2)
      if (end > i) {
        flush()
        nodes.push(<strong key={nodes.length}>{text.slice(i + 2, end)}</strong>)
        i = end + 2
        continue
      }
    }
    if (ch === '*') {
      const end = text.indexOf('*', i + 1)
      if (end > i) {
        flush()
        nodes.push(<em key={nodes.length}>{text.slice(i + 1, end)}</em>)
        i = end + 1
        continue
      }
    }
    if (ch === '[') {
      const close = text.indexOf(']', i + 1)
      if (close > i && text[close + 1] === '(') {
        const urlEnd = text.indexOf(')', close + 2)
        if (urlEnd > close) {
          flush()
          nodes.push(
            <a key={nodes.length} href={text.slice(close + 2, urlEnd)} target="_blank" rel="noreferrer" className="text-accent underline">
              {text.slice(i + 1, close)}
            </a>
          )
          i = urlEnd + 1
          continue
        }
      }
    }
    buf += ch
    i++
  }
  flush()
  return nodes
}
