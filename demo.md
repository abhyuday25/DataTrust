# DataTrust demo guide

This guide uses Windows PowerShell and the repository at `C:\Users\Abhyuday\Documents\DataTrust`. The main walkthrough runs the backend and frontend locally with Ollama. It demonstrates the Phase 1–4 flow: upload, inspect the catalog, ask a question, review the guarded SQL and result, continue a conversation, use history and exports, check cache reuse, and test dataset permissions. A separate scripted evaluation works without Ollama.

## 1. Prepare the machine

Install Python 3.12 or newer, Node.js 22 or newer, and Ollama. From PowerShell, confirm that the commands are available:

```powershell
python --version
node --version
npm --version
ollama --version
```

Open the repository:

```powershell
cd C:\Users\Abhyuday\Documents\DataTrust
```

Check which local Ollama models are installed:

```powershell
ollama list
```

You need one chat model and one embedding model. If either is missing, install a model of that type with `ollama pull <model-name>`, then run `ollama list` again. Use the **exact installed names** in the next step. Ollama must be running during the live demo. On systems where its desktop service is not already running, start `ollama serve` in a separate terminal and leave it open.

## 2. Configure the backend for a full demo

From the repository root, make a backend environment file if one does not already exist:

```powershell
if (-not (Test-Path .\backend\.env)) { Copy-Item .\.env.example .\backend\.env }
notepad .\backend\.env
```

Set these entries in `backend\.env`. Replace the two model names with the names shown by `ollama list`; choose your own admin email and a password of at least 12 characters. Do not commit the `.env` file.

```dotenv
APP_ENV=development
DUCKDB_PATH=../storage/demo.duckdb
DATA_DIR=../data/demo_uploads
FAISS_INDEX_PATH=../storage/demo_faiss
LLM_PROVIDER=ollama
LLM_MODEL=<installed-chat-model>
EMBEDDING_MODEL=<installed-embedding-model>
OLLAMA_BASE_URL=http://localhost:11434
CORS_ORIGINS=http://localhost:5173
AUTH_ENABLED=true
ADMIN_EMAIL=<your-admin-email>
ADMIN_PASSWORD=<your-private-password-of-at-least-12-characters>
```

Keep the other settings from `.env.example` or use their defaults. The demo paths above keep its DuckDB file, uploads and FAISS index separate from the default application data. If `demo.duckdb` already contains this admin account, startup does not change its existing password; use that password or select a new demo database path.

## 3. Start the backend

Open a new PowerShell terminal:

```powershell
cd C:\Users\Abhyuday\Documents\DataTrust\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Leave this terminal open. In another terminal, check the two health endpoints:

```powershell
Invoke-RestMethod http://localhost:8000/api/health
Invoke-RestMethod http://localhost:8000/api/readiness
```

`/api/health` should return `status: ok`. `/api/readiness` should return `status: ready` after Ollama is reachable and both configured model names are installed. If readiness is `unavailable`, verify `ollama list`, the model names in `backend\.env`, and `OLLAMA_BASE_URL`. A missing model configuration lets dataset management start but makes `/api/query` return 503.

## 4. Start the frontend

Open another PowerShell terminal:

```powershell
cd C:\Users\Abhyuday\Documents\DataTrust\frontend
npm ci
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` requests to the backend on port 8000. Sign in with the admin email and password from `backend\.env`.

## 5. Upload and inspect the sample data

1. Under **Datasets**, choose **Upload CSV or Parquet**.
2. Select `C:\Users\Abhyuday\Documents\DataTrust\data\sample_sales.csv`.
3. Select `sample_sales` if it is not selected automatically.
4. Show the catalog table: it should contain **5 rows and 7 columns**. Point out the `revenue` column's one missing value and the column profiles.
5. Expand **Version details**. The dataset ID, content version and schema hash are the identities used to keep retrieval, cache and conversations tied to the current data.

The upload registers a dataset and builds a DuckDB table. The first analytical question builds its FAISS index. Reuploading the same file under the same owner and display name returns a duplicate-name error; use the existing dataset for repeat demos.

## 6. Run a verified analytical query

1. In **Ask about sample_sales**, enter `What is total revenue?`.
2. Click **Run verified query**.
3. When the query succeeds, show **Status: verified**, **Route: analytics_query**, the answer, and the result table. For the sample file, the sum of non-null revenue is **484.5**.
4. Expand **SQL validation** and show that the guard approved the query. Expand **Executed SQL** to show the statement that actually ran.
5. Expand **Retrieved evidence** and **Pipeline stages**. The evidence comes from the uploaded catalog; the stages show route, plan, retrieval, SQL generation, validation, execution, profiling, synthesis and visualization timings.
6. If the result contains a suitable numeric measure, show the KPI or chart above the table.

The live model proposes the route, plan and SQL, so exact wording and SQL may vary. A result is labeled `verified` only after SQLGuard approval and read-only DuckDB execution. If the model returns `failed` or `unsupported`, inspect the displayed validation/error, try the same question again, and verify readiness; do not present a failed response as a verified result.

For a grouped view, start a new conversation and ask `Revenue by region in 2025`. A correct result on the sample data has North **289.5**, South **120.0**, East **75.0**, and West with null revenue. The UI may show a bar chart when the result shape supports it.

## 7. Demonstrate a follow-up conversation

After a **verified** grouped query, leave the conversation active and ask:

1. `Now only South`
2. `Break that down by month`
3. `Make it a line chart`

The UI sends the returned `conversation_id` with each follow-up. Show the changed result, SQL and pipeline stages. The backend loads a structured previous plan tied to the same user, dataset version and schema hash, then sends newly generated SQL through the **same SQLGuard**. The model may not interpret every follow-up correctly; use the result rows and validation details as the evidence of what happened. Click **Start a new conversation** before asking an unrelated question.

## 8. Show history, feedback and exports

1. Scroll to **Query history**. Click a previous question to reopen its persisted answer, SQL, validation and result.
2. On a verified result, type an optional **Feedback comment**, then click **Correct**, **Partly correct**, or **Incorrect**. The UI should show **Feedback saved.**
3. Click **Export CSV** and then **Export XLSX**. Open the downloaded files and compare their headers and rows with the displayed verified result. Exports use stored rows; they do not rerun model SQL.

History and exports are scoped to the signed-in user and their current dataset permissions. A result that was rejected or unsupported cannot be exported.

## 9. Show cache reuse

The UI keeps a conversation active after a successful query. Click **Start a new conversation** first; otherwise a new question may be treated as a follow-up and skip cache lookup. Enter the **exact same verified question** with the same dataset and click **Run verified query** again. To inspect the cache flag precisely, open the browser Network panel, select the latest `POST /api/query` response, and look for `metadata.cache_hit: true`.

Alternatively, use this PowerShell API check. Keep the backend running, and replace the email with the admin email from `backend\.env`:

```powershell
$adminEmail = Read-Host 'Admin email'
$adminPassword = Read-Host 'Admin password'
$loginBody = @{ email = $adminEmail; password = $adminPassword } | ConvertTo-Json
$login = Invoke-RestMethod http://localhost:8000/api/auth/login -Method Post -ContentType 'application/json' -Body $loginBody
$headers = @{ Authorization = "Bearer $($login.access_token)" }
$datasets = Invoke-RestMethod http://localhost:8000/api/datasets -Headers $headers
$dataset = $datasets | Where-Object name -eq 'sample_sales' | Select-Object -First 1
$body = @{ dataset_id = $dataset.id; question = 'What is total revenue?'; visualize = $true; max_rows = 1000 } | ConvertTo-Json
$first = Invoke-RestMethod http://localhost:8000/api/query -Method Post -Headers $headers -ContentType 'application/json' -Body $body
$second = Invoke-RestMethod http://localhost:8000/api/query -Method Post -Headers $headers -ContentType 'application/json' -Body $body
$first.status, $first.metadata.cache_hit, $second.status, $second.metadata.cache_hit
```

With a verified first response, the second identical request should report `cache_hit: true`. The first may already be a hit if this user asked the same question earlier. Each response gets a new `query_id`; a cache hit returns previously materialized rows without executing cached SQL. Reuse still requires current permission, dataset version/schema, embedding model, row cap, visualization flag, similarity threshold and TTL. If a model route changes or the first response was not verified, a hit is not guaranteed.

## 10. Show the deterministic SQL boundary

The validation endpoint checks SQL without running it. Reuse `$headers` and `$dataset` from step 9:

```powershell
$schema = Invoke-RestMethod "http://localhost:8000/api/datasets/$($dataset.id)/schema" -Headers $headers
$table = $schema.table.name
$safeSql = 'SELECT SUM(revenue) AS total FROM "' + $table + '"'
$safeBody = @{ dataset_id = $dataset.id; sql = $safeSql } | ConvertTo-Json
(Invoke-RestMethod http://localhost:8000/api/query/validate -Method Post -Headers $headers -ContentType 'application/json' -Body $safeBody).status
$blockedBody = @{ dataset_id = $dataset.id; sql = 'DROP TABLE datasets' } | ConvertTo-Json
(Invoke-RestMethod http://localhost:8000/api/query/validate -Method Post -Headers $headers -ContentType 'application/json' -Body $blockedBody).status
```

The safe `SELECT` should be `approved`; the `DROP TABLE` statement should be `rejected`. Neither validation call executes SQL. This demonstrates the deterministic policy independently of how the model phrases an answer.

## 11. Show dataset permissions (optional full RBAC demo)

Stay signed in as admin in the PowerShell API session from step 9. Create a regular user with a fresh email and password of at least 12 characters:

```powershell
$viewerEmail = Read-Host 'New user email'
$viewerPassword = Read-Host 'New user password (12+ characters)'
$createBody = @{ email = $viewerEmail; password = $viewerPassword; role = 'user' } | ConvertTo-Json
$viewer = Invoke-RestMethod http://localhost:8000/api/auth/users -Method Post -Headers $headers -ContentType 'application/json' -Body $createBody
$viewerLoginBody = @{ email = $viewerEmail; password = $viewerPassword } | ConvertTo-Json
$viewerLogin = Invoke-RestMethod http://localhost:8000/api/auth/login -Method Post -ContentType 'application/json' -Body $viewerLoginBody
$viewerHeaders = @{ Authorization = "Bearer $($viewerLogin.access_token)" }
Invoke-RestMethod http://localhost:8000/api/datasets -Headers $viewerHeaders
```

The new user's dataset list should be empty. Before granting access, this command should show HTTP **404**:

```powershell
curl.exe -i -H "Authorization: Bearer $($viewerLogin.access_token)" "http://localhost:8000/api/datasets/$($dataset.id)/schema"
```

Now grant access as admin, then retry:

```powershell
$grantBody = @{ user_id = $viewer.id } | ConvertTo-Json
Invoke-RestMethod "http://localhost:8000/api/datasets/$($dataset.id)/permissions" -Method Post -Headers $headers -ContentType 'application/json' -Body $grantBody
Invoke-RestMethod http://localhost:8000/api/datasets -Headers $viewerHeaders
curl.exe -i -H "Authorization: Bearer $($viewerLogin.access_token)" "http://localhost:8000/api/datasets/$($dataset.id)/schema"
```

The dataset should now appear and schema access should return HTTP **200**. The user may run their own questions, but cannot open another user's private query detail, conversation or cached response. If reusing the same demo database, choose a new user email to avoid a duplicate-user response.

## 12. Show metrics and evaluation

As admin, inspect process-local counters and stage averages:

```powershell
Invoke-RestMethod http://localhost:8000/api/metrics -Headers $headers | ConvertTo-Json -Depth 8
```

Look for request, successful-query, cache-hit/miss, repair and security-rejection counters where the corresponding actions occurred. Metrics reset when the backend process restarts.

The reproducible evaluation uses scripted model outputs and a temporary dataset, so it does **not** require Ollama and does **not** measure live Ollama answer quality. From the repository root:

```powershell
cd C:\Users\Abhyuday\Documents\DataTrust
.\backend\.venv\Scripts\python.exe evaluation\run_eval.py --check
```

`--check` exits nonzero if a gold case misses its expected outcome. Inspect `evaluation\reports\latest.md` for a readable summary and `evaluation\reports\latest.json` for per-case details. The 19 cases cover analytical results, schema, unsafe SQL, repair, missing and valid conversation context, and cache behavior. Timings vary by machine; scripted-provider scores must be labeled as such.

For the automated test suites:

```powershell
cd C:\Users\Abhyuday\Documents\DataTrust\backend
.\.venv\Scripts\python.exe -m pytest tests -q
cd ..\frontend
npm test
npm run build
```

## 13. Docker Compose alternative

If Docker is installed, you can run the two application services as containers. Create a **root** `.env` file (separate from `backend\.env`) with `LLM_MODEL`, `EMBEDDING_MODEL`, and, for the auth demo, `AUTH_ENABLED=true`, `ADMIN_EMAIL`, and `ADMIN_PASSWORD`. Use exact installed model names. By default the backend container reaches a host Ollama service at `host.docker.internal:11434`:

```powershell
cd C:\Users\Abhyuday\Documents\DataTrust
docker compose up --build
```

Open <http://localhost:8080>. If using the optional Ollama container instead, set `OLLAMA_DOCKER_BASE_URL=http://ollama:11434` in the root `.env`, run `docker compose --profile ollama up --build`, and install the selected models in that service with `docker compose exec ollama ollama pull <model-name>`. Compose persists app data under `storage` and `data`, and container model files in the `ollama_models` volume. The Docker path requires Docker and model downloads; it was not exercised in the development environment for this project.

## 14. End the demo

Click **Sign out** in the UI. Stop the backend, frontend and any manually started `ollama serve` terminal with **Ctrl+C**. Demo data remains in the configured DuckDB, upload and FAISS paths so history and cached results can be shown again after restarting. Keep the demo credentials private.
