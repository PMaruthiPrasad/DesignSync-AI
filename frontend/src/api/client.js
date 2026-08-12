/**
 * The single place the UI talks to the backend.
 *
 * All orchestration and business logic lives server-side; this module only
 * moves JSON. Components never call fetch directly.
 *
 * Base URL is empty by default, meaning "same origin" — which is how the
 * single-service Docker/Railway deploy serves the app. In development, Vite
 * proxies /api to the backend port.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      headers: options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch (cause) {
    throw new ApiError('Could not reach the API. Is the backend running?', 0)
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') {
        detail = body.detail
      } else if (Array.isArray(body.detail) && body.detail.length) {
        // FastAPI validation errors arrive as a list of field errors.
        detail = body.detail.map((e) => e.msg).join('; ')
      }
    } catch {
      /* response had no JSON body; keep the generic message */
    }
    throw new ApiError(detail, response.status)
  }

  return response.status === 204 ? null : response.json()
}

export const api = {
  health: () => request('/api/health'),

  getDemoRepository: () => request('/api/demo-repository'),

  uploadRepository: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/api/repositories/upload', { method: 'POST', body: form })
  },

  createAnalysis: (payload) =>
    request('/api/analyses', { method: 'POST', body: JSON.stringify(payload) }),

  listAnalyses: () => request('/api/analyses'),

  getAnalysis: (id) => request(`/api/analyses/${id}`),

  executeAnalysis: (id) => request(`/api/analyses/${id}/execute`, { method: 'POST' }),

  getExecution: (id) => request(`/api/executions/${id}`),

  getExecutionEvents: (id, afterSeq = 0) =>
    request(`/api/executions/${id}/events?after_seq=${afterSeq}`),

  getExecutionAgents: (id) => request(`/api/executions/${id}/agents`),

  getDashboardStats: () => request('/api/dashboard/stats'),
}
