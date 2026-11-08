"""显式白名单工具 LangGraph；一次请求只执行一个工具。"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..tools.registry import ToolRegistry
from .tool_state import SAFE_TOOL_STEPS, ToolState


class ToolGraph:
    """START -> validate -> execute once -> format -> END。"""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self.graph = self._build()

    def _build(self):
        builder = StateGraph(ToolState)
        builder.add_node("validate_tool_request", self.validate_tool_request)
        builder.add_node("execute_selected_tool", self.execute_selected_tool)
        builder.add_node("format_tool_response", self.format_tool_response)
        builder.add_edge(START, "validate_tool_request")
        builder.add_edge("validate_tool_request", "execute_selected_tool")
        builder.add_edge("execute_selected_tool", "format_tool_response")
        builder.add_edge("format_tool_response", END)
        return builder.compile()

    @staticmethod
    def _step(state: ToolState, name: str) -> list[str]:
        if name not in SAFE_TOOL_STEPS:
            raise ValueError(f"未定义的工具节点: {name}")
        return [*state["workflow_steps"], name]

    async def validate_tool_request(self, state: ToolState) -> dict:
        parsed = self._registry.parse_arguments(
            state["tool_name"],
            state["tool_input"],
        )
        return {
            "tool_input": parsed.model_dump(),
            "workflow_steps": self._step(
                state,
                "validate_tool_request",
            ),
        }

    async def execute_selected_tool(self, state: ToolState) -> dict:
        parsed = self._registry.parse_arguments(
            state["tool_name"],
            state["tool_input"],
        )
        outcome = await self._registry.execute(state["tool_name"], parsed)
        return {
            "tool_result": outcome.result,
            "status": outcome.status,
            "workflow_steps": self._step(
                state,
                "execute_selected_tool",
            ),
            "llm_called": outcome.llm_called,
            "retrieval_count": outcome.retrieval_count,
            "evidence_count": outcome.evidence_count,
            "refusal_reason": outcome.refusal_reason,
        }

    async def format_tool_response(self, state: ToolState) -> dict:
        status = state["status"]
        if status not in {"success", "refused"}:
            raise RuntimeError("工具工作流未产生最终状态")
        response = {
            "status": status,
            "tool_name": state["tool_name"],
            "result": state["tool_result"] or {},
            "workflow": {
                "steps": self._step(state, "format_tool_response"),
                "llm_called": state["llm_called"],
                "retrieval_count": state["retrieval_count"],
                "evidence_count": state["evidence_count"],
            },
            "refusal_reason": state.get("refusal_reason"),
        }
        return {
            "response": response,
            "workflow_steps": self._step(state, "format_tool_response"),
        }

    async def ainvoke(self, state: ToolState) -> ToolState:
        return await self.graph.ainvoke(
            state,
            config={"recursion_limit": 8},
        )
