// Rough per-million-token pricing. Approximate — provider sites are authoritative.
// USD per 1M tokens. {input, output}. Extend as needed.
// Matching is substring-based on the model id, longest match wins.
const TABLE = [
  // OpenAI
  { match: 'gpt-4o-mini', input: 0.15, output: 0.6 },
  { match: 'gpt-4o', input: 2.5, output: 10 },
  { match: 'gpt-4.1-mini', input: 0.4, output: 1.6 },
  { match: 'gpt-4.1', input: 2.0, output: 8.0 },
  { match: 'o4-mini', input: 1.1, output: 4.4 },
  { match: 'o3-mini', input: 1.1, output: 4.4 },
  { match: 'o3', input: 2.0, output: 8.0 },
  // Anthropic Claude
  { match: 'claude-haiku-4', input: 1.0, output: 5.0 },
  { match: 'claude-sonnet-4', input: 3.0, output: 15.0 },
  { match: 'claude-opus-4', input: 15.0, output: 75.0 },
  { match: 'claude-3-5-sonnet', input: 3.0, output: 15.0 },
  { match: 'claude-3-5-haiku', input: 0.8, output: 4.0 },
  // Google
  { match: 'gemini-2.0-flash', input: 0.1, output: 0.4 },
  { match: 'gemini-2.5-pro', input: 1.25, output: 10.0 },
  { match: 'gemini-2.5-flash', input: 0.3, output: 2.5 },
  // Meta via NVIDIA / OpenRouter
  { match: 'llama-3.3-70b', input: 0.72, output: 0.72 },
  { match: 'llama-3.1-70b', input: 0.72, output: 0.72 },
  { match: 'llama-3.1-405b', input: 3.5, output: 3.5 },
]

export function priceFor(modelId) {
  if (!modelId) return null
  const id = modelId.toLowerCase()
  let best = null
  for (const row of TABLE) {
    if (id.includes(row.match) && (!best || row.match.length > best.match.length)) best = row
  }
  return best
}

export function extractUsage(body) {
  if (!body || typeof body !== 'object') return null
  const u = body.usage
  if (!u) return null
  // OpenAI-compat
  if (typeof u.prompt_tokens === 'number' || typeof u.completion_tokens === 'number') {
    return {
      input: u.prompt_tokens || 0,
      output: u.completion_tokens || 0,
      total: u.total_tokens || ((u.prompt_tokens || 0) + (u.completion_tokens || 0)),
    }
  }
  // Anthropic native
  if (typeof u.input_tokens === 'number' || typeof u.output_tokens === 'number') {
    return {
      input: u.input_tokens || 0,
      output: u.output_tokens || 0,
      total: (u.input_tokens || 0) + (u.output_tokens || 0),
    }
  }
  return null
}

export function estimateCost(usage, modelId) {
  if (!usage) return null
  const p = priceFor(modelId)
  if (!p) return null
  const cost = (usage.input * p.input + usage.output * p.output) / 1_000_000
  return { usd: cost, priceMatch: p.match }
}

export function fmtCost(usd) {
  if (usd == null) return ''
  if (usd === 0) return '$0'
  if (usd < 0.01) return `$${usd.toFixed(4)}`
  if (usd < 1) return `$${usd.toFixed(3)}`
  return `$${usd.toFixed(2)}`
}
