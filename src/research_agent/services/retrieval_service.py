"""本地向量检索服务。"""

from __future__ import annotations

import logging

from pydantic import ValidationError

from ..core.config import Settings
from ..schemas.retrieval import (
    DocumentChunk,
    RetrievalResult,
    RetrievalSearchResponse,
)
from ..storage.vector_store import VectorStore, VectorStoreError
from .embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class RetrievalServiceError(Exception):
    """检索失败，携带对外的 500 错误信息。"""

    status_code = 500
    default_message = "向量检索失败"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class RetrievalService:
    """将查询向量交给 FAISS，并组装可追溯引用结果。"""

    def __init__(
        self,
        settings: Settings,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
    ) -> None:
        self._settings = settings
        self._embedding = embedding_service
        self._vector_store = vector_store

    def search(
        self,
        query: str,
        top_k: int | None,
        document_ids: list[str] | None,
    ) -> RetrievalSearchResponse:
        effective_top_k = top_k or self._settings.retrieval_top_k
        normalized_query = query.strip()
        if not normalized_query:
            raise RetrievalServiceError("query 不能为空")

        query_vector = self._embedding.embed_query(normalized_query)
        try:
            raw_results = self._vector_store.search(
                query_vector,
                top_k=effective_top_k,
                document_ids=(
                    set(document_ids) if document_ids is not None else None
                ),
            )
        except VectorStoreError as exc:
            logger.error("向量检索失败")
            raise RetrievalServiceError("向量索引损坏或读取失败") from exc

        results: list[RetrievalResult] = []
        for score, payload in raw_results:
            try:
                chunk = DocumentChunk.model_validate(payload)
            except ValidationError as exc:
                logger.error("manifest 中的 chunk 数据无效")
                raise RetrievalServiceError("向量索引中的 chunk 数据无效") from exc

            results.append(
                RetrievalResult(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    original_filename=chunk.original_filename,
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text[: self._settings.max_retrieval_text_length],
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    score=score,
                )
            )

        return RetrievalSearchResponse(query=normalized_query, results=results)
