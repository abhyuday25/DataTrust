# Observability

Each request receives `X-Request-ID`; analytical work receives `query_id` and selected dataset ID. Structured logs record route, retrieval document IDs/scores, validation status and reason codes, cache status/similarity, repair attempt/error code, stage durations and final status/latency. Prompts, passwords, tokens, raw provider output, SQL result rows and embeddings are not logged.

Admin-only `GET /api/metrics` returns process-local request/query/security/cache/repair counters and count/average stage latency over the newest 1,000 observations per stage. These reset on process restart and are not a distributed metrics backend. Persisted query records include response stage timings for later evaluation. The scripted benchmark reports P50/P95 and accuracy metrics separately.
