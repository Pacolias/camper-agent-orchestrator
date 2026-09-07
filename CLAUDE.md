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

Chunking uses `chunk_size=1500`/`chunk_overlap=300` (up from an original 500/50), and — more importantly — the raw text is **split by region before chunking**, not chunked-then-tagged. See "RAG pipeline" under Architecture below before touching `scripts/ingest.py`'s region-detection regexes; getting the section boundaries wrong silently mistags every chunk in that section.

Seed the POI SQLite DB (must be run before the SQL agent has real data to query — otherwise it silently falls back to mock data):

```bash
python scripts/seed_poi_db.py

```

Isolate a RAG retrieval problem to the ChromaDB/metadata layer vs. the agent's routing logic (`test_rag.py` at repo root — dumps region metadata counts, runs a manual `filter={"region": "Andalucía"}` query, and compares it against an unfiltered query for the same input, so a bad answer's source is obvious before you go looking in `rag_agent_node` or `supervisor_node`):

```bash
python test_rag.py

```

Run the evaluation suite (`evals/` — see its module docstrings for full design rationale):

```bash
python -m evals.run_evals                         # full 5-case dataset, 15s between cases
python -m evals.run_evals --case short_same_region # run a single named case
python -m evals.run_evals --delay 5                # tighter spacing (more rate-limit risk)
```

This makes real Gemini/Nominatim/OSRM calls and consumes real free-tier LLM quota — not a fast/free unit-test suite, and not meant to run on every commit. A case that errors (e.g. a 429) is reported separately from a case that fails an assertion; only the latter indicates an actual logic regression. See "Evaluation pipeline" under Architecture below.

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

`legal_region` is the canonical comunidad autónoma tag (or `"general"`) the RAG agent resolved for the current leg; `legal_context_by_region` is a `{region: legal_context}` cache that accumulates across the whole request (never cleared between legs) so a region visited by more than one leg is retrieved and stored once — see "RAG pipeline" below.

`split_count` counts how many times the supervisor has split the trip so far (see "Multi-leg replanning" below) — it bounds replanning, and unlike `itinerary_legs` it grows even when a split attempt itself turns out to still be infeasible, which is exactly why it (not `len(itinerary_legs)`) is the field used to bound further splitting.

### Supervisor (`app/agents/supervisor.py`)

* Loads its system prompt from `prompts/route.txt` at import time (not per-request).
* Uses `ChatGoogleGenerativeAI` (`gemini-flash-lite-latest`, via `settings.GEMINI_API_KEY`) with `.with_structured_output(SupervisorDecision)` — a Pydantic model forcing `reasoning`, `next_action` (`sql_agent`/`rag_agent`/`math_agent`/`end`), and `draft_route` on every call. This is the only LLM call in the graph, but it fires once per hub visit — a single `/api/route` request invokes Gemini **4 times** (initial + after each spoke) by design. This is a deliberate architecture choice (LLM-driven routing, kept intentionally for portfolio purposes) rather than a bug — do not "simplify" it to a deterministic router without being asked.
* Model choice matters a lot on a free-tier key: pinned dated models get deprecated (`gemini-2.5-flash` returned 404 "no longer available to new users" as of testing) and flagship `-flash` aliases (e.g. `gemini-flash-latest` → `gemini-3.8-flash` at time of writing) are capped at ~5 requests/minute on the free tier — too tight for 4 calls/request. `-lite` variants (`gemini-flash-lite-latest`) get a much higher free-tier RPM (~15) and are the reliable default here. If you change the model, sanity-check it against `client.models.list()` for the actual key in use, not just what a Google error message suggests as a replacement.
* `ChatGoogleGenerativeAI` retries transient errors internally (`max_retries=3` here, intentionally lower than the library default of 6 — with 4 sequential calls/request, the default's exponential backoff burns through a free-tier per-minute quota by itself). A rate-limit that still exhausts those retries surfaces as `langchain_core.exceptions.ModelRateLimitError` → `app/main.py` returns HTTP 429; a transient Gemini-side outage (`GoogleAPIError`/5xx, e.g. "high demand") surfaces as `langchain_core.exceptions.ModelAPIError` → HTTP 503. Both are caught explicitly before the generic `except Exception` → 500, so a caller can tell "back off and retry" from "something is actually broken." Keep both mappings if you touch `plan_route`'s exception handling.
* After the LLM decision, `supervisor_node` applies guard clauses that force `next_action = "end"` for a step whose data is already populated, preventing infinite re-routing loops if the LLM misroutes. These guard clauses check the exact same state keys the prompt's routing rules describe (`poi_data`, `legal_context`, `fuel_cost`) — keep them in sync if you touch either side.
* **Feasibility is enforced in Python, not just in the prompt.** `prompts/route.txt` instructs the model to check `math_analysis.feasible_within_daily_limit` — but an LLM can still ignore that instruction under the pressure of "produce a detailed itinerary" (this happened in testing: the model returned a confident "ready to go" itinerary despite `feasible_within_daily_limit: false`). `supervisor_node` computes feasibility fields **directly from `state["math_analysis"]`**, independent of what `draft_route`'s prose says. Treat `draft_route` as narrative/UX only — any code or caller that needs to know whether the plan is actually valid must read `feasible_within_daily_limit`, never parse `draft_route`.
* **"end" is never trusted at face value — verified against the actual state.** The three guard clauses (`if state.get("poi_data") and next_action == "sql_agent": next_action = "end"`, etc.) only stop the LLM from *re-visiting* a step whose data already exists; they do nothing to stop it from jumping straight to `"end"` while a step was *never* visited. This is a real, observed failure mode, not a hypothetical: with debug logging enabled, the model was caught choosing `next_action="math_agent"` (rule 3) while `legal_context` (rule 2) was still `""` — i.e. skipping the prompt's own strict ordering — and then, once `fuel_cost` was populated, emitting `next_action="end"` with `legal_context` still empty. Net effect: `rag_agent_node` never ran for that leg, so `legal_region` stayed `null` in the response — a bug that looked like a region-resolution problem (and was reported as one) but was actually a routing-completeness problem one level up. The fix is a second hard invariant, checked right after the three guard clauses: if `next_action == "end"` but `poi_data`/`legal_context`/`fuel_cost` (checked in that order) is still falsy, override to the corresponding agent instead of letting `"end"` through. This logs a `WARNING` when it fires, which is a real signal the model is misreading state, not just belt-and-suspenders — if this warning starts firing constantly, the prompt or `SupervisorDecision` schema needs attention, not just the guard. If you ever see a spoke's output field unexpectedly empty/null in a multi-leg (post-split) response, suspect this class of bug first — check for the corresponding `WARNING` in logs before assuming the spoke agent itself is broken.

* **Multi-leg replanning on infeasibility, bounded by `MAX_LEGS` (currently 4), not "exactly one split".** When a leg is infeasible, `supervisor_node` does not just end with a warning — it replans, without any change to the graph topology in `app/agents/graph.py`. Mechanism: `sql_agent_node`/`rag_agent_node`/`math_agent_node` are generic over whatever `state["origin"]`/`state["destination"]` currently are, so the supervisor repoints `destination` at a sub-leg and clears `poi_data`/`legal_context`/`legal_region`/`fuel_cost`/`math_analysis`, which makes the existing routing rules (rules 1-3 in the prompt) naturally re-trigger the sql→rag→math cycle for it — no new graph nodes needed. `legal_context_by_region` is deliberately NOT cleared between legs (see "RAG pipeline" below) — it accumulates across the whole request so a repeated region isn't re-fetched.
  This used to be hard-capped at exactly one split, on the assumption the LLM's first `intermediate_stop` guess would always leave a feasible remainder. That assumption broke in testing: `long_cross_region_split` (Barcelona→Málaga, 6h limit) split via Valencia — feasible for Barcelona→Valencia, but Valencia→Málaga alone came out to 6.82h, still over the limit — because the prompt only required the stop be reachable *from origin* within the limit, never that the *remaining* leg also fit. Two changes fixed it:
  - `prompts/route.txt` now tells the model to pick the stop *as close as possible to the farthest point reachable* within the daily limit, not merely *a* reachable point — maximizing progress per leg so the remainder is more likely to fit too.
  - `supervisor_node` no longer trusts that one split is enough. Every time a leg (the original attempt, or a leg produced by a previous split) comes back infeasible, it splits again — bounded by `split_count < MAX_LEGS - 1`. Bounded on `split_count` (an integer field on `RouteState`, incremented on every split and never reset), **not** on `len(itinerary_legs)`: a leg only gets appended to `itinerary_legs` once it's finished and superseded — if the LLM's proposed stop is *also* infeasible, the same not-yet-finished leg gets re-split instead of advancing, so `itinerary_legs` doesn't grow in that scenario. An earlier draft of this fix bounded on `len(itinerary_legs)` instead and looped forever under exactly that condition — caught by an adversarial "the LLM's stop is always infeasible" simulation before it ever reached the real API. If you touch this bound, re-run that kind of always-infeasible adversarial test, not just a happy-path one.
  Concretely, `supervisor_node` uses `final_destination` (the user's real target, set once on the first split) and `is_final_leg = not final_destination or state["destination"] == final_destination` to decide, on every `"end"`-eligible leg: split further (infeasible + budget left), advance to the next leg toward `final_destination` (not the final leg yet), or assemble `final_itinerary` (is the final leg, feasible or budget exhausted — either way, stop and report honestly: `feasible_within_daily_limit` is the AND of every recorded leg, with a `warning` if any leg is still infeasible when the budget runs out).
  Top-level `poi_data`/`legal_context`/`legal_region`/`fuel_cost`/`math_analysis` in the final response reflect only the **last** leg processed — `final_itinerary.legs` (each entry carrying `legal_region`, not the full text) plus `final_itinerary.legal_context_by_region` is the authoritative source for the full multi-leg picture.

### Spoke agents (`app/agents/*.py`)

Each is a plain function `(state: RouteState) -> dict` (LangGraph node signature), independent of the others:

* **`rag_agent_node`**: Hybrid (metadata-filtered + semantic) search over a persisted Chroma DB at `./chroma_db`. Per the **No Silent Fallbacks** rule above, it raises explicitly instead of degrading quietly: `FileNotFoundError` if `chroma_db/` doesn't exist, `ValueError` if the filtered similarity search returns zero docs. Full pipeline detailed in "RAG pipeline: region-tagged retrieval" below — read that before touching chunk metadata, the region alias table, or the per-region cache.
* **`sql_agent_node`**: Queries a real SQLite DB at `data/campers_poi.db` (seeded by `scripts/seed_poi_db.py`, gitignored — run the script once after cloning) via a read-only URI connection (`file:...?mode=ro`, so a missing DB fails loudly instead of sqlite3 silently creating an empty one). Falls back to hardcoded mock POI data **only on an actual query failure** (missing/corrupt DB) — a real query that legitimately finds zero matches for a destination returns an empty list, it does not trigger the mock. The seed data (50 real areas across 47 Spanish/Portuguese destinations, sourced mostly from park4night.com plus some areasac.es and official operator price lists — see comments in `seed_poi_db.py` for per-row sources) only covers those specific destinations; a `destination` outside that list legitimately returns `[]`, not an error.
* **`math_agent_node`**: Geocodes `origin`/`destination` via Nominatim (OpenStreetMap) and gets a real driving distance + duration from the public OSRM demo server, then derives fuel cost from `CONSUMPTION_L_PER_100KM`/`FUEL_PRICE_EUR_PER_L` (documented constants, not fetched live). Falls back to a randomized distance (`random.uniform(150, 400)` at an assumed 90 km/h) only if geocoding/routing genuinely fails (place not found, no route, network/service error) — same fallback-on-failure-only convention as `sql_agent_node`. Both APIs are free public instances with no key: Nominatim has a strict usage policy (identify via `User-Agent`, ~1 req/s) and the OSRM demo server is not meant for production load — fine for this project's traffic, but don't assume high throughput. Returns both `math_analysis` (full breakdown) and `fuel_cost` (the scalar the prompt's routing rule and the supervisor's guard clause both key off of) — keep both in sync if you touch this node.
  `_geocode` constrains Nominatim to `IBERIA_VIEWBOX` (a bounding box over Spain+Portugal) — without it, an ambiguous single-word place name can silently resolve to the wrong continent (discovered in testing: plain `"Sagres"` geocoded to São Paulo, Brazil, not the Portuguese village — OSRM would then either error out or, worse, return *some* plausible-looking distance for the wrong pair of coordinates). This app only ever plans Iberian routes, so the bounding box is a correctness fix, not a scope restriction to relax casually.

### RAG pipeline: region-tagged retrieval (`scripts/ingest.py` + `app/agents/rag_agent.py`)

`data/ley_costas_y_pernocta.pdf` (despite the filename, it's a DGT "Instrucción" about autocaravanas, not a coastal law) devotes one subsection — **"7.1 – Normativas autonómicas"**, bounded by "7.2 – Comunicación de datos" right after it — to a fixed enumeration of 14 comunidades autónomas, each as an `"En <región> el Decreto/Ley ..."` paragraph (no Baleares/Canarias/La Rioja/Ceuta/Melilla — this document doesn't cover them). Everything else in the PDF is national-level and applies regardless of destination.

An earlier version of this pipeline chunked the raw text first and only added a *soft* region hint to the query text afterward (`"...in Sagres, region: Faro"`). That failed in two ways: (1) a `chunk_size` chosen for chunk quality, not for respecting the document's own section boundaries, let a single chunk straddle two regions' paragraphs, so a query could retrieve a chunk that happened to be dominated by an unrelated region's text; (2) even with clean per-region chunks, a soft text hint competing purely on embedding similarity has no guarantee of winning against a much larger pool of general/preamble chunks. Both were observed directly: a Málaga→Huelva (Andalucía) route was returning País Vasco and Extremadura content.

The fix is two-part, split exactly as the code is:

**1. `scripts/ingest.py` — tag chunks by region using the document's real structure, not post-hoc detection.**
`_split_by_region()` locates the `"7.1 – Normativas autonómicas"` / `"7.2 – Comunicación de datos"` boundary via `REGIONAL_SECTION_START_RE`/`REGIONAL_SECTION_END_RE`, then splits *only* the text inside that span at each of the 14 `REGION_HEADER_RE` matches — text outside the span, and any of the span not covered by a region header, is tagged `"general"`. Each resulting segment is chunked independently (`RecursiveCharacterTextSplitter`, same 1500/300 as before) and every chunk gets `metadata={"region": <tag>}`. Splitting on the document's own subsection headers first — not "chunk then guess" and not "everything after the last regional match belongs to that region" (an earlier draft of this fix got that wrong too: it swallowed the unrelated "7.2" section into "Extremadura", since Extremadura is the last region in the list) — is what makes every chunk unambiguously belong to exactly one region. Verified: after this change (and after the signature-stamp stripping below), all 14 regions produce exactly one clean chunk each; only truly generic content is tagged `"general"` (27 chunks).
If the source PDF is ever replaced, `REGION_HEADER_RE`'s region list/order and the two `REGIONAL_SECTION_*_RE` anchors must be re-derived from the new document's actual text — they are not a generic "Spain's 17 comunidades autónomas" list, they're exactly what this specific PDF contains.

**1b. `scripts/ingest.py` — strip the digital-signature stamp before splitting.**
`PyPDFLoader` extracts a per-page signature-validation stamp (URL + CSV hash + signer name) and splices it directly into the flowing text mid-sentence, not as a clean paragraph — left in place it both pollutes chunk embeddings with irrelevant boilerplate and surfaces as literal noise in `legal_context` ("...FIRMANTE(1): PERE NAVARRO OLIVELLA..."). `SIGNATURE_STAMP_RE` strips all 16 occurrences (~6.5KB, 14% of the raw extracted text) before `_split_by_region()` runs. This is document-specific cleanup, not a generic PDF-noise filter — a different source PDF would need its own boilerplate identified and stripped the same way (inspect the raw extracted text for verbatim-repeated blocks first, the way this one was found).

**2. `app/agents/rag_agent.py` — Query Expansion (city → macro-region) before metadata filtering, hybrid retrieval within it.**
The app's destinations are cities ("Málaga", "Sagres"); the document's chunk metadata is comunidades autónomas. `_resolve_region()` is the Query Expansion step that bridges this gap, in two tiers:
  1. **`DESTINATION_REGION_MAP`** (primary): a static `{city: region}` table covering every destination actually seeded in `scripts/seed_poi_db.py`, kept in sync with it. Deterministic, zero network calls, zero latency.
  2. **`_get_region()` + `_canonical_region()`** (fallback, only for cities not in the map): live Nominatim geocoding (Iberia-bounded, same pattern as `math_agent`'s geocoder but deliberately not shared code — spokes stay independent), canonicalized through `REGION_ALIASES` since Nominatim/OSM names a region differently from how the document does (`"Euskadi"` vs. `"País Vasco"`, `"Comunitat Valenciana"` vs. `"Valencia"`).
  The static map is primary, not the live lookup, because of a failure actually observed in testing: a live geocode call per leg — multiplied by 2 legs after a route split, plus `math_agent`'s own geocode calls for the same request — could trip Nominatim's ~1 req/s policy; `_get_region`'s narrow exception handling then correctly (but unhelpfully) returned `None`, which surfaced as `legal_region: null` in the response despite the region being fully known and static. A lookup this deterministic doesn't need a network round-trip (or an LLM call — a static table is strictly better here: no latency, no cost, no quota, no hallucination risk) on the request's hot path. Portuguese destinations map to `None` deliberately, not to a placeholder region string — this document has no Portugal-specific content, so a `"general"`-only result is the honest answer, not a filter that can never match.
  Retrieval itself is two separate filtered queries, not one: up to 2 chunks with `filter={"region": resolved_region}` (guarantees the actual matching decree is included, rather than leaving it to compete on embedding similarity against ~30 general chunks) topped up to `k=3` total with `filter={"region": "general"}`.
De-duplication: `state["legal_context_by_region"]` is a running `{region: legal_context}` cache threaded through the whole request. If the current leg's region is already a key, `rag_agent_node` returns the cached text directly — no repeat ChromaDB query, and (see `supervisor_node`'s `_leg_summary()`) no repeat of the full text block in `itinerary_legs`; each leg stores only `legal_region`, and `final_itinerary.legal_context_by_region` carries the actual text once per region for the whole multi-leg response.
Known residual limitations: (1) `DESTINATION_REGION_MAP` only covers the 47 seeded destinations — a genuinely new city not in the map still depends on the live-geocoding fallback and can hit the same rate-limit-induced `None`; extend the map first if you add destinations to `seed_poi_db.py`. (2) The alias table only fixes the *region-naming* mismatch, not general multilingual-synonym awareness in the embedding model — an unanticipated Nominatim spelling not yet in `REGION_ALIASES` will silently fall back to `"general"` for the *fallback* path specifically.

### Config (`app/core/config.py`)

`Settings` (pydantic-settings) requires `GEMINI_API_KEY` from `.env` at import time — the process will fail to start without it. This key is what the supervisor's `ChatGoogleGenerativeAI` client authenticates with.

### Evaluation pipeline (`evals/`)

A custom, synchronous, non-pytest eval harness — see `evals/run_evals.py`'s module docstring for the full rationale (real network calls + real LLM quota per case ruled out pytest's cheap/parallel test assumptions; no concurrency is being exploited on purpose, so async would add risk with no benefit).

- **`evals/dataset.py`**: 5 golden `RouteTestCase`s, each with `expect_split`/`expect_feasible` derived from real, previously-observed distances — not guessed.
- **`evals/metrics.py`**: pure `check_*` functions returning `CheckResult` (never raising), so one failed assertion doesn't hide the others. All three checks read the **Python-computed** state fields (`math_analysis`, `itinerary_legs`, `legal_region`, `final_itinerary.feasible_within_daily_limit`) — never `draft_route`'s prose — matching the project's established rule that the LLM's narrative is not a source of truth for hard invariants. `check_rag_relevance` imports `DESTINATION_REGION_MAP` directly from `app.agents.rag_agent` as ground truth (never hand-duplicated) and only asserts "resolved to something, not null" for a leg destination outside that static map (an LLM-chosen intermediate stop can be any real city; those aren't independently verifiable here without reimplementing a geocoder).
- **`evals/callbacks.py`**: `TokenUsageTracker`, a `BaseCallbackHandler` accumulating LLM call count and `usage_metadata` token counts.
- **`evals/run_evals.py`**: the runner. Attaches `TokenUsageTracker` **without modifying `app/agents/supervisor.py`** — `supervisor_module.structured_llm` is a `Runnable`, and `.with_config({"callbacks": [tracker]})` returns a bound copy with the callback wired into every step of its chain; `unittest.mock.patch.object` swaps the module-level name in for one case's duration and restores it automatically (even on exception). This works because `supervisor_node` looks up the module global `structured_llm` fresh on every call rather than capturing it in a closure — if that ever changes (e.g. `structured_llm` gets imported by name into another module, or bound to a local variable at import time), this patch technique stops working silently and needs revisiting.
- Cost is reported from real token counts; the $/1K-token rate is a placeholder constant (`COST_PER_1K_*_TOKENS_USD`, both `0.0` — this project runs on Gemini's free tier) rather than a fabricated price. Update it if you move to a paid tier.
- A case that raises (e.g. a Gemini 429) is reported as an **error**, distinct from a **failed check** — only the latter means the system's logic actually regressed; don't conflate the two when reading a report.
- The exact "LLM said 'end' but a required field is still empty" guard (see the Supervisor section above) fires routinely even on simple single-leg cases in this eval suite — that's expected, not a bug in the eval harness; it's the invariant doing its job.
