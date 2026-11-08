"""search_knowledge_base 工具。"""

from __future__ import annotations

from ..schemas.tools import SearchToolArgs
from ..services.retrieval_service import RetrievalService
from .base import ToolOutcome


class KnowledgeBaseTool:
    """复用第三阶段检索，不调用 LLM、不重写 FAISS。"""

    name = "search_knowledge_base"
    arguments_model = SearchToolArgs

    def __init__(self, retrieval_service: RetrievalService) -> None:
        self._retrieval = retrieval_service

    def run(self, arguments: SearchToolArgs) -> ToolOutcome:
        response = self._retrieval.search(
            query=arguments.query,
            top_k=arguments.top_k,
            document_ids=arguments.document_ids,
        )
        return ToolOutcome(
            status="success",
            result=response.model_dump(),
            llm_called=False,
            retrieval_count=len(response.results),
            evidence_count=0,
        )
