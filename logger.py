import json
import time
import uuid
from typing import Callable, Any


def generate_request_id() -> str:
    return str(uuid.uuid4())[:8]


def log_tool_call(
    tool_name: str,
    fn: Callable,
    request_id: str = None,
    user_type: str = "unknown",
    intent: str = "unknown",
    args: dict = None
) -> Any:
    request_id = request_id or generate_request_id()
    start  = time.time()
    error  = None
    result = None

    try:
        result = fn()
    except Exception as e:
        error = str(e)
        raise
    finally:
        latency_ms = round((time.time() - start) * 1000, 2)
        log_entry = {
            "request_id": request_id,
            "user_type":  user_type,
            "intent":     intent,
            "tool":       tool_name,
            "args":       args or {},
            "latency_ms": latency_ms,
            "status":     "error" if error else "ok",
            "error":      error
        }
        print(f"[LOG] {json.dumps(log_entry)}")

    return result


def log_request_summary(
    request_id: str,
    user_type: str,
    intent: str,
    tools_called: list[str],
    total_latency_ms: float,
    token_estimate: int = None,
    session_id: str = None
):
    summary = {
        "event":            "REQUEST_COMPLETE",
        "request_id":       request_id,
        "session_id":       session_id,
        "user_type":        user_type,
        "intent":           intent,
        "tools_called":     tools_called,
        "total_latency_ms": total_latency_ms,
        "token_estimate":   token_estimate or estimate_tokens(tools_called)
    }
    print(f"[SUMMARY] {json.dumps(summary)}")


def estimate_tokens(tools_called: list[str]) -> int:
    base_tokens = 200
    per_tool    = 150
    return base_tokens + (len(tools_called) * per_tool)
