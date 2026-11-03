"""根路径和健康检查接口测试。"""

import httpx
import pytest

pytestmark = pytest.mark.anyio


async def test_root(client: httpx.AsyncClient) -> None:
    """根路径应返回项目名称、版本和说明。"""
    response = await client.get("/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "科研知识库与实验助理 Agent"
    assert payload["version"] == "0.1.0"
    assert payload["description"]


async def test_health(client: httpx.AsyncClient) -> None:
    """健康检查应返回 200 和约定的状态字段值。"""
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "research-agent",
        "version": "0.1.0",
    }


async def test_health_response_fields(client: httpx.AsyncClient) -> None:
    """健康检查响应应只包含约定的三个字段，且类型正确。"""
    response = await client.get("/api/v1/health")
    payload = response.json()

    assert set(payload) == {"status", "service", "version"}
    assert isinstance(payload["status"], str)
    assert isinstance(payload["service"], str)
    assert isinstance(payload["version"], str)
