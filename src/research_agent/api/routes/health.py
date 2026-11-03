"""健康检查路由。"""

from fastapi import APIRouter, Request

from ...core.config import SERVICE_NAME, Settings
from ...schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="健康检查",
    description="返回服务状态、服务标识和当前版本，用于存活探针。",
)
async def health_check(request: Request) -> HealthResponse:
    """返回固定的健康状态和当前应用配置中的版本。"""
    settings: Settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=settings.app_version,
    )
