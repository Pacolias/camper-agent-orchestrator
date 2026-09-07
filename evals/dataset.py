"""
Golden dataset of campervan routes for the evaluation pipeline.

Each case's expectations (`expect_split`, `expect_feasible`) are derived from
real, previously-observed distances (see CLAUDE.md / conversation history),
not guessed — e.g. Málaga->Sagres is a known ~518km / ~6.1h direct drive, so
a 4h daily limit is known to force a split. Destinations are drawn from
`app.agents.rag_agent.DESTINATION_REGION_MAP` / `scripts/seed_poi_db.py`
wherever possible, so region-relevance assertions can compare against a
static, deterministic ground truth instead of depending on live geocoding.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class RouteTestCase:
    name: str
    origin: str
    destination: str
    max_driving_hours_per_day: int
    requires_hookups: bool = False
    expect_split: bool = False
    expect_feasible: bool = True
    notes: str = ""


DATASET: list[RouteTestCase] = [
    RouteTestCase(
        name="short_same_region",
        origin="Málaga",
        destination="Huelva",
        max_driving_hours_per_day=4,
        expect_split=False,
        expect_feasible=True,
        notes="Short intra-Andalucía hop (~300km/~3.7h) — well under the daily limit.",
    ),
    RouteTestCase(
        name="cross_region_short",
        origin="Santander",
        destination="Bilbao",
        max_driving_hours_per_day=4,
        expect_split=False,
        expect_feasible=True,
        notes="Crosses a real region boundary (Cantabria -> País Vasco) but is short "
              "enough for one leg — tests that legal_region tracks the DESTINATION's "
              "region, not the origin's.",
    ),
    RouteTestCase(
        name="long_cross_region_split",
        origin="Barcelona",
        destination="Málaga",
        max_driving_hours_per_day=6,
        expect_split=True,
        expect_feasible=True,
        notes="~1000km Cataluña -> Andalucía. Must split into 2 legs, each individually "
              "feasible within 6h.",
    ),
    RouteTestCase(
        name="international_split_general_region",
        origin="Málaga",
        destination="Sagres",
        max_driving_hours_per_day=4,
        requires_hookups=True,
        expect_split=True,
        expect_feasible=True,
        notes="Known ~518km/~6.1h direct drive into Portugal. Must split; the "
              "Portugal-side leg has no region-specific legal content, so it must "
              "resolve to 'general' — not null, and not a fabricated region.",
    ),
    RouteTestCase(
        name="extreme_infeasible_after_split",
        origin="Madrid",
        destination="Cádiz",
        max_driving_hours_per_day=1,
        expect_split=True,
        expect_feasible=False,
        notes="Unrealistically strict limit for a ~650km trip: even after the one "
              "bounded split this system performs, both legs remain infeasible. "
              "The system must admit this (feasible_within_daily_limit=False + a "
              "warning), not silently report a single illegal route as done. "
              "KNOWN: this case forces MAX_LEGS splits, which needs 20+ Gemini calls "
              "— reliably exceeds the free tier's 15 RPM cap and surfaces as a 429 "
              "ERROR even with a fully-reset quota window, not a failed check. See "
              "README.md 'Known Limitations' — left as-is, not a logic bug.",
    ),
]
