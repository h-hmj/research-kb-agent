"""本地评测运行、列表和报告读取路由。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...core.exceptions import (
    EmbeddingModelUnavailableError,
    EvaluationDatasetError,
    EvaluationLimitError,
    EvaluationNotFoundError,
    EvaluationReportError,
    EvaluationRunFailedError,
    LLMUnavailableError,
)
from ...evaluation.schemas import (
    EvaluationListItem,
    EvaluationReport,
    EvaluationRunRequest,
    EvaluationRunResponse,
)
from ...services.embedding_service import EMBEDDING_UNAVAILABLE_DETAIL
from ...services.llm_service import LLM_UNAVAILABLE_DETAIL
from ...evaluation.evaluator import EvaluationService

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


def get_evaluation_service(request: Request) -> EvaluationService:
    service: EvaluationService = request.app.state.evaluation_service
    return service


@router.post(
    "/run",
    response_model=EvaluationRunResponse,
    summary="运行本地评测",
    description="同步执行小型数据集；不适合生产大批量任务。",
)
async def run_evaluation(
    payload: EvaluationRunRequest,
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> EvaluationRunResponse:
    try:
        report = await service.run_named(
            dataset_name=payload.dataset_name,
            mode=payload.mode,
            top_k=payload.top_k,
        )
        return EvaluationRunResponse(
            run_id=report.run_id,
            mode=report.mode,
            summary={
                "status": report.status,
                "metrics": report.metrics,
                "error_case_count": report.error_case_count,
            },
        )
    except (EvaluationDatasetError, EvaluationLimitError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.detail,
        ) from exc
    except EmbeddingModelUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=EMBEDDING_UNAVAILABLE_DETAIL,
        ) from exc
    except LLMUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=LLM_UNAVAILABLE_DETAIL,
        ) from exc
    except EvaluationRunFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=exc.detail,
        ) from exc


@router.get(
    "",
    response_model=list[EvaluationListItem],
    summary="最近评测列表",
)
async def list_evaluations(
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> list[EvaluationListItem]:
    return service.list_recent()


@router.get(
    "/{run_id}",
    response_model=EvaluationReport,
    summary="读取单次评测报告",
)
async def get_evaluation(
    run_id: str,
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> EvaluationReport:
    try:
        return service.load_report(run_id)
    except EvaluationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="评测报告不存在",
        ) from exc
    except EvaluationReportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="评测报告读取失败",
        ) from exc
