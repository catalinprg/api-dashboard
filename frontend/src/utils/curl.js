// Build a cURL command from a request echo (method, url, headers, query, body).
// Headers here are already masked for display — the generated cURL will include
// the masked placeholder for Authorization, so the user swaps in their real key.

function shellEscape(s) {
  if (s == null) return "''"
  const v = String(s)
  if (/^[A-Za-z0-9_./:=@+-]+$/.test(v)) return v
  return `'${v.replace(/'/g, `'\\''`)}'`
}

export function toCurl(request) {
  if (!request) return ''
  const { method = 'GET', url, headers = {}, query = {}, body } = request
  const q = new URLSearchParams(query || {}).toString()
  const fullUrl = q ? `${url}${url.includes('?') ? '&' : '?'}${q}` : url
  const parts = [`curl -X ${method}`, shellEscape(fullUrl)]
  for (const [k, v] of Object.entries(headers || {})) {
    parts.push(`-H ${shellEscape(`${k}: ${v}`)}`)
  }
  if (body != null && !['GET', 'HEAD'].includes(method)) {
    const data = typeof body === 'string' ? body : JSON.stringify(body)
    parts.push(`--data ${shellEscape(data)}`)
  }
  return parts.join(' \\\n  ')
}
