"""第六阶段科研工具请求、输出和统一响应模型。"""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .qa import QACitation
from .retrieval import RetrievalSearchResponse

ToolName = Literal[
    "search_knowledge_base",
    "generate_experiment_checklist",
    "summarize_meeting_notes",
]
ToolStatus = Literal["success", "refused"]


def _normalize_document_ids(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    normalized: list[str] = []
    for document_id in value:
        try:
            normalized.append(str(UUID(document_id)))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("document_ids 包含非法 UUID") from exc
    return normalized


class SearchToolArgs(BaseModel):
    """search_knowledge_base 输入。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[str] | None = None

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        query = value.strip()
        if not query:
            raise ValueError("query 不能为空")
        if len(query) > 2000:
            raise ValueError("query 不能超过 2000 字符")
        return query

    @field_validator("document_ids")
    @classmethod
    def validate_document_ids(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_document_ids(value)


class ChecklistToolArgs(BaseModel):
    """generate_experiment_checklist 输入。"""

    model_config = ConfigDict(extra="forbid")

    experiment_goal: str = Field(min_length=1)
    constraints: list[str] | None = Field(default=None, max_length=20)
    document_ids: list[str] | None = None
    top_k: int = Field(default=5, ge=1, le=20)

    @field_validator("experiment_goal")
    @classmethod
    def validate_goal(cls, value: str) -> str:
        goal = value.strip()
        if not goal:
            raise ValueError("experiment_goal 不能为空")
        if len(goal) > 1000:
            raise ValueError("experiment_goal 不能超过 1000 字符")
        return goal

    @field_validator("constraints")
    @classmethod
    def validate_constraints(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            text = item.strip()
            if not text:
                raise ValueError("constraints 不能包含空字符串")
            if len(text) > 500:
                raise ValueError("单条 constraint 不能超过 500 字符")
            normalized.append(text)
        return normalized

    @field_validator("document_ids")
    @classmethod
    def validate_document_ids(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_document_ids(value)


class MeetingSummaryToolArgs(BaseModel):
    """summarize_meeting_notes 输入。"""

    model_config = ConfigDict(extra="forbid")

    meeting_text: str = Field(min_length=1, max_length=20000)
    meeting_title: str | None = Field(default=None, max_length=200)
    focus: str | None = Field(default=None, max_length=500)

    @field_validator("meeting_text")
    @classmethod
    def validate_meeting_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("meeting_text 不能为空")
        if len(text) > 20000:
            raise ValueError("meeting_text 不能超过 20000 字符")
        return value

    @field_validator("meeting_title", "focus")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class ChecklistLLMItem(BaseModel):
    """LLM 输出的 checklist 条目，evidence_ids 尚未转换为 citations。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    category: Literal["preparation", "operation", "recording", "review"]
    content: str = Field(min_length=1, max_length=500)
    priority: Literal["high", "medium", "low"]
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)


class ChecklistLLMOutput(BaseModel):
    """LLM 输出的 checklist JSON。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    items: list[ChecklistLLMItem] = Field(min_length=1, max_length=30)
    notes: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, value: list[str]) -> list[str]:
        if any(not note.strip() or len(note) > 500 for note in value):
            raise ValueError("notes 每条必须非空且不超过 500 字符")
        return value


class ChecklistItem(BaseModel):
    """服务端转换后的 checklist 条目。"""

    id: str
    category: Literal["preparation", "operation", "recording", "review"]
    content: str
    priority: Literal["high", "medium", "low"]
    citations: list[QACitation]


class ChecklistResult(BaseModel):
    """checklist 成功结果。"""

    title: str
    items: list[ChecklistItem]
    notes: list[str]


class ChecklistRefusalResult(BaseModel):
    """checklist 拒答结果，明确返回空 checklist。"""

    checklist: list = Field(default_factory=list)


class MeetingLLMDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=1000)
    source_segment_ids: list[str] = Field(min_length=1)


class MeetingLLMActionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1, max_length=1000)
    owner: str | None = None
    deadline: str | None = None
    source_segment_ids: list[str] = Field(min_length=1)


class MeetingLLMRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=1000)
    source_segment_ids: list[str] = Field(min_length=1)


class MeetingLLMQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=1000)
    source_segment_ids: list[str] = Field(min_length=1)


class MeetingLLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=500)
    decisions: list[MeetingLLMDecision] = Field(
        default_factory=list,
        max_length=20,
    )
    action_items: list[MeetingLLMActionItem] = Field(
        default_factory=list,
        max_length=20,
    )
    risks: list[MeetingLLMRisk] = Field(default_factory=list, max_length=20)
    open_questions: list[MeetingLLMQuestion] = Field(
        default_factory=list,
        max_length=20,
    )


class MeetingCitation(BaseModel):
    segment_id: str
    text: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)


class MeetingDecision(BaseModel):
    content: str
    citations: list[MeetingCitation]


class MeetingActionItem(BaseModel):
    task: str
    owner: str | None
    deadline: str | None
    citations: list[MeetingCitation]


class MeetingRisk(BaseModel):
    content: str
    citations: list[MeetingCitation]


class MeetingOpenQuestion(BaseModel):
    content: str
    citations: list[MeetingCitation]


class MeetingSummaryResult(BaseModel):
    meeting_title: str | None
    summary: str
    decisions: list[MeetingDecision]
    action_items: list[MeetingActionItem]
    risks: list[MeetingRisk]
    open_questions: list[MeetingOpenQuestion]


class ToolRunRequest(BaseModel):
    """统一工具请求；arguments 由对应工具白名单 Schema 验证。"""

    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any]


class ToolWorkflow(BaseModel):
    steps: list[str]
    llm_called: bool
    retrieval_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)


class ToolRunResponse(BaseModel):
    """统一安全响应外壳。"""

    status: ToolStatus
    tool_name: ToolName
    result: (
        RetrievalSearchResponse
        | ChecklistResult
        | ChecklistRefusalResult
        | MeetingSummaryResult
    )
    workflow: ToolWorkflow
    refusal_reason: str | None = None
