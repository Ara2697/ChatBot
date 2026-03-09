import re
import json
import time
import uuid
from pathlib import Path
from state import AgentState
from tools import hot_picks, compliance_filter, stock_by_warehouse, vendor_validate, kb_search
from permissions import check_permission, redact_pii
from logger import log_tool_call, log_request_summary

# ── Load intent keywords from config — extendable without code changes ─────────
_KEYWORDS_PATH = Path(__file__).parent / "intent_keywords.json"
try:
    with open(_KEYWORDS_PATH) as f:
        INTENT_KEYWORDS: dict = json.load(f)
    print(f"[ROUTER] Loaded intent keywords from {_KEYWORDS_PATH.name}")
except Exception as e:
    print(f"[ROUTER] WARNING — could not load intent_keywords.json: {e}. Using defaults.")
    INTENT_KEYWORDS = {
        "VENDOR_ONBOARDING": ["upload", "missing", "lab report", "net wt", "fix"],
        "COMPLIANCE_CHECK":  ["blocked", "available", "legal", "why", "restricted"],
        "SALES_RECO":        ["hot pick", "recommend", "under $", "budget"],
        "OPS_STOCK":         ["stock", "warehouse", "inventory", "how many"],
        "GENERAL_KB":        []
    }

# Priority order — checked top to bottom
_INTENT_ORDER = [
    "VENDOR_ONBOARDING",
    "COMPLIANCE_CHECK",
    "SALES_RECO",
    "OPS_STOCK",
    "GENERAL_KB",
]


def _req_id(state: AgentState) -> str:
    return state.get("session", {}).get("request_id", str(uuid.uuid4())[:8])


def router_node(state: AgentState) -> dict:
    msg     = state["message"].lower()
    session = state.get("session", {})
    request_id = str(uuid.uuid4())[:8]
    session["request_id"] = request_id
    session["start_time"] = time.time()

    # ── Keyword matching from JSON config ──────────────────────────────────────
    intent = "GENERAL_KB"  # default
    for candidate in _INTENT_ORDER:
        keywords = INTENT_KEYWORDS.get(candidate, [])
        if any(kw in msg for kw in keywords):
            intent = candidate
            break

    entities = _extract_entities(msg, session)
    return {"intent": intent, "entities": entities, "session": session}


def _extract_entities(msg: str, session: dict) -> dict:
    entities = {}

    state_match = re.search(r'\b(CA|TX|FL|IL|NY|CO|WA|ID|SD|NE)\b', msg.upper())
    entities["us_state"] = state_match.group(1) if state_match else session.get("last_state", "CA")

    budget_match = re.search(r'\$\s?(\d+[\d,]*)', msg)
    entities["budget"] = float(budget_match.group(1).replace(",", "")) if budget_match else session.get("last_budget", 5000)

    sku_match = re.search(r'(SKU-\d+|PROD-\d+)', msg.upper())
    if sku_match:
        entities["product_id"]  = sku_match.group(1)
        entities["product_ids"] = [sku_match.group(1)]
    else:
        entities["product_ids"] = session.get("last_product_ids", [])

    quantity_match = re.search(r'add\s+(\d+)\s+of\s+the\s+(first|second|third)', msg)
    if quantity_match:
        qty   = int(quantity_match.group(1))
        order = {"first": 0, "second": 1, "third": 2}.get(quantity_match.group(2), 0)
        last_products = session.get("last_sales_product_ids") or session.get("last_product_ids", [])
        if last_products and order < len(last_products):
            entities["basket_product_id"] = last_products[order]
            entities["basket_qty"]        = qty

    entities["attributes"] = session.get("last_attributes", {})
    return entities


def route_by_intent(state: AgentState) -> str:
    return state["intent"]


def sales_node(state: AgentState) -> dict:
    check_permission(state["user_type"], "hot_picks")
    check_permission(state["user_type"], "compliance_filter")

    req_id   = _req_id(state)
    us_state = state["entities"].get("us_state", "CA")
    budget   = state["entities"].get("budget", 5000)
    session  = state.get("session", {})
    tools_called = []

    products = log_tool_call(
        tool_name  = "hot_picks",
        fn         = lambda: hot_picks(us_state, budget, limit=5),
        request_id = req_id,
        user_type  = state["user_type"],
        intent     = state["intent"],
        args       = {"state": us_state, "budget": budget}
    )
    tools_called.append("hot_picks")

    filtered = log_tool_call(
        tool_name  = "compliance_filter",
        fn         = lambda: compliance_filter(us_state, [p["product_id"] for p in products]),
        request_id = req_id,
        user_type  = state["user_type"],
        intent     = state["intent"],
        args       = {"state": us_state, "product_ids": [p["product_id"] for p in products]}
    )
    tools_called.append("compliance_filter")

    session.update({
        "last_intent":            "SALES_RECO",
        "last_state":             us_state,
        "last_budget":            budget,
        "last_product_ids":       [p["product_id"] for p in products],
        "last_sales_product_ids": [p["product_id"] for p in products],
        "tools_called":           tools_called
    })

    _log_summary(state, req_id, tools_called, session)
    return {"tool_outputs": {"products": products, "filtered": filtered}, "session": session}


def compliance_node(state: AgentState) -> dict:
    check_permission(state["user_type"], "compliance_filter")

    req_id      = _req_id(state)
    us_state    = state["entities"].get("us_state", "CA")
    product_ids = state["entities"].get("product_ids", [])
    session     = state.get("session", {})

    result = log_tool_call(
        tool_name  = "compliance_filter",
        fn         = lambda: compliance_filter(us_state, product_ids),
        request_id = req_id,
        user_type  = state["user_type"],
        intent     = state["intent"],
        args       = {"state": us_state, "product_ids": product_ids}
    )

    session.update({
        "last_intent":      "COMPLIANCE_CHECK",
        "last_state":       us_state,
        "last_product_ids": product_ids,
        "tools_called":     ["compliance_filter"]
    })

    _log_summary(state, req_id, ["compliance_filter"], session)
    return {"tool_outputs": result, "session": session}


def vendor_node(state: AgentState) -> dict:
    check_permission(state["user_type"], "vendor_validate")

    req_id     = _req_id(state)
    attributes = state["entities"].get("attributes", {})
    session    = state.get("session", {})

    if not attributes:
        attributes = _parse_vendor_attributes(state["message"])

    result = log_tool_call(
        tool_name  = "vendor_validate",
        fn         = lambda: vendor_validate(attributes),
        request_id = req_id,
        user_type  = state["user_type"],
        intent     = state["intent"],
        args       = {"attributes": attributes}
    )

    session.update({
        "last_intent":     "VENDOR_ONBOARDING",
        "last_attributes": attributes,
        "tools_called":    ["vendor_validate"]
    })

    _log_summary(state, req_id, ["vendor_validate"], session)
    return {"tool_outputs": result, "session": session}


def _parse_vendor_attributes(msg: str) -> dict:
    msg_lower = msg.lower()
    return {
        "name":                      "Submitted Product",
        "category":                  "THC Beverage" if "thc" in msg_lower else "Nicotine Vape",
        "net_wt_oz":                 None if "missing net wt" in msg_lower or "net wt" in msg_lower else 1.0,
        "net_vol_ml":                30,
        "nicotine_mg":               0,
        "lab_report_attached":       False if "no lab" in msg_lower else True,
        "fda_registration_attached": False
    }


def ops_node(state: AgentState) -> dict:
    check_permission(state["user_type"], "stock_by_warehouse")

    req_id     = _req_id(state)
    product_id = state["entities"].get("product_id") or \
                 (state["entities"].get("product_ids") or [None])[0]
    session    = state.get("session", {})

    result = log_tool_call(
        tool_name  = "stock_by_warehouse",
        fn         = lambda: stock_by_warehouse(product_id),
        request_id = req_id,
        user_type  = state["user_type"],
        intent     = state["intent"],
        args       = {"product_id": product_id}
    )

    session.update({
        "last_intent":      "OPS_STOCK",
        "last_product_ids": [product_id] if product_id else [],
        "tools_called":     ["stock_by_warehouse"]
    })

    _log_summary(state, req_id, ["stock_by_warehouse"], session)
    return {"tool_outputs": result, "session": session}


def kb_node(state: AgentState) -> dict:
    req_id  = _req_id(state)
    session = state.get("session", {})

    result = log_tool_call(
        tool_name  = "kb_search",
        fn         = lambda: kb_search(state["message"], top_k=2, user_visibility=state["user_type"]),
        request_id = req_id,
        user_type  = state["user_type"],
        intent     = state["intent"],
        args       = {"query": state["message"]}
    )

    session.update({"last_intent": "GENERAL_KB", "tools_called": ["kb_search"]})
    _log_summary(state, req_id, ["kb_search"], session)
    return {"tool_outputs": {"docs": result}, "session": session}


def formatter_node(state: AgentState) -> dict:
    from formatter import format_response
    safe_outputs = redact_pii(state["tool_outputs"])
    response = format_response(
        intent       = state["intent"],
        tool_outputs = safe_outputs,
        message      = state["message"],
        session      = state.get("session", {})
    )
    return {"response": response}


def _log_summary(state: AgentState, req_id: str, tools_called: list, session: dict):
    start      = session.get("start_time", time.time())
    latency_ms = round((time.time() - start) * 1000, 2)
    log_request_summary(
        request_id       = req_id,
        user_type        = state["user_type"],
        intent           = state["intent"],
        tools_called     = tools_called,
        total_latency_ms = latency_ms,
        session_id       = state.get("session_id", "unknown")
    )
