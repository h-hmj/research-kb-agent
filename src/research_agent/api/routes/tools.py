"""统一科研工具路由。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...core.exceptions import (
    EmbeddingModelUnavailableError,
    LLMUnavailableError,
    ToolOutputInvalidError,
    ToolValidationError,
)
from ...schemas.tools import ToolRunRequest, ToolRunResponse
from ...services.embedding_service import EMBEDDING_UNAVAILABLE_DETAIL
from ...services.llm_service import LLM_UNAVAILABLE_DETAIL
from ...services.retrieval_service import RetrievalServiceError
from ...services.tool_service import ToolService

router = APIRouter(prefix="/tools", tags=["tools"])


def get_tool_service(request: Request) -> ToolService:
    service: ToolService = request.app.state.tool_service
    return service


@router.post(
    "/run",
    response_model=ToolRunResponse,
    summary="执行一个白名单科研工具",
    description="工具名称由 API 显式指定，每次请求最多执行一次。",
)
async def run_tool(
    payload: ToolRunRequest,
    service: Annotated[ToolService, Depends(get_tool_service)],
) -> ToolRunResponse:
    try:
        return await service.run(
            tool_name=payload.tool_name,
            arguments=payload.arguments,
        )
    except ToolValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.detail,
        ) from exc
    except ToolOutputInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
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
    except RetrievalServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=exc.message,
        ) from exc
