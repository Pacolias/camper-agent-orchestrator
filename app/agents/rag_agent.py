from app.agents.state import RouteState

def rag_agent_node(State: RouteState):
    return {"legal_context": "It's illegal to camp outside of designated campgrounds in the Algarve."}