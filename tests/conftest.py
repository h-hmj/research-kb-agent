"""共享测试配置：所有测试使用临时数据目录和 ASGI 传输层。"""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from research_agent.core.config import Settings
from research_agent.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    """只运行 asyncio 后端，避免额外安装 trio。"""
    return "asyncio"


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """构造隔离的测试配置，禁止访问项目的真实 data 目录。"""
    data_dir = tmp_path / "data"
    return Settings(
        _env_file=None,
        app_name="科研知识库与实验助理 Agent",
        app_version="0.1.0",
        debug=False,
        api_prefix="/api/v1",
        log_level="INFO",
        data_dir=data_dir,
        max_upload_size_mb=1,
        documents_dir=data_dir / "documents",
        metadata_dir=data_dir / "metadata",
        chunks_dir=data_dir / "chunks",
        vector_store_dir=data_dir / "vector_store",
        embedding_model_path=tmp_path / "models" / "missing-model",
        embedding_device="cpu",
        embedding_normalize=True,
        chunk_size=120,
        chunk_overlap=20,
        retrieval_top_k=5,
        max_retrieval_text_length=1000,
        eval_dataset_dir=tmp_path / "eval_datasets",
        evaluation_dir=tmp_path / "evaluations",
        evaluation_max_cases=100,
        evaluation_max_error_rate=0.2,
        evaluation_save_details=False,
    )


@pytest.fixture
async def client(test_settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """为每个测试创建独立应用实例，并显式执行 lifespan。"""
    test_app = create_app(test_settings)
    transport = httpx.ASGITransport(app=test_app)

    async with test_app.router.lifespan_context(test_app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as test_client:
            yield test_client
