"""第五阶段：LangGraph 问题改写、二次检索与拒答测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import httpx
import pytest
from pydantic import ValidationError

from research_agent.agents.state import SAFE_WORKFLOW_STEPS
from research_agent.core.config import Settings
from research_agent.core.exceptions import LLMUnavailableError
from research_agent.main import create_app
from research_agent.services.llm_service import QA_REFUSAL_ANSWER
from tests.test_qa import (
    FakeEmbeddingService,
    UnavailableEmbeddingService,
    index_document,
    upload_pdf,
)

pytestmark = pytest.mark.anyio

AGENT_URL = "/api/v1/agent/ask"
DEFAULT_ANSWER = "根据证据，改写后的查询检索到了相关实验记录。"


@dataclass
class AgentFakeLLM:
    answer_text: str = DEFAULT_ANSWER
    rewrite_text: str = "beta"
    answer_available: bool = True
    rewrite_available: bool = True
    answer_calls: list[tuple[str, list]] = field(default_factory=list)
    rewrite_calls: list[str] = field(default_factory=list)

    async def answer(self, question: str, evidence: list) -> str:
        self.answer_calls.append((question, evidence))
        if not self.answer_available:
            raise LLMUnavailableError("answer unavailable")
        return self.answer_text

    async def rewrite(self, question: str) -> str:
        self.rewrite_calls.append(question)
        if not self.rewrite_available:
            raise LLMUnavailableError("rewrite unavailable")
        return self.rewrite_text


@dataclass
class AgentContext:
    app: object
    client: httpx.AsyncClient
    settings: Settings
    llm: AgentFakeLLM


@asynccontextmanager
async def agent_client(
    settings: Settings,
    embedding,
    llm: AgentFakeLLM,
) -> AsyncIterator[AgentContext]:
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
            yield AgentContext(
                app=app,
                client=client,
                settings=settings,
                llm=llm,
            )


@pytest.fixture
async def agent(test_settings: Settings) -> AsyncIterator[AgentContext]:
    llm = AgentFakeLLM()
    async with agent_client(
        test_settings,
        FakeEmbeddingService(),
        llm,
    ) as context:
        yield context


async def ask(
    client: httpx.AsyncClient,
    question: str,
    **kwargs,
) -> dict:
    response = await client.post(
        AGENT_URL,
        json={"question": question, **kwargs},
    )
    assert response.status_code == 200, response.text
    return response.json()


def assert_safe_steps(payload: dict) -> None:
    steps = payload["workflow"]["steps"]
    assert set(steps) <= SAFE_WORKFLOW_STEPS
    assert "model_prompt" not in steps
    assert "chain_of_thought" not in steps


def test_settings_reject_rewrite_attempts_above_one() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_query_rewrite_attempts=2)


async def test_graph_is_real_compiled_langgraph(
    test_settings: Settings,
) -> None:
    app = create_app(
        test_settings,
        embedding_service=FakeEmbeddingService(),
        llm_service=AgentFakeLLM(),
    )
    graph = app.state.agent_service.graph

    assert "CompiledStateGraph" in type(graph).__name__
    nodes = set(graph.get_graph().nodes)
    assert {
        "retrieve_initial",
        "assess_initial_evidence",
        "rewrite_query",
        "retrieve_retry",
        "assess_retry_evidence",
        "answer_with_evidence",
        "refuse",
    } <= nodes


async def test_initial_evidence_answers_without_rewrite(
    agent: AgentContext,
) -> None:
    document = await upload_pdf(agent.client, ["alpha alpha 证据。"])
    await index_document(agent.client, document["id"])

    payload = await ask(agent.client, "alpha")

    assert payload["status"] == "answered"
    assert payload["citations"]
    assert payload["workflow"]["rewrite_attempted"] is False
    assert payload["workflow"]["rewrite_count"] == 0
    assert payload["workflow"]["final_query"] == "alpha"
    assert "rewrite_query" not in payload["workflow"]["steps"]
    assert "retrieve_retry" not in payload["workflow"]["steps"]
    assert payload["workflow"]["initial_retrieval_count"] >= 1
    assert payload["workflow"]["final_retrieval_count"] == 0
    assert len(agent.llm.answer_calls) == 1
    assert agent.llm.rewrite_calls == []
    assert_safe_steps(payload)


async def test_rewrite_once_then_retry_answers(
    agent: AgentContext,
) -> None:
    document = await upload_pdf(agent.client, ["beta beta 二次证据。"])
    await index_document(agent.client, document["id"])
    agent.llm.rewrite_text = "beta"

    payload = await ask(agent.client, "alpha", top_k=1)

    assert payload["status"] == "answered"
    assert payload["workflow"]["rewrite_attempted"] is True
    assert payload["workflow"]["rewrite_count"] == 1
    assert payload["workflow"]["rewrite_changed"] is True
    assert payload["workflow"]["final_query"] == "beta"
    assert payload["workflow"]["initial_retrieval_count"] <= 1
    assert payload["workflow"]["final_retrieval_count"] <= 1
    assert payload["workflow"]["steps"] == [
        "retrieve_initial",
        "assess_initial_evidence",
        "rewrite_query",
        "retrieve_retry",
        "assess_retry_evidence",
        "answer",
    ]
    assert payload["citations"][0]["document_id"] == document["id"]
    assert "beta" in payload["citations"][0]["text"]
    assert len(agent.llm.rewrite_calls) == 1
    assert len(agent.llm.answer_calls) == 1
    assert_safe_steps(payload)


async def test_both_retrievals_insufficient_refuses(
    agent: AgentContext,
) -> None:
    document = await upload_pdf(agent.client, ["beta beta 只有这些。"])
    await index_document(agent.client, document["id"])
    agent.llm.rewrite_text = "gamma"

    payload = await ask(agent.client, "alpha")

    assert payload["status"] == "refused"
    assert payload["answer"] == QA_REFUSAL_ANSWER
    assert payload["citations"] == []
    assert payload["workflow"]["rewrite_count"] == 1
    assert payload["workflow"]["final_query"] == "gamma"
    assert payload["workflow"]["steps"].count("retrieve_retry") == 1
    assert payload["workflow"]["steps"][-1] == "refuse"
    assert payload["refusal_reason"] == (
        "经过问题改写和二次检索后，仍未检索到足够相关的文档证据。"
    )
    assert agent.llm.answer_calls == []
    assert_safe_steps(payload)


async def test_global_rewrite_disabled_refuses_without_rewrite(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(
        update={"enable_query_rewrite": False}
    )
    llm = AgentFakeLLM()
    async with agent_client(
        settings,
        FakeEmbeddingService(),
        llm,
    ) as context:
        document = await upload_pdf(context.client, ["beta beta"])
        await index_document(context.client, document["id"])

        payload = await ask(context.client, "alpha")

        assert payload["status"] == "refused"
        assert payload["workflow"]["rewrite_attempted"] is False
        assert payload["workflow"]["rewrite_count"] == 0
        assert payload["workflow"]["final_query"] == "alpha"
        assert "rewrite_query" not in payload["workflow"]["steps"]
        assert "retrieve_retry" not in payload["workflow"]["steps"]
        assert payload["refusal_reason"] == "未检索到足够相关的文档证据。"
        assert llm.rewrite_calls == []
        assert llm.answer_calls == []


async def test_max_rewrite_attempts_zero_prevents_rewrite(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(
        update={"max_query_rewrite_attempts": 0}
    )
    llm = AgentFakeLLM()
    async with agent_client(
        settings,
        FakeEmbeddingService(),
        llm,
    ) as context:
        document = await upload_pdf(context.client, ["beta beta"])
        await index_document(context.client, document["id"])

        payload = await ask(context.client, "alpha")

        assert payload["status"] == "refused"
        assert payload["workflow"]["rewrite_attempted"] is False
        assert payload["workflow"]["rewrite_count"] == 0
        assert "rewrite_query" not in payload["workflow"]["steps"]
        assert "retrieve_retry" not in payload["workflow"]["steps"]
        assert llm.rewrite_calls == []


async def test_request_can_disable_rewrite(agent: AgentContext) -> None:
    document = await upload_pdf(agent.client, ["beta beta"])
    await index_document(agent.client, document["id"])

    payload = await ask(agent.client, "alpha", enable_rewrite=False)

    assert payload["status"] == "refused"
    assert payload["workflow"]["rewrite_attempted"] is False
    assert payload["workflow"]["rewrite_count"] == 0
    assert "rewrite_query" not in payload["workflow"]["steps"]
    assert "retrieve_retry" not in payload["workflow"]["steps"]
    assert agent.llm.rewrite_calls == []
    assert agent.llm.answer_calls == []


async def test_rewrite_llm_unavailable_refuses_without_retry(
    agent: AgentContext,
) -> None:
    document = await upload_pdf(agent.client, ["beta beta"])
    await index_document(agent.client, document["id"])
    agent.llm.rewrite_available = False

    payload = await ask(agent.client, "alpha")

    assert payload["status"] == "refused"
    assert payload["citations"] == []
    assert payload["workflow"]["rewrite_attempted"] is True
    assert payload["workflow"]["rewrite_count"] == 1
    assert "retrieve_retry" not in payload["workflow"]["steps"]
    assert payload["workflow"]["final_retrieval_count"] == 0
    assert payload["refusal_reason"] == (
        "初次检索未找到足够证据，且无法完成问题改写后的二次检索。"
    )
    assert len(agent.llm.rewrite_calls) == 1
    assert agent.llm.answer_calls == []
    assert_safe_steps(payload)


@pytest.mark.parametrize(
    "bad_rewrite",
    [
        "",
        "```\nbeta\n```",
        '{"query": "beta"}',
        QA_REFUSAL_ANSWER,
        "1. beta",
        '"beta"',
        "x" * 501,
    ],
)
async def test_invalid_rewrite_output_refuses_without_retry(
    agent: AgentContext,
    bad_rewrite: str,
) -> None:
    document = await upload_pdf(agent.client, ["beta beta"])
    await index_document(agent.client, document["id"])
    agent.llm.rewrite_text = bad_rewrite

    payload = await ask(agent.client, "alpha")

    assert payload["status"] == "refused"
    assert payload["workflow"]["rewrite_attempted"] is True
    assert "retrieve_retry" not in payload["workflow"]["steps"]
    assert payload["workflow"]["final_retrieval_count"] == 0
    assert agent.llm.answer_calls == []


async def test_trace_disabled_returns_no_steps(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"agent_trace_enabled": False})
    llm = AgentFakeLLM()
    async with agent_client(
        settings,
        FakeEmbeddingService(),
        llm,
    ) as context:
        document = await upload_pdf(context.client, ["alpha alpha"])
        await index_document(context.client, document["id"])

        payload = await ask(context.client, "alpha")

        assert payload["status"] == "answered"
        assert payload["workflow"]["steps"] == []
        assert payload["workflow"]["initial_retrieval_count"] >= 1


async def test_unchanged_rewrite_is_marked(
    agent: AgentContext,
) -> None:
    document = await upload_pdf(agent.client, ["beta beta"])
    await index_document(agent.client, document["id"])
    agent.llm.rewrite_text = "alpha"

    payload = await ask(agent.client, "alpha")

    assert payload["status"] == "refused"
    assert payload["workflow"]["rewrite_attempted"] is True
    assert payload["workflow"]["rewrite_changed"] is False
    assert payload["workflow"]["rewrite_count"] == 1
    assert "retrieve_retry" in payload["workflow"]["steps"]


async def test_embedding_unavailable_returns_503(
    test_settings: Settings,
) -> None:
    llm = AgentFakeLLM()
    async with agent_client(
        test_settings,
        UnavailableEmbeddingService(),
        llm,
    ) as context:
        response = await context.client.post(
            AGENT_URL,
            json={"question": "alpha"},
        )

        assert response.status_code == 503
        assert "Embedding" in response.json()["detail"]
        assert llm.rewrite_calls == []
        assert llm.answer_calls == []


async def test_answer_llm_unavailable_returns_503(
    agent: AgentContext,
) -> None:
    document = await upload_pdf(agent.client, ["alpha alpha 证据。"])
    await index_document(agent.client, document["id"])
    agent.llm.answer_available = False

    response = await agent.client.post(
        AGENT_URL,
        json={"question": "alpha"},
    )

    assert response.status_code == 503
    assert response.json()["detail"].startswith("本地 LLM 服务不可用")
    assert agent.llm.rewrite_calls == []


async def test_document_filter_is_strict_on_both_retrievals(
    agent: AgentContext,
) -> None:
    first = await upload_pdf(agent.client, ["beta beta"], "first.pdf")
    second = await upload_pdf(agent.client, ["gamma gamma"], "second.pdf")
    await index_document(agent.client, first["id"])
    await index_document(agent.client, second["id"])
    agent.llm.rewrite_text = "beta"

    first_payload = await ask(
        agent.client,
        "alpha",
        document_ids=[first["id"]],
    )
    assert first_payload["status"] == "answered"
    assert all(
        citation["document_id"] == first["id"]
        for citation in first_payload["citations"]
    )

    second_payload = await ask(
        agent.client,
        "alpha",
        document_ids=[second["id"]],
    )
    assert second_payload["status"] == "refused"
    assert second_payload["citations"] == []


async def test_unindexed_document_is_not_used(
    agent: AgentContext,
) -> None:
    indexed = await upload_pdf(agent.client, ["beta beta"], "indexed.pdf")
    await upload_pdf(agent.client, ["uniqueterm uniqueterm"], "unindexed.pdf")
    await index_document(agent.client, indexed["id"])
    agent.llm.rewrite_text = "uniqueterm"

    payload = await ask(agent.client, "alpha")

    assert payload["status"] == "refused"
    assert payload["citations"] == []


async def test_citations_are_unique_sorted_and_from_retry_evidence(
    agent: AgentContext,
) -> None:
    document = await upload_pdf(
        agent.client,
        ["beta beta beta 实验证据。"],
    )
    await index_document(agent.client, document["id"])
    agent.llm.rewrite_text = "beta"

    payload = await ask(agent.client, "alpha")

    citations = payload["citations"]
    chunk_ids = [item["chunk_id"] for item in citations]
    assert len(chunk_ids) == len(set(chunk_ids))
    assert [item["score"] for item in citations] == sorted(
        [item["score"] for item in citations],
        reverse=True,
    )
    assert all("beta" in item["text"] for item in citations)
    assert payload["workflow"]["rewrite_count"] <= 1


async def test_answer_llm_fixed_refusal_does_not_rewrite(
    agent: AgentContext,
) -> None:
    document = await upload_pdf(agent.client, ["alpha alpha 证据。"])
    await index_document(agent.client, document["id"])
    agent.llm.answer_text = QA_REFUSAL_ANSWER

    payload = await ask(agent.client, "alpha")

    assert payload["status"] == "refused"
    assert payload["citations"] == []
    assert payload["workflow"]["rewrite_attempted"] is False
    assert "rewrite_query" not in payload["workflow"]["steps"]
    assert "retrieve_retry" not in payload["workflow"]["steps"]
    assert payload["workflow"]["steps"][-1] == "answer"
    assert agent.llm.rewrite_calls == []


async def test_consecutive_requests_have_isolated_workflow_state(
    agent: AgentContext,
) -> None:
    document = await upload_pdf(agent.client, ["beta beta 证据。"])
    await index_document(agent.client, document["id"])
    agent.llm.rewrite_text = "beta"

    first = await ask(agent.client, "alpha")
    second = await ask(agent.client, "beta")

    assert first["status"] == "answered"
    assert first["workflow"]["rewrite_count"] == 1
    assert second["status"] == "answered"
    assert second["workflow"]["rewrite_count"] == 0
    assert second["workflow"]["rewrite_attempted"] is False
    assert "rewrite_query" not in second["workflow"]["steps"]
    assert len(agent.llm.rewrite_calls) == 1


async def test_invalid_agent_requests_return_422(agent: AgentContext) -> None:
    invalid_payloads = [
        {"question": ""},
        {"question": "   "},
        {"question": "x" * 2001},
        {"question": "alpha", "top_k": 0},
        {"question": "alpha", "top_k": 21},
        {"question": "alpha", "document_ids": ["not-a-uuid"]},
        {"question": "alpha", "max_rewrite_attempts": 2},
    ]

    for payload in invalid_payloads:
        response = await agent.client.post(AGENT_URL, json=payload)
        assert response.status_code == 422, (payload, response.text)
