import { useEffect, useRef, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from './api'
import type { DatasetSchema, DatasetSummary, HistoryItem, QueryResponse, QueryResult, Visualization } from './types'

function Chart({ result, spec }: { result: QueryResult; spec: Visualization }) {
  const index = (field: string | null) => result.columns.indexOf(field || '')
  if (spec.type === 'kpi' && index(spec.value) >= 0) return <div className="kpi"><strong>{spec.value}</strong><p>{String(result.rows[0]?.[index(spec.value)] ?? '—')}</p></div>
  const xi = index(spec.x), yi = index(spec.y)
  if (spec.type === 'table' || xi < 0 || yi < 0) return null
  const data = result.rows.map(row => ({ x: row[xi] as string | number, y: Number(row[yi]) })).filter(point => Number.isFinite(point.y))
  if (!data.length) return null
  return <div className="chart" role="img" aria-label={`${spec.type} chart of ${spec.y} by ${spec.x}`}><ResponsiveContainer width="100%" height={300}>
    {spec.type === 'bar' ? <BarChart data={data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="x" /><YAxis /><Tooltip /><Bar dataKey="y" fill="steelblue" /></BarChart>
      : spec.type === 'line' ? <LineChart data={data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="x" /><YAxis /><Tooltip /><Line dataKey="y" stroke="steelblue" /></LineChart>
      : <ScatterChart><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="x" type="number" /><YAxis dataKey="y" type="number" /><Tooltip /><Scatter data={data} fill="steelblue" /></ScatterChart>}
  </ResponsiveContainer></div>
}

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
  const [authRequired, setAuthRequired] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [conversationId, setConversationId] = useState('')
  const [feedbackComment, setFeedbackComment] = useState('')
  const [feedbackStatus, setFeedbackStatus] = useState('')
  const queryRun = useRef(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    api.datasets().then(data => { if (active) { setDatasets(data); setAuthRequired(false) } }).catch(e => { if (active) { if (e.message === 'Sign in to continue') setAuthRequired(true); else setError(e.message) } }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [retry])

  useEffect(() => {
    if (!selected) { queryRun.current += 1; setSchema(null); setQuery(null); setQueryBusy(false); setHistory([]); setConversationId(''); return }
    let active = true
    queryRun.current += 1
    setQueryBusy(false)
    setSchema(null)
    setQuery(null)
    setConversationId('')
    setError('')
    api.schema(selected).then(data => { if (active) setSchema(data) }).catch(e => { if (active) setError(e.message) })
    api.history(selected).then(data => { if (active) setHistory(data) }).catch(() => { if (active) setHistory([]) })
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
    try { const response = await api.query({ dataset_id: selected, question: question.trim(), conversation_id: conversationId || undefined, max_rows: 1000, visualize: true }); if (run === queryRun.current) { setQuery(response); if (response.conversation_id) setConversationId(response.conversation_id); void api.history(selected).then(setHistory) } }
    catch (e) { if (run === queryRun.current) setQueryError(e instanceof Error ? e.message : 'Query failed') }
    finally { if (run === queryRun.current) setQueryBusy(false) }
  }

  async function signIn() {
    try { await api.login(email, password); setPassword(''); setError(''); setAuthRequired(false); setRetry(value => value + 1) }
    catch (e) { setError(e instanceof Error ? e.message : 'Sign in failed') }
  }

  async function showHistory(id: string) {
    try { const detail = await api.detail(id); setQuestion(detail.question); setQuery(detail.response); setConversationId(detail.response.conversation_id || '') }
    catch (e) { setQueryError(e instanceof Error ? e.message : 'History unavailable') }
  }

  async function exportQuery(format: 'csv' | 'xlsx') {
    if (!query) return
    try {
      const blob = await api.export(query.query_id, format)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url; link.download = `query_${query.query_id}.${format}`; link.click(); URL.revokeObjectURL(url)
    } catch (e) { setQueryError(e instanceof Error ? e.message : 'Export failed') }
  }

  async function sendFeedback(label: string) {
    if (!query) return
    try { await api.feedback(query.query_id, label, feedbackComment); setFeedbackStatus('Feedback saved.'); setFeedbackComment('') }
    catch (e) { setFeedbackStatus(e instanceof Error ? e.message : 'Feedback failed') }
  }

  return <main>
    <header><h1>DataTrust</h1><p>Grounded analytics</p>{api.hasToken() && <button onClick={() => { api.logout(); setSelected(''); setDatasets([]); setAuthRequired(true) }}>Sign out</button>}</header>
    {authRequired && <section aria-labelledby="login-heading"><h2 id="login-heading">Sign in</h2><label>Email<input type="email" value={email} onChange={e => setEmail(e.target.value)} /></label><label>Password<input type="password" value={password} onChange={e => setPassword(e.target.value)} /></label><button onClick={() => void signIn()}>Sign in</button>{error && <p role="alert" className="error">{error}</p>}</section>}
    {!authRequired && <>
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
      {conversationId && <p>Continuing this conversation. <button onClick={() => setConversationId('')}>Start a new conversation</button></p>}
      <button disabled={queryBusy || !question.trim()} onClick={() => void submitQuery()}>Run verified query</button>
      {queryBusy && <p role="status">Running the query pipeline…</p>}
      {queryError && <p role="alert" className="error">{queryError}</p>}
      {query && <div aria-live="polite">
        <h3>Status: {query.status}</h3>
        {query.route && <p>Route: {query.route.route}</p>}
        {query.error && <p role="alert" className="error">{query.error.message}</p>}
        {query.answer && <p>{query.answer}</p>}
        {query.metadata.repair_attempts > 0 && <p>Query repaired after {query.metadata.repair_attempts} {query.metadata.repair_attempts === 1 ? 'retry' : 'retries'}.</p>}
        {query.plan?.assumptions.length ? <p>Assumptions: {query.plan.assumptions.join('; ')}</p> : null}
        {query.validation && <details open><summary>SQL validation: {query.validation.status}</summary><ul>{query.validation.checks.map((c, i) => <li key={i}>{c.passed ? '✓' : '✗'} {c.name}</li>)}</ul>{query.validation.reasons.map((r, i) => <p key={i}>{r.message}</p>)}</details>}
        {query.sql && <details><summary>{query.status === 'verified' ? 'Executed SQL' : 'Blocked SQL'}</summary><pre>{query.sql}</pre></details>}
        {query.result && query.visualization && <Chart result={query.result} spec={query.visualization} />}
        {query.result && <><ResultTable result={query.result} />{query.result.truncated && <p>Results truncated at the requested row limit.</p>}</>}
        {query.status === 'verified' && <p><button onClick={() => void exportQuery('csv')}>Export CSV</button> <button onClick={() => void exportQuery('xlsx')}>Export XLSX</button></p>}
        {query.status === 'verified' && <div><label>Feedback comment<input value={feedbackComment} onChange={e => setFeedbackComment(e.target.value)} maxLength={2000} /></label><button onClick={() => void sendFeedback('correct')}>Correct</button> <button onClick={() => void sendFeedback('partially_correct')}>Partly correct</button> <button onClick={() => void sendFeedback('incorrect')}>Incorrect</button>{feedbackStatus && <p role="status">{feedbackStatus}</p>}</div>}
        {query.evidence && <details><summary>Retrieved evidence ({query.evidence.documents.length})</summary><ul>{query.evidence.documents.map(d => <li key={d.document_id}><strong>{d.object_type}: {d.column_name || d.table_name}</strong> · score {d.score} · {d.content}</li>)}</ul></details>}
        <details><summary>Pipeline stages ({query.metadata.latency_ms} ms)</summary><ol>{query.metadata.stages.map((s, i) => <li key={i}>{s.name}: {s.duration_ms} ms</li>)}</ol></details>
      </div>}
    </section>}
    {schema && <section aria-labelledby="history-heading"><h2 id="history-heading">Query history</h2>{history.length ? <ul>{history.map(item => <li key={item.query_id}><button onClick={() => void showHistory(item.query_id)}>{item.question}</button> · {item.status}</li>)}</ul> : <p>No queries yet.</p>}</section>}
    </>}
  </main>
}
