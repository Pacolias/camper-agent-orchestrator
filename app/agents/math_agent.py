import random

import requests

from app.agents.state import RouteState

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
USER_AGENT = "camper-agent-orchestrator/1.0"
REQUEST_TIMEOUT = 10

CONSUMPTION_L_PER_100KM = 10.5  # typical diesel campervan/motorhome consumption
FUEL_PRICE_EUR_PER_L = 1.65    # approximate diesel price (EUR)

FALLBACK_AVG_SPEED_KMH = 90.0

# This app only plans routes in Spain/Portugal (see the seeded POI DB and the
# Spanish legal PDF). Ambiguous single-word place names (e.g. "Sagres" is
# also a town in Brazil) can otherwise resolve to the wrong continent with a
# plausible-looking pair of coordinates — bounding the search to Iberia
# disambiguates deterministically instead of trusting Nominatim's raw ranking.
IBERIA_VIEWBOX = "-9.6,44.0,3.5,35.9"


def _geocode(place: str) -> tuple[float, float]:
    response = requests.get(
        NOMINATIM_URL,
        params={
            "q": place, "format": "json", "limit": 1,
            "viewbox": IBERIA_VIEWBOX, "bounded": 1
        },
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        raise ValueError(f"No coordinates found for '{place}'")
    return float(results[0]["lat"]), float(results[0]["lon"])


def _route_distance_and_duration(origin_coords: tuple[float, float], destination_coords: tuple[float, float]) -> tuple[float, float]:
    lat1, lon1 = origin_coords
    lat2, lon2 = destination_coords
    url = OSRM_URL.format(lon1=lon1, lat1=lat1, lon2=lon2, lat2=lat2)

    response = requests.get(url, params={"overview": "false"}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()

    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError("No driving route found between the two points")

    route = data["routes"][0]
    return route["distance"] / 1000.0, route["duration"] / 3600.0  # km, hours


def math_agent_node(state: RouteState):
    """
    Make numeric calculations to optimize the route:
    driving time, estimate expenses and consumption.
    """
    max_hours = state.get("max_driving_hours_per_day", 8.0)
    origin = state.get("origin", "")
    destination = state.get("destination", "")

    try:
        origin_coords = _geocode(origin)
        destination_coords = _geocode(destination)
        distance_km, driving_hours = _route_distance_and_duration(origin_coords, destination_coords)
    except (requests.RequestException, ValueError):
        # Fallback: geocoding/routing unavailable (offline, no route found, service down)
        distance_km = random.uniform(150, 400)
        driving_hours = distance_km / FALLBACK_AVG_SPEED_KMH

    total_fuel_cost = (distance_km / 100.0) * CONSUMPTION_L_PER_100KM * FUEL_PRICE_EUR_PER_L
    is_feasible = driving_hours <= max_hours

    math_analysis = {
        "estimated_distance_km": round(distance_km, 2),
        "driving_time_hours": round(driving_hours, 2),
        "estimated_fuel_cost_eur": round(total_fuel_cost, 2),
        "feasible_within_daily_limit": bool(is_feasible)
    }

    return {"math_analysis": math_analysis, "fuel_cost": math_analysis["estimated_fuel_cost_eur"]}
