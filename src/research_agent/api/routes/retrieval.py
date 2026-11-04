"""本地向量检索路由。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...schemas.retrieval import RetrievalSearchRequest, RetrievalSearchResponse
from ...services.embedding_service import (
    EMBEDDING_UNAVAILABLE_DETAIL,
    EmbeddingModelUnavailableError,
)
from ...services.retrieval_service import RetrievalService, RetrievalServiceError

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


def get_retrieval_service(request: Request) -> RetrievalService:
    """从应用状态中取出检索服务。"""
    service: RetrievalService = request.app.state.retrieval_service
    return service


@router.post(
    "/search",
    response_model=RetrievalSearchResponse,
    summary="检索相关文本块",
    description="返回文档名、文档 ID、页码、chunk 序号、原文片段和相似度分数。",
)
def search(
    payload: RetrievalSearchRequest,
    service: Annotated[RetrievalService, Depends(get_retrieval_service)],
) -> RetrievalSearchResponse:
    """执行本地向量检索，不生成回答。"""
    try:
        return service.search(
            query=payload.query,
            top_k=payload.top_k,
            document_ids=payload.document_ids,
        )
    except EmbeddingModelUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=EMBEDDING_UNAVAILABLE_DETAIL,
        ) from exc
    except RetrievalServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
        ) from exc
