const BASE = ''

async function request(path, opts = {}) {
  const r = await fetch(BASE + path, {
    headers: { 'content-type': 'application/json' },
    credentials: 'same-origin',
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  })
  // If the backend requires auth and we don't have a valid session, bounce to login.
  if (r.status === 401 && !path.startsWith('/api/auth/')) {
    if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
      window.location.href = '/login'
    }
  }
  const text = await r.text()
  let data
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!r.ok) {
    const msg = (data && data.detail) || r.statusText || 'Request failed'
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return data
}

export const api = {
  listProviders: () => request('/api/providers'),
  createProvider: (data) => request('/api/providers', { method: 'POST', body: data }),
  updateProvider: (id, data) => request(`/api/providers/${id}`, { method: 'PATCH', body: data }),
  deleteProvider: (id) => request(`/api/providers/${id}`, { method: 'DELETE' }),
  pingProvider: (id) => request(`/api/providers/${id}/ping`, { method: 'POST' }),
  addEndpoint: (id, data) => request(`/api/providers/${id}/endpoints`, { method: 'POST', body: data }),
  updateEndpoint: (id, data) => request(`/api/endpoints/${id}`, { method: 'PATCH', body: data }),
  deleteEndpoint: (id) => request(`/api/endpoints/${id}`, { method: 'DELETE' }),
  invokeHTTP: (data) => request('/api/invoke/http', { method: 'POST', body: data }),
  invokeGraphQL: (data) => request('/api/invoke/graphql', { method: 'POST', body: data }),
  listHistory: (limit = 200, q = '') => request(`/api/history?limit=${limit}${q ? `&q=${encodeURIComponent(q)}` : ''}`),
  deleteHistory: (id) => request(`/api/history/${id}`, { method: 'DELETE' }),
  clearHistory: () => request('/api/history', { method: 'DELETE' }),
  // Presets
  listPresets: () => request('/api/presets'),
  createPreset: (data) => request('/api/presets', { method: 'POST', body: data }),
  updatePreset: (id, data) => request(`/api/presets/${id}`, { method: 'PATCH', body: data }),
  deletePreset: (id) => request(`/api/presets/${id}`, { method: 'DELETE' }),
  // Export / Import
  exportConfig: (includeKeys = true) => request(`/api/config/export?include_keys=${includeKeys ? 'true' : 'false'}`),
  importConfig: (data) => request('/api/config/import', { method: 'POST', body: data }),
  importSpec: (data) => request('/api/config/import-spec', { method: 'POST', body: data }),
  // Data-driven Runs
  listRuns: () => request('/api/runs'),
  getRun: (id) => request(`/api/runs/${id}`),
  createRun: (data) => request('/api/runs', { method: 'POST', body: data }),
  updateRun: (id, data) => request(`/api/runs/${id}`, { method: 'PATCH', body: data }),
  deleteRun: (id) => request(`/api/runs/${id}`, { method: 'DELETE' }),
  previewRun: (id) => request(`/api/runs/${id}/preview`, { method: 'POST' }),
  executeRun: (id, sync = false) => request(`/api/runs/${id}/execute${sync ? '?sync=true' : ''}`, { method: 'POST' }),
  listRunExecutions: (id, limit = 50) => request(`/api/runs/${id}/executions?limit=${limit}`),
  getRunExecution: (runId, execId) => request(`/api/runs/${runId}/executions/${execId}`),
  cancelRunExecution: (runId, execId) => request(`/api/runs/${runId}/executions/${execId}/cancel`, { method: 'POST' }),
  deleteRunExecution: (runId, execId) => request(`/api/runs/${runId}/executions/${execId}`, { method: 'DELETE' }),
  // Scheduled jobs
  listScheduledJobs: () => request('/api/scheduled-jobs'),
  createScheduledJob: (data) => request('/api/scheduled-jobs', { method: 'POST', body: data }),
  updateScheduledJob: (id, data) => request(`/api/scheduled-jobs/${id}`, { method: 'PATCH', body: data }),
  deleteScheduledJob: (id) => request(`/api/scheduled-jobs/${id}`, { method: 'DELETE' }),
  runScheduledJob: (id) => request(`/api/scheduled-jobs/${id}/run`, { method: 'POST' }),
  // Webhooks
  listWebhooks: () => request('/api/webhooks'),
  createWebhook: (data) => request('/api/webhooks', { method: 'POST', body: data }),
  updateWebhook: (id, data) => request(`/api/webhooks/${id}`, { method: 'PATCH', body: data }),
  deleteWebhook: (id) => request(`/api/webhooks/${id}`, { method: 'DELETE' }),
  listWebhookEvents: (id, limit = 100) => request(`/api/webhooks/${id}/events?limit=${limit}`),
  clearWebhookEvents: (id) => request(`/api/webhooks/${id}/events`, { method: 'DELETE' }),
  deleteWebhookEvent: (id) => request(`/api/webhook-events/${id}`, { method: 'DELETE' }),
  // Auth
  authStatus: () => request('/api/auth/status'),
  authMe: () => request('/api/auth/me'),
  authLogout: () => request('/api/auth/logout', { method: 'POST' }),
}


