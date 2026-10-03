import type { APIError, DatasetSchema, DatasetSummary, HistoryItem, QueryRequest, QueryResponse } from './types'

let token = typeof sessionStorage === 'undefined' ? '' : sessionStorage.getItem('datatrust_token') || ''
const auth = (): Record<string, string> => token ? { Authorization: `Bearer ${token}` } : {}
const get = (path: string) => fetch(path, { headers: auth() })

async function result<T>(response: Response): Promise<T> {
  const body = await response.json()
  if (!response.ok) throw new Error((body as APIError).error?.message || 'Request failed')
  return body as T
}

export const api = {
  hasToken: () => Boolean(token),
  login: async (email: string, password: string) => {
    const data = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) }).then(result<{ access_token: string }>)
    token = data.access_token
    if (typeof sessionStorage !== 'undefined') sessionStorage.setItem('datatrust_token', token)
  },
  logout: () => { void fetch('/api/auth/logout', { method: 'POST', headers: auth() }).catch(() => {}); token = ''; if (typeof sessionStorage !== 'undefined') sessionStorage.removeItem('datatrust_token') },
  datasets: () => get('/api/datasets').then(result<DatasetSummary[]>),
  schema: (id: string) => get(`/api/datasets/${encodeURIComponent(id)}/schema`).then(result<DatasetSchema>),
  upload: (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return fetch('/api/datasets/upload', { method: 'POST', headers: auth(), body }).then(result<DatasetSchema>)
  },
  query: (payload: QueryRequest) => fetch('/api/query', { method: 'POST', headers: { ...auth(), 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }).then(result<QueryResponse>),
  history: (datasetId: string) => get(`/api/history?dataset_id=${encodeURIComponent(datasetId)}&limit=30`).then(result<HistoryItem[]>),
  detail: (id: string) => get(`/api/query/${encodeURIComponent(id)}`).then(result<{ question: string; response: QueryResponse }>),
  feedback: (id: string, label: string, comment: string) => fetch(`/api/query/${encodeURIComponent(id)}/feedback`, { method: 'POST', headers: { ...auth(), 'Content-Type': 'application/json' }, body: JSON.stringify({ label, comment }) }).then(result<{ status: string }>),
  export: async (id: string, format: 'csv' | 'xlsx') => {
    const response = await get(`/api/query/${encodeURIComponent(id)}/export?format=${format}`)
    if (!response.ok) throw new Error((await response.json() as APIError).error?.message || 'Export failed')
    return response.blob()
  },
}
