"""LangGraph 节点：检索、证据判断、改写、回答和拒答。"""

from __future__ import annotations

from typing import Literal

from ..core.config import Settings
from ..core.exceptions import QueryRewriteError
from ..services.llm_service import QA_REFUSAL_ANSWER
from ..services.qa_service import NO_EVIDENCE_REASON, QAService
from ..services.query_rewrite_service import QueryRewriteService
from ..services.retrieval_service import RetrievalService
from .state import AgentState, SAFE_WORKFLOW_STEPS

RETRY_NO_EVIDENCE_REASON = (
    "经过问题改写和二次检索后，仍未检索到足够相关的文档证据。"
)
REWRITE_FAILED_REASON = (
    "初次检索未找到足够证据，且无法完成问题改写后的二次检索。"
)

InitialRoute = Literal["answer", "rewrite", "refuse"]
RewriteRoute = Literal["retrieve_retry", "refuse"]
RetryRoute = Literal["answer", "refuse"]


class AgentNodes:
    """无副作用节点集合；每次请求使用独立 state。"""

    def __init__(
        self,
        settings: Settings,
        retrieval_service: RetrievalService,
        qa_service: QAService,
        rewrite_service: QueryRewriteService,
    ) -> None:
        self._settings = settings
        self._retrieval = retrieval_service
        self._qa = qa_service
        self._rewriter = rewrite_service

    @staticmethod
    def _steps_for(state: AgentState, step: str) -> list[str]:
        if step not in SAFE_WORKFLOW_STEPS:
            raise ValueError(f"未定义的 workflow step: {step}")
        return [*state["workflow_steps"], step]

    async def retrieve_initial(self, state: AgentState) -> dict:
        """使用原始问题执行唯一一次初次检索。"""
        retrieved = self._retrieval.search(
            query=state["original_question"],
            top_k=state["top_k"],
            document_ids=state["document_ids"],
        )
        return {
            "initial_results": retrieved.results,
            "initial_retrieval_count": len(retrieved.results),
            "final_retrieval_count": 0,
            "retrieval_count": 1,
            "workflow_steps": self._steps_for(state, "retrieve_initial"),
        }

    async def assess_initial_evidence(self, state: AgentState) -> dict:
        """复用第四阶段证据阈值；只判断是否足够，不做额外检索。"""
        evidence = self._qa.select_evidence(
            state["initial_results"],
            max_context_chars=self._settings.agent_max_context_chars,
        )
        insufficient = len(evidence) < self._settings.min_evidence_count
        updates: dict = {
            "evidence": evidence,
            "evidence_count": len(evidence),
            "workflow_steps": self._steps_for(
                state,
                "assess_initial_evidence",
            ),
        }
        if insufficient and not self._can_rewrite(state):
            updates["refusal_reason"] = NO_EVIDENCE_REASON
        return updates

    def route_initial(
        self,
        state: AgentState,
    ) -> InitialRoute:
        """初次证据足够则回答；否则最多改写一次；再否则拒答。"""
        if state["evidence_count"] >= self._settings.min_evidence_count:
            return "answer"
        if self._can_rewrite(state):
            return "rewrite"
        return "refuse"

    async def rewrite_query(self, state: AgentState) -> dict:
        """只改写检索查询，不回答；失败时直接转入拒答。"""
        updates: dict = {
            "rewrite_attempted": True,
            "rewrite_count": 1,
            "workflow_steps": self._steps_for(state, "rewrite_query"),
        }
        try:
            rewritten = await self._rewriter.rewrite(state["original_question"])
        except QueryRewriteError:
            updates.update(
                {
                    "rewrite_failed": True,
                    "rewrite_changed": False,
                    "refusal_reason": REWRITE_FAILED_REASON,
                }
            )
            return updates

        updates.update(
            {
                "rewritten_question": rewritten,
                "current_question": rewritten,
                "rewrite_changed": rewritten != state["original_question"],
            }
        )
        return updates

    def route_rewrite(
        self,
        state: AgentState,
    ) -> RewriteRoute:
        if state["rewrite_failed"]:
            return "refuse"
        return "retrieve_retry"

    async def retrieve_retry(self, state: AgentState) -> dict:
        """仅使用改写后的查询检索一次，参数与初次完全相同。"""
        retrieved = self._retrieval.search(
            query=state["current_question"],
            top_k=state["top_k"],
            document_ids=state["document_ids"],
        )
        return {
            "final_results": retrieved.results,
            "final_retrieval_count": len(retrieved.results),
            "retrieval_count": 2,
            "workflow_steps": self._steps_for(state, "retrieve_retry"),
        }

    async def assess_retry_evidence(self, state: AgentState) -> dict:
        """使用与初次完全相同的阈值判断二次检索结果。"""
        evidence = self._qa.select_evidence(
            state["final_results"],
            max_context_chars=self._settings.agent_max_context_chars,
        )
        insufficient = len(evidence) < self._settings.min_evidence_count
        updates: dict = {
            "evidence": evidence,
            "evidence_count": len(evidence),
            "workflow_steps": self._steps_for(
                state,
                "assess_retry_evidence",
            ),
        }
        if insufficient:
            updates["refusal_reason"] = RETRY_NO_EVIDENCE_REASON
        return updates

    def route_retry(
        self,
        state: AgentState,
    ) -> RetryRoute:
        if state["evidence_count"] >= self._settings.min_evidence_count:
            return "answer"
        return "refuse"

    async def answer_with_evidence(self, state: AgentState) -> dict:
        """复用第四阶段回答逻辑；不再执行检索或改写。"""
        retrieved_count = (
            state["final_retrieval_count"]
            if state["retrieval_count"] == 2
            else state["initial_retrieval_count"]
        )
        response = await self._qa.answer_from_evidence(
            question=state["original_question"],
            evidence=state["evidence"],
            retrieved_count=retrieved_count,
            top_k=state["top_k"],
        )
        return {
            "status": response.status,
            "answer": response.answer,
            "citations": response.citations,
            "refusal_reason": response.refusal_reason,
            "workflow_steps": self._steps_for(state, "answer"),
        }

    async def refuse(self, state: AgentState) -> dict:
        """不调用回答 LLM，返回固定拒答与空引用。"""
        reason = state.get("refusal_reason") or NO_EVIDENCE_REASON
        return {
            "status": "refused",
            "answer": QA_REFUSAL_ANSWER,
            "citations": [],
            "refusal_reason": reason,
            "workflow_steps": self._steps_for(state, "refuse"),
        }

    def _can_rewrite(self, state: AgentState) -> bool:
        return (
            self._settings.enable_query_rewrite
            and state["enable_rewrite"]
            and self._settings.max_query_rewrite_attempts >= 1
            and state["rewrite_count"] == 0
        )
