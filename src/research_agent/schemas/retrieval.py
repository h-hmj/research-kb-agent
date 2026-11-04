"""第三阶段分块、索引和检索的 Pydantic 模型。"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class DocumentChunk(BaseModel):
    """页码级文本块，同时作为 chunk JSON 和 manifest 的数据结构。"""

    id: str = Field(description="稳定且唯一的 chunk ID")
    document_id: str = Field(description="所属文档 UUID")
    original_filename: str = Field(description="文档原始文件名")
    page_number: int = Field(ge=1, description="从 1 开始的页码")
    chunk_index: int = Field(ge=0, description="页内 chunk 序号，从 0 开始")
    text: str = Field(min_length=1, description="chunk 原文")
    char_start: int = Field(ge=0, description="在该页文本中的起始位置")
    char_end: int = Field(ge=0, description="在该页文本中的结束位置，不包含")
    character_count: int = Field(ge=1, description="字符数")

    @model_validator(mode="after")
    def validate_ranges(self) -> "DocumentChunk":
        """字符范围和字符数必须与原文一致。"""
        if self.char_end <= self.char_start:
            raise ValueError("char_end 必须大于 char_start")
        if self.char_end - self.char_start != len(self.text):
            raise ValueError("字符范围必须与 text 长度一致")
        if self.character_count != len(self.text):
            raise ValueError("character_count 必须等于 text 长度")
        return self


class IndexDocumentResponse(BaseModel):
    """单文档索引结果。"""

    document_id: str
    status: Literal["indexed"] = "indexed"
    page_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    embedding_dimension: int = Field(ge=0)


class RetrievalSearchRequest(BaseModel):
    """自然语言检索请求。"""

    query: str = Field(min_length=1, description="自然语言查询")
    top_k: int | None = Field(default=None, ge=1, le=20)
    document_ids: list[str] | None = Field(
        default=None,
        description="可选的文档 UUID 过滤列表",
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        query = value.strip()
        if not query:
            raise ValueError("query 不能为空")
        return query

    @field_validator("document_ids")
    @classmethod
    def validate_document_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for document_id in value:
            try:
                normalized.append(str(UUID(document_id)))
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValueError("document_ids 包含非法 UUID") from exc
        return normalized


class RetrievalResult(BaseModel):
    """带原文引用的检索结果。"""

    chunk_id: str
    document_id: str
    original_filename: str
    page_number: int = Field(ge=1)
    chunk_index: int = Field(ge=0)
    text: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    score: float


class RetrievalSearchResponse(BaseModel):
    """检索响应，不包含生成式回答。"""

    query: str
    results: list[RetrievalResult]
