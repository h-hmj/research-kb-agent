"""评测数据集、样例结果与报告模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EvaluationMode = Literal["retrieval", "qa", "agent", "compare"]


class ExpectedSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_filename: str = Field(min_length=1, max_length=260)
    page_number: int = Field(gt=0)
    document_id: str | None = None

    @field_validator("original_filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        filename = value.strip()
        if not filename:
            raise ValueError("original_filename 不能为空")
        return filename


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1)
    answerable: bool
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    expected_sources: list[ExpectedSource] = Field(default_factory=list)
    expected_answer_keywords: list[str] = Field(
        default_factory=list,
        max_length=20,
    )
    notes: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("id 不能为空")
        return value

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        question = value.strip()
        if not question:
            raise ValueError("question 不能为空")
        if len(question) > 2000:
            raise ValueError("question 不能超过 2000 字符")
        return question

    @field_validator("expected_answer_keywords")
    @classmethod
    def validate_keywords(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            keyword = item.strip()
            if not keyword:
                raise ValueError("expected_answer_keywords 不能包含空字符串")
            if len(keyword) > 100:
                raise ValueError("单个关键词不能超过 100 字符")
            normalized.append(keyword)
        return normalized

    @field_validator("expected_sources")
    @classmethod
    def validate_expected_sources(
        cls,
        value: list[ExpectedSource],
        info,
    ) -> list[ExpectedSource]:
        answerable = info.data.get("answerable")
        if answerable is True and not value:
            raise ValueError("answerable=true 时 expected_sources 不能为空")
        if answerable is False and value:
            raise ValueError("answerable=false 时 expected_sources 必须为空")
        return value


class EvalDataset(BaseModel):
    name: str
    sha256: str
    cases: list[EvalCase]


class DatasetSummary(BaseModel):
    name: str
    sha256: str
    total_cases: int
    answerable_cases: int
    unanswerable_cases: int


class CaseResult(BaseModel):
    case_id: str
    expected_answerable: bool
    actual_status: Literal["answered", "refused", "retrieval", "error"]
    retrieval_hit: bool | None = None
    first_relevant_rank: int | None = None
    citation_correct_count: int = 0
    citation_total_count: int = 0
    expected_source_count: int = 0
    matched_expected_source_count: int = 0
    keyword_hit: bool | None = None
    rewrite_attempted: bool = False
    retry_success: bool | None = None
    error_code: str | None = None
    question_prefix: str | None = None
    answer_prefix: str | None = None


class EvaluationReport(BaseModel):
    run_id: str
    created_at: str
    status: Literal["success", "failed"]
    mode: EvaluationMode
    dataset: DatasetSummary
    configuration: dict[str, Any]
    metrics: dict[str, Any]
    case_results: list[CaseResult] | dict[str, list[CaseResult]]
    error_case_count: int = 0
    limitations: list[str] = Field(default_factory=list)


class EvaluationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_name: str = Field(min_length=1, max_length=260)
    mode: EvaluationMode
    top_k: int = Field(default=5, ge=1, le=20)


class EvaluationRunResponse(BaseModel):
    run_id: str
    mode: EvaluationMode
    summary: dict[str, Any]
    report_available: bool = True


class EvaluationListItem(BaseModel):
    run_id: str
    created_at: str
    mode: str
    status: str
    dataset_name: str
    total_cases: int
    answerable_cases: int
    unanswerable_cases: int
    error_case_count: int
    metrics: dict[str, Any]
