from typing import TypedDict

class RouteState(TypedDict):
    user_request: str
    origin: str | None
    destination: str | None
    max_driving_hours_per_day: int
    requires_hookups: bool
    legal_context: str
    legal_region: str | None
    legal_context_by_region: dict[str, str]
    poi_data: list[dict]
    fuel_cost: float
    math_analysis: dict
    final_itinerary: dict
    errors: list[str]
    next_action: str
    final_destination: str | None
    itinerary_legs: list[dict]