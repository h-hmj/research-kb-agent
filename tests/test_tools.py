"""第六阶段：受控科研工具、ToolGraph 与结构化输出测试。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

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

TOOLS_URL = "/api/v1/tools/run"


def checklist_json(
    *,
    item_id: str = "item-1",
    category: Literal[
        "preparation",
        "operation",
        "recording",
        "review",
    ] = "preparation",
    priority: Literal["high", "medium", "low"] = "high",
    evidence_id: str = "evidence-1",
) -> str:
    return json.dumps(
        {
            "title": "实验准备 checklist",
            "items": [
                {
                    "id": item_id,
                    "category": category,
                    "content": "准备实验材料并核对条件。",
                    "priority": priority,
                    "evidence_ids": [evidence_id],
                }
            ],
            "notes": ["仅基于当前检索资料。"],
        }
    )


@dataclass
class ToolFakeLLM:
    complete_text: str = ""
    complete_available: bool = True
    complete_calls: list[list[dict[str, str]]] = field(default_factory=list)

    async def complete(self, messages: list[dict[str, str]]) -> str:
        self.complete_calls.append(messages)
        if not self.complete_available:
            raise LLMUnavailableError("complete unavailable")
        return self.complete_text

    async def answer(self, question: str, evidence: list) -> str:
        raise AssertionError("answer should not be called by tools")

    async def rewrite(self, question: str) -> str:
        raise AssertionError("rewrite should not be called by tools")


@dataclass
class ToolContext:
    app: Any
    client: httpx.AsyncClient
    settings: Settings
    llm: ToolFakeLLM


@asynccontextmanager
async def tool_client(
    settings: Settings,
    embedding,
    llm: ToolFakeLLM,
) -> AsyncIterator[ToolContext]:
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
            yield ToolContext(
                app=app,
                client=client,
                settings=settings,
                llm=llm,
            )


@pytest.fixture
async def tools(test_settings: Settings) -> AsyncIterator[ToolContext]:
    llm = ToolFakeLLM(complete_text=checklist_json())
    async with tool_client(
        test_settings,
        FakeEmbeddingService(),
        llm,
    ) as context:
        yield context


async def run_tool(
    client: httpx.AsyncClient,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict:
    response = await client.post(
        TOOLS_URL,
        json={"tool_name": tool_name, "arguments": arguments},
    )
    assert response.status_code == 200, response.text
    return response.json()


def assert_safe_workflow(payload: dict) -> None:
    workflow = payload["workflow"]
    assert workflow["steps"] == [
        "validate_tool_request",
        "execute_selected_tool",
        "format_tool_response",
    ]
    assert set(workflow) == {
        "steps",
        "llm_called",
        "retrieval_count",
        "evidence_count",
    }


async def test_tool_graph_is_real_compiled_langgraph(
    test_settings: Settings,
) -> None:
    app = create_app(
        test_settings,
        embedding_service=FakeEmbeddingService(),
        llm_service=ToolFakeLLM(),
    )
    graph = app.state.tool_service.graph

    assert "CompiledStateGraph" in type(graph).__name__
    nodes = set(graph.get_graph().nodes)
    assert {
        "validate_tool_request",
        "execute_selected_tool",
        "format_tool_response",
    } <= nodes


async def test_unknown_tool_name_returns_422(tools: ToolContext) -> None:
    response = await tools.client.post(
        TOOLS_URL,
        json={"tool_name": "../../shell", "arguments": {}},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "不支持的工具名称。"


async def test_each_tool_rejects_invalid_arguments(
    tools: ToolContext,
) -> None:
    cases = [
        ("search_knowledge_base", {}),
        ("search_knowledge_base", {"query": "   "}),
        ("search_knowledge_base", {"query": "alpha", "top_k": 0}),
        ("generate_experiment_checklist", {}),
        ("generate_experiment_checklist", {"experiment_goal": "   "}),
        (
            "generate_experiment_checklist",
            {"experiment_goal": "实验", "constraints": ["x"] * 21},
        ),
        ("summarize_meeting_notes", {}),
        ("summarize_meeting_notes", {"meeting_text": "   "}),
    ]

    for tool_name, arguments in cases:
        response = await tools.client.post(
            TOOLS_URL,
            json={"tool_name": tool_name, "arguments": arguments},
        )
        assert response.status_code == 422, (tool_name, arguments, response.text)


async def test_search_returns_compatible_fields_without_llm(
    tools: ToolContext,
) -> None:
    document = await upload_pdf(tools.client, ["alpha alpha 证据。"])
    await index_document(tools.client, document["id"])

    payload = await run_tool(
        tools.client,
        "search_knowledge_base",
        {"query": "alpha", "top_k": 5},
    )

    assert payload["status"] == "success"
    assert payload["tool_name"] == "search_knowledge_base"
    assert payload["result"]["query"] == "alpha"
    result = payload["result"]["results"][0]
    assert result["document_id"] == document["id"]
    assert result["original_filename"] == "experiment.pdf"
    assert result["page_number"] == 1
    assert result["chunk_id"]
    assert result["text"]
    assert isinstance(result["score"], float)
    assert payload["workflow"]["llm_called"] is False
    assert payload["workflow"]["retrieval_count"] >= 1
    assert tools.llm.complete_calls == []
    assert_safe_workflow(payload)


async def test_search_empty_index_returns_empty_results(
    tools: ToolContext,
) -> None:
    payload = await run_tool(
        tools.client,
        "search_knowledge_base",
        {"query": "没有索引"},
    )

    assert payload["status"] == "success"
    assert payload["result"]["results"] == []
    assert payload["workflow"]["llm_called"] is False


async def test_search_embedding_unavailable_returns_503(
    test_settings: Settings,
) -> None:
    llm = ToolFakeLLM()
    async with tool_client(
        test_settings,
        UnavailableEmbeddingService(),
        llm,
    ) as context:
        response = await context.client.post(
            TOOLS_URL,
            json={
                "tool_name": "search_knowledge_base",
                "arguments": {"query": "alpha"},
            },
        )

        assert response.status_code == 503
        assert "Embedding" in response.json()["detail"]


async def test_checklist_success_with_server_citations(
    tools: ToolContext,
) -> None:
    document = await upload_pdf(
        tools.client,
        ["alpha alpha 样品数量有限，需要空白对照。"],
    )
    await index_document(tools.client, document["id"])
    tools.llm.complete_text = checklist_json()

    payload = await run_tool(
        tools.client,
        "generate_experiment_checklist",
        {
            "experiment_goal": "alpha",
            "constraints": ["样品数量有限"],
            "top_k": 5,
        },
    )

    assert payload["status"] == "success"
    assert payload["tool_name"] == "generate_experiment_checklist"
    result = payload["result"]
    assert result["title"] == "实验准备 checklist"
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["id"] == "item-1"
    assert item["category"] == "preparation"
    assert item["priority"] == "high"
    assert item["citations"]
    citation = item["citations"][0]
    assert citation["document_id"] == document["id"]
    assert citation["original_filename"] == "experiment.pdf"
    assert citation["page_number"] == 1
    assert citation["chunk_id"]
    assert citation["text"].startswith("alpha")
    assert item["citations"] == [
        {
            **citation,
        }
    ]
    assert payload["workflow"]["llm_called"] is True
    assert payload["workflow"]["retrieval_count"] >= 1
    assert payload["workflow"]["evidence_count"] >= 1
    assert len(tools.llm.complete_calls) == 1
    assert_safe_workflow(payload)


async def test_checklist_forged_evidence_id_returns_503(
    tools: ToolContext,
) -> None:
    document = await upload_pdf(tools.client, ["alpha alpha"])
    await index_document(tools.client, document["id"])
    tools.llm.complete_text = checklist_json(evidence_id="evidence-999")

    response = await tools.client.post(
        TOOLS_URL,
        json={
            "tool_name": "generate_experiment_checklist",
            "arguments": {"experiment_goal": "alpha"},
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "本地 LLM 返回的 checklist 格式无效，请稍后重试。"
    )


async def test_checklist_no_evidence_refuses_without_llm(
    tools: ToolContext,
) -> None:
    payload = await run_tool(
        tools.client,
        "generate_experiment_checklist",
        {"experiment_goal": "不存在的实验目标"},
    )

    assert payload["status"] == "refused"
    assert payload["result"] == {"checklist": []}
    assert payload["refusal_reason"] == (
        "未检索到足够的资料证据，无法生成基于知识库的实验 checklist。"
    )
    assert payload["workflow"]["llm_called"] is False
    assert payload["workflow"]["evidence_count"] == 0
    assert tools.llm.complete_calls == []


async def test_checklist_low_score_refuses_without_llm(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"min_retrieval_score": 0.99})
    llm = ToolFakeLLM(complete_text=checklist_json())
    async with tool_client(
        settings,
        FakeEmbeddingService(),
        llm,
    ) as context:
        document = await upload_pdf(context.client, ["alpha beta"])
        await index_document(context.client, document["id"])

        payload = await run_tool(
            context.client,
            "generate_experiment_checklist",
            {"experiment_goal": "alpha"},
        )

        assert payload["status"] == "refused"
        assert llm.complete_calls == []


async def test_checklist_llm_unavailable_returns_503(
    tools: ToolContext,
) -> None:
    document = await upload_pdf(tools.client, ["alpha alpha"])
    await index_document(tools.client, document["id"])
    tools.llm.complete_available = False

    response = await tools.client.post(
        TOOLS_URL,
        json={
            "tool_name": "generate_experiment_checklist",
            "arguments": {"experiment_goal": "alpha"},
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"].startswith("本地 LLM 服务不可用")


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        checklist_json(category="invalid-category"),  # type: ignore[arg-type]
        checklist_json(priority="urgent"),  # type: ignore[arg-type]
        json.dumps(
            {
                "title": "实验准备 checklist",
                "items": [
                    {
                        "id": "same",
                        "category": "preparation",
                        "content": "a",
                        "priority": "high",
                        "evidence_ids": ["evidence-1"],
                    },
                    {
                        "id": "same",
                        "category": "operation",
                        "content": "b",
                        "priority": "low",
                        "evidence_ids": ["evidence-1"],
                    },
                ],
            }
        ),
    ],
)
async def test_checklist_invalid_model_output_returns_503(
    tools: ToolContext,
    raw: str,
) -> None:
    document = await upload_pdf(tools.client, ["alpha alpha"])
    await index_document(tools.client, document["id"])
    tools.llm.complete_text = raw

    response = await tools.client.post(
        TOOLS_URL,
        json={
            "tool_name": "generate_experiment_checklist",
            "arguments": {"experiment_goal": "alpha"},
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "本地 LLM 返回的 checklist 格式无效，请稍后重试。"
    )


async def test_meeting_summary_segment_citations(tools: ToolContext) -> None:
    meeting_text = "实验进度：完成 A 组。\n\n下周计划：补做 B 组。"
    tools.llm.complete_text = json.dumps(
        {
            "summary": "本次组会确认了 A 组进度并安排 B 组补做。",
            "decisions": [
                {
                    "content": "A 组实验已完成。",
                    "source_segment_ids": ["segment-1"],
                }
            ],
            "action_items": [
                {
                    "task": "补做 B 组实验。",
                    "owner": None,
                    "deadline": None,
                    "source_segment_ids": ["segment-2"],
                }
            ],
            "risks": [],
            "open_questions": [],
        },
        ensure_ascii=False,
    )

    payload = await run_tool(
        tools.client,
        "summarize_meeting_notes",
        {
            "meeting_title": "2026-11-07 组会",
            "meeting_text": meeting_text,
            "focus": "实验进度",
        },
    )

    assert payload["status"] == "success"
    assert payload["tool_name"] == "summarize_meeting_notes"
    result = payload["result"]
    assert result["meeting_title"] == "2026-11-07 组会"
    assert result["summary"].startswith("本次组会")
    assert result["action_items"][0]["owner"] is None
    assert result["action_items"][0]["deadline"] is None
    assert result["decisions"][0]["citations"][0]["segment_id"] == "segment-1"
    assert result["action_items"][0]["citations"][0]["segment_id"] == "segment-2"
    assert result["action_items"][0]["citations"][0]["text"] == "下周计划：补做 B 组。"
    assert payload["workflow"]["retrieval_count"] == 0
    assert payload["workflow"]["evidence_count"] == 2
    assert payload["workflow"]["llm_called"] is True


async def test_meeting_summary_forged_segment_returns_503(
    tools: ToolContext,
) -> None:
    tools.llm.complete_text = json.dumps(
        {
            "summary": "会议摘要。",
            "decisions": [
                {
                    "content": "结论。",
                    "source_segment_ids": ["segment-99"],
                }
            ],
            "action_items": [],
            "risks": [],
            "open_questions": [],
        },
        ensure_ascii=False,
    )

    response = await tools.client.post(
        TOOLS_URL,
        json={
            "tool_name": "summarize_meeting_notes",
            "arguments": {"meeting_text": "第一段。\n\n第二段。"},
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "本地 LLM 返回的组会总结格式无效，请稍后重试。"
    )


async def test_meeting_summary_rejects_empty_text(
    tools: ToolContext,
) -> None:
    for text in ("", "   ", "\n\n"):
        response = await tools.client.post(
            TOOLS_URL,
            json={
                "tool_name": "summarize_meeting_notes",
                "arguments": {"meeting_text": text},
            },
        )
        assert response.status_code == 422, response.text


async def test_meeting_summary_context_limit_returns_422(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(
        update={"max_meeting_context_chars": 10}
    )
    llm = ToolFakeLLM()
    async with tool_client(
        settings,
        FakeEmbeddingService(),
        llm,
    ) as context:
        response = await context.client.post(
            TOOLS_URL,
            json={
                "tool_name": "summarize_meeting_notes",
                "arguments": {"meeting_text": "第一段很长。\n\n第二段也很长。"},
            },
        )

        assert response.status_code == 422
        assert "上下文上限" in response.json()["detail"]
        assert llm.complete_calls == []


async def test_meeting_summary_llm_unavailable_returns_503(
    tools: ToolContext,
) -> None:
    tools.llm.complete_available = False

    response = await tools.client.post(
        TOOLS_URL,
        json={
            "tool_name": "summarize_meeting_notes",
            "arguments": {"meeting_text": "第一段。"},
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"].startswith("本地 LLM 服务不可用")


async def test_tool_workflow_is_safe_and_state_is_isolated(
    tools: ToolContext,
) -> None:
    document = await upload_pdf(tools.client, ["alpha alpha"])
    await index_document(tools.client, document["id"])

    search = await run_tool(
        tools.client,
        "search_knowledge_base",
        {"query": "alpha"},
    )
    tools.llm.complete_text = checklist_json()
    checklist = await run_tool(
        tools.client,
        "generate_experiment_checklist",
        {"experiment_goal": "alpha"},
    )

    assert search["workflow"]["llm_called"] is False
    assert checklist["workflow"]["llm_called"] is True
    assert search["workflow"]["steps"] == checklist["workflow"]["steps"]
    for payload in (search, checklist):
        assert_safe_workflow(payload)
        serialized = json.dumps(payload, ensure_ascii=False)
        assert "system_prompt" not in serialized
        assert "messages" not in serialized
        assert "C:\\\\" not in serialized
        assert "D:\\\\" not in serialized
        assert "sk-" not in serialized
        assert "chain_of_thought" not in serialized
