import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from langchain_core.exceptions import ModelRateLimitError, ModelAPIError

from app.agents.graph import app_graph

# Configure logging for observability
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Camper Agent Orchestrator",
    description="API for planning and orchestrating campervan routes and pernoctation stops."
)

class RoutePayload(BaseModel):
    origin: str = Field(..., description="Starting point of the trip")
    destination: str = Field(..., description="Final destination")
    max_driving_hours_per_day: int = Field(default=4, description="Max driving time before stopping")
    requires_hookups: bool = Field(default=False, description="Requires electricity/water services at stops")
    preferences: Optional[List[str]] = Field(default=None, description="E.g., ['coastal', 'free_camping']")

@app.post("/api/route")
async def plan_route(payload: RoutePayload):
    """
    Orchestrates the route planning process, evaluation waypoints,
    service areas and driving limits for campervans.
    """
    logger.info(f"Initiating route calculation from {payload.origin} to {payload.destination} ")

    try:

        prefs_str = ", ".join(payload.preferences) if payload.preferences else "None"
        synthesized_request = (
            f"Plan a route from {payload.origin} to {payload.destination}. "
            f"Max {payload.max_driving_hours_per_day}h driving/day. "
            f"Hookups required: {payload.requires_hookups}. Preferences: {prefs_str}."
        )


        initial_state = {
            "user_request": synthesized_request,
            "origin": payload.origin,
            "destination": payload.destination,
            "max_driving_hours_per_day": payload.max_driving_hours_per_day,
            "requires_hookups": payload.requires_hookups,
            "legal_context": "",
            "legal_region": None,
            "legal_context_by_region": {},
            "poi_data": [],
            "fuel_cost": 0.0,
            "final_itinerary": {},
            "errors": [],
            "final_destination": None,
            "itinerary_legs": [],
            "split_count": 0
        }


        final_state = app_graph.invoke(initial_state)

        logger.info("Route successfully orchestrated by LangGraph.")
        return {"status": "success", "data": final_state}

    except ValueError as ve:
        logger.error(f"Value error during route planning: {ve}")
        raise HTTPException(status_code=422, detail=str(ve))
    except ModelRateLimitError as e:
        logger.error(f"Gemini API rate limit exceeded: {e}")
        raise HTTPException(status_code=429, detail="Gemini API rate limit exceeded. Please retry shortly.")
    except ModelAPIError as e:
        logger.error(f"Gemini API server-side failure: {e}")
        raise HTTPException(status_code=503, detail="Gemini API is temporarily unavailable. Please retry shortly.")
    except Exception as e:
        logger.error(f"Validation error during route planning: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error while planning the route.")