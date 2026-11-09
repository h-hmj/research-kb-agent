"""第七阶段：Request ID、安全日志和进程内指标测试。"""

from __future__ import annotations

import json
import logging
import re

import pytest

from research_agent.core.config import Settings
from research_agent.core.logging import configure_logging
from research_agent.main import create_app
from tests.test_qa import FakeEmbeddingService, index_document, upload_pdf
from tests.test_streaming import (
    FakeStreamingLLM,
    parse_sse,
    stream_ask,
    stream_client,
)

pytestmark = pytest.mark.anyio

METRICS_URL = "/api/v1/observability/metrics"


async def test_request_id_generated_and_returned(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"stream_heartbeat_seconds": 0})
    async with stream_client(
        settings,
        FakeEmbeddingService(),
        FakeStreamingLLM(),
    ) as context:
        response = await context.client.get("/api/v1/health")
        request_id = response.headers.get("x-request-id")

        assert response.status_code == 200
        assert request_id
        assert re.fullmatch(r"[0-9a-f-]{36}", request_id)


async def test_safe_client_request_id_is_preserved(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"stream_heartbeat_seconds": 0})
    async with stream_client(
        settings,
        FakeEmbeddingService(),
        FakeStreamingLLM(),
    ) as context:
        response = await context.client.get(
            "/api/v1/health",
            headers={"X-Request-ID": "client.req-123"},
        )
        assert response.headers["x-request-id"] == "client.req-123"


async def test_invalid_and_overlong_request_ids_are_replaced(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"stream_heartbeat_seconds": 0})
    async with stream_client(
        settings,
        FakeEmbeddingService(),
        FakeStreamingLLM(),
    ) as context:
        invalid = await context.client.get(
            "/api/v1/health",
            headers={"X-Request-ID": "bad id with spaces"},
        )
        long = await context.client.get(
            "/api/v1/health",
            headers={"X-Request-ID": "x" * 129},
        )

        assert invalid.headers["x-request-id"] != "bad id with spaces"
        assert long.headers["x-request-id"] != "x" * 129
        assert invalid.headers["x-request-id"] != long.headers["x-request-id"]


async def test_stream_request_id_header_is_preserved(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"stream_heartbeat_seconds": 0})
    async with stream_client(
        settings,
        FakeEmbeddingService(),
        FakeStreamingLLM(),
    ) as context:
        response = await context.client.post(
            "/api/v1/agent/ask/stream",
            json={"question": "没有索引"},
            headers={"X-Request-ID": "stream-req-1"},
        )
        assert response.headers["x-request-id"] == "stream-req-1"
        events = parse_sse(response.text)
        assert all(
            data.get("request_id") == "stream-req-1"
            for _, data in events
            if "request_id" in data
        )


async def test_stream_metrics_are_recorded(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"stream_heartbeat_seconds": 0})
    llm = FakeStreamingLLM(tokens=["回答", "完成。"])
    async with stream_client(
        settings,
        FakeEmbeddingService(),
        llm,
    ) as context:
        document = await upload_pdf(context.client, ["alpha alpha"])
        await index_document(context.client, document["id"])
        _, events = await stream_ask(context.client, "alpha")
        final = [data for name, data in events if name == "final"][0]

        response = await context.client.get(METRICS_URL)
        metrics = response.json()

        assert response.status_code == 200
        assert final["status"] == "answered"
        assert metrics["requests_total"] >= 1
        assert metrics["agent_stream"]["requests_total"] == 1
        assert metrics["agent_stream"]["answered_total"] == 1
        assert metrics["agent_stream"]["refused_total"] == 0
        assert metrics["agent_stream"]["errors_total"] == 0
        assert metrics["agent_stream"]["average_duration_ms"] >= 0
        assert metrics["llm"]["stream_calls_total"] == 1
        assert metrics["llm"]["calls_total"] == 0
        assert "generated_at" in metrics


async def test_stream_metrics_refused_and_error_counts(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"stream_heartbeat_seconds": 0})
    llm = FakeStreamingLLM()
    async with stream_client(
        settings,
        FakeEmbeddingService(),
        llm,
    ) as context:
        _, refused_events = await stream_ask(context.client, "没有索引")
        assert [data for name, data in refused_events if name == "final"][0][
            "status"
        ] == "refused"

        document = await upload_pdf(context.client, ["alpha alpha"])
        await index_document(context.client, document["id"])
        llm.stream_available = False
        _, error_events = await stream_ask(context.client, "alpha")
        assert [data for name, data in error_events if name == "error"][0][
            "code"
        ] == "llm_unavailable"

        metrics = (await context.client.get(METRICS_URL)).json()
        assert metrics["agent_stream"]["requests_total"] == 2
        assert metrics["agent_stream"]["answered_total"] == 0
        assert metrics["agent_stream"]["refused_total"] == 1
        assert metrics["agent_stream"]["errors_total"] == 1
        assert metrics["llm"]["stream_calls_total"] == 1
        assert metrics["llm"]["errors_total"] == 1


async def test_metrics_endpoint_does_not_call_llm_or_leak_content(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"stream_heartbeat_seconds": 0})
    llm = FakeStreamingLLM()
    async with stream_client(
        settings,
        FakeEmbeddingService(),
        llm,
    ) as context:
        response = await context.client.get(METRICS_URL)
        body = json.dumps(response.json(), ensure_ascii=False)

        assert response.status_code == 200
        assert llm.stream_calls == []
        for forbidden in ("question", "prompt", "api_key", "evidence_text"):
            assert forbidden not in body
        assert "C:\\\\" not in body
        assert "generated_at" in response.json()


async def test_metrics_disabled_returns_404(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(
        update={
            "enable_metrics_endpoint": False,
            "stream_heartbeat_seconds": 0,
        }
    )
    async with stream_client(
        settings,
        FakeEmbeddingService(),
        FakeStreamingLLM(),
    ) as context:
        response = await context.client.get(METRICS_URL)
        assert response.status_code == 404


async def test_stream_disabled_returns_404(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(
        update={"enable_streaming": False, "stream_heartbeat_seconds": 0}
    )
    async with stream_client(
        settings,
        FakeEmbeddingService(),
        FakeStreamingLLM(),
    ) as context:
        response = await context.client.post(
            "/api/v1/agent/ask/stream",
            json={"question": "alpha"},
        )
        assert response.status_code == 404


async def test_file_logging_disabled_does_not_create_file(
    test_settings: Settings,
    tmp_path,
) -> None:
    log_dir = tmp_path / "disabled-logs"
    settings = test_settings.model_copy(
        update={
            "enable_file_logging": False,
            "log_dir": log_dir,
        }
    )
    try:
        create_app(
            settings,
            embedding_service=FakeEmbeddingService(),
            llm_service=FakeStreamingLLM(),
        )
        assert not log_dir.exists()
    finally:
        configure_logging("INFO", enable_file_logging=False)


async def test_file_logging_enabled_writes_under_log_dir(
    test_settings: Settings,
    tmp_path,
) -> None:
    log_dir = tmp_path / "enabled-logs"
    settings = test_settings.model_copy(
        update={
            "enable_file_logging": True,
            "log_dir": log_dir,
            "log_max_bytes": 1024 * 1024,
            "log_backup_count": 1,
        }
    )
    try:
        create_app(
            settings,
            embedding_service=FakeEmbeddingService(),
            llm_service=FakeStreamingLLM(),
        )
        logging.getLogger("research_agent.test").info("file_logging_probe")
        for handler in logging.getLogger().handlers:
            handler.flush()
        log_file = log_dir / "app.log"
        assert log_file.is_file()
        text = log_file.read_text(encoding="utf-8")
        assert "file_logging_probe" in text
        assert "request_id=" in text
    finally:
        configure_logging("INFO", enable_file_logging=False)
