from langgraph.graph import StateGraph, END
from app.agents.state import RouteState
from app.agents.supervisor import supervisor_node
from app.agents.sql_agent import sql_agent_node
from app.agents.rag_agent import rag_agent_node
from app.agents.math_agent import math_agent_node

def router(state: RouteState):
    action = state.get("next_action", "end")
    if action == "end":
        return END
    return action

workflow = StateGraph(RouteState)

workflow.add_node("supervisor", supervisor_node)
workflow.add_node("sql_agent", sql_agent_node)
workflow.add_node("rag_agent", rag_agent_node)
workflow.add_node("math_agent", math_agent_node)

workflow.set_entry_point("supervisor")

workflow.add_conditional_edges(
    "supervisor",
    router,
    {
        "sql_agent": "sql_agent",
        "rag_agent": "rag_agent",
        "math_agent": "math_agent",
        END: END
    }
)

workflow.add_edge("sql_agent", "supervisor")
workflow.add_edge("rag_agent", "supervisor")
workflow.add_edge("math_agent", "supervisor")

app_graph = workflow.compile()