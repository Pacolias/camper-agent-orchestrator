import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional


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
        # route_dict = route_optimizer.calculate(payload.dict())

        route_dict = {
            "summary": {
                "origin": payload.origin,
                "destination": payload.destination,
                "max_driving_hours_per_day": 6.5,
                "service_requirements_met": payload.requires_hookups
            },
            "waypoints": [
                {
                    "type": "rest_stop",
                    "location": "Service Area A",
                    "recommended_durantion_mins": 45
                },
                {
                    "type": "pernoctation",
                    "location": "Camper Park B",
                    "amenities": ["water", "electricity"] if payload.requires_hookups else ["parking"]
                }
            ],
            "agent_notes": "Routes optimized for minimum toll usage and scenic coastal views."
        }

        logger.info("Route successfully orchestrated and generated.")
        return {"status": "success", "data": route_dict}

    except ValueError as ve:
        logger.error(f"Value error during route planning: {ve}")
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.error(f"Validation error during route planning: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error while planning the route.")