"""Agent SSE 流式服务：复用同一个 LangGraph，只增加事件出口。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator

from ..core.config import Settings
from ..core.exceptions import (
    EmbeddingModelUnavailableError,
    LLMUnavailableError,
)
from ..core.request_context import reset_request_id, set_request_id
from .agent_service import AgentService
from .embedding_service import EMBEDDING_UNAVAILABLE_DETAIL
from .llm_service import LLM_UNAVAILABLE_DETAIL
from .metrics_service import MetricsService

logger = logging.getLogger(__name__)


def sse_event(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


def _error_payload(request_id: str, code: str, message: str) -> dict:
    return {
        "request_id": request_id,
        "code": code,
        "message": message,
    }


class QueueEventSink:
    def __init__(self, queue: asyncio.Queue) -> None:
        self._queue = queue

    async def emit(self, event: str, data: dict) -> None:
        await self._queue.put((event, data))


class AgentStreamService:
    def __init__(
        self,
        settings: Settings,
        agent_service: AgentService,
        metrics: MetricsService,
    ) -> None:
        self._settings = settings
        self._agent = agent_service
        self._metrics = metrics

    def _record_error(self, request_id: str, code: str, started: float) -> None:
        duration_ms = (time.perf_counter() - started) * 1000
        self._metrics.record_agent_stream_result("error", duration_ms)
        logger.warning(
            "agent_stream_error code=%s duration_ms=%.0f",
            code,
            duration_ms,
        )

    async def stream(
        self,
        question: str,
        top_k: int | None,
        document_ids: list[str] | None,
        enable_rewrite: bool,
        request_id: str,
    ) -> AsyncIterator[str]:
        """执行 Agent 并把安全事件编码为 SSE。"""
        token = set_request_id(request_id)
        started = time.perf_counter()
        self._metrics.record_agent_stream_start()
        logger.info("agent_stream_started")
        queue: asyncio.Queue = asyncio.Queue()
        sink = QueueEventSink(queue)
        task: asyncio.Task | None = None
        get_task: asyncio.Task | None = None
        try:
            yield sse_event(
                "workflow",
                {
                    "request_id": request_id,
                    "step": "request_received",
                    "message": "已收到请求",
                },
            )
            state = self._agent.build_initial_state(
                question,
                top_k,
                document_ids,
                enable_rewrite,
                request_id=request_id,
                event_sink=sink,
            )
            task = asyncio.create_task(self._agent.run_state(state))
            while True:
                if task.done() and queue.empty():
                    break
                get_task = asyncio.create_task(queue.get())
                timeout = self._settings.stream_heartbeat_seconds or None
                done, _ = await asyncio.wait(
                    {get_task, task},
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if get_task in done:
                    event, data = get_task.result()
                    yield sse_event(event, data)
                    continue
                get_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await get_task
                if task.done():
                    break
                yield ": heartbeat\n\n"

            final_state = await task
            status = final_state.get("status")
            if status not in {"answered", "refused"}:
                raise RuntimeError("Agent 流式工作流未产生最终状态")

            yield sse_event(
                "workflow",
                {
                    "request_id": request_id,
                    "step": "completed",
                    "message": "工作流完成",
                },
            )
            workflow = self._agent.build_workflow(final_state)
            total_ms = (time.perf_counter() - started) * 1000
            final_data = {
                "request_id": request_id,
                "status": status,
                "refusal_reason": final_state.get("refusal_reason"),
                "workflow": workflow.model_dump(),
                "metrics": {
                    "total_duration_ms": round(total_ms, 2),
                    "retrieval_duration_ms": round(
                        final_state.get("retrieval_duration_ms", 0.0),
                        2,
                    ),
                    "llm_duration_ms": round(
                        final_state.get("llm_duration_ms", 0.0),
                        2,
                    ),
                },
            }
            yield sse_event("final", final_data)
            self._metrics.record_agent_stream_result(status, total_ms)
            if status == "answered":
                logger.info(
                    "agent_stream_completed duration_ms=%.0f",
                    total_ms,
                )
            else:
                logger.info(
                    "agent_stream_refused duration_ms=%.0f",
                    total_ms,
                )
        except asyncio.CancelledError:
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            logger.info(
                "client_disconnected duration_ms=%.0f",
                (time.perf_counter() - started) * 1000,
            )
            raise
        except EmbeddingModelUnavailableError as exc:
            self._record_error(request_id, "embedding_unavailable", started)
            yield sse_event(
                "error",
                _error_payload(
                    request_id,
                    "embedding_unavailable",
                    EMBEDDING_UNAVAILABLE_DETAIL,
                ),
            )
        except LLMUnavailableError as exc:
            self._record_error(request_id, "llm_unavailable", started)
            yield sse_event(
                "error",
                _error_payload(
                    request_id,
                    "llm_unavailable",
                    LLM_UNAVAILABLE_DETAIL,
                ),
            )
        except Exception as exc:
            self._record_error(request_id, "internal_error", started)
            yield sse_event(
                "error",
                _error_payload(
                    request_id,
                    "internal_error",
                    "流式处理失败，请稍后重试。",
                ),
            )
        finally:
            if get_task is not None and not get_task.done():
                get_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await get_task
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            reset_request_id(token)
