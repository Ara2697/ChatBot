from typing import Optional
from typing_extensions import TypedDict


class AgentState(TypedDict):
    message: str
    user_type: str
    session_id: str
    intent: str
    entities: dict
    tool_outputs: dict
    response: str
    session: dict
