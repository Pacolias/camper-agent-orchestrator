from typing import TypedDict

class RouteState(TypedDict):
    user_request: str
    origin: str | None
    destination: str | None
    max_driving_hours_per_day: int
    requires_hookups: bool
    legal_context: str
    poi_data: list[dict]
    fuel_cost: float
    math_analysis: dict
    final_itinerary: dict
    errors: list[str]
    next_action: str