"""Agent 图入口：初始化隔离状态并组装安全响应。"""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from ..agents.nodes import AgentNodes
from ..agents.research_graph import ResearchGraph
from ..agents.state import AgentState
from ..core.config import Settings
from ..schemas.agent import AgentAskResponse, AgentWorkflow
from .qa_service import QAService
from .query_rewrite_service import QueryRewriteService
from .retrieval_service import RetrievalService

logger = logging.getLogger(__name__)


class AgentService:
    """每个请求创建独立 state，图执行结束后必须给出 answered/refused。"""

    def __init__(
        self,
        settings: Settings,
        retrieval_service: RetrievalService,
        qa_service: QAService,
        rewrite_service: QueryRewriteService,
    ) -> None:
        self._settings = settings
        self._nodes = AgentNodes(
            settings=settings,
            retrieval_service=retrieval_service,
            qa_service=qa_service,
            rewrite_service=rewrite_service,
        )
        self._graph = ResearchGraph(self._nodes)
        self.graph = self._graph.graph

    def build_initial_state(
        self,
        question: str,
        top_k: int | None,
        document_ids: list[str] | None,
        enable_rewrite: bool,
        *,
        request_id: str | None = None,
        event_sink=None,
    ) -> AgentState:
        """构造隔离状态；非流式与流式共用同一字段集合。"""
        effective_top_k = top_k or self._settings.agent_top_k
        original_question = question.strip()
        return {
            "request_id": request_id or str(uuid4()),
            "event_sink": event_sink,
            "original_question": original_question,
            "current_question": original_question,
            "document_ids": document_ids,
            "top_k": effective_top_k,
            "enable_rewrite": enable_rewrite,
            "initial_results": [],
            "final_results": [],
            "evidence": [],
            "rewrite_attempted": False,
            "rewrite_count": 0,
            "rewritten_question": None,
            "rewrite_failed": False,
            "rewrite_changed": False,
            "answer": None,
            "citations": [],
            "status": "pending",
            "refusal_reason": None,
            "workflow_steps": [],
            "retrieval_count": 0,
            "initial_retrieval_count": 0,
            "final_retrieval_count": 0,
            "evidence_count": 0,
            "retrieval_duration_ms": 0.0,
            "llm_duration_ms": 0.0,
        }

    async def run_state(self, state: AgentState) -> AgentState:
        return await self._graph.ainvoke(state)

    def build_workflow(self, final_state: AgentState) -> AgentWorkflow:
        steps = (
            list(final_state.get("workflow_steps", []))
            if self._settings.agent_trace_enabled
            else []
        )
        return AgentWorkflow(
            original_question=final_state["original_question"],
            final_query=final_state.get("current_question")
            or final_state["original_question"],
            rewrite_attempted=final_state.get("rewrite_attempted", False),
            rewrite_count=final_state.get("rewrite_count", 0),
            rewrite_changed=final_state.get("rewrite_changed", False),
            steps=steps,
            initial_retrieval_count=final_state.get(
                "initial_retrieval_count",
                0,
            ),
            final_retrieval_count=final_state.get(
                "final_retrieval_count",
                0,
            ),
            evidence_count=final_state.get("evidence_count", 0),
        )

    async def ask(
        self,
        question: str,
        top_k: int | None,
        document_ids: list[str] | None,
        enable_rewrite: bool,
    ) -> AgentAskResponse:
        """执行一次完整工作流；不跨请求复用 state。"""
        request_id = str(uuid4())
        started = time.perf_counter()
        initial_state = self.build_initial_state(
            question,
            top_k,
            document_ids,
            enable_rewrite,
            request_id=request_id,
        )

        try:
            final_state = await self.run_state(initial_state)
            status = final_state.get("status")
            if status not in {"answered", "refused"}:
                raise RuntimeError("Agent 工作流未产生最终状态")

            response = AgentAskResponse(
                status=status,
                answer=final_state.get("answer") or "",
                citations=list(final_state.get("citations", [])),
                workflow=self.build_workflow(final_state),
                refusal_reason=final_state.get("refusal_reason"),
            )
            logger.info(
                "Agent completed request_id=%s initial=%d final=%d "
                "evidence=%d rewrite=%s status=%s duration_ms=%.0f",
                request_id,
                response.workflow.initial_retrieval_count,
                response.workflow.final_retrieval_count,
                response.workflow.evidence_count,
                response.workflow.rewrite_attempted,
                response.status,
                (time.perf_counter() - started) * 1000,
            )
            return response
        except Exception as exc:
            logger.warning(
                "Agent request failed request_id=%s error=%s",
                request_id,
                type(exc).__name__,
            )
            raise
