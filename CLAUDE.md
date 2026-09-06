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

Ingest the legal-context PDF into ChromaDB (must be run before the RAG agent has real data to search). The script wipes and rebuilds `chroma_db/` from scratch every run (`Chroma.from_documents` appends to an existing store rather than replacing it, so re-running without wiping first would duplicate/mix chunk generations):

```bash
python scripts/ingest.py

```

Chunking uses `chunk_size=1500`/`chunk_overlap=300` (up from an original 500/50) — the source PDF is organized as long per-region enumerations, and the smaller size used to cut chunks mid-region, so a query could retrieve a chunk describing a completely unrelated comunidad autónoma. Don't shrink this back down without re-checking retrieval relevance for a few destinations.

Seed the POI SQLite DB (must be run before the SQL agent has real data to query — otherwise it silently falls back to mock data):

```bash
python scripts/seed_poi_db.py

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

`requirements.txt` is still stale relative to what's actually imported/used (missing `langgraph`, `langchain-core`, `langchain-community`, `langchain-chroma`, `langchain-huggingface`, `langchain-text-splitters`). A fresh `pip install -r requirements.txt` will not be sufficient to run the app — check the venv or add the missing packages if setting up a new environment.

`math_agent_node` calls two free, keyless public APIs over the network (Nominatim for geocoding, the public OSRM demo server for routing) — running the app fully offline exercises its fallback path (randomized distance), not the real calculation.

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

`final_destination` and `itinerary_legs` support the multi-leg replanning described below. `origin`/`destination` are the CURRENT LEG being planned, not necessarily the user's original request — after a split, `destination` temporarily holds the intermediate stop while `final_destination` remembers the real target. Any code reading `origin`/`destination` to mean "the whole trip" will be wrong once a split has happened; use `itinerary_legs` for the full picture.

### Supervisor (`app/agents/supervisor.py`)

* Loads its system prompt from `prompts/route.txt` at import time (not per-request).
* Uses `ChatGoogleGenerativeAI` (`gemini-flash-lite-latest`, via `settings.GEMINI_API_KEY`) with `.with_structured_output(SupervisorDecision)` — a Pydantic model forcing `reasoning`, `next_action` (`sql_agent`/`rag_agent`/`math_agent`/`end`), and `draft_route` on every call. This is the only LLM call in the graph, but it fires once per hub visit — a single `/api/route` request invokes Gemini **4 times** (initial + after each spoke) by design. This is a deliberate architecture choice (LLM-driven routing, kept intentionally for portfolio purposes) rather than a bug — do not "simplify" it to a deterministic router without being asked.
* Model choice matters a lot on a free-tier key: pinned dated models get deprecated (`gemini-2.5-flash` returned 404 "no longer available to new users" as of testing) and flagship `-flash` aliases (e.g. `gemini-flash-latest` → `gemini-3.8-flash` at time of writing) are capped at ~5 requests/minute on the free tier — too tight for 4 calls/request. `-lite` variants (`gemini-flash-lite-latest`) get a much higher free-tier RPM (~15) and are the reliable default here. If you change the model, sanity-check it against `client.models.list()` for the actual key in use, not just what a Google error message suggests as a replacement.
* `ChatGoogleGenerativeAI` retries transient errors internally (`max_retries=3` here, intentionally lower than the library default of 6 — with 4 sequential calls/request, the default's exponential backoff burns through a free-tier per-minute quota by itself). A rate-limit that still exhausts those retries surfaces as `langchain_core.exceptions.ModelRateLimitError` → `app/main.py` returns HTTP 429; a transient Gemini-side outage (`GoogleAPIError`/5xx, e.g. "high demand") surfaces as `langchain_core.exceptions.ModelAPIError` → HTTP 503. Both are caught explicitly before the generic `except Exception` → 500, so a caller can tell "back off and retry" from "something is actually broken." Keep both mappings if you touch `plan_route`'s exception handling.
* After the LLM decision, `supervisor_node` applies guard clauses that force `next_action = "end"` for a step whose data is already populated, preventing infinite re-routing loops if the LLM misroutes. These guard clauses check the exact same state keys the prompt's routing rules describe (`poi_data`, `legal_context`, `fuel_cost`) — keep them in sync if you touch either side.
* **Feasibility is enforced in Python, not just in the prompt.** `prompts/route.txt` instructs the model to check `math_analysis.feasible_within_daily_limit` — but an LLM can still ignore that instruction under the pressure of "produce a detailed itinerary" (this happened in testing: the model returned a confident "ready to go" itinerary despite `feasible_within_daily_limit: false`). `supervisor_node` computes feasibility fields **directly from `state["math_analysis"]`**, independent of what `draft_route`'s prose says. Treat `draft_route` as narrative/UX only — any code or caller that needs to know whether the plan is actually valid must read `feasible_within_daily_limit`, never parse `draft_route`.

* **Multi-leg replanning on infeasibility.** When a leg is infeasible, `supervisor_node` does not just end with a warning — it replans as two legs, without any change to the graph topology in `app/agents/graph.py`. Mechanism: `sql_agent_node`/`rag_agent_node`/`math_agent_node` are generic over whatever `state["origin"]`/`state["destination"]` currently are, so the supervisor repoints those two fields at a sub-leg and clears `poi_data`/`legal_context`/`fuel_cost`/`math_analysis`, which makes the existing routing rules (rules 1-3 in the prompt) naturally re-trigger the sql→rag→math cycle for that sub-leg — no new graph nodes needed. Concretely, in `supervisor_node`:
  1. **First infeasible leg** (`final_destination` not yet set): the LLM proposes `intermediate_stop` (a real, geographically sensible town along the route — this is genuine LLM reasoning, not looked up); Python saves `final_destination = destination`, sets `destination = intermediate_stop`, resets the per-leg fields, and routes back to `sql_agent`.
  2. **First leg (origin → intermediate stop) finishes**: Python appends it to `itinerary_legs`, then sets `origin = intermediate_stop`, `destination = final_destination`, resets the per-leg fields again, and routes back to `sql_agent` for the second leg.
  3. **Second leg (intermediate stop → final destination) finishes**: Python appends it to `itinerary_legs` and assembles `final_itinerary.legs` + `total_fuel_cost_eur` (summed) + an aggregate `feasible_within_daily_limit` (AND of both legs), then ends.
  The split is **bounded to exactly one intermediate stop** — guarded by checking `final_destination` before allowing a split, so a leg that is *still* infeasible after the first split cannot trigger a second one; it just gets recorded with `feasible_within_daily_limit: false` in its leg entry and the final response carries a `warning` recommending manual replanning. Don't remove that guard — it's the only thing preventing an unbounded replanning loop. If you ever need >1 intermediate stop, this would need a small redesign (e.g. a leg index/queue instead of a single `final_destination` sentinel), not just relaxing the guard.
  Top-level `poi_data`/`legal_context`/`fuel_cost`/`math_analysis` in the final response reflect only the **last** leg processed — `final_itinerary.legs` is the authoritative source for the full multi-leg picture.

### Spoke agents (`app/agents/*.py`)

Each is a plain function `(state: RouteState) -> dict` (LangGraph node signature), independent of the others:

* **`rag_agent_node`**: Semantic search over a persisted Chroma DB at `./chroma_db` (built by `scripts/ingest.py` from `data/ley_costas_y_pernocta.pdf`, a **Spanish-only** legal PDF organized by comunidad autónoma) using `HuggingFaceEmbeddings("all-MiniLM-L6-v2")`. Per the **No Silent Fallbacks** rule above, it raises explicitly instead of degrading quietly: `FileNotFoundError` if `chroma_db/` doesn't exist (run `scripts/ingest.py` first), `ValueError` if the similarity search returns zero docs for the destination. Both propagate up through the graph to `plan_route`'s exception handling in `app/main.py` (a bare `ValueError` maps to HTTP 422; `FileNotFoundError` falls through to 500) — don't reintroduce a `try/except` that swallows these.
  The search query is enriched with the destination's real administrative region (`_get_region`, a Nominatim lookup local to this file, deliberately not shared with `math_agent`'s geocoder to keep the spokes independent) — e.g. `"...in Sagres, region: Faro"` instead of just `"...in Sagres"` — which measurably improves relevance (verified: querying with region correctly favors the passage introducing the per-region enumeration over an unrelated region's chunk). This lookup is wrapped in a *narrow* `try/except requests.RequestException` that falls back to querying without the region hint — this is NOT a reintroduction of the banned silent fallback: the actual retrieval (the ChromaDB search a few lines below) is never caught or faked, only an optional query-enrichment step degrades gracefully if Nominatim is briefly unreachable.
  Known residual limitation: because the PDF only covers Spain, a destination outside Spain (e.g. Sagres, Portugal) has no genuinely matching region-specific passage to retrieve — the region hint helps genuine Spanish destinations, not this case. Separately, the embedding model (`all-MiniLM-L6-v2`, generic/English-oriented) doesn't reliably equate a geocoded region name with how the PDF names it (e.g. Nominatim's "Euskadi" vs. the PDF's "País Vasco") — this is an embedding-model limitation, not something chunking or query text can fully fix; don't assume the returned chunk always names the exact geocoded region.
* **`sql_agent_node`**: Queries a real SQLite DB at `data/campers_poi.db` (seeded by `scripts/seed_poi_db.py`, gitignored — run the script once after cloning) via a read-only URI connection (`file:...?mode=ro`, so a missing DB fails loudly instead of sqlite3 silently creating an empty one). Falls back to hardcoded mock POI data **only on an actual query failure** (missing/corrupt DB) — a real query that legitimately finds zero matches for a destination returns an empty list, it does not trigger the mock. The seed data (50 real areas across 47 Spanish/Portuguese destinations, sourced mostly from park4night.com plus some areasac.es and official operator price lists — see comments in `seed_poi_db.py` for per-row sources) only covers those specific destinations; a `destination` outside that list legitimately returns `[]`, not an error.
* **`math_agent_node`**: Geocodes `origin`/`destination` via Nominatim (OpenStreetMap) and gets a real driving distance + duration from the public OSRM demo server, then derives fuel cost from `CONSUMPTION_L_PER_100KM`/`FUEL_PRICE_EUR_PER_L` (documented constants, not fetched live). Falls back to a randomized distance (`random.uniform(150, 400)` at an assumed 90 km/h) only if geocoding/routing genuinely fails (place not found, no route, network/service error) — same fallback-on-failure-only convention as `sql_agent_node`. Both APIs are free public instances with no key: Nominatim has a strict usage policy (identify via `User-Agent`, ~1 req/s) and the OSRM demo server is not meant for production load — fine for this project's traffic, but don't assume high throughput. Returns both `math_analysis` (full breakdown) and `fuel_cost` (the scalar the prompt's routing rule and the supervisor's guard clause both key off of) — keep both in sync if you touch this node.
  `_geocode` constrains Nominatim to `IBERIA_VIEWBOX` (a bounding box over Spain+Portugal) — without it, an ambiguous single-word place name can silently resolve to the wrong continent (discovered in testing: plain `"Sagres"` geocoded to São Paulo, Brazil, not the Portuguese village — OSRM would then either error out or, worse, return *some* plausible-looking distance for the wrong pair of coordinates). This app only ever plans Iberian routes, so the bounding box is a correctness fix, not a scope restriction to relax casually.

### Config (`app/core/config.py`)

`Settings` (pydantic-settings) requires `GEMINI_API_KEY` from `.env` at import time — the process will fail to start without it. This key is what the supervisor's `ChatGoogleGenerativeAI` client authenticates with.
