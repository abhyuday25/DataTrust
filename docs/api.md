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

An analytics response includes `query_id`, `status:"unverified"`, typed `route` and `plan`, generated `sql`, `validation:"unverified"`, `result:null`, `evidence` with document IDs/scores/content, and `metadata` with total and stage durations. The exact SQL and IDs depend on the provider and dataset; no answer or result rows are invented. Schema questions return `status:"completed"`, a catalog-based `answer`, and evidence without SQL. Follow-ups return `needs_context`; general/unsafe requests return `unsupported`; pipeline failures return `failed` with a safe `{code,message}` error.

Missing dataset is 404, malformed request or excess `max_rows` is 422, and unconfigured provider is 503. No arbitrary SQL request field or execution endpoint exists. The request ID is in `X-Request-ID`; query ID is in the response. A future Phase 3 response may add verified execution results after a deterministic SQL Guard.
