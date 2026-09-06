# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Context

A FastAPI backend that orchestrates a **Hub-and-Spoke multi-agent system** (via LangGraph) for campervan route planning. A central Supervisor agent inspects a shared state object on every iteration and routes execution to one of three specialist agents until all required data is populated, then produces a final itinerary.

## Development Rules & AI Engineering Guidelines

- **No Silent Fallbacks:** Never use silent fallbacks for missing context. If the ChromaDB vector store is missing or a semantic search fails in the `rag_agent_node`, raise an explicit exception. We need to debug retrieval failures loudly.
- **Strict State Typing:** `RouteState` is the single source of truth. Do not read or write keys to the state dictionary (like the current `math_analysis`) that are not explicitly declared in the `RouteState` TypedDict. If a new state variable is needed, update the type definition first.
- **Routing & Prompt Traceability:** Before modifying the routing logic in `prompts/route.txt` or the supervisor guard clauses, explicitly explain the expected impact on the agent's decision-making process.
- **Architectural Mentorship:** When modifying the Hub-and-Spoke architecture or adding a new specialized agent, briefly explain to the user why the change improves context isolation or parallelization compared to a single-agent approach. Act as a senior AI Engineer mentoring the user.

## Commands

There is no build step, linter config, or test suite configured in this repo (`tests/` is empty, no `pytest.ini`/`pyproject.toml`/`.flake8`). Don't invent tooling that isn't there.

Run the API locally:
```bash
uvicorn app.main:app --reload

```

Ingest the legal-context PDF into ChromaDB (must be run before the RAG agent has real data to search):

```bash
python scripts/ingest.py

```

Docker:

```bash
docker build -t camper-agent-orchestrator .
docker run -d --name camper-api -p 8000:8000 --env-file .env camper-agent-orchestrator

```

Exercise the graph end-to-end:

```bash
curl -X POST "http://localhost:8000/api/route" \
     -H "Content-Type: application/json" \
     -d '{"origin": "Málaga", "destination": "Sagres", "max_driving_hours_per_day": 4, "requires_hookups": true, "preferences": ["coastal"]}'

```

`requirements.txt` is still stale relative to what's actually imported/used (missing `langgraph`, `langchain-core`, `langchain-community`, `langchain-chroma`, `langchain-huggingface`, `langchain-text-splitters`, `numpy`). A fresh `pip install -r requirements.txt` will not be sufficient to run the app — check the venv or add the missing packages if setting up a new environment.

## Architecture

### The orchestration loop (`app/agents/graph.py`)

A `StateGraph` (LangGraph) with a single conditional hub:

```text
supervisor -> (router reads state["next_action"]) -> {sql_agent | rag_agent | math_agent | END}
sql_agent / rag_agent / math_agent -> supervisor   (always loops back)

```

Every spoke agent returns to `supervisor`, never to each other and never to `END` directly — only the supervisor decides when the loop terminates. `app.main` builds the `initial_state` dict and calls `app_graph.invoke(initial_state)` synchronously inside the `/api/route` endpoint.

### Shared state (`app/agents/state.py`)

`RouteState` (a `TypedDict`) is the single object threaded through every node. Each node reads whatever fields it needs and returns a **partial dict** of updates (LangGraph merges these into state — nodes do not mutate state directly or return the whole state).

`math_analysis` and `requires_hookups`/`max_driving_hours_per_day` are properly declared here — `app.main` populates the latter two from the request payload so `sql_agent_node`/`math_agent_node` actually receive them (they previously silently defaulted to `False`/`8.0` because `initial_state` never set them — fixed, don't regress it).

### Supervisor (`app/agents/supervisor.py`)

* Loads its system prompt from `prompts/route.txt` at import time (not per-request).
* Uses `ChatGoogleGenerativeAI` (`gemini-flash-lite-latest`, via `settings.GEMINI_API_KEY`) with `.with_structured_output(SupervisorDecision)` — a Pydantic model forcing `reasoning`, `next_action` (`sql_agent`/`rag_agent`/`math_agent`/`end`), and `draft_route` on every call. This is the only LLM call in the graph, but it fires once per hub visit — a single `/api/route` request invokes Gemini **4 times** (initial + after each spoke) by design. This is a deliberate architecture choice (LLM-driven routing, kept intentionally for portfolio purposes) rather than a bug — do not "simplify" it to a deterministic router without being asked.
* Model choice matters a lot on a free-tier key: pinned dated models get deprecated (`gemini-2.5-flash` returned 404 "no longer available to new users" as of testing) and flagship `-flash` aliases (e.g. `gemini-flash-latest` → `gemini-3.8-flash` at time of writing) are capped at ~5 requests/minute on the free tier — too tight for 4 calls/request. `-lite` variants (`gemini-flash-lite-latest`) get a much higher free-tier RPM (~15) and are the reliable default here. If you change the model, sanity-check it against `client.models.list()` for the actual key in use, not just what a Google error message suggests as a replacement.
* `ChatGoogleGenerativeAI` retries transient errors internally (`max_retries=3` here, intentionally lower than the library default of 6 — with 4 sequential calls/request, the default's exponential backoff burns through a free-tier per-minute quota by itself). A rate-limit that still exhausts those retries surfaces as `langchain_core.exceptions.ModelRateLimitError` → `app/main.py` returns HTTP 429; a transient Gemini-side outage (`GoogleAPIError`/5xx, e.g. "high demand") surfaces as `langchain_core.exceptions.ModelAPIError` → HTTP 503. Both are caught explicitly before the generic `except Exception` → 500, so a caller can tell "back off and retry" from "something is actually broken." Keep both mappings if you touch `plan_route`'s exception handling.
* After the LLM decision, `supervisor_node` applies guard clauses that force `next_action = "end"` for a step whose data is already populated, preventing infinite re-routing loops if the LLM misroutes. These guard clauses check the exact same state keys the prompt's routing rules describe (`poi_data`, `legal_context`, `fuel_cost`) — keep them in sync if you touch either side.

### Spoke agents (`app/agents/*.py`)

Each is a plain function `(state: RouteState) -> dict` (LangGraph node signature), independent of the others:

* **`rag_agent_node`**: Semantic search over a persisted Chroma DB at `./chroma_db` (built by `scripts/ingest.py` from `data/ley_costas_y_pernocta.pdf`) using `HuggingFaceEmbeddings("all-MiniLM-L6-v2")`. On any exception it silently falls back to a hardcoded legal-context string.
* **`sql_agent_node`**: Real SQLite querying is commented out; it currently returns **hardcoded mock POI data**, correctly filtered by `state["requires_hookups"]`. Treat POI results as fake until the SQL path is wired back up.
* **`math_agent_node`**: Computes fuel cost / driving time from a **randomized distance** (`np.random.uniform(150, 400)`), not an actual route distance. Returns both `math_analysis` (full breakdown) and `fuel_cost` (the scalar the prompt's routing rule and the supervisor's guard clause both key off of) — keep both in sync if you touch this node.

### Config (`app/core/config.py`)

`Settings` (pydantic-settings) requires `GEMINI_API_KEY` from `.env` at import time — the process will fail to start without it. This key is what the supervisor's `ChatGoogleGenerativeAI` client authenticates with.
