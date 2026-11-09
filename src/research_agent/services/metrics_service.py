"""进程内基础指标；不持久化、不对外发起任何请求。"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import numpy as np

from ..schemas.qa import EvidenceChunk
from .llm_service import LLMService

logger = logging.getLogger(__name__)


class MetricsService:
    """线程安全的进程内计数器，重启后归零。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests_total = 0
        self._requests_by_path: dict[str, int] = {}
        self._responses_by_status: dict[str, int] = {}
        self._agent_stream_requests_total = 0
        self._agent_stream_answered_total = 0
        self._agent_stream_refused_total = 0
        self._agent_stream_errors_total = 0
        self._tool_requests_total = 0
        self._llm_calls_total = 0
        self._llm_stream_calls_total = 0
        self._embedding_errors_total = 0
        self._llm_errors_total = 0
        self._total_request_duration_ms = 0.0
        self._total_agent_stream_duration_ms = 0.0

    def record_request(self, path: str, status_code: int, duration_ms: float) -> None:
        with self._lock:
            self._requests_total += 1
            self._requests_by_path[path] = (
                self._requests_by_path.get(path, 0) + 1
            )
            status = str(status_code)
            self._responses_by_status[status] = (
                self._responses_by_status.get(status, 0) + 1
            )
            self._total_request_duration_ms += max(0.0, duration_ms)

    def record_agent_stream_start(self) -> None:
        with self._lock:
            self._agent_stream_requests_total += 1

    def record_agent_stream_result(self, status: str, duration_ms: float) -> None:
        with self._lock:
            if status == "answered":
                self._agent_stream_answered_total += 1
            elif status == "refused":
                self._agent_stream_refused_total += 1
            else:
                self._agent_stream_errors_total += 1
            self._total_agent_stream_duration_ms += max(0.0, duration_ms)

    def record_tool_request(self) -> None:
        with self._lock:
            self._tool_requests_total += 1

    def record_llm_call(self, *, stream: bool = False) -> None:
        with self._lock:
            if stream:
                self._llm_stream_calls_total += 1
            else:
                self._llm_calls_total += 1

    def record_llm_error(self) -> None:
        with self._lock:
            self._llm_errors_total += 1

    def record_embedding_error(self) -> None:
        with self._lock:
            self._embedding_errors_total += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            stream_requests = self._agent_stream_requests_total
            average = (
                self._total_agent_stream_duration_ms / stream_requests
                if stream_requests
                else 0.0
            )
            return {
                "requests_total": self._requests_total,
                "requests_by_path": dict(self._requests_by_path),
                "responses_by_status": dict(self._responses_by_status),
                "agent_stream": {
                    "requests_total": self._agent_stream_requests_total,
                    "answered_total": self._agent_stream_answered_total,
                    "refused_total": self._agent_stream_refused_total,
                    "errors_total": self._agent_stream_errors_total,
                    "average_duration_ms": round(average, 2),
                },
                "tool_requests_total": self._tool_requests_total,
                "llm": {
                    "calls_total": self._llm_calls_total,
                    "stream_calls_total": self._llm_stream_calls_total,
                    "errors_total": self._llm_errors_total,
                },
                "embedding_errors_total": self._embedding_errors_total,
                "total_request_duration_ms": round(
                    self._total_request_duration_ms,
                    2,
                ),
                "total_agent_stream_duration_ms": round(
                    self._total_agent_stream_duration_ms,
                    2,
                ),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }


class MeteredEmbeddingService:
    """为任意 Embedding 实现增加错误计数。"""

    def __init__(self, inner, metrics: MetricsService) -> None:
        self._inner = inner
        self._metrics = metrics

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        try:
            return self._inner.embed_texts(texts)
        except Exception:
            self._metrics.record_embedding_error()
            raise

    def embed_query(self, query: str) -> np.ndarray:
        try:
            return self._inner.embed_query(query)
        except Exception:
            self._metrics.record_embedding_error()
            raise


class MeteredLLMService:
    """包装 LLM，使所有调用与错误进入进程内指标和安全日志。"""

    def __init__(self, inner: LLMService, metrics: MetricsService) -> None:
        self._inner = inner
        self._metrics = metrics

    async def answer(
        self,
        question: str,
        evidence: list[EvidenceChunk],
    ) -> str:
        self._metrics.record_llm_call(stream=False)
        try:
            return await self._inner.answer(question, evidence)
        except Exception:
            self._metrics.record_llm_error()
            raise

    async def rewrite(self, question: str) -> str:
        self._metrics.record_llm_call(stream=False)
        try:
            return await self._inner.rewrite(question)
        except Exception:
            self._metrics.record_llm_error()
            raise

    async def complete(self, messages: list[dict[str, str]]) -> str:
        self._metrics.record_llm_call(stream=False)
        try:
            return await self._inner.complete(messages)
        except Exception:
            self._metrics.record_llm_error()
            raise

    async def stream_answer(
        self,
        question: str,
        evidence: list[EvidenceChunk],
    ) -> AsyncIterator[str]:
        self._metrics.record_llm_call(stream=True)
        started = time.perf_counter()
        logger.info("llm_stream_started")
        try:
            async for token in self._inner.stream_answer(question, evidence):
                yield token
        except Exception as exc:
            self._metrics.record_llm_error()
            logger.warning(
                "llm_stream_failed error=%s duration_ms=%.0f",
                type(exc).__name__,
                (time.perf_counter() - started) * 1000,
            )
            raise
        logger.info(
            "llm_stream_completed duration_ms=%.0f",
            (time.perf_counter() - started) * 1000,
        )
