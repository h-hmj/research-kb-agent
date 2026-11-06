"""LangGraph Agent 单轮问答路由。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...core.exceptions import (
    EmbeddingModelUnavailableError,
    LLMUnavailableError,
)
from ...schemas.agent import AgentAskRequest, AgentAskResponse
from ...services.agent_service import AgentService
from ...services.embedding_service import EMBEDDING_UNAVAILABLE_DETAIL
from ...services.llm_service import LLM_UNAVAILABLE_DETAIL
from ...services.retrieval_service import RetrievalServiceError

router = APIRouter(prefix="/agent", tags=["agent"])


def get_agent_service(request: Request) -> AgentService:
    """从应用状态中取出 Agent 编排服务。"""
    service: AgentService = request.app.state.agent_service
    return service


@router.post(
    "/ask",
    response_model=AgentAskResponse,
    summary="LangGraph 检索失败改写与二次检索",
    description=(
        "初次证据不足时最多改写一次并二次检索；仍不足则明确拒答。"
    ),
)
async def ask(
    payload: AgentAskRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentAskResponse:
    """执行一次有界 LangGraph 工作流。"""
    try:
        return await service.ask(
            question=payload.question,
            top_k=payload.top_k,
            document_ids=payload.document_ids,
            enable_rewrite=payload.enable_rewrite,
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
