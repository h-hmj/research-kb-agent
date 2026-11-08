"""工具图入口：隔离状态、统一响应和安全日志。"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import uuid4

from ..agents.tool_graph import ToolGraph
from ..agents.tool_state import ToolState
from ..schemas.tools import ToolRunResponse
from ..tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ToolService:
    def __init__(self, registry: ToolRegistry) -> None:
        self._graph = ToolGraph(registry)
        self.graph = self._graph.graph

    async def run(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolRunResponse:
        request_id = str(uuid4())
        started = time.perf_counter()
        initial_state: ToolState = {
            "request_id": request_id,
            "tool_name": tool_name,
            "tool_input": arguments,
            "tool_result": None,
            "status": "pending",
            "workflow_steps": [],
            "llm_called": False,
            "retrieval_count": 0,
            "evidence_count": 0,
            "refusal_reason": None,
            "error_code": None,
            "response": None,
        }

        try:
            final_state = await self._graph.ainvoke(initial_state)
            response_data = final_state.get("response")
            if not response_data:
                raise RuntimeError("工具工作流未生成响应")
            response = ToolRunResponse.model_validate(response_data)
            logger.info(
                "Tool completed request_id=%s tool=%s llm=%s status=%s "
                "retrieval=%d evidence=%d duration_ms=%.0f",
                request_id,
                response.tool_name,
                response.workflow.llm_called,
                response.status,
                response.workflow.retrieval_count,
                response.workflow.evidence_count,
                (time.perf_counter() - started) * 1000,
            )
            return response
        except Exception as exc:
            logger.warning(
                "Tool request failed request_id=%s tool=%s error=%s",
                request_id,
                tool_name,
                type(exc).__name__,
            )
            raise
