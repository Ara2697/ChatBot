from langgraph.graph import StateGraph, START, END
from state import AgentState
from nodes import (
    router_node,
    route_by_intent,
    sales_node,
    compliance_node,
    vendor_node,
    ops_node,
    kb_node,
    formatter_node
)

sessions: dict = {}


def build_graph() -> StateGraph:
    workflow = StateGraph(AgentState)

    workflow.add_node("router",     router_node)
    workflow.add_node("sales",      sales_node)
    workflow.add_node("compliance", compliance_node)
    workflow.add_node("vendor",     vendor_node)
    workflow.add_node("ops",        ops_node)
    workflow.add_node("kb",         kb_node)
    workflow.add_node("formatter",  formatter_node)

    workflow.add_edge(START, "router")

    workflow.add_conditional_edges(
        "router",
        route_by_intent,
        {
            "SALES_RECO":        "sales",
            "COMPLIANCE_CHECK":  "compliance",
            "VENDOR_ONBOARDING": "vendor",
            "OPS_STOCK":         "ops",
            "GENERAL_KB":        "kb"
        }
    )

    workflow.add_edge("sales",      "formatter")
    workflow.add_edge("compliance", "formatter")
    workflow.add_edge("vendor",     "formatter")
    workflow.add_edge("ops",        "formatter")
    workflow.add_edge("kb",         "formatter")
    workflow.add_edge("formatter",  END)

    return workflow.compile()


graph = build_graph()


def chat(message: str, user_type: str = "internal_sales", session_id: str = "default") -> str:
    valid_user_types = ["internal_sales", "portal_vendor", "portal_customer"]
    if user_type not in valid_user_types:
        return f"Error: unknown user_type '{user_type}'. Must be one of {valid_user_types}"

    session = sessions.get(session_id, {})

    initial_state: AgentState = {
        "message":      message,
        "user_type":    user_type,
        "session_id":   session_id,
        "intent":       "",
        "entities":     {},
        "tool_outputs": {},
        "response":     "",
        "session":      session
    }

    try:
        result = graph.invoke(initial_state)
        sessions[session_id] = result.get("session", {})
        return result.get("response", "[No response generated]")
    except PermissionError as e:
        return f"Access denied: {e}"
    except Exception as e:
        return f"Error processing request: {e}"


if __name__ == "__main__":
    print("\n" + "="*60)
    print("GW Products USA — AI Chat Service Demo")
    print("="*60)

    SESSION = "demo-session-001"

    print("\n[Q1] SALES: Give me hot picks for CA under $5000")
    print("-"*50)
    print(chat("Give me hot picks for CA under $5000", session_id=SESSION))

    print("\n[Q2] COMPLIANCE: Why is SKU-001 not available in CA?")
    print("-"*50)
    print(chat("Why is SKU-001 not available in CA? Suggest alternatives.", session_id=SESSION))

    print("\n[Q3] OPS: How much stock does SKU-001 have and where?")
    print("-"*50)
    print(chat("How much stock does SKU-001 have and where?", session_id=SESSION))

    print("\n[Q4] VENDOR: Missing Net Wt and no lab report")
    print("-"*50)
    print(chat(
        "I'm uploading a product missing Net Wt and no lab report — what do I fix?",
        user_type  = "portal_vendor",
        session_id = SESSION
    ))

    print("\n[Q5] MEMORY: Add 2 of the first one to the basket")
    print("-"*50)
    print(chat("Ok add 2 of the first one to the basket", session_id=SESSION))

    print("\n[BONUS] PERMISSION: portal_customer tries vendor_validate")
    print("-"*50)
    print(chat(
        "I'm uploading a product missing Net Wt",
        user_type  = "portal_customer",
        session_id = SESSION
    ))
