"""Agent SSE 流式路由。"""

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from ...schemas.agent import AgentAskRequest
from ...services.agent_stream_service import AgentStreamService

router = APIRouter(prefix="/agent", tags=["agent"])


def get_stream_service(request: Request) -> AgentStreamService:
    service: AgentStreamService = request.app.state.agent_stream_service
    return service


@router.post(
    "/ask/stream",
    summary="LangGraph Agent SSE 流式问答",
    description="返回 workflow、token、citations、final 或 error 事件。",
)
async def ask_stream(
    payload: AgentAskRequest,
    request: Request,
    service: Annotated[AgentStreamService, Depends(get_stream_service)],
) -> StreamingResponse:
    settings = request.app.state.settings
    if not settings.enable_streaming:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="流式接口未启用。",
        )
    request_id = getattr(request.state, "request_id", None) or str(uuid4())
    return StreamingResponse(
        service.stream(
            question=payload.question,
            top_k=payload.top_k,
            document_ids=payload.document_ids,
            enable_rewrite=payload.enable_rewrite,
            request_id=request_id,
        ),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )
