from typing import TypedDict

class RouteState(TypedDict):
    user_request: str
    origin: str | None
    destination: str | None
    legal_context: str
    poi_data: list[dict]
    fuel_cost: float
    final_itinerary: dict
    errors: list[str]
    next_action: str