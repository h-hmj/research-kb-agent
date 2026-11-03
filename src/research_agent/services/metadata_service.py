"""文档元数据的领域层服务。"""

import logging

from pydantic import ValidationError

from ..schemas.documents import DocumentDetail, DocumentSummary
from ..storage.metadata_store import MetadataStore, MetadataStoreError

logger = logging.getLogger(__name__)


class MetadataService:
    """在低层元数据存储和 Pydantic 模型之间进行转换。"""

    def __init__(self, store: MetadataStore) -> None:
        self._store = store

    def save(self, document: DocumentDetail) -> None:
        """保存完整的文档详情。"""
        self._store.write(document.id, document.model_dump(mode="json"))

    def get(self, document_id: str) -> DocumentDetail | None:
        """读取并校验单个文档详情。"""
        payload = self._store.read(document_id)
        if payload is None:
            return None

        try:
            return DocumentDetail.model_validate(payload)
        except ValidationError as exc:
            raise MetadataStoreError("文档元数据内容无效") from exc

    def list_all(self) -> list[DocumentSummary]:
        """读取全部元数据，跳过结构不合法的记录。"""
        summaries: list[DocumentSummary] = []
        for payload in self._store.iter_all():
            try:
                summaries.append(DocumentSummary.model_validate(payload))
            except ValidationError:
                logger.warning("跳过结构无效的文档元数据")
        return summaries

    def delete(self, document_id: str) -> bool:
        """删除元数据文件。"""
        return self._store.delete(document_id)
