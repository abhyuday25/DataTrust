# Architecture

```mermaid
flowchart LR
  UI[React UI] --> API[FastAPI]
  API --> A[Auth and dataset permissions]
  A --> C[Conversation and materialized cache]
  C --> O[QueryOrchestrator]
  O --> R[Router]
  O --> P[Planner]
  O --> G[RAG: catalog documents + embeddings + FAISS]
  O --> S[SQL Agent]
  S --> V[SQLGlot Guard]
  V --> Q[ApprovedQuery]
  Q --> E[Read-only DuckDB]
  E --> F[Result profile and synthesis]
  F --> H[Deterministic chart plan]
  H --> C
  O --> RP[Repair Agent]
  RP --> V
  API --> D[DatasetService + DuckDB catalog]
  D --> G
  C --> M[DuckDB history, feedback, cache, conversations]
  O --> T[Metrics and trace]
```

Phase 1 remains in `core.py`, `routes.py`, `service.py`, `db.py`, and `schemas.py`. `providers.py` defines LLM and embedding protocols with a local Ollama HTTP implementation. `agents.py` owns Router, Planner, SQL, Repair and Synthesis prompts. `rag.py` creates deterministic table/column documents and a per-dataset FAISS index. `query_service.py` coordinates stages; `sql_guard.py` owns approval; `executor.py` owns read-only execution; `result_ops.py` profiles rows and chooses charts. The frontend talks only to `api.ts`.

Trusted data flows from the DuckDB catalog to agent prompts and retrieval documents. User questions, model output, and retrieved descriptions are untrusted. The Planner sees a compact catalog summary before retrieval; its references are checked against catalog truth. Planner-guided retrieval supplies bounded evidence to the SQL Agent. Every initial or repaired SQL statement passes the same AST guard before a read-only DuckDB connection executes it. Only executed rows feed synthesis and chart planning. Phase 4 adds server-side authorization, structured conversation plans, per-user materialized cache, history, feedback, exports, metrics, and evaluation.

```text
React → FastAPI → Query Orchestrator
                  Router / Planner / RAG / SQL Agent / Repair Agent (Ollama)
                  ───── deterministic trust boundary ─────
                  SQLGlot Guard → ApprovedQuery → Read-only DuckDB
                                               ↓
                  Result Profiler → Synthesizer (Ollama) → Deterministic Chart Planner → Response
```

The trust boundary is crossed only by an `ApprovedQuery` from the guard. Synthesis receives executed rows; chart selection uses typed result metadata and no generated frontend code.

Router, Planner, SQL Agent, Repair Agent, and Synthesizer are probabilistic Ollama consumers behind `LLMClient`. Catalog checks, SQLGuard, read-only execution, profile/chart logic, cache identity, permissions, and persistence are deterministic. The cache returns previously materialized rows only after current authorization and identity checks; it does not reexecute SQL. Conversation state stores the previous typed plan and is checked against user, dataset version, and schema hash before a follow-up generates new SQL through the same guard.

Ingestion remains a trusted application write: upload → fixed format reader → generated DuckDB table → profile → catalog transaction. No HTTP endpoint accepts arbitrary SQL. The catalog is authoritative; FAISS is a rebuildable candidate index. Stored indexes are checked against dataset ID, content version, schema hash, embedding model/dimension, document count, and document identities before use.
