"""LangGraph Agent 的显式状态。"""

from __future__ import annotations

from typing import Literal, Protocol, TypedDict

from ..schemas.qa import EvidenceChunk, QACitation
from ..schemas.retrieval import RetrievalResult

AgentStatus = Literal["pending", "answered", "refused", "error"]

SAFE_WORKFLOW_STEPS = frozenset(
    {
        "retrieve_initial",
        "assess_initial_evidence",
        "rewrite_query",
        "retrieve_retry",
        "assess_retry_evidence",
        "answer",
        "refuse",
    }
)


class EventSink(Protocol):
    """流式事件入口；非流式执行时状态中为 None。"""

    async def emit(self, event: str, data: dict) -> None:
        ...


class AgentState(TypedDict):
    """图节点之间传递的状态，不保存 Prompt 或模型原始输出。"""

    request_id: str
    event_sink: EventSink | None
    original_question: str
    current_question: str
    document_ids: list[str] | None
    top_k: int
    enable_rewrite: bool
    initial_results: list[RetrievalResult]
    final_results: list[RetrievalResult]
    evidence: list[EvidenceChunk]
    rewrite_attempted: bool
    rewrite_count: int
    rewritten_question: str | None
    rewrite_failed: bool
    rewrite_changed: bool
    answer: str | None
    citations: list[QACitation]
    status: AgentStatus
    refusal_reason: str | None
    workflow_steps: list[str]
    retrieval_count: int
    initial_retrieval_count: int
    final_retrieval_count: int
    evidence_count: int
    retrieval_duration_ms: float
    llm_duration_ms: float
