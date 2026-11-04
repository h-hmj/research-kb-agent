"""API 路由集合。"""

from .documents import router as documents_router
from .health import router as health_router
from .retrieval import router as retrieval_router

__all__ = ["documents_router", "health_router", "retrieval_router"]
