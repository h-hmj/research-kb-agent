"""第七阶段：SSE 流式 Agent、事件顺序和错误处理测试。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from research_agent.core.config import Settings
from research_agent.core.exceptions import LLMUnavailableError
from research_agent.main import create_app
from tests.test_qa import (
    FakeEmbeddingService,
    UnavailableEmbeddingService,
    index_document,
    upload_pdf,
)

pytestmark = pytest.mark.anyio

STREAM_URL = "/api/v1/agent/ask/stream"


class FakeStreamingLLM:
    def __init__(
        self,
        tokens: list[str] | None = None,
        *,
        stream_available: bool = True,
        rewrite_available: bool = True,
        rewrite_text: str = "beta",
    ) -> None:
        self.tokens = tokens or ["根据资料，", "空白对照用于排除干扰。"]
        self.stream_available = stream_available
        self.rewrite_available = rewrite_available
        self.rewrite_text = rewrite_text
        self.stream_calls: list[str] = []
        self.rewrite_calls: list[str] = []

    async def stream_answer(self, question: str, evidence: list) -> AsyncIterator[str]:
        self.stream_calls.append(question)
        if not self.stream_available:
            raise LLMUnavailableError("stream unavailable")
        for token in self.tokens:
            yield token

    async def answer(self, question: str, evidence: list) -> str:
        return "".join(self.tokens)

    async def rewrite(self, question: str) -> str:
        self.rewrite_calls.append(question)
        if not self.rewrite_available:
            raise LLMUnavailableError("rewrite unavailable")
        return self.rewrite_text

    async def complete(self, messages: list[dict[str, str]]) -> str:
        return "{}"


@dataclass
class StreamContext:
    app: Any
    client: httpx.AsyncClient
    settings: Settings
    llm: FakeStreamingLLM


@asynccontextmanager
async def stream_client(
    settings: Settings,
    embedding,
    llm: FakeStreamingLLM,
) -> AsyncIterator[StreamContext]:
    app = create_app(
        settings,
        embedding_service=embedding,
        llm_service=llm,
    )
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield StreamContext(
                app=app,
                client=client,
                settings=settings,
                llm=llm,
            )


@pytest.fixture
async def stream(test_settings: Settings) -> AsyncIterator[StreamContext]:
    settings = test_settings.model_copy(
        update={"stream_heartbeat_seconds": 0}
    )
    llm = FakeStreamingLLM()
    async with stream_client(
        settings,
        FakeEmbeddingService(),
        llm,
    ) as context:
        yield context


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in text.strip().split("\n\n"):
        if not block.strip() or block.lstrip().startswith(":"):
            continue
        event_name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if event_name and data is not None:
            events.append((event_name, data))
    return events


async def stream_ask(
    client: httpx.AsyncClient,
    question: str,
    **kwargs,
) -> tuple[httpx.Response, list[tuple[str, dict]]]:
    response = await client.post(
        STREAM_URL,
        json={"question": question, **kwargs},
    )
    assert response.status_code == 200, response.text
    return response, parse_sse(response.text)


def assert_sse_types(events: list[tuple[str, dict]]) -> None:
    assert all(isinstance(data, dict) for _, data in events)
    assert all(event in {"workflow", "token", "citations", "final", "error"} for event, _ in events)


async def test_stream_headers_and_request_id(stream: StreamContext) -> None:
    response, events = await stream_ask(stream.client, "无索引问题")

    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["x-request-id"]
    assert events[0][0] == "workflow"
    assert events[-1][0] == "final"
    assert_sse_types(events)


async def test_initial_evidence_streams_tokens_and_citations(
    stream: StreamContext,
) -> None:
    document = await upload_pdf(stream.client, ["alpha alpha 证据。"])
    await index_document(stream.client, document["id"])

    _, events = await stream_ask(stream.client, "alpha")
    names = [name for name, _ in events]
    workflow_steps = [
        data["step"] for name, data in events if name == "workflow"
    ]
    tokens = "".join(
        data["content"] for name, data in events if name == "token"
    )
    citations = [data for name, data in events if name == "citations"]
    finals = [data for name, data in events if name == "final"]

    assert "rewrite_query" not in workflow_steps
    assert "retrieve_retry" not in workflow_steps
    assert tokens == "".join(stream.llm.tokens)
    assert len(citations) == 1
    assert len(finals) == 1
    assert finals[0]["status"] == "answered"
    assert len(stream.llm.stream_calls) == 1
    assert names.index("citations") < names.index("final")
    assert_sse_types(events)


async def test_rewrite_then_retry_streams_citations(
    stream: StreamContext,
) -> None:
    document = await upload_pdf(stream.client, ["beta beta 二次证据。"])
    await index_document(stream.client, document["id"])

    _, events = await stream_ask(stream.client, "alpha")
    workflow_steps = [
        data["step"] for name, data in events if name == "workflow"
    ]
    final = [data for name, data in events if name == "final"][0]
    citations = [data for name, data in events if name == "citations"][0]

    assert "rewrite_query" in workflow_steps
    assert "retrieve_retry" in workflow_steps
    assert final["status"] == "answered"
    assert citations["citations"][0]["document_id"] == document["id"]
    assert "beta" in citations["citations"][0]["text"]
    assert len(stream.llm.rewrite_calls) == 1


async def test_both_retrievals_insufficient_refuses_without_tokens(
    stream: StreamContext,
) -> None:
    document = await upload_pdf(stream.client, ["beta beta"])
    await index_document(stream.client, document["id"])
    stream.llm.rewrite_text = "gamma"

    _, events = await stream_ask(stream.client, "alpha")
    names = [name for name, _ in events]
    final = [data for name, data in events if name == "final"][0]

    assert "token" not in names
    assert "citations" not in names
    assert final["status"] == "refused"
    assert final["refusal_reason"] == (
        "经过问题改写和二次检索后，仍未检索到足够相关的文档证据。"
    )
    assert stream.llm.stream_calls == []


async def test_disabled_rewrite_refuses_without_retry(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(
        update={
            "enable_query_rewrite": False,
            "stream_heartbeat_seconds": 0,
        }
    )
    llm = FakeStreamingLLM()
    async with stream_client(
        settings,
        FakeEmbeddingService(),
        llm,
    ) as context:
        document = await upload_pdf(context.client, ["beta beta"])
        await index_document(context.client, document["id"])
        _, events = await stream_ask(context.client, "alpha")
        steps = [data["step"] for name, data in events if name == "workflow"]
        final = [data for name, data in events if name == "final"][0]

        assert "rewrite_query" not in steps
        assert "retrieve_retry" not in steps
        assert final["status"] == "refused"
        assert llm.rewrite_calls == []
        assert llm.stream_calls == []


async def test_rewrite_failure_refuses_without_error(
    stream: StreamContext,
) -> None:
    document = await upload_pdf(stream.client, ["beta beta"])
    await index_document(stream.client, document["id"])
    stream.llm.rewrite_available = False

    _, events = await stream_ask(stream.client, "alpha")
    names = [name for name, _ in events]
    final = [data for name, data in events if name == "final"][0]

    assert "error" not in names
    assert "retrieve_retry" not in [
        data["step"] for name, data in events if name == "workflow"
    ]
    assert final["status"] == "refused"
    assert final["refusal_reason"] == (
        "初次检索未找到足够证据，且无法完成问题改写后的二次检索。"
    )


async def test_answer_llm_unavailable_sends_error_without_final(
    stream: StreamContext,
) -> None:
    document = await upload_pdf(stream.client, ["alpha alpha"])
    await index_document(stream.client, document["id"])
    stream.llm.stream_available = False

    _, events = await stream_ask(stream.client, "alpha")
    names = [name for name, _ in events]
    errors = [data for name, data in events if name == "error"]

    assert len(errors) == 1
    assert errors[0]["code"] == "llm_unavailable"
    assert "citations" not in names
    assert "final" not in names


async def test_embedding_unavailable_sends_safe_sse_error(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(
        update={"stream_heartbeat_seconds": 0}
    )
    llm = FakeStreamingLLM()
    async with stream_client(
        settings,
        UnavailableEmbeddingService(),
        llm,
    ) as context:
        response, events = await stream_ask(context.client, "alpha")
        errors = [data for name, data in events if name == "error"]

        assert response.status_code == 200
        assert len(errors) == 1
        assert errors[0]["code"] == "embedding_unavailable"
        assert "error" in [name for name, _ in events]
        assert "final" not in [name for name, _ in events]


async def test_empty_stream_chunks_are_not_sent(
    stream: StreamContext,
) -> None:
    document = await upload_pdf(stream.client, ["alpha alpha"])
    await index_document(stream.client, document["id"])
    stream.llm.tokens = ["", "有效", "", "答案"]

    _, events = await stream_ask(stream.client, "alpha")
    tokens = [data["content"] for name, data in events if name == "token"]

    assert tokens == ["有效", "答案"]


async def test_stream_workflow_does_not_expose_sensitive_fields(
    stream: StreamContext,
) -> None:
    document = await upload_pdf(stream.client, ["alpha alpha"])
    await index_document(stream.client, document["id"])

    _, events = await stream_ask(stream.client, "alpha")
    serialized = json.dumps(events, ensure_ascii=False)

    for forbidden in (
        "system_prompt",
        "messages",
        "chain_of_thought",
        "api_key",
        "C:\\\\",
        "D:\\\\",
        "Bearer ",
    ):
        assert forbidden not in serialized
    final = [data for name, data in events if name == "final"][0]
    assert final["metrics"]["total_duration_ms"] >= 0
    assert final["metrics"]["retrieval_duration_ms"] >= 0
    assert final["metrics"]["llm_duration_ms"] >= 0
