import type { APIError, DatasetSchema, DatasetSummary, QueryRequest, QueryResponse } from './types'

async function result<T>(response: Response): Promise<T> {
  const body = await response.json()
  if (!response.ok) throw new Error((body as APIError).error?.message || 'Request failed')
  return body as T
}

export const api = {
  datasets: () => fetch('/api/datasets').then(result<DatasetSummary[]>),
  schema: (id: string) => fetch(`/api/datasets/${encodeURIComponent(id)}/schema`).then(result<DatasetSchema>),
  upload: (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return fetch('/api/datasets/upload', { method: 'POST', body }).then(result<DatasetSchema>)
  },
  query: (payload: QueryRequest) => fetch('/api/query', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }).then(result<QueryResponse>),
}
