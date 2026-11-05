"""第四阶段问答、证据与引用模型。"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

QAStatus = Literal["answered", "refused"]


class QARequest(BaseModel):
    """单轮问答请求。"""

    question: str = Field(min_length=1, description="用户问题")
    top_k: int | None = Field(default=None, ge=1, le=20)
    document_ids: list[str] | None = Field(default=None)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        question = value.strip()
        if not question:
            raise ValueError("question 不能为空")
        if len(question) > 2000:
            raise ValueError("question 不能超过 2000 字符")
        return question

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


class EvidenceChunk(BaseModel):
    """实际送入 LLM 的证据块。"""

    chunk_id: str
    document_id: str
    original_filename: str
    page_number: int = Field(ge=1)
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    score: float


class QACitation(BaseModel):
    """服务端生成的页码级引用。"""

    citation_id: str
    chunk_id: str
    document_id: str
    original_filename: str
    page_number: int = Field(ge=1)
    chunk_index: int = Field(ge=0)
    text: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    score: float


class QARetrievalInfo(BaseModel):
    """问答使用的检索摘要。"""

    query: str
    retrieved_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    top_k: int = Field(ge=1, le=20)


class QAResponse(BaseModel):
    """单轮问答响应。"""

    status: QAStatus
    answer: str
    citations: list[QACitation]
    retrieval: QARetrievalInfo
    refusal_reason: str | None = None
