"""受控单轮问答路由。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...core.exceptions import (
    EmbeddingModelUnavailableError,
    LLMUnavailableError,
)
from ...schemas.qa import QARequest, QAResponse
from ...services.embedding_service import EMBEDDING_UNAVAILABLE_DETAIL
from ...services.llm_service import LLM_UNAVAILABLE_DETAIL
from ...services.qa_service import QAService
from ...services.retrieval_service import RetrievalServiceError

router = APIRouter(prefix="/qa", tags=["qa"])


def get_qa_service(request: Request) -> QAService:
    """从应用状态中取出问答编排服务。"""
    service: QAService = request.app.state.qa_service
    return service


@router.post(
    "/ask",
    response_model=QAResponse,
    summary="基于本地知识库单轮问答",
    description="检索证据后调用本地 LLM；证据不足时明确拒答。",
)
async def ask(
    payload: QARequest,
    service: Annotated[QAService, Depends(get_qa_service)],
) -> QAResponse:
    """执行单轮问答，返回回答和服务端生成的引用。"""
    try:
        return await service.ask(
            question=payload.question,
            top_k=payload.top_k,
            document_ids=payload.document_ids,
        )
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
    except RetrievalServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=exc.message,
        ) from exc
