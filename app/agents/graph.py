from langgraph.graph import StateGraph, END
from app.agents.state import RouteState
from app.agents.supervisor import supervisor_node
from app.agents.sql_agent import sql_agent_node

def router(state: RouteState):
    return state.get("next_action", "end")

workflow = StateGraph(RouteState)

workflow.add_node("supervisor", supervisor_node)
workflow.add_node("sql_agent", sql_agent_node)

workflow.set_entry_point("supervisor")

workflow.add_conditional_edges(
    "supervisor",
    router,
    {
        "sql_agent": "sql_agent",
        "rag_agent": END,
        "math_agent": END,
        "end": END
    }
)

workflow.add_edge("sql_agent", "supervisor")

app_graph = workflow.compile()