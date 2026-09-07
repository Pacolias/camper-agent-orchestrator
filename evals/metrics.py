"""
Pure evaluation functions for one graph run's final state.

Each check returns a CheckResult instead of raising, so run_evals.py can
collect every check for a case (and every case in the suite) even when one
fails — a single assertion failure must not hide the others.

All checks operate on the STRUCTURAL/COMPUTED fields the Python state
machine controls (math_analysis, itinerary_legs, legal_region,
final_itinerary.feasible_within_daily_limit) — never on draft_route's prose.
That split is deliberate: draft_route is LLM narrative and can phrase things
however the model likes; the fields checked here are what supervisor_node
computes deterministically from real tool output, which is what previous
debugging in this project established as the only trustworthy source of
truth (see CLAUDE.md, "Feasibility is enforced in Python, not just in the
prompt" / "'end' is never trusted at face value").
"""
from dataclasses import dataclass

from app.agents.rag_agent import DESTINATION_REGION_MAP, GENERAL_TAG

# Floating-point tolerance for driving-time comparisons (OSRM durations have
# sub-second precision that rounds unevenly against an integer hour limit).
EPSILON_HOURS = 0.05


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def _effective_legs(result: dict) -> list[dict]:
    """
    Normalize single-leg and multi-leg responses into one shape. A route that
    never needed splitting never populates itinerary_legs (see
    supervisor_node), so build a one-item list from the top-level fields in
    that case instead of treating "no legs" as "no data".
    """
    legs = result.get("itinerary_legs") or []
    if legs:
        return [
            {
                "destination": leg.get("destination"),
                "driving_time_hours": (leg.get("math_analysis") or {}).get("driving_time_hours"),
                "legal_region": leg.get("legal_region"),
            }
            for leg in legs
        ]
    return [{
        "destination": result.get("destination"),
        "driving_time_hours": (result.get("math_analysis") or {}).get("driving_time_hours"),
        "legal_region": result.get("legal_region"),
    }]


def check_constraint_adherence(result: dict, max_hours: float, expect_feasible: bool) -> CheckResult:
    """Metric 1: no leg in the final itinerary may exceed max_driving_hours_per_day."""
    legs = _effective_legs(result)
    violations = [
        leg for leg in legs
        if leg["driving_time_hours"] is not None and leg["driving_time_hours"] > max_hours + EPSILON_HOURS
    ]

    if expect_feasible:
        passed = not violations
        detail = (
            "all legs within limit"
            if passed
            else f"{len(violations)} leg(s) exceed {max_hours}h: "
                 + ", ".join(f"{v['destination']} ({v['driving_time_hours']}h)" for v in violations)
        )
        return CheckResult("constraint_adherence", passed, detail)

    # Deliberately-unsolvable case: the system MAY remain infeasible, but it
    # must say so explicitly rather than silently reporting success on an
    # illegal route.
    final_itinerary = result.get("final_itinerary") or {}
    passed = final_itinerary.get("feasible_within_daily_limit") is False and "warning" in final_itinerary
    detail = (
        "honestly reported infeasible with a warning"
        if passed
        else f"expected an honest infeasibility warning; got "
             f"feasible_within_daily_limit={final_itinerary.get('feasible_within_daily_limit')!r}, "
             f"warning_present={'warning' in final_itinerary}"
    )
    return CheckResult("constraint_adherence", passed, detail)


def check_routing_logic(result: dict, expect_split: bool) -> CheckResult:
    """
    Metric 2: if the direct route is infeasible, the supervisor must replan
    as multiple legs with an intermediate stop — never a single illegal leg,
    and never an abrupt 'end' that just discards the excess driving time.
    """
    legs_field = result.get("itinerary_legs") or []
    did_split = len(legs_field) >= 2 and result.get("final_destination") is not None

    if expect_split:
        passed = did_split
        detail = (
            f"split into {len(legs_field)} legs via intermediate stop "
            f"{legs_field[0]['destination']!r}" if passed
            else "expected a multi-leg split, but the route ended as a single leg "
                 "(the supervisor either judged it feasible, which contradicts the "
                 "test case, or failed to propose an intermediate_stop)"
        )
    else:
        passed = not did_split
        detail = "single leg, no split needed" if passed else \
            f"unexpected split into {len(legs_field)} legs for a route that should fit in one leg"

    return CheckResult("agentic_routing_logic", passed, detail)


def check_rag_relevance(result: dict) -> CheckResult:
    """
    Metric 3: legal_region must match the real administrative region of the
    leg's destination — never null, and never a region unrelated to where
    the leg actually goes.

    Ground truth comes from DESTINATION_REGION_MAP, imported directly from
    production code (not hand-duplicated) so the test can't silently drift
    from what the app actually does. A leg whose destination is NOT in that
    static map (e.g. an LLM-chosen intermediate stop the map doesn't cover)
    falls back to live Nominatim geocoding in production — that path isn't
    independently verifiable here without re-implementing a geocoder, so for
    those legs this only asserts "resolved to something" (not null), which
    still catches the exact bug this project hit (silent None on rate-limit).
    """
    legs = _effective_legs(result)
    problems = []
    unverified = []

    for leg in legs:
        dest_key = (leg["destination"] or "").strip().lower()
        actual = leg["legal_region"]

        if actual is None:
            problems.append(f"{leg['destination']!r}: legal_region is null")
            continue

        if dest_key in DESTINATION_REGION_MAP:
            expected = DESTINATION_REGION_MAP[dest_key] or GENERAL_TAG
            if actual != expected:
                problems.append(f"{leg['destination']!r}: expected {expected!r}, got {actual!r}")
        else:
            unverified.append(leg["destination"])

    passed = not problems
    detail_parts = []
    if passed:
        detail_parts.append("all legs resolved to their correct region")
    else:
        detail_parts.append("; ".join(problems))
    if unverified:
        detail_parts.append(f"(not independently verified, outside static map: {unverified})")

    return CheckResult("rag_context_relevance", passed, " ".join(detail_parts))
