# DataTrust

DataTrust is a foundation for verified natural-language analytics. It enables users to ask questions about their datasets through an intuitive interface while maintaining security and control.

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- Node 22+

### Local Development

#### Backend Setup
```bash
cd backend
python -m pip install -r requirements.txt
cp ../../.env.example .env  # Set your AI provider credentials
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
# Create .env file in root directory with your AI provider credentials
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
- **Important**: Generated SQL is returned unverified and is never executed

### Phase 3: Security (Future)
- Full SQL Guard
- Read-only executor

## ⚙️ AI Configuration

Set these environment variables in `backend/.env`:

```env
LLM_PROVIDER=openai              # or openai_compatible
LLM_MODEL=gpt-4                  # Your model choice
LLM_API_KEY=your_api_key         # Your API key
EMBEDDING_MODEL=text-embedding-3-small  # Embedding model
LLM_BASE_URL=https://api.openai.com/v1  # Custom endpoint if needed
LLM_TIMEOUT_SECONDS=30           # Request timeout
RAG_TOP_K=5                      # Number of retrieval results
```

**Note**: 
- Without credentials, dataset features work but `/api/query` returns 503
- Tests use deterministic fake providers (no paid calls)

## 🔒 Security & Scope

### What DataTrust Does:
- Validates selected datasets and questions
- Routes intent and generates SQL plans
- Retrieves evidence from FAISS indices
- Returns SQL as a separate typed object
- Answers schema questions from metadata

### What DataTrust Doesn't Do:
- **Execute generated SQL**
- Return result rows or synthesized answers
- Parse or approve SQL for execution

### Security Features:
- Stream uploads with size limits (`MAX_UPLOAD_MB`)
- Fixed CSV/Parquet readers
- Clean error messages (no raw DuckDB details)
- FAISS indices are derived data (can be rebuilt)

### Important Notes:
- DuckDB and uploaded files must persist together
- Profiling uses max 10,000 rows per column
- Queries to external providers include bounded metadata
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
