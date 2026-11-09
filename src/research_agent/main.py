"""FastAPI 应用入口。"""

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api.routes.agent import router as agent_router
from .api.routes.agent_stream import router as agent_stream_router
from .api.routes.documents import router as documents_router
from .api.routes.health import router as health_router
from .api.routes.observability import router as observability_router
from .api.routes.qa import router as qa_router
from .api.routes.retrieval import router as retrieval_router
from .api.routes.tools import router as tools_router
from .core.config import Settings, get_settings
from .core.logging import configure_logging
from .core.request_context import (
    reset_request_id,
    safe_request_id,
    set_request_id,
)
from .schemas.common import RootResponse
from .services.agent_service import AgentService
from .services.agent_stream_service import AgentStreamService
from .services.checklist_service import ChecklistService
from .services.citation_service import CitationService
from .services.document_service import DocumentService
from .services.embedding_service import (
    EmbeddingService,
    SentenceTransformerEmbeddingService,
)
from .services.indexing_service import IndexingService
from .services.llm_service import LLMService, OpenAICompatibleLLMService
from .services.meeting_summary_service import MeetingSummaryService
from .services.metrics_service import (
    MeteredEmbeddingService,
    MeteredLLMService,
    MetricsService,
)
from .services.qa_service import QAService
from .services.query_rewrite_service import QueryRewriteService
from .services.retrieval_service import RetrievalService
from .services.tool_service import ToolService
from .storage.chunk_store import ChunkStore
from .storage.vector_store import VectorStore
from .tools.checklist_tool import ChecklistTool
from .tools.knowledge_base_tool import KnowledgeBaseTool
from .tools.meeting_summary_tool import MeetingSummaryTool
from .tools.registry import ToolDefinition, ToolRegistry

logger = logging.getLogger(__name__)

PROJECT_DESCRIPTION = (
    "面向论文与实验记录的知识库与实验助理后端"
    "（第七阶段：SSE 流式问答与基础可观测性）。"
)


def create_app(
    custom_settings: Settings | None = None,
    embedding_service: EmbeddingService | None = None,
    llm_service: LLMService | None = None,
) -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    settings = custom_settings or get_settings()
    metrics = MetricsService()
    configure_logging(
        settings.log_level,
        enable_file_logging=settings.enable_file_logging,
        log_dir=settings.log_dir,
        log_max_bytes=settings.log_max_bytes,
        log_backup_count=settings.log_backup_count,
    )

    base_embedding = embedding_service or SentenceTransformerEmbeddingService(
        model_path=settings.embedding_model_path,
        device=settings.embedding_device,
        normalize=settings.embedding_normalize,
    )
    embedding = MeteredEmbeddingService(base_embedding, metrics)
    vector_store = VectorStore(settings.vector_store_dir)
    chunk_store = ChunkStore(settings.chunks_dir)
    indexing_service = IndexingService(
        settings=settings,
        embedding_service=embedding,
        vector_store=vector_store,
        chunk_store=chunk_store,
    )
    retrieval_service = RetrievalService(
        settings=settings,
        embedding_service=embedding,
        vector_store=vector_store,
    )
    base_llm = llm_service or OpenAICompatibleLLMService(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )
    llm = MeteredLLMService(base_llm, metrics)
    citation_service = CitationService(
        max_text_length=settings.max_citation_text_length
    )
    qa_service = QAService(
        settings=settings,
        retrieval_service=retrieval_service,
        llm_service=llm,
        citation_service=citation_service,
    )
    rewrite_service = QueryRewriteService(settings, llm)
    agent_service = AgentService(
        settings=settings,
        retrieval_service=retrieval_service,
        qa_service=qa_service,
        rewrite_service=rewrite_service,
    )
    agent_stream_service = AgentStreamService(
        settings=settings,
        agent_service=agent_service,
        metrics=metrics,
    )
    checklist_service = ChecklistService(
        settings=settings,
        retrieval_service=retrieval_service,
        qa_service=qa_service,
        citation_service=citation_service,
        llm_service=llm,
    )
    meeting_service = MeetingSummaryService(settings, llm)
    tool_registry = ToolRegistry(
        [
            ToolDefinition(
                name="search_knowledge_base",
                arguments_model=KnowledgeBaseTool.arguments_model,
                runner=KnowledgeBaseTool(retrieval_service).run,
            ),
            ToolDefinition(
                name="generate_experiment_checklist",
                arguments_model=ChecklistTool.arguments_model,
                runner=ChecklistTool(checklist_service).run,
            ),
            ToolDefinition(
                name="summarize_meeting_notes",
                arguments_model=MeetingSummaryTool.arguments_model,
                runner=MeetingSummaryTool(meeting_service).run,
            ),
        ]
    )
    tool_service = ToolService(tool_registry, metrics)
    document_service = DocumentService(settings)
    document_service.set_index_cleaner(indexing_service.remove_document_index)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """创建本地数据目录，并在应用生命周期边界输出日志。"""
        for directory in (
            settings.data_dir,
            settings.documents_dir,
            settings.metadata_dir,
            settings.chunks_dir,
            settings.vector_store_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        indexing_service.reconcile_orphan_chunks()
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
    app.state.document_service = document_service
    app.state.indexing_service = indexing_service
    app.state.retrieval_service = retrieval_service
    app.state.qa_service = qa_service
    app.state.agent_service = agent_service
    app.state.agent_stream_service = agent_stream_service
    app.state.tool_service = tool_service
    app.state.metrics = metrics

    app.include_router(health_router, prefix=settings.api_prefix)
    app.include_router(documents_router, prefix=settings.api_prefix)
    app.include_router(retrieval_router, prefix=settings.api_prefix)
    app.include_router(qa_router, prefix=settings.api_prefix)
    app.include_router(agent_router, prefix=settings.api_prefix)
    app.include_router(agent_stream_router, prefix=settings.api_prefix)
    app.include_router(tools_router, prefix=settings.api_prefix)
    if settings.enable_metrics_endpoint:
        app.include_router(observability_router, prefix=settings.api_prefix)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = safe_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        token = set_request_id(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            status_code = 500
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            metrics.record_request(
                path,
                500,
                (time.perf_counter() - started) * 1000,
            )
            logger.error(
                "request_completed method=%s path=%s status=500 duration_ms=%.0f",
                request.method,
                path,
                (time.perf_counter() - started) * 1000,
            )
            reset_request_id(token)
            raise
        response.headers["X-Request-ID"] = request_id
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        duration_ms = (time.perf_counter() - started) * 1000
        metrics.record_request(path, status_code, duration_ms)
        logger.info(
            "request_completed method=%s path=%s status=%d duration_ms=%.0f",
            request.method,
            path,
            status_code,
            duration_ms,
        )
        reset_request_id(token)
        return response

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
            "unhandled_exception method=%s path=%s error=%s",
            request.method,
            request.url.path,
            type(exc).__name__,
        )
        response = JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
        )
        request_id = getattr(request.state, "request_id", None)
        if request_id:
            response.headers["X-Request-ID"] = request_id
        return response

    return app


app = create_app()
