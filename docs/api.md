# DataTrust API (Phases 1–2)

All responses include `X-Request-ID`. Errors use `{"error":{"code":"...","message":"..."}}`; unexpected errors also include `request_id`. No internal paths or raw DuckDB errors are returned.

`GET /api/health` → `{"status":"ok"}`.

`POST /api/datasets/upload` accepts multipart `file` with `.csv` or `.parquet`. Example: `curl -F "file=@data/sample_sales.csv" http://localhost:8000/api/datasets/upload`. Returns 201 with `dataset`, `table`, and `warnings`. A table has `name`, `row_count`, and `columns`; each column has `name`, `dtype`, `description`, and `profile`. Profile contains `null_count`, `null_percentage`, `distinct_count`, `minimum`, `maximum`, and `samples`. Errors include 413 for oversize, 415 for format, 409 for duplicate name, and 422 for invalid content.

Example response (hashes and timestamps shortened here for readability):

```json
{
  "dataset": {"id":"a1b2","name":"sample_sales","version":"sha256...","schema_hash":"sha256...","row_count":5,"created_at":"2026-10-03T00:00:00","updated_at":"2026-10-03T00:00:00"},
  "table": {"name":"dataset_a1b2","description":null,"row_count":5,"columns":[{"name":"revenue","dtype":"DOUBLE","description":null,"profile":{"null_count":1,"null_percentage":20.0,"distinct_count":4,"minimum":"49.5","maximum":"240.0","samples":["49.5","120.0"]}}]},
  "warnings": []
}
```

The actual response includes every column and full 64-character hashes.

`GET /api/datasets` → an array of `{id,name,version,schema_hash,row_count,created_at,updated_at}`.

Example: `curl http://localhost:8000/api/datasets` → `[{"id":"a1b2","name":"sample_sales","version":"sha256...","schema_hash":"sha256...","row_count":5,"created_at":"2026-10-03T00:00:00","updated_at":"2026-10-03T00:00:00"}]`.

`GET /api/datasets/{id}/schema` → the same `dataset`, `table`, and `warnings` shape as upload. Missing IDs return 404.

Example: `curl http://localhost:8000/api/datasets/a1b2/schema` → the upload response shown above. Missing ID response: `{"error":{"code":"not_found","message":"Dataset not found"}}`.

## Phase 2 query

`POST /api/query` accepts JSON with `dataset_id` (registered UUID hex), `question` (1–2,000 nonblank characters), optional `conversation_id`, `visualize`, and `max_rows` (default 1,000; cannot exceed `MAX_RESULT_ROWS`). Example after upload:

```json
{"dataset_id":"<id from upload>","question":"Top 5 regions by revenue","max_rows":1000}
```

An analytics response includes `query_id`, `status:"verified"` only after guard approval and successful execution, typed `route` and `plan`, executed `sql`, structured `validation`, `result` with columns/rows/row_count/truncated/duration_ms, `result_profile`, `visualization`, grounded `answer`, `findings`, `assumptions`, evidence, and `metadata` with total/stage durations and `repair_attempts`. A guard or execution failure returns `status:"failed"` and a safe `{code,message}` error. Schema questions return `completed` with a catalog answer; follow-ups return `needs_context`; general/unsafe requests return `unsupported`.

Missing dataset is 404, malformed request or excess `max_rows` is 422, and unconfigured provider is 503. No arbitrary SQL request field or execution endpoint exists. The request ID is in `X-Request-ID`; query ID is in the response. `/api/health` remains a liveness endpoint when Ollama is offline; `/api/readiness` reports whether configured Ollama models are listed by the local server.

Examples of response shapes from tested paths (IDs and SQL vary by dataset):

```json
{"status":"verified","validation":{"status":"approved","checks":[{"name":"parseable","passed":true}]},"result":{"columns":["region","total_revenue"],"rows":[["North",12.5],["South",7.0]],"row_count":2,"truncated":false},"visualization":{"type":"bar","x":"region","y":"total_revenue","value":null},"metadata":{"repair_attempts":0}}
```

The actual response also carries `query_id`, route, plan, answer, result profile, evidence, assumptions, and stage timings. A security rejection has `status:"failed"`, `validation.status:"rejected"`, `result:null`, and `error.code:"FORBIDDEN_STATEMENT"` (or the matching policy reason). A successful first repair returns `status:"verified"` and `metadata.repair_attempts:1`; an exhausted repair returns `status:"failed"`, a safe execution error code and `repair_attempts:2`. Empty executed results remain `verified` with `rows:[]`, `row_count:0`, a table visualization, and an answer stating that no rows were returned. Offline Ollama returns a safe `provider_unavailable` or `provider_timeout` error while `/api/health` remains `ok`.
