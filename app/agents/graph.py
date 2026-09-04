from langgraph.graph import StateGraph, END
from app.agents.state import RouteState
from app.agents.supervisor import supervisor_node

workflow = StateGraph(RouteState)

workflow.add_node("supervisor", supervisor_node)

workflow.set_entry_point("supervisor")
workflow.add_edge("supervisor", END)

app_graph = workflow.compile()