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
        effective_top_k = top_k or self._settings.agent_top_k
        original_question = question.strip()

        initial_state: AgentState = {
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
        }

        try:
            final_state = await self._graph.ainvoke(initial_state)
            status = final_state.get("status")
            if status not in {"answered", "refused"}:
                raise RuntimeError("Agent 工作流未产生最终状态")

            steps = (
                list(final_state.get("workflow_steps", []))
                if self._settings.agent_trace_enabled
                else []
            )
            response = AgentAskResponse(
                status=status,
                answer=final_state.get("answer") or "",
                citations=list(final_state.get("citations", [])),
                workflow=AgentWorkflow(
                    original_question=original_question,
                    final_query=final_state.get("current_question")
                    or original_question,
                    rewrite_attempted=final_state.get(
                        "rewrite_attempted",
                        False,
                    ),
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
                ),
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
