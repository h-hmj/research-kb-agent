"""第三阶段：分块、索引、检索、持久化与删除同步测试。"""

from __future__ import annotations

import json
import re
import zlib
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
import numpy as np
import pymupdf
import pytest
from pydantic import ValidationError

from research_agent.core.config import Settings
from research_agent.main import create_app
from research_agent.schemas.documents import DocumentPage
from research_agent.services.chunking_service import build_chunks
from research_agent.services.embedding_service import (
    EMBEDDING_UNAVAILABLE_DETAIL,
    EmbeddingModelUnavailableError,
    SentenceTransformerEmbeddingService,
)

pytestmark = pytest.mark.anyio

DOCUMENTS_URL = "/api/v1/documents"
SEARCH_URL = "/api/v1/retrieval/search"


class FakeEmbeddingService:
    """确定性哈希 Embedding，只替代模型推理。"""

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
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("Embedding 输入不能为空")
        return np.vstack([self._encode_one(text) for text in texts]).astype(
            np.float32
        )

    def embed_query(self, query: str) -> np.ndarray:
        if not query.strip():
            raise ValueError("query 不能为空")
        return self._encode_one(query)


class UnavailableEmbeddingService:
    """模拟本地模型目录缺失/加载失败。"""

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        raise EmbeddingModelUnavailableError("unavailable")

    def embed_query(self, query: str) -> np.ndarray:
        raise EmbeddingModelUnavailableError("unavailable")


@dataclass
class ApiContext:
    client: httpx.AsyncClient
    settings: Settings
    embedding: FakeEmbeddingService


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
    filename: str = "paper.pdf",
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


async def index_document(client: httpx.AsyncClient, document_id: str) -> dict:
    response = await client.post(f"{DOCUMENTS_URL}/{document_id}/index")
    assert response.status_code == 200, response.text
    return response.json()


async def search(
    client: httpx.AsyncClient,
    query: str,
    **kwargs,
) -> dict:
    response = await client.post(
        SEARCH_URL,
        json={"query": query, **kwargs},
    )
    assert response.status_code == 200, response.text
    return response.json()


@asynccontextmanager
async def app_client(
    settings: Settings,
    embedding,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, embedding_service=embedding)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client


@pytest.fixture
async def api(test_settings: Settings) -> AsyncIterator[ApiContext]:
    embedding = FakeEmbeddingService()
    async with app_client(test_settings, embedding) as client:
        yield ApiContext(
            client=client,
            settings=test_settings,
            embedding=embedding,
        )


def page(page_number: int, text: str) -> DocumentPage:
    return DocumentPage(
        page_number=page_number,
        text=text,
        character_count=len(text),
    )


# ---------------------------------------------------------------------------
# 分块纯逻辑
# ---------------------------------------------------------------------------


async def test_chunk_size_overlap_and_ranges() -> None:
    text = "实验需要空白对照。" * 60
    chunks = build_chunks(
        [page(1, text)],
        document_id="doc-1",
        original_filename="experiment.pdf",
        chunk_size=80,
        chunk_overlap=15,
    )

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text) <= 80
        assert chunk.character_count == len(chunk.text)
        assert text[chunk.char_start : chunk.char_end] == chunk.text
    assert any(
        left.char_start < right.char_start < left.char_end
        for left, right in zip(chunks, chunks[1:])
    )


async def test_chunk_page_numbers_start_at_one_and_never_cross_pages() -> None:
    pages = [
        page(1, "第一页内容。" * 30),
        page(2, "第二页内容。" * 30),
    ]
    chunks = build_chunks(
        pages,
        document_id="doc-2",
        original_filename="two-pages.pdf",
        chunk_size=70,
        chunk_overlap=10,
    )

    assert {chunk.page_number for chunk in chunks} == {1, 2}
    for chunk in chunks:
        source = pages[chunk.page_number - 1].text
        assert source[chunk.char_start : chunk.char_end] == chunk.text
        assert chunk.page_number in {1, 2}


async def test_blank_page_produces_no_chunks() -> None:
    chunks = build_chunks(
        [page(1, " \n\t "), page(2, "有效内容。")],
        document_id="doc-3",
        original_filename="blank.pdf",
        chunk_size=50,
        chunk_overlap=10,
    )

    assert chunks
    assert all(chunk.page_number == 2 for chunk in chunks)


async def test_chunk_ids_are_stable() -> None:
    pages = [page(1, "稳定 ID 测试。" * 30)]
    first = build_chunks(
        pages, "doc-4", "stable.pdf", chunk_size=60, chunk_overlap=10
    )
    second = build_chunks(
        pages, "doc-4", "stable.pdf", chunk_size=60, chunk_overlap=10
    )

    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]
    assert len({chunk.id for chunk in first}) == len(first)


async def test_invalid_chunk_overlap_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            chunk_size=100,
            chunk_overlap=100,
        )


# ---------------------------------------------------------------------------
# 索引与检索
# ---------------------------------------------------------------------------


async def test_index_and_search_returns_citation_fields(api: ApiContext) -> None:
    document = await upload_pdf(
        api.client,
        ["alpha alpha alpha context", "beta context content"],
    )
    indexed = await index_document(api.client, document["id"])

    assert indexed["status"] == "indexed"
    assert indexed["page_count"] == 2
    assert indexed["chunk_count"] > 0
    assert indexed["embedding_dimension"] == FakeEmbeddingService.dimension

    detail = await api.client.get(f"{DOCUMENTS_URL}/{document['id']}")
    assert detail.json()["index_status"] == "indexed"

    result = await search(api.client, "alpha")
    assert result["results"]
    top = result["results"][0]
    assert top["document_id"] == document["id"]
    assert top["original_filename"] == "paper.pdf"
    assert top["page_number"] == 1
    assert isinstance(top["chunk_index"], int)
    assert "alpha" in top["text"]
    assert isinstance(top["score"], float)
    assert top["char_end"] > top["char_start"]


async def test_index_creates_chunk_json_and_manifest(api: ApiContext) -> None:
    document = await upload_pdf(api.client, ["alpha and beta"])
    indexed = await index_document(api.client, document["id"])

    chunk_path = api.settings.chunks_dir / f"{document['id']}.json"
    manifest_path = api.settings.vector_store_dir / "manifest.json"
    index_path = api.settings.vector_store_dir / "index.faiss"

    assert chunk_path.is_file()
    assert manifest_path.is_file()
    assert index_path.is_file()

    chunks = json.loads(chunk_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(chunks) == indexed["chunk_count"]
    assert len(manifest["entries"]) == indexed["chunk_count"]
    assert manifest["dimension"] == FakeEmbeddingService.dimension


async def test_search_scores_are_descending(api: ApiContext) -> None:
    document = await upload_pdf(
        api.client,
        [
            "alpha alpha alpha context",
            "alpha context context context",
            "beta beta beta",
        ],
    )
    await index_document(api.client, document["id"])

    results = (await search(api.client, "alpha"))["results"]
    scores = [item["score"] for item in results]
    assert scores == sorted(scores, reverse=True)
    assert len(scores) >= 2


async def test_document_ids_filter_is_strict(api: ApiContext) -> None:
    first = await upload_pdf(api.client, ["alpha alpha"], "first.pdf")
    second = await upload_pdf(api.client, ["beta beta"], "second.pdf")
    await index_document(api.client, first["id"])
    await index_document(api.client, second["id"])

    only_second = await search(
        api.client,
        "alpha",
        document_ids=[second["id"]],
    )
    assert all(
        item["document_id"] == second["id"] for item in only_second["results"]
    )
    assert all(
        item["document_id"] != first["id"] for item in only_second["results"]
    )

    only_first = await search(
        api.client,
        "alpha",
        document_ids=[first["id"]],
    )
    assert only_first["results"]
    assert all(
        item["document_id"] == first["id"] for item in only_first["results"]
    )


async def test_empty_index_returns_empty_results(api: ApiContext) -> None:
    response = await api.client.post(SEARCH_URL, json={"query": "alpha"})
    assert response.status_code == 200
    assert response.json()["results"] == []


async def test_unindexed_document_is_not_searchable(api: ApiContext) -> None:
    unindexed = await upload_pdf(api.client, ["alpha alpha"], "not-indexed.pdf")
    indexed = await upload_pdf(api.client, ["beta beta"], "indexed.pdf")
    await index_document(api.client, indexed["id"])

    result = await search(api.client, "alpha")
    assert all(
        item["document_id"] != unindexed["id"] for item in result["results"]
    )


async def test_reindex_does_not_duplicate_chunks(api: ApiContext) -> None:
    document = await upload_pdf(api.client, ["alpha alpha beta"])
    first = await index_document(api.client, document["id"])
    second = await index_document(api.client, document["id"])

    manifest = json.loads(
        (api.settings.vector_store_dir / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    entries = [
        entry
        for entry in manifest["entries"]
        if entry["chunk"]["document_id"] == document["id"]
    ]
    assert len(entries) == second["chunk_count"] == first["chunk_count"]
    ids = [entry["chunk"]["id"] for entry in entries]
    assert len(ids) == len(set(ids))


async def test_delete_removes_chunks_and_index(api: ApiContext) -> None:
    document = await upload_pdf(api.client, ["alpha alpha"])
    await index_document(api.client, document["id"])

    response = await api.client.delete(f"{DOCUMENTS_URL}/{document['id']}")
    assert response.status_code == 204
    assert not (api.settings.chunks_dir / f"{document['id']}.json").exists()
    assert not (api.settings.vector_store_dir / "index.faiss").exists()
    assert not (api.settings.vector_store_dir / "manifest.json").exists()

    results = await search(api.client, "alpha")
    assert all(
        item["document_id"] != document["id"] for item in results["results"]
    )


async def test_delete_one_document_keeps_other_index(api: ApiContext) -> None:
    first = await upload_pdf(api.client, ["alpha alpha"], "first.pdf")
    second = await upload_pdf(api.client, ["beta beta"], "second.pdf")
    await index_document(api.client, first["id"])
    await index_document(api.client, second["id"])

    response = await api.client.delete(f"{DOCUMENTS_URL}/{first['id']}")
    assert response.status_code == 204

    result = await search(api.client, "beta")
    assert result["results"]
    assert all(
        item["document_id"] == second["id"] for item in result["results"]
    )
    assert (api.settings.chunks_dir / f"{second['id']}.json").is_file()


async def test_index_persists_across_app_restart(
    api: ApiContext,
    test_settings: Settings,
) -> None:
    document = await upload_pdf(api.client, ["alpha alpha beta"])
    await index_document(api.client, document["id"])

    async with app_client(test_settings, api.embedding) as restarted:
        result = await search(restarted, "alpha")
        assert result["results"]
        assert result["results"][0]["document_id"] == document["id"]


async def test_max_retrieval_text_length_is_prefix(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(
        update={"max_retrieval_text_length": 18}
    )
    source = "alpha " + "beta " * 40
    async with app_client(settings, FakeEmbeddingService()) as client:
        document = await upload_pdf(client, [source])
        await index_document(client, document["id"])
        result = await search(client, "alpha")

        assert result["results"]
        text = result["results"][0]["text"]
        assert len(text) <= 18
        assert source.startswith(text)
        assert text.startswith("alpha")


async def test_missing_document_index_returns_404(api: ApiContext) -> None:
    response = await api.client.post(
        f"{DOCUMENTS_URL}/00000000-0000-0000-0000-000000000000/index"
    )
    assert response.status_code == 404


async def test_model_unavailable_returns_503(test_settings: Settings) -> None:
    unavailable = UnavailableEmbeddingService()
    async with app_client(test_settings, unavailable) as client:
        document = await upload_pdf(client, ["alpha alpha"])

        index_response = await client.post(
            f"{DOCUMENTS_URL}/{document['id']}/index"
        )
        assert index_response.status_code == 503
        assert index_response.json() == {
            "detail": EMBEDDING_UNAVAILABLE_DETAIL
        }

        search_response = await client.post(
            SEARCH_URL,
            json={"query": "alpha"},
        )
        assert search_response.status_code == 503
        assert search_response.json() == {
            "detail": EMBEDDING_UNAVAILABLE_DETAIL
        }


async def test_empty_query_is_rejected(api: ApiContext) -> None:
    response = await api.client.post(SEARCH_URL, json={"query": "   "})
    assert response.status_code == 422


async def test_real_embedding_service_does_not_load_missing_model(
    test_settings: Settings,
) -> None:
    service = SentenceTransformerEmbeddingService(
        test_settings.embedding_model_path
    )
    with pytest.raises(EmbeddingModelUnavailableError):
        service.embed_query("alpha")


async def test_top_k_limits_results(api: ApiContext) -> None:
    document = await upload_pdf(
        api.client,
        ["alpha alpha", "alpha beta", "alpha"],
    )
    await index_document(api.client, document["id"])

    result = await search(api.client, "alpha", top_k=1)
    assert len(result["results"]) == 1


async def test_index_status_defaults_to_not_indexed(api: ApiContext) -> None:
    document = await upload_pdf(api.client, ["alpha alpha"])
    assert document["index_status"] == "not_indexed"
    detail = await api.client.get(f"{DOCUMENTS_URL}/{document['id']}")
    assert detail.json()["index_status"] == "not_indexed"


async def test_corrupt_index_returns_clear_500(api: ApiContext) -> None:
    document = await upload_pdf(api.client, ["alpha alpha"])
    await index_document(api.client, document["id"])

    index_path = api.settings.vector_store_dir / "index.faiss"
    index_path.write_bytes(b"broken-index")

    response = await api.client.post(SEARCH_URL, json={"query": "alpha"})
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "索引" in detail
    assert str(api.settings.vector_store_dir) not in detail
