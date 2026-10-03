import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { DatasetSchema, DatasetSummary, QueryResponse, QueryResult } from './types'

function ResultTable({ result }: { result: QueryResult }) {
  if (result.rows.length === 0) return <p>No rows returned.</p>
  return <div className="table-wrap"><table><thead><tr>{result.columns.map((column, i) => <th key={i}>{column}</th>)}</tr></thead><tbody>{result.rows.slice(0, 1000).map((row, i) => <tr key={i}>{row.map((value, j) => <td key={j}>{value === null ? '—' : String(value)}</td>)}</tr>)}</tbody></table>{result.rows.length > 1000 && <p>Showing the first 1,000 rows.</p>}</div>
}

export function App() {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [selected, setSelected] = useState('')
  const [schema, setSchema] = useState<DatasetSchema | null>(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [question, setQuestion] = useState('')
  const [query, setQuery] = useState<QueryResponse | null>(null)
  const [queryBusy, setQueryBusy] = useState(false)
  const [queryError, setQueryError] = useState('')
  const queryRun = useRef(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    api.datasets().then(data => { if (active) setDatasets(data) }).catch(e => { if (active) setError(e.message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [retry])

  useEffect(() => {
    if (!selected) { queryRun.current += 1; setSchema(null); setQuery(null); setQueryBusy(false); return }
    let active = true
    queryRun.current += 1
    setQueryBusy(false)
    setSchema(null)
    setQuery(null)
    setError('')
    api.schema(selected).then(data => { if (active) setSchema(data) }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [selected, retry])

  async function upload(file?: File) {
    if (!file) return
    setError('')
    if (!/\.(csv|parquet)$/i.test(file.name)) { setError('Choose a CSV or Parquet file'); return }
    setUploading(true)
    try {
      const added = await api.upload(file)
      setDatasets(current => [added.dataset, ...current])
      setSelected(added.dataset.id)
      setSchema(added)
    } catch (e) { setError(e instanceof Error ? e.message : 'Upload failed') }
    finally { setUploading(false) }
  }

  async function submitQuery() {
    if (!selected || !question.trim()) return
    setQueryBusy(true)
    setQueryError('')
    setQuery(null)
    const run = ++queryRun.current
    try { const response = await api.query({ dataset_id: selected, question: question.trim(), max_rows: 1000 }); if (run === queryRun.current) setQuery(response) }
    catch (e) { if (run === queryRun.current) setQueryError(e instanceof Error ? e.message : 'Query failed') }
    finally { if (run === queryRun.current) setQueryBusy(false) }
  }

  return <main>
    <header><h1>DataTrust</h1><p>Grounded analytics</p></header>
    <section aria-labelledby="datasets-heading">
      <h2 id="datasets-heading">Datasets</h2>
      <label className="upload">Upload CSV or Parquet<input type="file" accept=".csv,.parquet" disabled={uploading} onChange={e => { void upload(e.target.files?.[0]); e.target.value = '' }} /></label>
      {uploading && <p role="status">Uploading and profiling…</p>}
      {error && <p role="alert" className="error">{error} <button onClick={() => { setError(''); setRetry(value => value + 1) }}>Retry</button></p>}
      {loading ? <p role="status">Loading datasets…</p> : datasets.length === 0 ? <p>No datasets yet. Upload one to inspect its schema.</p> : <label className="selector">Select dataset<select value={selected} onChange={e => setSelected(e.target.value)}><option value="">Choose a dataset</option>{datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>}
    </section>
    {selected && !schema && !error && <p role="status">Loading schema…</p>}
    {schema && <section aria-labelledby="schema-heading">
      <h2 id="schema-heading">{schema.dataset.name}</h2>
      <p>{schema.table.row_count.toLocaleString()} rows · {schema.table.columns.length} columns</p>
      {schema.warnings.map(w => <p className="warning" key={w}>{w}</p>)}
      <div className="table-wrap"><table><thead><tr><th>Column</th><th>Type</th><th>Nulls</th><th>Distinct</th><th>Range</th><th>Samples</th></tr></thead><tbody>{schema.table.columns.map(c => <tr key={c.name}><th scope="row">{c.name}</th><td>{c.dtype}</td><td>{c.profile ? `${c.profile.null_count} (${c.profile.null_percentage}%)` : 'Unavailable'}</td><td>{c.profile?.distinct_count ?? '—'}</td><td>{c.profile ? `${c.profile.minimum ?? '—'} – ${c.profile.maximum ?? '—'}` : '—'}</td><td>{c.profile?.samples.join(', ') || '—'}</td></tr>)}</tbody></table></div>
      <details><summary>Version details</summary><p>Dataset ID: {schema.dataset.id}</p><p>Content version: {schema.dataset.version}</p><p>Schema hash: {schema.dataset.schema_hash}</p></details>
    </section>}
    {schema && <section aria-labelledby="query-heading">
      <h2 id="query-heading">Ask about {schema.dataset.name}</h2>
      <label>Question<textarea value={question} onChange={e => setQuestion(e.target.value)} maxLength={2000} placeholder="What were the top regions by revenue?" /></label>
      <button disabled={queryBusy || !question.trim()} onClick={() => void submitQuery()}>Generate grounded SQL</button>
      {queryBusy && <p role="status">Running the query pipeline…</p>}
      {queryError && <p role="alert" className="error">{queryError}</p>}
      {query && <div aria-live="polite">
        <h3>Status: {query.status}</h3>
        {query.route && <p>Route: {query.route.route}</p>}
        {query.error && <p role="alert" className="error">{query.error.message}</p>}
        {query.answer && <p>{query.answer}</p>}
        {query.plan?.assumptions.length ? <p>Assumptions: {query.plan.assumptions.join('; ')}</p> : null}
        {query.sql && <details open><summary>{query.status === 'unverified' ? 'Unverified SQL — not executed' : 'Generated SQL'}</summary><pre>{query.sql}</pre></details>}
        {query.result ? <ResultTable result={query.result} /> : query.sql && <p>No result table: this SQL has not been executed.</p>}
        {query.evidence && <details><summary>Retrieved evidence ({query.evidence.documents.length})</summary><ul>{query.evidence.documents.map(d => <li key={d.document_id}><strong>{d.object_type}: {d.column_name || d.table_name}</strong> · score {d.score} · {d.content}</li>)}</ul></details>}
        <details><summary>Pipeline stages ({query.metadata.latency_ms} ms)</summary><ol>{query.metadata.stages.map((s, i) => <li key={i}>{s.name}: {s.duration_ms} ms</li>)}</ol></details>
      </div>}
    </section>}
  </main>
}
