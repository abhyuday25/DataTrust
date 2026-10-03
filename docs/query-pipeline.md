# Query pipeline

`POST /api/query` validates a dataset ID, nonblank question (max 2,000 characters), optional conversation ID, and `max_rows` against `MAX_RESULT_ROWS`. It assigns a query ID and returns stage durations. The request ID remains in the HTTP header and structured logs.

For analytics: authentication/dataset permission → Router → per-user materialized cache candidate check → Planner (or structured follow-up plan update) → plan grounding → FAISS retrieval → SQL Agent → SQL Guard → read-only executor → result profiler → Synthesizer → deterministic visualization → persisted conversation/history/cache → verified response. Repairable execution failures may trigger up to two Repair Agent calls; each repaired SQL is revalidated by the same guard. Provider failures and policy rejection produce safe structured failures. Stage timings and evidence IDs/scores are logged with query/dataset IDs; prompts and result rows are not.

Schema questions use Router → retrieval and a deterministic list of actual catalog columns. General questions are declined. Follow-ups return `needs_context`. Analytics responses include execution timing, verified rows, validation checks, repair count and chart spec.

The SQL Guard parses DuckDB SQL with SQLGlot, requires one SELECT, checks real AST table and column references against the selected catalog, and rejects external access functions. The executor accepts an approved object, opens a read-only connection, disables external access, caps rows, and interrupts work after `QUERY_TIMEOUT_SECONDS` where DuckDB supports it. See `sql-policy.md` and `security.md` for boundaries.

| Stage | Input → output | Boundary and failure |
| --- | --- | --- |
| routing | question → typed route | Ollama via provider; safe provider failure |
| planning | question and catalog → typed plan | Ollama; deterministic plan grounding rejects unknown fields |
| retrieval | plan and catalog → document IDs/scores | FAISS; invalid index/embedding fails safely |
| sql_generation | question, plan and evidence → typed SQL | Ollama; output remains untrusted |
| validation | SQL and selected catalog → checks, ApprovedQuery | deterministic SQLGlot guard; rejection stops execution |
| execution | ApprovedQuery → capped rows | read-only DuckDB; classified error or timeout |
| repair | safe error and bounded context → new SQL | Ollama; same validation follows every repair |
| result_profiling | executed rows → typed profile | deterministic bounded scan |
| synthesis | executed rows/profile → answer | Ollama; unsupported numerical claims fall back |
| visualization | result shape → typed chart | deterministic; invalid shapes use table |
| cache | question embedding and current catalog → materialized response or miss | deterministic identity/TTL/authorization after similarity; no SQL reexecution |
| conversation | prior typed plan and current follow-up → updated state | user/dataset/version/schema checks; new SQL still guarded |

Logs include `request_id`, `query_id`, `dataset_id`, stage name and duration, retrieval document IDs and scores, final status and total latency. The API includes validation reasons and repair count. Prompts, raw database errors and result rows are not logged. This trace is the Phase 4 evaluation input; there is no metrics dashboard yet.
