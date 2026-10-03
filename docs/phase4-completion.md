# Phase 4 completion report

## A. Repository audit

Before Phase 4, DataTrust had CSV/Parquet registration, DuckDB catalog metadata, FAISS retrieval, typed Router/Planner/SQL agents, one SQLGlot guard for generated and repaired SQL, a read-only bounded executor, result profiling, synthesis, deterministic charts, and a React query workspace. It had no persistent query state, auth, benchmark, or CI.

## B. Implemented

Added a per-user materialized semantic cache, structured persistent conversations, query history/detail, feedback, CSV/XLSX export, login and dataset RBAC, operational counters, a scripted pipeline benchmark, CI, deployment configuration, UI controls, and documentation. Existing guard and executor remain the execution boundary.

## C. Semantic cache

Questions are trimmed, whitespace-collapsed and case-folded; the existing embedding provider supplies a vector. A cosine scan over the newest 500 entries in the user/dataset/model/row-policy scope checks a configurable threshold (default 0.92). Reuse also requires current dataset ID, content version, schema hash, user ID, embedding model, row cap, visualization flag, TTL, and a typed verified response with approved validation. Expired entries are removed on writes; stale entries miss on reads. A hit returns stored rows with a new query ID and history entry, never reexecutes cached SQL, and follows a fresh authorization check.

## D. Conversation

DuckDB stores the last question, typed plan, SQL, result columns and visualization with user, dataset ID, version and schema hash. A follow-up loads that state, modifies the plan, retrieves evidence, generates SQL and passes it through the same guard. Foreign IDs return 404; stale or different-dataset state returns 409. Tests cover filters, grouping and chart changes.

## E. Authentication and RBAC

Optional development auth uses PBKDF2-HMAC-SHA256 hashes, random bearer sessions whose digests are stored with 12-hour expiry, and admin/user roles. Production refuses to start without auth. Uploads have owners; admins may grant access. Dataset list/schema/query/validation and history/detail/feedback/export enforce permissions server-side. The query route authorizes the dataset before the guard receives its catalog, so the table allow-list is restricted to the selected authorized dataset.

## F. History, feedback and export

Query responses are persisted with owner, dataset, status and timestamp. History supports pagination and filters; detail and feedback use the same owner and current permission checks. CSV/XLSX export uses stored verified bounded rows and escapes formula-like strings, including headers. The React workspace exposes all three workflows.

## G. Observability

Every HTTP response has `X-Request-ID`. Structured logs include request/query/dataset IDs, route, evidence IDs and scores, guard reasons, cache status/similarity, repair errors, stage durations and final status. Admin-only `/api/metrics` exposes process-local request, cache, query, repair and security counters with bounded stage-latency samples. Prompts, tokens, embeddings and result rows are not logged.

## H. Evaluation

The 19-case gold set covers easy, medium, hard, repair, schema, out-of-domain, ambiguous, adversarial, multi-turn and cache cases. `python evaluation/run_eval.py --check` uses scripted models but real FastAPI, RAG, guard, executor and response handling, and fails if a case misses its expected status, route, result, schema, security outcome, cache outcome or conversation continuity. The [JSON report](../evaluation/reports/latest.json) and [readable report](../evaluation/reports/latest.md) record timestamp, benchmark/dataset/schema versions, provider/models/configuration, per-case and category results, failures, and metrics. Latest local run: 19/19 passed; execution/result/schema/security and repair rates 100%, false blocks 0%, cache hits 9.09%, P50 106.98 ms, P95 363.66 ms. Timings vary by host. These are scripted-provider results, not Ollama quality measurements.

## I. Deployment

Existing backend/frontend Dockerfiles are wired through Compose. Compose can reach host Ollama or an optional Ollama service and persists DuckDB/FAISS/uploads and optional model files. `/api/health` reports process liveness; `/api/readiness` checks configured Ollama models. CI installs dependencies, runs backend tests, gated evaluation, frontend tests and production build without live Ollama. Docker and Compose could not be executed on this host because Docker is absent.

## J. Tests

- `python -m pytest tests -q` from `backend`: 32 passed, one upstream Starlette/httpx deprecation warning.
- `npm test` from `frontend`: 5 passed.
- `npm run build` from `frontend`: passed, with a bundle-size warning from Vite.
- `python evaluation/run_eval.py --check` from root: 19/19 passed.
- `python -m compileall -q app` from `backend`: passed.
- `git diff --check`: passed.

## K. Security regression

Phase 3 adversarial SQL, prompt injection and malicious repair tests pass. Phase 4 tests reject stale cache identities and cross-user cache reuse, reject cross-user or stale conversations, and return 404 for unauthorized datasets/history detail/feedback/export. A cache hit never calls the executor; repaired and follow-up SQL still use the guard. The benchmark rejects its four adversarial cases.

## L. Actual pipeline sample

The scripted benchmark uploaded `data/sample_sales.csv`, then asked “What is total revenue?”. Router selected analytics, Planner used the uploaded table, RAG supplied catalog evidence, the SQL Agent proposed `SELECT SUM(revenue) AS total FROM <uploaded table>`, SQLGuard approved it, read-only DuckDB returned `484.5`, synthesis described the executed result, and chart planning selected a result view. The verified response created cache, conversation and history records; a later identical question was served from cache. Authentication and dataset grants were exercised in the separate end-to-end API test. No live Ollama run was performed.

## M. Documentation

Created `docs/cache.md`, `docs/conversation.md`, `docs/authentication-authorization.md`, `docs/evaluation.md`, `docs/observability.md`, `docs/deployment.md`, and this report. Updated `README.md`, `.env.example`, `docs/api.md`, `docs/architecture.md`, `docs/dataset-versioning.md`, `docs/development.md`, `docs/query-pipeline.md`, and `docs/security.md`. Existing SQL policy, provider, RAG and repair docs were checked for consistency.

## N. Known limits

The application remains single-table analytics; no join benchmark is meaningful yet. The 19-case set is a representative initial benchmark below the suggested 50–200 range. Live Ollama answer quality, token/resource usage and Docker startup remain unmeasured here. Login rate limiting and TLS belong at the deployment edge; the in-process metrics are not distributed. Cache lookup scans at most 500 recent scoped entries. The frontend build warns about its 640 kB JavaScript bundle.

## O. Definition of done

Cache identity, conversations, product workflow, RBAC, SQL security regression, scripted evaluation, logs/metrics, docs and CI checks passed. Docker/Compose runtime, Ollama model quality/resource metrics and a 50+ question or join benchmark remain unverified or outside the current single-table scope. The scripted benchmark is not evidence of live model accuracy.
