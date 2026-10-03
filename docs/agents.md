# Agents

`agents.py` contains short Router, Planner, SQL, Repair and Synthesizer prompts. All call the `LLMClient` protocol in `providers.py`; agents never import an Ollama SDK or DuckDB. Ollama requests JSON-schema output, and Pydantic validates it. Provider failure, timeout, missing models and malformed output become normalized errors; prompts and result rows are not logged.

**Router** receives the user question and returns a typed route, two intent flags, and confidence. Routes are `analytics_query`, `schema_question`, `general_question`, `follow_up`, and `unsupported`. It never writes SQL. Destructive imperatives are deterministically classified unsupported before the provider call. General questions are declined because DataTrust is an analytics product. Follow-ups return `needs_context` until conversation state exists.

**Planner** receives the question and a bounded list of real catalog columns/types (at most 100). It returns objective, tables, dimensions, measures, filters, joins, grouping, ordering, limit, visualization intent, and assumptions. The orchestrator rejects unknown table/column references. Phase 1 has one physical table per dataset, so joins are rejected rather than invented.

**SQL Agent** receives the question, validated plan, and up to 12,000 characters of retrieved evidence with document IDs. It returns SQL, declared table/column references, and assumptions. Those declarations do not grant execution rights: the AST guard derives real references. **Repair Agent** receives a classified execution error and may try twice; each output passes the same guard. **Synthesizer** receives only executed rows and a bounded result profile. Numerical claims absent from the rows fall back to a deterministic summary.
