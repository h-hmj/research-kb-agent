"""API 路由集合。"""

from .documents import router as documents_router
from .health import router as health_router
from .qa import router as qa_router
from .retrieval import router as retrieval_router

__all__ = [
    "documents_router",
    "health_router",
    "qa_router",
    "retrieval_router",
]
