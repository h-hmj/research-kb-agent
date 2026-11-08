"""FastAPI 应用入口。"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api.routes.agent import router as agent_router
from .api.routes.documents import router as documents_router
from .api.routes.health import router as health_router
from .api.routes.qa import router as qa_router
from .api.routes.retrieval import router as retrieval_router
from .api.routes.tools import router as tools_router
from .core.config import Settings, get_settings
from .core.logging import configure_logging
from .schemas.common import RootResponse
from .services.agent_service import AgentService
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
    "（第六阶段：白名单科研工具调用）。"
)


def create_app(
    custom_settings: Settings | None = None,
    embedding_service: EmbeddingService | None = None,
    llm_service: LLMService | None = None,
) -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    settings = custom_settings or get_settings()
    configure_logging(settings.log_level)

    embedding = embedding_service or SentenceTransformerEmbeddingService(
        model_path=settings.embedding_model_path,
        device=settings.embedding_device,
        normalize=settings.embedding_normalize,
    )
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
    llm = llm_service or OpenAICompatibleLLMService(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )
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
    tool_service = ToolService(tool_registry)
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
    app.state.tool_service = tool_service

    app.include_router(health_router, prefix=settings.api_prefix)
    app.include_router(documents_router, prefix=settings.api_prefix)
    app.include_router(retrieval_router, prefix=settings.api_prefix)
    app.include_router(qa_router, prefix=settings.api_prefix)
    app.include_router(agent_router, prefix=settings.api_prefix)
    app.include_router(tools_router, prefix=settings.api_prefix)

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
