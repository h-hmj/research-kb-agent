"""本地基础可观测性接口。"""

from typing import Any

from fastapi import APIRouter, Request

from ...services.metrics_service import MetricsService

router = APIRouter(prefix="/observability", tags=["observability"])


@router.get(
    "/metrics",
    summary="读取进程内基础指标",
    description="只读本地计数，不触发 LLM、Embedding 或 Docker 请求。",
)
async def metrics(request: Request) -> dict[str, Any]:
    service: MetricsService = request.app.state.metrics
    return service.snapshot()
