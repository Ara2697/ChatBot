# GW Products USA — AI Chat Service

## How to Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Add your API key
cp .env.example .env
# Open .env and replace sk-ant-your-key-here with your actual Anthropic API key

# 3. Run the demo
python main.py
```

## Architecture Overview

```
main.py          → LangGraph graph assembly + chat() entry point
state.py         → AgentState TypedDict (shared across all nodes)
nodes.py         → Router + 5 chain nodes + formatter node
tools.py         → 5 deterministic tools reading from seed_data.json
formatter.py     → LLM wrapper (Claude Haiku) — formats tool outputs only
logger.py        → Structured JSON logs per tool call + request summary
permissions.py   → Tool allowlists per user_type + PII redaction
seed_data.json   → Data source (products, inventory, vendors, kb_docs)
```

## Where Things Live

| Concern | File | Detail |
|---|---|---|
| Intent routing | `nodes.py` → `router_node` | Keyword matching, no LLM |
| Tool logic | `tools.py` | Pure Python, deterministic |
| Graph/chains | `main.py` → `build_graph()` | LangGraph StateGraph |
| Session state | `main.py` → `sessions` dict | In-memory, keyed by session_id |
| Observability | `logger.py` | JSON logs to stdout |
| Permissions | `permissions.py` → `check_permission()` | Called top of every node |
| PII redaction | `permissions.py` → `redact_pii()` | Applied before LLM call |

## Supported Intents

| Intent | Chain |
|---|---|
| `SALES_RECO` | hot_picks → compliance_filter |
| `COMPLIANCE_CHECK` | compliance_filter + alternatives |
| `VENDOR_ONBOARDING` | vendor_validate + checklist |
| `OPS_STOCK` | stock_by_warehouse |
| `GENERAL_KB` | kb_search |

## User Types & Permissions

| user_type | Allowed Tools |
|---|---|
| `internal_sales` | All tools |
| `portal_vendor` | vendor_validate, kb_search |
| `portal_customer` | hot_picks, compliance_filter, kb_search |

## Notes

- `seed_data.json` was built from the schema in Appendix A of the test spec.
- LLM is used only in `formatter.py` to explain tool outputs — never to make decisions.
- Compliance decisions are 100% deterministic — LLM cannot override them.
- Session state is in-memory. In production: swap `sessions` dict for Redis or LangGraph MemorySaver.
- Odoo integration: each tool's data source becomes a JSON-RPC call to the relevant Odoo model.
