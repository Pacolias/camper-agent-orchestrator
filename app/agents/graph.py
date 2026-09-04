from langgraph.graph import StateGraph, END
from app.agents.state import RouteState

def dummy_node(state: RouteState):
    current_errors = state.get("errors", [])
    current_errors.append("Dummy node executed")

    return {"errors": current_errors}

workflow = StateGraph(RouteState)

workflow.add_node("dummy", dummy_node)

workflow.set_entry_point("dummy")
workflow.add_edge("dummy", END)

app_graph = workflow.compile()