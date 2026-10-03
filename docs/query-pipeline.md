# Query pipeline

`POST /api/query` validates a dataset ID, nonblank question (max 2,000 characters), optional conversation ID, and `max_rows` against `MAX_RESULT_ROWS`. It assigns a query ID and returns stage durations. The request ID remains in the HTTP header and structured logs.

For analytics: Router (intent) → Planner (typed catalog-grounded plan) → grounding check → FAISS retrieval (version-matched evidence) → SQL Agent (typed SQL) → grounding check → **unverified response**. Provider timeouts/failures, malformed structured output, missing catalog references, and unavailable retrieval return structured safe failures. Stages and evidence IDs/scores are logged with query/dataset IDs; secrets, prompts, and result rows are not.

Schema questions use Router → retrieval and a deterministic list of actual catalog columns. General questions are declined. Follow-ups return `needs_context`. Phase 2 never executes SQL, so there is no execution timing or result table. The frontend can render a generic result table once Phase 3 supplies verified rows.

The Phase 2 grounding check verifies plan fields and declared SQL references against catalog names and rejects obvious multi-statement/non-SELECT output. It does **not** fully parse SQL, prove declared references match SQL text, enforce function/table policies, or approve execution. Phase 3 must attach a deterministic AST/policy guard and read-only executor after `GeneratedSQL`, enforce row/time limits there, and send every generated or repaired statement through that guard.
