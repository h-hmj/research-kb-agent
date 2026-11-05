"""第四阶段：证据判断、问答、引用与拒答测试。"""

from __future__ import annotations

import re
import zlib
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import httpx
import numpy as np
import pymupdf
import pytest

from research_agent.core.config import Settings
from research_agent.core.exceptions import (
    EmbeddingModelUnavailableError,
    LLMUnavailableError,
)
from research_agent.main import create_app
from research_agent.schemas.qa import EvidenceChunk
from research_agent.services.embedding_service import EMBEDDING_UNAVAILABLE_DETAIL
from research_agent.services.llm_service import (
    LLM_UNAVAILABLE_DETAIL,
    QA_REFUSAL_ANSWER,
    build_qa_messages,
)

pytestmark = pytest.mark.anyio

DOCUMENTS_URL = "/api/v1/documents"
QA_URL = "/api/v1/qa/ask"
DEFAULT_ANSWER = "根据证据，空白对照用于排除非处理因素造成的干扰。"


class FakeEmbeddingService:
    """确定性哈希 Embedding。"""

    dimension = 32

    def _encode_one(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimension, dtype=np.float32)
        for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower()):
            vector[zlib.crc32(token.encode("utf-8")) % self.dimension] += 1.0
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector /= norm
        return vector

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        return np.vstack([self._encode_one(text) for text in texts]).astype(
            np.float32
        )

    def embed_query(self, query: str) -> np.ndarray:
        return self._encode_one(query)


class UnavailableEmbeddingService:
    def embed_texts(self, texts: list[str]) -> np.ndarray:
        raise EmbeddingModelUnavailableError("unavailable")

    def embed_query(self, query: str) -> np.ndarray:
        raise EmbeddingModelUnavailableError("unavailable")


@dataclass
class FakeLLMService:
    answer_text: str = DEFAULT_ANSWER
    available: bool = True
    calls: list[tuple[str, list[EvidenceChunk]]] = field(default_factory=list)

    async def answer(
        self,
        question: str,
        evidence: list[EvidenceChunk],
    ) -> str:
        if not self.available:
            raise LLMUnavailableError("unavailable")
        self.calls.append((question, evidence))
        return self.answer_text


@dataclass
class QAContext:
    client: httpx.AsyncClient
    settings: Settings
    embedding: FakeEmbeddingService
    llm: FakeLLMService


@asynccontextmanager
async def qa_client(
    settings: Settings,
    embedding,
    llm,
) -> AsyncIterator[httpx.AsyncClient]:
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
            yield client


@pytest.fixture
async def qa(test_settings: Settings) -> AsyncIterator[QAContext]:
    embedding = FakeEmbeddingService()
    llm = FakeLLMService()
    async with qa_client(test_settings, embedding, llm) as client:
        yield QAContext(
            client=client,
            settings=test_settings,
            embedding=embedding,
            llm=llm,
        )


def make_pdf_bytes(page_texts: Sequence[str]) -> bytes:
    document = pymupdf.open()
    try:
        for text in page_texts:
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text, fontsize=12)
        return document.tobytes()
    finally:
        document.close()


async def upload_pdf(
    client: httpx.AsyncClient,
    page_texts: Sequence[str],
    filename: str = "experiment.pdf",
) -> dict:
    response = await client.post(
        DOCUMENTS_URL,
        files={
            "file": (
                filename,
                make_pdf_bytes(page_texts),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def index_document(client: httpx.AsyncClient, document_id: str) -> None:
    response = await client.post(f"{DOCUMENTS_URL}/{document_id}/index")
    assert response.status_code == 200, response.text


async def ask(
    client: httpx.AsyncClient,
    question: str,
    **kwargs,
) -> dict:
    response = await client.post(
        QA_URL,
        json={"question": question, **kwargs},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_answered_with_server_citations(qa: QAContext) -> None:
    document = await upload_pdf(
        qa.client,
        ["alpha alpha alpha 空白对照用于排除干扰。"],
    )
    await index_document(qa.client, document["id"])

    payload = await ask(qa.client, "alpha 空白对照")

    assert payload["status"] == "answered"
    assert payload["answer"] == DEFAULT_ANSWER
    assert payload["refusal_reason"] is None
    assert payload["retrieval"]["retrieved_count"] >= 1
    assert payload["retrieval"]["evidence_count"] >= 1
    assert payload["retrieval"]["top_k"] == 5
    assert len(payload["citations"]) == len(qa.llm.calls[0][1]) == 1

    citation = payload["citations"][0]
    assert citation["document_id"] == document["id"]
    assert citation["original_filename"] == "experiment.pdf"
    assert citation["page_number"] == 1
    assert citation["chunk_index"] == 0
    assert citation["chunk_id"]
    assert citation["text"].startswith("alpha")
    assert citation["char_end"] > citation["char_start"]
    assert isinstance(citation["score"], float)
    assert citation["citation_id"] == "citation-1"


async def test_llm_is_called_once_for_answered(qa: QAContext) -> None:
    document = await upload_pdf(qa.client, ["alpha alpha 实验证据。"])
    await index_document(qa.client, document["id"])

    await ask(qa.client, "alpha")

    assert len(qa.llm.calls) == 1
    question, evidence = qa.llm.calls[0]
    assert "alpha" in question
    assert evidence


async def test_citations_are_unique_and_sorted(qa: QAContext) -> None:
    document = await upload_pdf(
        qa.client,
        [
            "alpha alpha alpha context",
            "alpha context context context",
            "beta beta",
        ],
    )
    await index_document(qa.client, document["id"])

    payload = await ask(qa.client, "alpha", top_k=5)
    citations = payload["citations"]

    chunk_ids = [item["chunk_id"] for item in citations]
    assert len(chunk_ids) == len(set(chunk_ids))
    assert [item["score"] for item in citations] == sorted(
        [item["score"] for item in citations],
        reverse=True,
    )
    assert all("alpha" in item["text"] for item in citations)


async def test_no_index_refuses_without_llm(qa: QAContext) -> None:
    payload = await ask(qa.client, "alpha")

    assert payload["status"] == "refused"
    assert payload["answer"] == QA_REFUSAL_ANSWER
    assert payload["citations"] == []
    assert payload["refusal_reason"] == "未检索到足够相关的文档证据。"
    assert payload["retrieval"]["retrieved_count"] == 0
    assert payload["retrieval"]["evidence_count"] == 0
    assert qa.llm.calls == []


async def test_low_score_is_refused_without_llm(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"min_retrieval_score": 0.99})
    embedding = FakeEmbeddingService()
    llm = FakeLLMService()
    async with qa_client(settings, embedding, llm) as client:
        document = await upload_pdf(client, ["alpha beta"])
        await index_document(client, document["id"])

        payload = await ask(client, "alpha")

        assert payload["status"] == "refused"
        assert payload["citations"] == []
        assert llm.calls == []


async def test_min_evidence_count_is_refused_without_llm(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"min_evidence_count": 2})
    embedding = FakeEmbeddingService()
    llm = FakeLLMService()
    async with qa_client(settings, embedding, llm) as client:
        document = await upload_pdf(client, ["alpha alpha 单页证据"])
        await index_document(client, document["id"])

        payload = await ask(client, "alpha")

        assert payload["status"] == "refused"
        assert payload["retrieval"]["evidence_count"] == 1
        assert llm.calls == []


async def test_llm_fixed_refusal_is_normalized(qa: QAContext) -> None:
    document = await upload_pdf(qa.client, ["alpha alpha 证据。"])
    await index_document(qa.client, document["id"])
    qa.llm.answer_text = QA_REFUSAL_ANSWER

    payload = await ask(qa.client, "alpha")

    assert payload["status"] == "refused"
    assert payload["answer"] == QA_REFUSAL_ANSWER
    assert payload["citations"] == []
    assert payload["refusal_reason"] == "检索证据不足以支持可靠回答。"


async def test_embedding_unavailable_returns_503(
    test_settings: Settings,
) -> None:
    embedding = UnavailableEmbeddingService()
    llm = FakeLLMService()
    async with qa_client(test_settings, embedding, llm) as client:
        response = await client.post(
            QA_URL,
            json={"question": "alpha"},
        )

        assert response.status_code == 503
        assert response.json() == {
            "detail": EMBEDDING_UNAVAILABLE_DETAIL
        }
        assert llm.calls == []


async def test_llm_unavailable_with_evidence_returns_503(qa: QAContext) -> None:
    document = await upload_pdf(qa.client, ["alpha alpha 证据。"])
    await index_document(qa.client, document["id"])
    qa.llm.available = False

    response = await qa.client.post(QA_URL, json={"question": "alpha"})

    assert response.status_code == 503
    assert response.json() == {"detail": LLM_UNAVAILABLE_DETAIL}


async def test_no_evidence_does_not_require_llm(
    test_settings: Settings,
) -> None:
    llm = FakeLLMService(available=False)
    async with qa_client(
        test_settings,
        FakeEmbeddingService(),
        llm,
    ) as client:
        payload = await ask(client, "alpha")

        assert payload["status"] == "refused"
        assert payload["citations"] == []
        assert llm.calls == []


async def test_invalid_request_fields_return_422(qa: QAContext) -> None:
    invalid_payloads = [
        {"question": ""},
        {"question": "   "},
        {"question": "x" * 2001},
        {"question": "alpha", "top_k": 0},
        {"question": "alpha", "top_k": 21},
        {"question": "alpha", "document_ids": ["not-a-uuid"]},
    ]

    for payload in invalid_payloads:
        response = await qa.client.post(QA_URL, json=payload)
        assert response.status_code == 422, (payload, response.text)


async def test_document_ids_filter_is_strict(qa: QAContext) -> None:
    first = await upload_pdf(qa.client, ["alpha alpha"], "first.pdf")
    second = await upload_pdf(qa.client, ["beta beta"], "second.pdf")
    await index_document(qa.client, first["id"])
    await index_document(qa.client, second["id"])

    payload = await ask(
        qa.client,
        "beta",
        document_ids=[second["id"]],
    )

    assert payload["status"] == "answered"
    assert payload["citations"]
    assert all(
        item["document_id"] == second["id"] for item in payload["citations"]
    )

    wrong_filter = await ask(
        qa.client,
        "beta",
        document_ids=[first["id"]],
    )
    assert wrong_filter["status"] == "refused"
    assert wrong_filter["citations"] == []


async def test_unindexed_document_is_not_used(qa: QAContext) -> None:
    indexed = await upload_pdf(qa.client, ["beta beta"], "indexed.pdf")
    await upload_pdf(qa.client, ["uniqueterm uniqueterm"], "unindexed.pdf")
    await index_document(qa.client, indexed["id"])

    payload = await ask(qa.client, "uniqueterm")

    assert payload["status"] == "refused"
    assert payload["citations"] == []
    assert qa.llm.calls == []


async def test_context_is_limited_and_only_selected_evidence_is_prompted(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"max_context_chars": 20})
    embedding = FakeEmbeddingService()
    llm = FakeLLMService()
    async with qa_client(settings, embedding, llm) as client:
        document = await upload_pdf(
            client,
            ["alpha " * 100],
        )
        await index_document(client, document["id"])

        payload = await ask(client, "alpha", top_k=5)

        assert payload["status"] == "answered"
        assert llm.calls
        evidence = llm.calls[0][1]
        assert sum(len(item.text) for item in evidence) <= 20
        assert len(payload["citations"]) == len(evidence)
        assert all(
            len(item["text"]) <= 20 for item in payload["citations"]
        )

        messages = build_qa_messages("alpha", evidence)
        assert messages[0]["role"] == "system"
        assert all(item.text in messages[1]["content"] for item in evidence)


async def test_citation_text_uses_configured_prefix(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(
        update={"max_citation_text_length": 10}
    )
    embedding = FakeEmbeddingService()
    llm = FakeLLMService()
    async with qa_client(settings, embedding, llm) as client:
        document = await upload_pdf(
            client,
            ["alpha alpha alpha 这是很长的原始证据文本。"],
        )
        await index_document(client, document["id"])

        payload = await ask(client, "alpha")
        citation = payload["citations"][0]

        assert len(citation["text"]) <= 10
        assert citation["text"].startswith("alpha")


async def test_qa_uses_only_retrieved_evidence_in_prompt() -> None:
    evidence = [
        EvidenceChunk(
            chunk_id="chunk-1",
            document_id="doc-1",
            original_filename="one.pdf",
            page_number=1,
            chunk_index=0,
            text="selected evidence only",
            char_start=0,
            char_end=21,
            score=0.9,
        )
    ]
    messages = build_qa_messages("问题", evidence)

    assert "selected evidence only" in messages[1]["content"]
    assert "unselected evidence" not in messages[1]["content"]
    assert "只能依据" in messages[0]["content"]
    assert QA_REFUSAL_ANSWER in messages[1]["content"]
