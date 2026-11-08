"""API 路由集合。"""

from .agent import router as agent_router
from .documents import router as documents_router
from .health import router as health_router
from .qa import router as qa_router
from .retrieval import router as retrieval_router
from .tools import router as tools_router

__all__ = [
    "agent_router",
    "documents_router",
    "health_router",
    "qa_router",
    "retrieval_router",
    "tools_router",
]
