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
    return { ok: true, json: async () => ({ status: 'unverified', result: null }) }
  }
  assert.equal((await api.query({ dataset_id: 'abc', question: 'Top regions by revenue' })).status, 'unverified')
})
