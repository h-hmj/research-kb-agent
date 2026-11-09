"""评测编排：数据加载、三种模式、指标计算和报告。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ..core.config import Settings
from ..core.exceptions import (
    EmbeddingModelUnavailableError,
    EvaluationDatasetError,
    EvaluationLimitError,
    EvaluationRunFailedError,
    LLMUnavailableError,
)
from ..schemas.qa import QACitation
from ..schemas.retrieval import RetrievalResult
from ..services.agent_service import AgentService
from ..services.qa_service import QAService
from ..services.retrieval_service import RetrievalService
from .dataset_loader import dataset_summary, load_dataset, load_named_dataset
from .metrics import calculate_metrics, citation_counts, first_relevant_rank
from .report_service import EvaluationReportService
from .schemas import (
    CaseResult,
    EvalCase,
    EvalDataset,
    EvaluationMode,
    EvaluationReport,
)

LIMITATIONS = [
    "关键词命中率不等同于回答准确率、事实正确性或科研结论正确性。",
    "Citation Precision/Recall 只验证系统返回来源与人工标注来源的匹配。",
    "评测结果只对当前数据集、知识库、模型和配置有效。",
    "sample_eval 仅用于演示格式，不代表真实科研基准或通用模型性能。",
]


def _run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"eval-{stamp}-{uuid4().hex[:8]}"


class EvaluationService:
    """同步本地小规模评测；API 与 CLI 共用此类。"""

    def __init__(
        self,
        settings: Settings,
        retrieval_service: RetrievalService,
        qa_service: QAService,
        agent_service: AgentService,
        report_service: EvaluationReportService,
    ) -> None:
        self._settings = settings
        self._retrieval = retrieval_service
        self._qa = qa_service
        self._agent = agent_service
        self._reports = report_service

    def list_recent(self, limit: int = 20):
        return self._reports.list_recent(limit)

    def load_report(self, run_id: str) -> EvaluationReport:
        return self._reports.load(run_id)

    async def run_named(
        self,
        dataset_name: str,
        mode: EvaluationMode,
        top_k: int,
    ) -> EvaluationReport:
        dataset = load_named_dataset(
            self._settings.eval_dataset_dir,
            dataset_name,
        )
        return await self._run_dataset(dataset, mode, top_k)

    async def run_path(
        self,
        dataset_path: Path,
        mode: EvaluationMode,
        top_k: int,
    ) -> EvaluationReport:
        dataset = load_dataset(Path(dataset_path))
        return await self._run_dataset(dataset, mode, top_k)

    async def _run_dataset(
        self,
        dataset: EvalDataset,
        mode: EvaluationMode,
        top_k: int,
    ) -> EvaluationReport:
        if len(dataset.cases) > self._settings.evaluation_max_cases:
            raise EvaluationLimitError(
                "数据集样例数超过 EVALUATION_MAX_CASES。"
            )

        if mode == "compare":
            qa_results = await self._run_cases(dataset.cases, "qa", top_k)
            agent_results = await self._run_cases(
                dataset.cases,
                "agent",
                top_k,
            )
            metrics = {
                "qa": calculate_metrics(qa_results, "qa"),
                "agent": calculate_metrics(agent_results, "agent"),
            }
            case_results: list[CaseResult] | dict[str, list[CaseResult]] = {
                "qa": qa_results,
                "agent": agent_results,
            }
            all_results = qa_results + agent_results
        else:
            all_results = await self._run_cases(dataset.cases, mode, top_k)
            metrics = calculate_metrics(all_results, mode)
            case_results = all_results

        error_count = sum(
            1 for result in all_results if result.error_code is not None
        )
        error_rate = (
            error_count / len(all_results) if all_results else 0.0
        )
        status = (
            "failed"
            if error_rate > self._settings.evaluation_max_error_rate
            else "success"
        )
        now = datetime.now(timezone.utc).isoformat()
        report = EvaluationReport(
            run_id=_run_id(),
            created_at=now,
            status=status,
            mode=mode,
            dataset=dataset_summary(dataset),
            configuration={
                "top_k": top_k,
                "min_retrieval_score": self._settings.min_retrieval_score,
                "min_evidence_count": self._settings.min_evidence_count,
                "enable_query_rewrite": self._settings.enable_query_rewrite,
                "max_query_rewrite_attempts": (
                    self._settings.max_query_rewrite_attempts
                ),
            },
            metrics=metrics,
            case_results=case_results,
            error_case_count=error_count,
            limitations=LIMITATIONS,
        )
        self._reports.save(report)
        if status == "failed":
            raise EvaluationRunFailedError(
                "评测内部错误比例超过 EVALUATION_MAX_ERROR_RATE。"
            )
        return report

    async def _run_cases(
        self,
        cases: list[EvalCase],
        mode: EvaluationMode,
        top_k: int,
    ) -> list[CaseResult]:
        results: list[CaseResult] = []
        for case in cases:
            try:
                results.append(await self._evaluate_case(case, mode, top_k))
            except (EmbeddingModelUnavailableError, LLMUnavailableError):
                raise
            except Exception:
                results.append(self._error_case(case))
        return results

    async def _evaluate_case(
        self,
        case: EvalCase,
        mode: EvaluationMode,
        top_k: int,
    ) -> CaseResult:
        if mode == "retrieval":
            retrieved = self._retrieval.search(
                query=case.question,
                top_k=top_k,
                document_ids=case.document_ids or None,
            )
            rank = first_relevant_rank(
                retrieved.results,
                case.expected_sources,
            )
            return self._result(
                case,
                actual_status="retrieval",
                retrieved=retrieved.results,
                rank=rank,
                citations=[],
                answer="",
                rewrite_attempted=False,
                retry_success=None,
            )

        if mode == "qa":
            retrieved = self._retrieval.search(
                query=case.question,
                top_k=top_k,
                document_ids=case.document_ids or None,
            )
            response = await self._qa.ask(
                question=case.question,
                top_k=top_k,
                document_ids=case.document_ids or None,
            )
            rank = first_relevant_rank(
                retrieved.results,
                case.expected_sources,
            )
            return self._result(
                case,
                actual_status=response.status,
                retrieved=retrieved.results,
                rank=rank,
                citations=response.citations,
                answer=response.answer,
                rewrite_attempted=False,
                retry_success=None,
            )

        response = await self._agent.ask(
            question=case.question,
            top_k=top_k,
            document_ids=case.document_ids or None,
            enable_rewrite=True,
        )
        final_query = response.workflow.final_query or case.question
        retrieved = self._retrieval.search(
            query=final_query,
            top_k=top_k,
            document_ids=case.document_ids or None,
        )
        rank = first_relevant_rank(
            retrieved.results,
            case.expected_sources,
        )
        retry_success = (
            response.workflow.rewrite_attempted
            and response.status == "answered"
            and "retrieve_retry" in response.workflow.steps
        )
        return self._result(
            case,
            actual_status=response.status,
            retrieved=retrieved.results,
            rank=rank,
            citations=response.citations,
            answer=response.answer,
            rewrite_attempted=response.workflow.rewrite_attempted,
            retry_success=retry_success,
        )

    def _result(
        self,
        case: EvalCase,
        *,
        actual_status: str,
        retrieved: list[RetrievalResult],
        rank: int | None,
        citations: list[QACitation],
        answer: str,
        rewrite_attempted: bool,
        retry_success: bool | None,
    ) -> CaseResult:
        correct, total, matched = citation_counts(
            citations,
            case.expected_sources,
        )
        keywords = case.expected_answer_keywords
        keyword_hit = None
        if (
            case.answerable
            and actual_status == "answered"
            and keywords
        ):
            lowered = answer.lower()
            keyword_hit = all(keyword.lower() in lowered for keyword in keywords)
        return CaseResult(
            case_id=case.id,
            expected_answerable=case.answerable,
            actual_status=actual_status,  # type: ignore[arg-type]
            retrieval_hit=rank is not None,
            first_relevant_rank=rank,
            citation_correct_count=correct,
            citation_total_count=total,
            expected_source_count=len(case.expected_sources),
            matched_expected_source_count=matched,
            keyword_hit=keyword_hit,
            rewrite_attempted=rewrite_attempted,
            retry_success=retry_success,
            error_code=None,
            question_prefix=(
                case.question[:200]
                if self._settings.evaluation_save_details
                else None
            ),
            answer_prefix=(
                answer[:500]
                if self._settings.evaluation_save_details
                else None
            ),
        )

    @staticmethod
    def _error_case(case: EvalCase) -> CaseResult:
        return CaseResult(
            case_id=case.id,
            expected_answerable=case.answerable,
            actual_status="error",
            expected_source_count=len(case.expected_sources),
            error_code="internal_error",
        )
