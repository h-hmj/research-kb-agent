"""FastAPI 应用入口。"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api.routes.documents import router as documents_router
from .api.routes.health import router as health_router
from .core.config import Settings, get_settings
from .core.logging import configure_logging
from .schemas.common import RootResponse
from .services.document_service import DocumentService

logger = logging.getLogger(__name__)

PROJECT_DESCRIPTION = "面向论文与实验记录的知识库与实验助理后端（第二阶段：文档接入基础）。"


def create_app(custom_settings: Settings | None = None) -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    settings = custom_settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """创建本地数据目录，并在应用生命周期边界输出日志。"""
        for directory in (
            settings.data_dir,
            settings.documents_dir,
            settings.metadata_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        logger.info(
            "应用启动: %s v%s (debug=%s, api_prefix=%s)",
            settings.app_name,
            settings.app_version,
            settings.debug,
            settings.api_prefix,
        )
        yield
        logger.info("应用关闭: %s", settings.app_name)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=PROJECT_DESCRIPTION,
        debug=settings.debug,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.document_service = DocumentService(settings)

    app.include_router(health_router, prefix=settings.api_prefix)
    app.include_router(documents_router, prefix=settings.api_prefix)

    @app.get(
        "/",
        response_model=RootResponse,
        tags=["meta"],
        summary="项目信息",
        description="返回项目名称、版本和说明。",
    )
    async def read_root() -> RootResponse:
        """返回项目的基本信息。"""
        return RootResponse(
            name=settings.app_name,
            version=settings.app_version,
            description=PROJECT_DESCRIPTION,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        """记录未处理异常，并返回不暴露内部细节的 500 响应。"""
        logger.error(
            "请求处理异常: %s %s",
            request.method,
            request.url.path,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
        )

    return app


app = create_app()
