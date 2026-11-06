"""第五阶段 Agent 请求、工作流摘要与响应模型。"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .qa import QACitation

AgentStatus = Literal["answered", "refused"]


class AgentAskRequest(BaseModel):
    """Agent 单轮请求；不暴露改写次数参数。"""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)
    document_ids: list[str] | None = None
    enable_rewrite: bool = True

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


class AgentWorkflow(BaseModel):
    """安全的流程摘要，不含 Prompt、模型输出或思维链。"""

    original_question: str
    final_query: str
    rewrite_attempted: bool
    rewrite_count: int = Field(ge=0, le=1)
    rewrite_changed: bool
    steps: list[str]
    initial_retrieval_count: int = Field(ge=0)
    final_retrieval_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)


class AgentAskResponse(BaseModel):
    """Agent 单轮回答或拒答。"""

    status: AgentStatus
    answer: str
    citations: list[QACitation]
    workflow: AgentWorkflow
    refusal_reason: str | None = None
