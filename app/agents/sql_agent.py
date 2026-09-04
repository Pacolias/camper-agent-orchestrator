from app.agents.state import RouteState

def sql_agent_node(State: RouteState):
    mock_pois = [
        {"name": "Camping La Rosaleda (Conil)", "hookups": True},
        {"name": "Camping Ria Formosa (Algarve)", "hookups": True}
    ]

    return {"pois": mock_pois}