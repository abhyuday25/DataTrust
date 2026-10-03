# DataTrust

DataTrust is a foundation for verified natural-language analytics. Phase 1 registers CSV and Parquet datasets in DuckDB and exposes schema and profiling metadata. Phase 2 adds typed Router, Planner, retrieval, and SQL-generation stages. **Generated SQL is returned as unverified and is never executed in Phase 2.** The full SQL Guard and read-only executor belong to Phase 3.

## Run locally

Requires Python 3.12+ and Node 22+. From `backend`, run `python -m pip install -r requirements.txt`, then `python -m uvicorn app.main:app --reload`. Copy the root `.env.example` to `backend/.env` and set provider values to enable queries. Relative paths resolve from the backend working directory. From `frontend`, run `npm ci` and `npm run dev`; open http://localhost:5173. Docker Compose is also configured: place provider variables in a root `.env`, run `docker compose up --build`, then open http://localhost:8080.

Upload `data/sample_sales.csv` in the UI or with `curl -F "file=@data/sample_sales.csv" http://localhost:8000/api/datasets/upload` from the repository root. Select the dataset, then ask “Top 5 regions by revenue” or “What columns are available?” The first query builds the dataset's FAISS index automatically; later queries reload it if its version, schema hash, and embedding model match. See [RAG](docs/rag.md).

## AI configuration

Set `LLM_PROVIDER=openai` (or `openai_compatible`), `LLM_MODEL`, `LLM_API_KEY`, and `EMBEDDING_MODEL` in `backend/.env`. `LLM_BASE_URL` defaults to `https://api.openai.com/v1` and can point to an API supporting Chat Completions JSON-schema responses and embeddings. `LLM_TIMEOUT_SECONDS` and `RAG_TOP_K` bound calls and context. Credentials stay on the backend. With no credentials, dataset features continue to work and `/api/query` returns 503. Automated tests use deterministic fake providers and make no paid calls.

## Scope and security

`POST /api/query` validates the selected dataset and question, routes intent, grounds a plan against the catalog, retrieves version-matched evidence from FAISS, and generates SQL as a separate typed object. It checks declared schema references but **does not parse or approve SQL for execution**. It returns no result rows or synthesized answer for analytical questions. Schema questions are answered from catalog metadata. Follow-ups require future conversation state.

The upload service streams to generated filenames, enforces `MAX_UPLOAD_MB`, uses a fixed CSV/Parquet reader list, and keeps client errors free of raw DuckDB details. DuckDB and uploaded files must persist together. Profiling uses at most 10,000 rows per column. The FAISS index is derived data and can be rebuilt. Queries sent to a configured external provider include the user question and bounded catalog metadata, potentially including short representative samples; configure the provider according to your data policy. Do not expose this service directly to untrusted Internet traffic: authentication and hardened execution are future work.

## Tests and docs

From `backend`: `python -m pytest tests -q`. From `frontend`: `npm test` and `npm run build` (includes TypeScript checking). No separate linter or formatter is configured. See [architecture](docs/architecture.md), [agents](docs/agents.md), [RAG](docs/rag.md), [query pipeline](docs/query-pipeline.md), [API](docs/api.md), and [development](docs/development.md).
