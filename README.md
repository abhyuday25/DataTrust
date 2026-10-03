# DataTrust

DataTrust runs natural-language analytics over uploaded CSV and Parquet datasets. A local Ollama model proposes SQL; an AST guard decides whether it may execute in read-only DuckDB.

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- Node 22+
- [Ollama](https://ollama.com/) with a chat model and an embedding model installed locally

### Local Development

#### Backend Setup
```bash
cd backend
python -m pip install -r requirements.txt
cp ../.env.example .env  # Set LLM_MODEL and EMBEDDING_MODEL
python -m uvicorn app.main:app --reload
```

#### Frontend Setup
```bash
cd frontend
npm ci
npm run dev
# Open http://localhost:5173
```

#### Using Docker Compose
```bash
# Create .env in the root and set the local Ollama models
docker compose up --build
# Open http://localhost:8080
```

### Try It Out

1. Upload the sample dataset:
   - **UI**: Upload `data/sample_sales.csv` through the web interface
   - **CLI**: `curl -F “file=@data/sample_sales.csv” http://localhost:8000/api/datasets/upload`

2. Ask questions like:
   - “Top 5 regions by revenue”
   - “What columns are available?”

The first query automatically builds a FAISS index for the dataset. Subsequent queries reuse this index if the dataset version, schema hash, and embedding model match.

## 🧠 Architecture Overview

### Phase 1: Dataset Registration
- Registers CSV and Parquet datasets in DuckDB
- Exposes schema and profiling metadata

### Phase 2: Query Processing
- Typed Router and Planner
- Retrieval and SQL generation
- Generated SQL is a proposal and has no execution authority

### Phase 3: Verified Analytics
- SQLGlot DuckDB AST guard, catalog table and column checks, and default-deny function policy
- Read-only DuckDB executor with disabled external access, timeout and row cap
- Up to two guarded repairs after repairable execution errors
- Result profiling, grounded synthesis, and deterministic charts

## ⚙️ AI Configuration

Set these environment variables in `backend/.env` (or root `.env` for Docker Compose). The model names below are examples; install and select models available in your local Ollama instance:

```env
LLM_PROVIDER=ollama
LLM_MODEL=<installed-chat-model>
EMBEDDING_MODEL=<installed-embedding-model>
OLLAMA_BASE_URL=http://localhost:11434
LLM_TIMEOUT_SECONDS=30           # Request timeout
RAG_TOP_K=5                      # Number of retrieval results
```

**Note**: 
- Without configured model names, dataset features work but `/api/query` returns 503
- Tests use deterministic fake providers (no paid calls)
- Check installed models with `ollama list`; use `ollama pull <model>` to install one
- Start the server with `ollama serve` if it is not already running

## 🔒 Security & Scope

### What DataTrust Does:
- Validates selected datasets and questions
- Routes intent and generates SQL plans
- Retrieves evidence from FAISS indices
- Guards generated and repaired SQL before any analytical execution
- Executes approved SQL on a dedicated read-only connection
- Returns typed validation, rows, profiling and visualization metadata
- Answers schema questions from metadata

### Current limits
- One selected uploaded table per analytical query; external table functions, arbitrary UDFs and set operations are denied
- The thread cancellation timeout interrupts DuckDB where possible; a native operation that ignores interruption can outlive the response briefly
- Synthesis checks numerical claims, but cannot prove every natural-language statement; inspect the returned rows and SQL for important decisions

### Planned Phase 4

Semantic cache, conversation follow-ups, query history, authentication, evaluation and production deployment work are planned for Phase 4.

### Security Features:
- Stream uploads with size limits (`MAX_UPLOAD_MB`)
- Fixed CSV/Parquet readers
- Clean error messages (no raw DuckDB details)
- FAISS indices are derived data (can be rebuilt)

### Important Notes:
- DuckDB and uploaded files must persist together
- Profiling uses max 10,000 rows per column
- Local Ollama receives bounded metadata and result rows
- **Do not expose directly to untrusted internet traffic**

## 🧪 Testing & Documentation

### Running Tests
```bash
# Backend
cd backend
python -m pytest tests -q

# Frontend
cd frontend
npm test
npm run build  # Includes TypeScript checking
```

### Documentation
See detailed docs for:
- [Architecture](docs/architecture.md)
- [AI Agents](docs/agents.md)
- [RAG System](docs/rag.md)
- [Query Pipeline](docs/query-pipeline.md)
- [API Reference](docs/api.md)
- [Development Guide](docs/development.md)
- [SQL Policy](docs/sql-policy.md)
- [Security](docs/security.md)
- [Local LLM Provider](docs/llm-providers.md)
- [Repair Loop](docs/repair-loop.md)
