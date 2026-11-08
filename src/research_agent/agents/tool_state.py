"""受控工具图状态。"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

ToolStateStatus = Literal["pending", "success", "refused", "error"]

SAFE_TOOL_STEPS = frozenset(
    {
        "validate_tool_request",
        "execute_selected_tool",
        "format_tool_response",
    }
)


class ToolState(TypedDict):
    request_id: str
    tool_name: str
    tool_input: dict[str, Any]
    tool_result: dict[str, Any] | None
    status: ToolStateStatus
    workflow_steps: list[str]
    llm_called: bool
    retrieval_count: int
    evidence_count: int
    refusal_reason: str | None
    error_code: str | None
    response: dict[str, Any] | None
