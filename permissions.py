TOOL_ALLOWLIST = {
    "internal_sales": [
        "hot_picks",
        "compliance_filter",
        "stock_by_warehouse",
        "vendor_validate",
        "kb_search"
    ],
    "portal_vendor": [
        "vendor_validate",
        "kb_search"
    ],
    "portal_customer": [
        "hot_picks",
        "compliance_filter",
        "kb_search"
    ]
}


def check_permission(user_type: str, tool_name: str) -> None:
    allowed_tools = TOOL_ALLOWLIST.get(user_type)
    if allowed_tools is None:
        raise PermissionError(
            f"Unknown user_type '{user_type}'. "
            f"Must be one of: {list(TOOL_ALLOWLIST.keys())}"
        )
    if tool_name not in allowed_tools:
        raise PermissionError(
            f"user_type '{user_type}' is not allowed to call '{tool_name}'. "
            f"Allowed tools: {allowed_tools}"
        )


def get_allowed_tools(user_type: str) -> list[str]:
    return TOOL_ALLOWLIST.get(user_type, [])


PII_FIELDS = ["customer_id", "vendor_id", "email", "phone", "address"]

def redact_pii(data: dict) -> dict:
    if not isinstance(data, dict):
        return data
    return {
        k: "[REDACTED]" if k in PII_FIELDS else (
            redact_pii(v) if isinstance(v, dict) else
            [redact_pii(i) if isinstance(i, dict) else i for i in v] if isinstance(v, list)
            else v
        )
        for k, v in data.items()
    }
