"""受控单轮问答编排：检索、证据判断、LLM 或拒答、引用。"""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from ..core.config import Settings
from ..core.exceptions import LLMUnavailableError
from ..schemas.qa import (
    EvidenceChunk,
    QAResponse,
    QARetrievalInfo,
)
from ..schemas.retrieval import RetrievalResult
from .citation_service import CitationService
from .llm_service import LLMService, QA_REFUSAL_ANSWER
from .retrieval_service import RetrievalService

logger = logging.getLogger(__name__)

NO_EVIDENCE_REASON = "未检索到足够相关的文档证据。"
LLM_REFUSAL_REASON = "检索证据不足以支持可靠回答。"


class QAService:
    """只基于检索证据回答；证据不足或模型拒答时不生成引用。"""

    def __init__(
        self,
        settings: Settings,
        retrieval_service: RetrievalService,
        llm_service: LLMService,
        citation_service: CitationService,
    ) -> None:
        self._settings = settings
        self._retrieval = retrieval_service
        self._llm = llm_service
        self._citations = citation_service

    async def ask(
        self,
        question: str,
        top_k: int | None,
        document_ids: list[str] | None,
    ) -> QAResponse:
        """执行单轮问答，所有引用由服务端从实际证据生成。"""
        request_id = str(uuid4())
        started = time.perf_counter()
        effective_top_k = top_k or self._settings.qa_top_k
        query = question.strip()

        try:
            retrieved = self._retrieval.search(
                query=query,
                top_k=effective_top_k,
                document_ids=document_ids,
            )
            retrieved_count = len(retrieved.results)
            evidence = self.select_evidence(retrieved.results)
            evidence_count = len(evidence)

            if evidence_count < self._settings.min_evidence_count:
                response = self._refused(
                    query,
                    retrieved_count=retrieved_count,
                    evidence_count=evidence_count,
                    top_k=effective_top_k,
                    reason=NO_EVIDENCE_REASON,
                )
            else:
                response = await self.answer_from_evidence(
                    question=query,
                    evidence=evidence,
                    retrieved_count=retrieved_count,
                    top_k=effective_top_k,
                )
            self._log_result(
                request_id,
                retrieved_count,
                evidence_count,
                response.status,
                started,
            )
            return response
        except Exception as exc:
            logger.warning(
                "QA request failed request_id=%s error=%s",
                request_id,
                type(exc).__name__,
            )
            raise

    async def answer_from_evidence(
        self,
        question: str,
        evidence: list[EvidenceChunk],
        retrieved_count: int,
        top_k: int,
    ) -> QAResponse:
        """复用第四阶段的“证据 -> LLM -> 服务端引用”逻辑，不再检索。"""
        answer = (await self._llm.answer(question, evidence)).strip()
        if not answer:
            raise LLMUnavailableError("LLM 返回空回答")

        evidence_count = len(evidence)
        if answer == QA_REFUSAL_ANSWER:
            return self._refused(
                question,
                retrieved_count=retrieved_count,
                evidence_count=evidence_count,
                top_k=top_k,
                reason=LLM_REFUSAL_REASON,
            )

        return QAResponse(
            status="answered",
            answer=answer,
            citations=self._citations.build(evidence),
            retrieval=QARetrievalInfo(
                query=question,
                retrieved_count=retrieved_count,
                evidence_count=evidence_count,
                top_k=top_k,
            ),
            refusal_reason=None,
        )

    def select_evidence(
        self,
        results: list[RetrievalResult],
        max_context_chars: int | None = None,
    ) -> list[EvidenceChunk]:
        """按第四阶段阈值筛选证据，可覆盖上下文长度上限。"""
        evidence: list[EvidenceChunk] = []
        remaining_chars = (
            self._settings.max_context_chars
            if max_context_chars is None
            else max_context_chars
        )

        for result in results:
            if result.score < self._settings.min_retrieval_score:
                continue
            if remaining_chars <= 0:
                break
            text = result.text[:remaining_chars]
            if not text:
                break
            evidence.append(
                EvidenceChunk(
                    chunk_id=result.chunk_id,
                    document_id=result.document_id,
                    original_filename=result.original_filename,
                    page_number=result.page_number,
                    chunk_index=result.chunk_index,
                    text=text,
                    char_start=result.char_start,
                    char_end=result.char_end,
                    score=result.score,
                )
            )
            remaining_chars -= len(text)

        return evidence

    def _refused(
        self,
        query: str,
        retrieved_count: int,
        evidence_count: int,
        top_k: int,
        reason: str,
    ) -> QAResponse:
        return QAResponse(
            status="refused",
            answer=QA_REFUSAL_ANSWER,
            citations=[],
            retrieval=QARetrievalInfo(
                query=query,
                retrieved_count=retrieved_count,
                evidence_count=evidence_count,
                top_k=top_k,
            ),
            refusal_reason=reason,
        )

    @staticmethod
    def _log_result(
        request_id: str,
        retrieved_count: int,
        evidence_count: int,
        status: str,
        started: float,
    ) -> None:
        logger.info(
            "QA completed request_id=%s retrieved=%d evidence=%d status=%s duration_ms=%.0f",
            request_id,
            retrieved_count,
            evidence_count,
            status,
            (time.perf_counter() - started) * 1000,
        )
