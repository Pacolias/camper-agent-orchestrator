import numpy as np

from app.agents.state import RouteState

def math_agent_node(state: RouteState):
    """
    Make numeric calculations to optimize the route:
    driving time, stimate expenses and consume.
    """
    max_hours = state.get("max_driving_hours_per_day", 8.0)
    
    distance_km = np.random.uniform(150, 400) 
    avg_speed_kmh = 90.0
    consumption_l_100 = 10.5
    fuel_price_eur = 1.65
    
    metrics = np.array([distance_km, avg_speed_kmh, consumption_l_100, fuel_price_eur])
    driving_hours = metrics[0] / metrics[1]
    total_fuel_cost = (metrics[0] / 100.0) * metrics[2] * metrics[3]
    
    is_feasible = driving_hours <= max_hours
    
    math_analysis = {
        "estimated_distance_km": round(float(metrics[0]), 2),
        "driving_time_hours": round(float(driving_hours), 2),
        "estimated_fuel_cost_eur": round(float(total_fuel_cost), 2),
        "feasible_within_daily_limit": bool(is_feasible)
    }
    
    return {"math_analysis": math_analysis}