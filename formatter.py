import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()


def _get_client():
    if PROVIDER == "anthropic":
        try:
            import anthropic
            return anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        except Exception as e:
            raise RuntimeError(f"Anthropic init failed: {e}")

    elif PROVIDER == "gemini":
        try:
            from google import genai
            return genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        except Exception as e:
            raise RuntimeError(f"Gemini init failed: {e}")

    elif PROVIDER == "ollama":
        try:
            import ollama
            return ollama
        except Exception as e:
            raise RuntimeError(f"Ollama init failed: {e}")

    else:
        raise RuntimeError(f"Unknown LLM_PROVIDER: '{PROVIDER}'. Use: ollama | anthropic | gemini")


def _call_llm(prompt: str) -> str:
    client = _get_client()

    if PROVIDER == "anthropic":
        response = client.messages.create(
            model   = "claude-3-5-haiku-20241022",
            max_tokens = 400,
            messages   = [{"role": "user", "content": prompt}]
        )
        return response.content[0].text

    elif PROVIDER == "gemini":
        response = client.models.generate_content(
            model    = "gemini-2.0-flash",
            contents = prompt
        )
        return response.text

    elif PROVIDER == "ollama":
        model    = os.environ.get("OLLAMA_MODEL", "deepseek-r1:1.5b")
        response = client.chat(
            model    = model,
            messages = [{"role": "user", "content": prompt}]
        )
        return response["message"]["content"]


SYSTEM_PROMPT = """You are a concise B2B sales assistant for GW Products USA.
RULES:
1. Only use data from the tool results provided. Never invent facts.
2. Never override compliance decisions. Blocked = blocked, always.
3. Keep responses under 150 words. Professional tone.
4. If tool results are empty, say so honestly."""


PROMPT_TEMPLATES = {

    "SALES_RECO": """
{system}

User asked: "{message}"

ALLOWED products (safe to recommend):
{allowed}

REVIEW products (lab report required):
{review}

Format a clean recommendation. Show ALLOWED first, flag REVIEW items. Never mention blocked products.
""",

    "COMPLIANCE_CHECK": """
{system}

User asked: "{message}"

State: {state}
BLOCKED: {blocked}
ALTERNATIVES: {alternatives}

Explain why the product is blocked in {state}. Suggest the alternatives. Be factual and brief.
""",

    "VENDOR_ONBOARDING": """
{system}

User asked: "{message}"

Validation result:
Status: {status}
Missing fields: {missing_fields}
Required documents: {required_documents}

Give the vendor a clear checklist of exactly what to fix. Be direct.
""",

    "OPS_STOCK": """
{system}

User asked: "{message}"

Product: {name} ({sku})
Warehouses: {warehouses}
Total: {total_qty} units

Summarise stock per warehouse. Highlight zero-stock locations.
""",

    "GENERAL_KB": """
{system}

User asked: "{message}"

Relevant policy docs:
{docs}

Answer using only the policy snippets above.
"""
}


def _build_prompt(intent: str, tool_outputs: dict, message: str, session: dict) -> str:
    t = PROMPT_TEMPLATES.get(intent, PROMPT_TEMPLATES["GENERAL_KB"])

    if intent == "SALES_RECO":
        f = tool_outputs.get("filtered", {})
        return t.format(
            system  = SYSTEM_PROMPT,
            message = message,
            allowed = json.dumps(f.get("allowed", []), indent=2),
            review  = json.dumps(f.get("review",  []), indent=2),
        )
    elif intent == "COMPLIANCE_CHECK":
        state = tool_outputs.get("state", session.get("last_state", "unknown"))
        return t.format(
            system       = SYSTEM_PROMPT,
            message      = message,
            state        = state,
            blocked      = json.dumps(tool_outputs.get("blocked",      []), indent=2),
            alternatives = json.dumps(tool_outputs.get("alternatives", []), indent=2),
        )
    elif intent == "VENDOR_ONBOARDING":
        return t.format(
            system             = SYSTEM_PROMPT,
            message            = message,
            status             = tool_outputs.get("status",             "UNKNOWN"),
            missing_fields     = tool_outputs.get("missing_fields",     []),
            required_documents = tool_outputs.get("required_documents", []),
        )
    elif intent == "OPS_STOCK":
        return t.format(
            system     = SYSTEM_PROMPT,
            message    = message,
            name       = tool_outputs.get("name",      "Unknown"),
            sku        = tool_outputs.get("sku",       "N/A"),
            warehouses = json.dumps(tool_outputs.get("warehouses", []), indent=2),
            total_qty  = tool_outputs.get("total_qty", 0),
        )
    else:
        docs = tool_outputs.get("docs", [])
        docs_text = "\n\n".join(
            f"[{d['doc_id']}] {d['title']}:\n{d['snippet']}" for d in docs
        ) if docs else "No relevant documents found."
        return t.format(system=SYSTEM_PROMPT, message=message, docs=docs_text)


def format_response(intent: str, tool_outputs: dict, message: str, session: dict) -> str:
    try:
        # Basket / memory shortcut
        is_basket = "basket" in message.lower() or (
            "add" in message.lower() and "first" in message.lower()
        )
        if is_basket:
            last_ids = session.get("last_sales_product_ids", [])
            prompt = f"""{SYSTEM_PROMPT}

User said: "{message}"

Previous sales results (in order):
{json.dumps(last_ids, indent=2)}

Confirm which product the user is adding (the first one) and acknowledge 2 units added to basket.
Keep it under 60 words."""
        else:
            prompt = _build_prompt(intent, tool_outputs, message, session)

        result = _call_llm(prompt)
        print(f"[LLM] Provider: {PROVIDER.upper()} ✓")
        return result

    except Exception as e:
        print(f"[LLM ERROR] Provider '{PROVIDER}': {e}")
        return f"[LLM unavailable — raw results]: {json.dumps(tool_outputs, indent=2)}"
