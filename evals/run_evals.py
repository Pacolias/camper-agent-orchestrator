"""
Custom evaluation runner for the campervan route-planning LangGraph pipeline.

Why not pytest: every case here makes real network calls (Gemini, Nominatim,
OSRM) and consumes real LLM quota on a free-tier key that this project has
repeatedly rate-limited during development (see CLAUDE.md). pytest's model
assumes fast, cheap, independently-orderable tests; this suite needs
sequential execution with deliberate spacing between cases, plus one
aggregate structured report at the end rather than a per-test dot.

Why not async: there is no concurrency to exploit — cases are run one at a
time ON PURPOSE to respect Nominatim's ~1 req/s policy and Gemini's
per-minute quota. Async would only invite parallelizing the cases later,
which would make results LESS reliable, not more. A plain synchronous script
also mirrors how app/main.py itself calls the graph (app_graph.invoke, not
ainvoke).

Token/cost observability (Metric 4) is attached WITHOUT modifying
app/agents/supervisor.py: that module's `structured_llm` is a plain
Runnable, and `.with_config({"callbacks": [...]})` returns a new bound copy
with a callback attached to every step in its chain (including the
underlying chat model call) — no production code needs a `config` parameter
threaded through it. `unittest.mock.patch.object` swaps the module-level
name for the duration of one case and restores it automatically, even if
the case raises.

Usage:
    python -m evals.run_evals
    python -m evals.run_evals --delay 5              # seconds between cases (default 15)
    python -m evals.run_evals --case short_same_region
"""
import argparse
import sys
import time
import traceback
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents import supervisor as supervisor_module  # noqa: E402
from app.agents.graph import app_graph  # noqa: E402
from evals.callbacks import TokenUsageTracker  # noqa: E402
from evals.dataset import DATASET, RouteTestCase  # noqa: E402
from evals.metrics import CheckResult, check_constraint_adherence, check_rag_relevance, check_routing_logic  # noqa: E402

# Placeholder rate — this project runs on Gemini's free tier (see CLAUDE.md),
# so actual $ cost today is $0 regardless of this estimate. Set these to your
# billing tier's published per-1K-token rate if you move off the free tier.
COST_PER_1K_INPUT_TOKENS_USD = 0.0
COST_PER_1K_OUTPUT_TOKENS_USD = 0.0

DEFAULT_DELAY_SECONDS = 15.0


def build_initial_state(case: RouteTestCase) -> dict:
    """Mirrors app/main.py's plan_route() initial_state construction exactly."""
    return {
        "user_request": (
            f"Plan a route from {case.origin} to {case.destination}. "
            f"Max {case.max_driving_hours_per_day}h driving/day. "
            f"Hookups required: {case.requires_hookups}."
        ),
        "origin": case.origin,
        "destination": case.destination,
        "max_driving_hours_per_day": case.max_driving_hours_per_day,
        "requires_hookups": case.requires_hookups,
        "legal_context": "",
        "legal_region": None,
        "legal_context_by_region": {},
        "poi_data": [],
        "fuel_cost": 0.0,
        "final_itinerary": {},
        "errors": [],
        "final_destination": None,
        "itinerary_legs": [],
        "split_count": 0,
    }


def run_case(case: RouteTestCase) -> dict:
    tracker = TokenUsageTracker()
    traced_llm = supervisor_module.structured_llm.with_config({"callbacks": [tracker]})

    error = None
    result_state = None
    start = time.perf_counter()
    with patch.object(supervisor_module, "structured_llm", traced_llm):
        try:
            result_state = app_graph.invoke(build_initial_state(case))
        except Exception as exc:  # noqa: BLE001 - one case's failure must not abort the suite
            error = exc
    latency_s = time.perf_counter() - start

    checks: list[CheckResult] = []
    if error is None:
        checks = [
            check_constraint_adherence(result_state, case.max_driving_hours_per_day, case.expect_feasible),
            check_routing_logic(result_state, case.expect_split),
            check_rag_relevance(result_state),
        ]

    return {
        "case": case,
        "error": error,
        "result_state": result_state,
        "latency_s": latency_s,
        "llm_calls": tracker.llm_calls,
        "input_tokens": tracker.input_tokens,
        "output_tokens": tracker.output_tokens,
        "checks": checks,
    }


def estimated_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (
        (input_tokens / 1000) * COST_PER_1K_INPUT_TOKENS_USD
        + (output_tokens / 1000) * COST_PER_1K_OUTPUT_TOKENS_USD
    )


def print_report(runs: list[dict]) -> bool:
    width = 88
    print("\n" + "=" * width)
    print("EVAL REPORT — Campervan Route Orchestrator")
    print("=" * width)

    total_checks_passed = 0
    total_checks = 0
    cases_passed = 0
    error_cases = []

    for i, run in enumerate(runs):
        case: RouteTestCase = run["case"]
        print(f"\n[{i + 1}/{len(runs)}] {case.name}  ({case.origin} -> {case.destination}, "
              f"max={case.max_driving_hours_per_day}h)")

        if run["error"] is not None:
            print(f"  ERROR   {type(run['error']).__name__}: {run['error']}")
            print(f"          (transient failure — likely a Gemini/Nominatim rate limit, not a "
                  f"logic bug; rerun with --case {case.name} once quota resets)")
            error_cases.append(case.name)
            continue

        case_passed = True
        for check in run["checks"]:
            total_checks += 1
            status = "PASS" if check.passed else "FAIL"
            if check.passed:
                total_checks_passed += 1
            else:
                case_passed = False
            print(f"  {status:<4}  {check.name:<26} {check.detail}")

        cost = estimated_cost_usd(run["input_tokens"], run["output_tokens"])
        print(
            f"  latency: {run['latency_s']:.2f}s | llm_calls: {run['llm_calls']} | "
            f"tokens: {run['input_tokens']} in / {run['output_tokens']} out | "
            f"est. cost: ${cost:.4f}"
        )

        if case_passed:
            cases_passed += 1

    total_latency = sum(r["latency_s"] for r in runs)
    total_llm_calls = sum(r["llm_calls"] for r in runs)
    total_input_tokens = sum(r["input_tokens"] for r in runs)
    total_output_tokens = sum(r["output_tokens"] for r in runs)
    total_cost = estimated_cost_usd(total_input_tokens, total_output_tokens)

    print("\n" + "-" * width)
    print("SUMMARY")
    print("-" * width)
    print(f"Cases:            {cases_passed}/{len(runs) - len(error_cases)} passed"
          f"{f' ({len(error_cases)} errored)' if error_cases else ''}")
    print(f"Checks:           {total_checks_passed}/{total_checks} passed")
    print(f"Total latency:    {total_latency:.2f}s")
    print(f"Total LLM calls:  {total_llm_calls}")
    print(f"Total tokens:     {total_input_tokens + total_output_tokens:,} "
          f"({total_input_tokens:,} in / {total_output_tokens:,} out)")
    print(f"Est. total cost:  ${total_cost:.4f} "
          f"(free tier — see COST_PER_1K_*_TOKENS_USD to change)")
    if error_cases:
        print(f"\nERRORED CASES (not counted as logic failures): {', '.join(error_cases)}")
    print("=" * width)

    return cases_passed == (len(runs) - len(error_cases)) and not error_cases


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY_SECONDS,
        help=f"Seconds to wait between cases, to respect Gemini/Nominatim rate limits "
             f"(default: {DEFAULT_DELAY_SECONDS})"
    )
    parser.add_argument("--case", type=str, default=None, help="Run only the named case")
    args = parser.parse_args()

    cases = [c for c in DATASET if args.case is None or c.name == args.case]
    if not cases:
        available = ", ".join(c.name for c in DATASET)
        print(f"No case named {args.case!r}. Available: {available}")
        sys.exit(2)

    runs = []
    for i, case in enumerate(cases):
        print(f"\n[{i + 1}/{len(cases)}] Running {case.name!r} "
              f"({case.origin} -> {case.destination})...")
        try:
            runs.append(run_case(case))
        except Exception:  # noqa: BLE001 - surface unexpected harness bugs without losing prior results
            print(f"  HARNESS ERROR while running {case.name!r}:")
            traceback.print_exc()
            runs.append({
                "case": case, "error": RuntimeError("harness error, see traceback above"),
                "result_state": None, "latency_s": 0.0, "llm_calls": 0,
                "input_tokens": 0, "output_tokens": 0, "checks": [],
            })
        if i < len(cases) - 1:
            time.sleep(args.delay)

    all_passed = print_report(runs)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
