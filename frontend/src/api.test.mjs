import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import { api } from './api.ts'

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })

test('lists datasets', async () => {
  globalThis.fetch = async url => {
    assert.equal(url, '/api/datasets')
    return { ok: true, json: async () => [{ id: 'abc', name: 'Sales' }] }
  }
  assert.equal((await api.datasets())[0].name, 'Sales')
})

test('upload sends multipart file and returns schema', async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/datasets/upload')
    assert.equal(options.method, 'POST')
    assert.ok(options.body instanceof FormData)
    return { ok: true, json: async () => ({ dataset: { id: 'abc' } }) }
  }
  assert.equal((await api.upload(new File(['a\n1'], 'sales.csv'))).dataset.id, 'abc')
})

test('surfaces backend validation errors', async () => {
  globalThis.fetch = async () => ({ ok: false, json: async () => ({ error: { message: 'File is empty' } }) })
  await assert.rejects(api.schema('abc'), /File is empty/)
})

test('submits a typed natural-language query', async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/query')
    assert.equal(options.method, 'POST')
    assert.equal(JSON.parse(options.body).question, 'Top regions by revenue')
    return { ok: true, json: async () => ({ status: 'verified', result: { columns: [], rows: [], row_count: 0, truncated: false, duration_ms: 1 } }) }
  }
  assert.equal((await api.query({ dataset_id: 'abc', question: 'Top regions by revenue' })).status, 'verified')
})

test('uses a login token for history and feedback', async () => {
  globalThis.fetch = async (url, options = {}) => {
    if (url === '/api/auth/login') return { ok: true, json: async () => ({ access_token: 'test-token' }) }
    assert.equal(options.headers.Authorization, 'Bearer test-token')
    if (url.startsWith('/api/history')) return { ok: true, json: async () => [{ query_id: 'q1' }] }
    if (url === '/api/query/q1/feedback') return { ok: true, json: async () => ({ status: 'recorded' }) }
    if (url === '/api/auth/logout') return { ok: true, json: async () => ({ status: 'signed_out' }) }
    throw new Error(url)
  }
  await api.login('one@example.com', 'password')
  assert.equal((await api.history('abc'))[0].query_id, 'q1')
  assert.equal((await api.feedback('q1', 'correct', 'good')).status, 'recorded')
  api.logout()
  assert.equal(api.hasToken(), false)
})
