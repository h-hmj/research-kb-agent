"""文档上传、解析、查询和删除的协调服务。"""

import logging
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

from ..core.config import Settings
from ..schemas.documents import DocumentDetail, DocumentListResponse
from ..storage.file_storage import FileStorage, FileTooLargeError
from ..storage.metadata_store import MetadataStore, MetadataStoreError
from .metadata_service import MetadataService
from .pdf_service import PDFParseError, PDFService

logger = logging.getLogger(__name__)

_ALLOWED_PDF_CONTENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "application/pdf",
        "application/x-pdf",
        "application/octet-stream",
        "binary/octet-stream",
    }
)


class DocumentServiceError(Exception):
    """文档业务异常基类，携带对外的 HTTP 状态码。"""

    status_code: int = 500
    default_message: str = "服务器内部错误"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class DocumentValidationError(DocumentServiceError):
    """文件名、类型或 PDF 内容不符合要求。"""

    status_code = 400
    default_message = "文件格式错误"


class DocumentTooLargeError(DocumentServiceError):
    """上传文件超过配置大小。"""

    status_code = 413
    default_message = "上传文件过大"


class DocumentNotFoundError(DocumentServiceError):
    """文档不存在。"""

    status_code = 404
    default_message = "文档不存在"


class DocumentStorageError(DocumentServiceError):
    """本地文件或元数据读写失败。"""

    status_code = 500
    default_message = "服务器内部错误"


class DocumentService:
    """协调 PDF 校验、保存、解析与元数据管理。"""

    def __init__(self, settings: Settings) -> None:
        self._max_upload_size_mb = settings.max_upload_size_mb
        self._max_upload_size_bytes = settings.max_upload_size_mb * 1024 * 1024
        self._file_storage = FileStorage(settings.documents_dir)
        self._metadata_service = MetadataService(MetadataStore(settings.metadata_dir))
        self._pdf_service = PDFService()
        self._index_cleaner: Callable[[str], None] | None = None

    def set_index_cleaner(self, cleaner: Callable[[str], None]) -> None:
        """注入删除文档时的索引清理回调。"""
        self._index_cleaner = cleaner

    @staticmethod
    def _sanitize_original_filename(filename: str | None) -> str:
        """提取安全的基础文件名，拒绝空名称、控制字符和非 PDF 扩展名。"""
        raw_filename = (filename or "").strip()
        if not raw_filename:
            raise DocumentValidationError("文件名不能为空")

        normalized = raw_filename.replace("\\", "/")
        base_name = normalized.rsplit("/", maxsplit=1)[-1].strip()
        if base_name in {"", ".", ".."} or "\x00" in base_name:
            raise DocumentValidationError("文件名无效")
        if any(ord(character) < 32 for character in base_name):
            raise DocumentValidationError("文件名包含非法字符")
        if len(base_name) > 255:
            raise DocumentValidationError("文件名过长")
        if Path(base_name).suffix.lower() != ".pdf":
            raise DocumentValidationError("只支持 PDF 文件")

        return base_name

    @staticmethod
    def _validate_content_type(content_type: str | None) -> None:
        """Content-Type 存在且明确不是 PDF 时拒绝上传。"""
        normalized = (content_type or "").split(";", maxsplit=1)[0].strip().lower()
        if normalized and normalized not in _ALLOWED_PDF_CONTENT_TYPES:
            raise DocumentValidationError("只支持 PDF 文件")

    @staticmethod
    def _canonical_document_id(document_id: str) -> str:
        """将外部文档 ID 规范化为 UUID；非法 ID 按不存在处理。"""
        try:
            return str(UUID(document_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise DocumentNotFoundError("文档不存在") from exc

    def _cleanup_failed_file(self, document_id: str) -> None:
        """尽力清理失败上传留下的 PDF 文件。"""
        try:
            self._file_storage.delete(document_id)
        except OSError as exc:
            logger.warning(
                "清理失败的上传文件时出错: document_id=%s (%s)",
                document_id,
                type(exc).__name__,
            )

    async def create_document(
        self,
        filename: str | None,
        content_type: str | None,
        chunks: AsyncIterator[bytes],
    ) -> DocumentDetail:
        """校验并保存上传内容，解析 PDF 后原子写入元数据。"""
        original_filename = self._sanitize_original_filename(filename)
        self._validate_content_type(content_type)

        document_id = str(uuid4())
        try:
            file_size = await self._file_storage.save_chunks(
                chunks=chunks,
                document_id=document_id,
                max_bytes=self._max_upload_size_bytes,
            )
        except FileTooLargeError as exc:
            raise DocumentTooLargeError(
                f"文件大小不能超过 {self._max_upload_size_mb} MB"
            ) from exc
        except OSError as exc:
            logger.error("保存上传文件失败: document_id=%s", document_id)
            raise DocumentStorageError("文档保存失败") from exc

        try:
            pdf_data = self._file_storage.read_bytes(document_id)
        except OSError as exc:
            self._cleanup_failed_file(document_id)
            logger.error("读取上传文件失败: document_id=%s", document_id)
            raise DocumentStorageError("文档读取失败") from exc

        try:
            pages = self._pdf_service.parse(pdf_data)
        except PDFParseError as exc:
            self._cleanup_failed_file(document_id)
            raise DocumentValidationError("PDF 文件损坏或无法解析") from exc

        document = DocumentDetail(
            id=document_id,
            original_filename=original_filename,
            stored_filename=f"{document_id}.pdf",
            file_size=file_size,
            page_count=len(pages),
            created_at=datetime.now(timezone.utc).isoformat(),
            status="processed",
            index_status="not_indexed",
            pages=pages,
        )

        try:
            self._metadata_service.save(document)
        except MetadataStoreError as exc:
            self._cleanup_failed_file(document_id)
            logger.error("保存文档元数据失败: document_id=%s", document_id)
            raise DocumentStorageError("文档元数据保存失败") from exc

        return document

    def list_documents(self, page: int, page_size: int) -> DocumentListResponse:
        """按创建时间倒序返回分页文档列表。"""
        try:
            documents = self._metadata_service.list_all()
        except MetadataStoreError as exc:
            logger.error("读取文档列表失败")
            raise DocumentStorageError("文档列表读取失败") from exc

        documents.sort(key=lambda item: item.created_at, reverse=True)
        total = len(documents)
        start = (page - 1) * page_size
        end = start + page_size

        return DocumentListResponse(
            items=documents[start:end],
            page=page,
            page_size=page_size,
            total=total,
        )

    def get_document(self, document_id: str) -> DocumentDetail:
        """按 UUID 获取文档详情。"""
        canonical_id = self._canonical_document_id(document_id)
        try:
            document = self._metadata_service.get(canonical_id)
        except MetadataStoreError as exc:
            logger.error("读取文档详情失败: document_id=%s", canonical_id)
            raise DocumentStorageError("文档详情读取失败") from exc

        if document is None:
            raise DocumentNotFoundError("文档不存在")
        return document

    def delete_document(self, document_id: str) -> None:
        """删除索引、PDF 与元数据；目标路径均由 UUID 派生。"""
        canonical_id = self._canonical_document_id(document_id)
        try:
            document = self._metadata_service.get(canonical_id)
        except MetadataStoreError as exc:
            logger.error("读取待删除文档失败: document_id=%s", canonical_id)
            raise DocumentStorageError("文档删除失败") from exc

        if document is None:
            raise DocumentNotFoundError("文档不存在")

        if self._index_cleaner is not None:
            self._index_cleaner(canonical_id)

        try:
            self._file_storage.delete(canonical_id)
        except OSError as exc:
            logger.error("删除文档文件失败: document_id=%s", canonical_id)
            raise DocumentStorageError("文档删除失败") from exc

        try:
            self._metadata_service.delete(canonical_id)
        except MetadataStoreError as exc:
            logger.error("删除文档元数据失败: document_id=%s", canonical_id)
            raise DocumentStorageError("文档删除失败") from exc
