"""单文档分块、向量化和索引编排。"""

from __future__ import annotations

import json
import logging
from uuid import UUID

import numpy as np

from ..core.config import Settings
from ..schemas.retrieval import IndexDocumentResponse
from ..storage.chunk_store import ChunkStore, ChunkStoreError
from ..storage.metadata_store import MetadataStore, MetadataStoreError
from ..storage.vector_store import VectorStore, VectorStoreError
from .chunking_service import build_chunks
from .document_service import DocumentNotFoundError, DocumentStorageError
from .embedding_service import EmbeddingService
from .metadata_service import MetadataService

logger = logging.getLogger(__name__)


class IndexingService:
    """协调页码分块、Embedding、chunk JSON 和 FAISS 索引。"""

    def __init__(
        self,
        settings: Settings,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
        chunk_store: ChunkStore,
    ) -> None:
        self._settings = settings
        self._embedding = embedding_service
        self._vector_store = vector_store
        self._chunk_store = chunk_store
        self._metadata = MetadataService(MetadataStore(settings.metadata_dir))

    def index_document(self, document_id: str) -> IndexDocumentResponse:
        """为单份文档创建或重建索引。"""
        canonical_id = self._canonical_id(document_id)
        try:
            document = self._metadata.get(canonical_id)
        except MetadataStoreError as exc:
            raise DocumentStorageError("文档元数据读取失败") from exc
        if document is None:
            raise DocumentNotFoundError("文档不存在")

        chunks = build_chunks(
            pages=document.pages,
            document_id=canonical_id,
            original_filename=document.original_filename,
            chunk_size=self._settings.chunk_size,
            chunk_overlap=self._settings.chunk_overlap,
        )

        if chunks:
            vectors = self._embedding.embed_texts([chunk.text for chunk in chunks])
            vectors = np.asarray(vectors, dtype=np.float32)
            if vectors.ndim != 2 or vectors.shape[0] != len(chunks):
                raise DocumentStorageError("Embedding 返回结果格式错误")
        else:
            vectors = np.empty((0, 0), dtype=np.float32)

        with self._vector_store.lock:
            try:
                old_chunk_data = self._chunk_store.read_bytes(canonical_id)
                self._chunk_store.write(canonical_id, chunks)
            except ChunkStoreError as exc:
                raise DocumentStorageError("文档分块写入失败") from exc

            try:
                dimension = self._vector_store.upsert_document(
                    canonical_id,
                    chunks,
                    vectors,
                )
            except VectorStoreError as exc:
                self._restore_chunks(canonical_id, old_chunk_data)
                logger.error("向量索引写入失败: document_id=%s", canonical_id)
                raise DocumentStorageError("向量索引写入失败") from exc

        try:
            updated = document.model_copy(update={"index_status": "indexed"})
            self._metadata.save(updated)
        except MetadataStoreError:
            logger.warning("索引成功但元数据状态更新失败: document_id=%s", canonical_id)

        return IndexDocumentResponse(
            document_id=canonical_id,
            page_count=document.page_count,
            chunk_count=len(chunks),
            embedding_dimension=int(vectors.shape[1]) if chunks else dimension,
        )

    def remove_document_index(self, document_id: str) -> None:
        """删除文档的 FAISS 向量、manifest 记录和 chunk 文件。"""
        canonical_id = self._canonical_id(document_id)
        with self._vector_store.lock:
            try:
                self._vector_store.delete_document(canonical_id)
            except VectorStoreError as exc:
                logger.error("删除文档向量失败: document_id=%s", canonical_id)
                raise DocumentStorageError("文档索引删除失败") from exc

            try:
                self._chunk_store.delete(canonical_id)
            except ChunkStoreError as exc:
                logger.error("删除文档分块失败: document_id=%s", canonical_id)
                raise DocumentStorageError("文档分块删除失败") from exc

    def reconcile_orphan_chunks(self) -> None:
        """启动时清理 manifest 中已不存在的非空 chunk 文件。"""
        try:
            with self._vector_store.lock:
                indexed_ids = self._vector_store.indexed_document_ids()
                for document_id in self._chunk_store.list_document_ids():
                    if document_id in indexed_ids:
                        continue
                    raw = self._chunk_store.read_bytes(document_id)
                    if raw is None:
                        continue
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                    except (UnicodeError, json.JSONDecodeError):
                        payload = None
                    if isinstance(payload, list) and not payload:
                        continue
                    logger.warning(
                        "发现孤立 chunk 文件并清理: document_id=%s",
                        document_id,
                    )
                    self._chunk_store.delete(document_id)
        except VectorStoreError:
            logger.error("索引启动检查失败，保留现有 chunk 文件")
        except Exception as exc:
            logger.warning("孤立 chunk 检查失败: %s", type(exc).__name__)

    @staticmethod
    def _canonical_id(document_id: str) -> str:
        try:
            return str(UUID(document_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise DocumentNotFoundError("文档不存在") from exc

    def _restore_chunks(self, document_id: str, old_data: bytes | None) -> None:
        try:
            self._chunk_store.restore(document_id, old_data)
        except ChunkStoreError:
            logger.critical("恢复旧 chunk 文件失败: document_id=%s", document_id)
