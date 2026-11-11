"""受控单轮问答编排：检索、证据判断、LLM 或拒答、引用。

三条原则：
- 证据门槛前置：证据不足时直接拒答，不调用回答 LLM（省成本、避免幻觉）；
- 引用只由服务端从实际证据生成，模型输出不参与引用构造；
- 两种拒答来源分开记录：检索侧无证据 vs 模型侧判定证据不足。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
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

# 检索阶段就判定证据不足：请求不会进入 LLM 调用。
NO_EVIDENCE_REASON = "未检索到足够相关的文档证据。"
# 证据已过阈值，但模型仍返回固定拒答话术时使用。
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
        # 请求未指定 top_k 时回落到配置默认值（接口层已保证 top_k 为正数）。
        effective_top_k = top_k or self._settings.qa_top_k
        query = question.strip()  #去掉首尾空格和换行。

        try:
            retrieved = self._retrieval.search(
                query=query,
                top_k=effective_top_k,
                document_ids=document_ids,
            )
            retrieved_count = len(retrieved.results)
            # 检索条数 != 可用证据数：这里会再按分数阈值和上下文预算筛一遍。
            evidence = self.select_evidence(retrieved.results)
            evidence_count = len(evidence)

            # 证据不足时直接确定性拒答，完全不调用回答 LLM。
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
        """复用第四阶段的“证据 -> LLM -> 服务端引用”逻辑，不再检索。

        Agent 图在二次检索后会直接调用本方法，因此这里刻意不含检索逻辑。
        """
        # 统一去掉首尾空白，避免把纯换行当成有效回答写进响应。
        answer = (await self._llm.answer(question, evidence)).strip()
        return self._response_from_answer(
            question,
            answer,
            evidence,
            retrieved_count,
            top_k,
        )

    async def answer_from_evidence_stream(
        self,
        question: str,
        evidence: list[EvidenceChunk],
        retrieved_count: int,
        top_k: int,
        emit_token: Callable[[str], Awaitable[None]],
    ) -> QAResponse:
        """流式回答；只把模型增量文本交给调用方，不泄露内部元数据。"""
        # 边转发增量 token，边在本地累积完整回答，
        # 这样流结束后仍能复用同步路径的校验与引用构造逻辑。
        tokens: list[str] = []
        async for token in self._llm.stream_answer(question, evidence):
            if not token:
                continue
            tokens.append(token)
            await emit_token(token)
        answer = "".join(tokens).strip()
        return self._response_from_answer(
            question,
            answer,
            evidence,
            retrieved_count,
            top_k,
        )

    def _response_from_answer(
        self,
        question: str,
        answer: str,
        evidence: list[EvidenceChunk],
        retrieved_count: int,
        top_k: int,
    ) -> QAResponse:
        # 空回答视为模型服务异常，由上层转成 503，而不是伪造一个正常答案。
        if not answer:
            raise LLMUnavailableError("LLM 返回空回答")
        evidence_count = len(evidence)
        # 模型返回与固定拒答话术完全一致时按拒答处理，并丢弃引用。
        # 这里用精确匹配，避免正文中恰好出现该句话的正常回答被误判。
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
            # 引用来自实际送入 LLM 的证据，而不是解析模型输出。
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
        """按第四阶段阈值筛选证据，可覆盖上下文长度上限。

        输入的 results 预期已按相关度降序排列（由检索服务保证），
        本方法只做“阈值过滤 + 预算截断”，不做重排。
        """
        evidence: list[EvidenceChunk] = []
        # 上下文预算是字符数上限：None 表示使用全局配置，
        # Agent 图会传入更小的 agent_max_context_chars。
        remaining_chars = (
            self._settings.max_context_chars
            if max_context_chars is None
            else max_context_chars
        )

        for result in results:
            # 分数低于阈值的结果直接丢弃，也不占用上下文预算。
            if result.score < self._settings.min_retrieval_score:
                continue
            # 预算耗尽就停止（不是 continue）：后面的证据已无处安放。
            if remaining_chars <= 0:
                break
            # 最后一条证据可能只放得下一部分，按剩余预算截取前缀。
            text = result.text[:remaining_chars]
            if not text:
                break
            # char_start/char_end 保留 chunk 在页面中的原始偏移，供前端定位；
            # 注意 text 被截断时，偏移描述的仍是完整 chunk 的范围。
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
            # 按实际放入的字符数扣减预算，而不是按 chunk 原长度。
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
        """统一构造拒答响应：固定话术 + 空引用，并保留检索侧统计。"""
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
        # 只记录计数与耗时，不打印问题原文和证据内容，避免日志泄露文档内容。
        logger.info(
            "QA completed request_id=%s retrieved=%d evidence=%d status=%s duration_ms=%.0f",
            request_id,
            retrieved_count,
            evidence_count,
            status,
            (time.perf_counter() - started) * 1000,
        )
