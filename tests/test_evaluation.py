"""第八阶段：数据集校验、指标、评测服务和报告测试。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from research_agent.core.config import Settings
from research_agent.core.exceptions import (
    EvaluationDatasetError,
    EvaluationLimitError,
    EvaluationRunFailedError,
    LLMUnavailableError,
)
from research_agent.evaluation.dataset_loader import (
    load_dataset,
    load_named_dataset,
    safe_dataset_path,
)
from research_agent.evaluation.metrics import calculate_metrics
from research_agent.evaluation.schemas import CaseResult
from research_agent.main import create_app
from tests.test_qa import (
    FakeEmbeddingService,
    UnavailableEmbeddingService,
    index_document,
    upload_pdf,
)

pytestmark = pytest.mark.anyio

EVAL_URL = "/api/v1/evaluations"


class EvalFakeLLM:
    def __init__(self, answer_text: str = "alpha beta 结果") -> None:
        self.answer_text = answer_text
        self.answer_available = True
        self.rewrite_text = "beta"
        self.rewrite_available = True
        self.calls: list[str] = []

    async def answer(self, question: str, evidence: list) -> str:
        self.calls.append(question)
        if not self.answer_available:
            raise LLMUnavailableError("unavailable")
        return self.answer_text

    async def rewrite(self, question: str) -> str:
        if not self.rewrite_available:
            raise LLMUnavailableError("unavailable")
        if question == "zeta":
            return "beta"
        if question == "gamma":
            return "gamma"
        return self.rewrite_text

    async def complete(self, messages: list[dict[str, str]]) -> str:
        return "{}"

    async def stream_answer(self, question: str, evidence: list):
        yield self.answer_text


@dataclass
class EvalContext:
    app: Any
    client: httpx.AsyncClient
    settings: Settings


@asynccontextmanager
async def eval_client(
    settings: Settings,
    embedding=None,
    llm: EvalFakeLLM | None = None,
) -> AsyncIterator[EvalContext]:
    app = create_app(
        settings,
        embedding_service=embedding or FakeEmbeddingService(),
        llm_service=llm or EvalFakeLLM(),
    )
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield EvalContext(app=app, client=client, settings=settings)


def dataset_rows() -> list[dict]:
    return [
        {
            "id": "a1",
            "question": "alpha",
            "answerable": True,
            "document_ids": [],
            "expected_sources": [
                {
                    "original_filename": "sample_experiment.pdf",
                    "page_number": 1,
                }
            ],
            "expected_answer_keywords": ["alpha"],
            "notes": "人工标签 A1",
        },
        {
            "id": "a2",
            "question": "beta",
            "answerable": True,
            "document_ids": [],
            "expected_sources": [
                {
                    "original_filename": "sample_experiment.pdf",
                    "page_number": 2,
                }
            ],
            "expected_answer_keywords": ["beta"],
            "notes": "人工标签 A2",
        },
        {
            "id": "a3",
            "question": "zeta",
            "answerable": True,
            "document_ids": [],
            "expected_sources": [
                {
                    "original_filename": "sample_experiment.pdf",
                    "page_number": 2,
                }
            ],
            "expected_answer_keywords": ["beta"],
            "notes": "人工标签 A3：需要改写",
        },
        {
            "id": "u1",
            "question": "gamma",
            "answerable": False,
            "document_ids": [],
            "expected_sources": [],
            "expected_answer_keywords": [],
            "notes": "人工标签 U1：应拒答",
        },
    ]


def write_dataset(settings: Settings, rows: list[dict] | None = None) -> Path:
    directory = Path(settings.eval_dataset_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "sample_eval.jsonl"
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in (rows or dataset_rows()))
        + "\n",
        encoding="utf-8",
    )
    return path


async def index_sample(client: httpx.AsyncClient) -> dict:
    document = await upload_pdf(
        client,
        ["alpha alpha 空白对照", "beta beta 温度"],
        filename="sample_experiment.pdf",
    )
    await index_document(client, document["id"])
    return document


def get_report(app) -> Any:
    return app.state.evaluation_service


async def test_dataset_loader_valid_and_hash(tmp_path: Path) -> None:
    path = tmp_path / "sample.jsonl"
    rows = dataset_rows()[:2]
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(content + "\n\n", encoding="utf-8")

    dataset = load_dataset(path)

    assert len(dataset.cases) == 2
    assert dataset.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert dataset.cases[0].id == "a1"


def test_dataset_loader_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text("{not-json}\n", encoding="utf-8")
    with pytest.raises(EvaluationDatasetError) as error:
        load_dataset(path)
    assert "第 1 行" in error.value.detail


def test_dataset_loader_rejects_duplicate_id(tmp_path: Path) -> None:
    path = tmp_path / "dup.jsonl"
    row = dataset_rows()[0]
    path.write_text(
        json.dumps(row, ensure_ascii=False) + "\n" + json.dumps(row, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(EvaluationDatasetError) as error:
        load_dataset(path)
    assert "id 重复" in error.value.detail


def test_dataset_loader_rejects_contradictory_labels(tmp_path: Path) -> None:
    path = tmp_path / "bad_label.jsonl"
    row = dataset_rows()[0]
    row["answerable"] = False
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(EvaluationDatasetError) as error:
        load_dataset(path)
    assert "expected_sources" in error.value.detail


def test_dataset_path_traversal_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(EvaluationDatasetError):
        safe_dataset_path(tmp_path, "../secret.jsonl")
    with pytest.raises(EvaluationDatasetError):
        safe_dataset_path(tmp_path, r"..\secret.jsonl")
    with pytest.raises(EvaluationDatasetError):
        safe_dataset_path(tmp_path, "C:\\secret.jsonl")
    with pytest.raises(EvaluationDatasetError):
        safe_dataset_path(tmp_path, "sample.txt")


def test_metrics_calculation() -> None:
    results = [
        CaseResult(
            case_id="a1",
            expected_answerable=True,
            actual_status="answered",
            retrieval_hit=True,
            first_relevant_rank=1,
            citation_correct_count=1,
            citation_total_count=1,
            expected_source_count=1,
            matched_expected_source_count=1,
            keyword_hit=True,
        ),
        CaseResult(
            case_id="a2",
            expected_answerable=True,
            actual_status="refused",
            retrieval_hit=True,
            first_relevant_rank=1,
            expected_source_count=1,
        ),
        CaseResult(
            case_id="u1",
            expected_answerable=False,
            actual_status="answered",
            retrieval_hit=False,
            citation_correct_count=0,
            citation_total_count=1,
        ),
        CaseResult(
            case_id="u2",
            expected_answerable=False,
            actual_status="refused",
        ),
    ]
    metrics = calculate_metrics(results, "qa")

    assert metrics["retrieval"]["recall_at_k"] == 1.0
    assert metrics["retrieval"]["mrr_at_k"] == 1.0
    assert metrics["citation"]["precision"] == 0.5
    assert metrics["citation"]["recall"] == 0.5
    assert metrics["refusal"]["accuracy"] == 0.5
    assert metrics["refusal"]["hallucinated_answer_rate"] == 0.5
    assert metrics["refusal"]["false_refusal_rate"] == 0.5
    assert metrics["answer"]["keyword_hit_rate"] == 1.0
    assert metrics["answer"]["keyword_evaluated_cases"] == 1
    assert metrics["agent"]["rewrite_rate"] is None


def test_metrics_no_citations_and_no_keywords_are_null() -> None:
    results = [
        CaseResult(
            case_id="a1",
            expected_answerable=True,
            actual_status="answered",
            retrieval_hit=True,
            first_relevant_rank=1,
            citation_total_count=0,
            expected_source_count=1,
        )
    ]
    metrics = calculate_metrics(results, "agent")
    assert metrics["citation"]["precision"] is None
    assert metrics["citation"]["recall"] == 0.0
    assert metrics["answer"]["keyword_hit_rate"] is None
    assert metrics["agent"]["retry_success_rate"] is None


async def test_retrieval_mode_metrics_and_safe_report(
    test_settings: Settings,
) -> None:
    write_dataset(test_settings)
    async with eval_client(test_settings) as context:
        await index_sample(context.client)
        response = await context.client.post(
            f"{EVAL_URL}/run",
            json={
                "dataset_name": "sample_eval.jsonl",
                "mode": "retrieval",
                "top_k": 5,
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["mode"] == "retrieval"
        assert result["report_available"] is True

        report = await context.client.get(f"{EVAL_URL}/{result['run_id']}")
        assert report.status_code == 200
        body = report.json()
        assert body["status"] == "success"
        assert body["dataset"]["sha256"]
        assert body["metrics"]["retrieval"]["recall_at_k"] == 1.0
        assert body["case_results"]
        serialized = json.dumps(body, ensure_ascii=False)
        assert "alpha" not in serialized
        assert "人工标签" not in serialized
        assert "C:\\\\" not in serialized


async def test_compare_qa_and_agent_metrics(
    test_settings: Settings,
) -> None:
    write_dataset(test_settings)
    async with eval_client(test_settings) as context:
        await index_sample(context.client)
        response = await context.client.post(
            f"{EVAL_URL}/run",
            json={
                "dataset_name": "sample_eval.jsonl",
                "mode": "compare",
                "top_k": 5,
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert set(result["summary"]["metrics"]) == {"qa", "agent"}

        report = (await context.client.get(f"{EVAL_URL}/{result['run_id']}")).json()
        qa = report["metrics"]["qa"]
        agent = report["metrics"]["agent"]
        assert qa["refusal"]["false_refusal_rate"] == pytest.approx(1 / 3)
        assert agent["refusal"]["accuracy"] == 1.0
        assert agent["retrieval"]["recall_at_k"] == 1.0
        assert agent["agent"]["rewrite_rate"] == pytest.approx(1 / 2)
        assert agent["agent"]["retry_success_rate"] == pytest.approx(1 / 2)
        assert report["configuration"]["top_k"] == 5


async def test_evaluation_list_and_invalid_run_id(
    test_settings: Settings,
) -> None:
    write_dataset(test_settings)
    async with eval_client(test_settings) as context:
        await index_sample(context.client)
        run = await context.client.post(
            f"{EVAL_URL}/run",
            json={
                "dataset_name": "sample_eval.jsonl",
                "mode": "retrieval",
                "top_k": 5,
            },
        )
        assert run.status_code == 200
        listing = await context.client.get(EVAL_URL)
        assert listing.status_code == 200
        items = listing.json()
        assert len(items) == 1
        assert "question" not in json.dumps(items, ensure_ascii=False)
        assert (await context.client.get(f"{EVAL_URL}/not-a-run")).status_code == 404


async def test_evaluation_max_cases_returns_422(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"evaluation_max_cases": 1})
    write_dataset(settings)
    async with eval_client(settings) as context:
        response = await context.client.post(
            f"{EVAL_URL}/run",
            json={
                "dataset_name": "sample_eval.jsonl",
                "mode": "retrieval",
                "top_k": 5,
            },
        )
        assert response.status_code == 422


async def test_retrieval_works_when_llm_unavailable(
    test_settings: Settings,
) -> None:
    write_dataset(test_settings)
    llm = EvalFakeLLM()
    llm.answer_available = False
    async with eval_client(test_settings, llm=llm) as context:
        await index_sample(context.client)
        retrieval = await context.client.post(
            f"{EVAL_URL}/run",
            json={
                "dataset_name": "sample_eval.jsonl",
                "mode": "retrieval",
                "top_k": 5,
            },
        )
        assert retrieval.status_code == 200
        qa = await context.client.post(
            f"{EVAL_URL}/run",
            json={
                "dataset_name": "sample_eval.jsonl",
                "mode": "qa",
                "top_k": 5,
            },
        )
        assert qa.status_code == 503


async def test_qa_agent_compare_fail_when_llm_unavailable(
    test_settings: Settings,
) -> None:
    write_dataset(test_settings)
    llm = EvalFakeLLM()
    llm.answer_available = False
    async with eval_client(test_settings, llm=llm) as context:
        await index_sample(context.client)
        for mode in ("qa", "agent", "compare"):
            response = await context.client.post(
                f"{EVAL_URL}/run",
                json={
                    "dataset_name": "sample_eval.jsonl",
                    "mode": mode,
                    "top_k": 5,
                },
            )
            assert response.status_code == 503, (mode, response.text)


async def test_dataset_name_traversal_returns_422(
    test_settings: Settings,
) -> None:
    write_dataset(test_settings)
    async with eval_client(test_settings) as context:
        response = await context.client.post(
            f"{EVAL_URL}/run",
            json={
                "dataset_name": "../sample_eval.jsonl",
                "mode": "retrieval",
                "top_k": 5,
            },
        )
        assert response.status_code == 422


async def test_report_files_and_safe_markdown(
    test_settings: Settings,
) -> None:
    write_dataset(test_settings)
    async with eval_client(test_settings) as context:
        await index_sample(context.client)
        response = await context.client.post(
            f"{EVAL_URL}/run",
            json={
                "dataset_name": "sample_eval.jsonl",
                "mode": "compare",
                "top_k": 5,
            },
        )
        assert response.status_code == 200
        run_id = response.json()["run_id"]
        report_dir = Path(test_settings.evaluation_dir)
        assert (report_dir / f"{run_id}.json").is_file()
        markdown = (report_dir / f"{run_id}.md").read_text(encoding="utf-8")
        assert "## 运行概览" in markdown
        assert "## 指标" in markdown
        assert "QA" in markdown
        assert "Agent" in markdown
        assert "alpha" not in markdown
        assert "人工标签" not in markdown


async def test_embedding_unavailable_returns_503(
    test_settings: Settings,
) -> None:
    write_dataset(test_settings)
    async with eval_client(
        test_settings,
        embedding=UnavailableEmbeddingService(),
    ) as context:
        response = await context.client.post(
            f"{EVAL_URL}/run",
            json={
                "dataset_name": "sample_eval.jsonl",
                "mode": "retrieval",
                "top_k": 5,
            },
        )
        assert response.status_code == 503


class FlakyRetrieval:
    def __init__(self, inner) -> None:
        self._inner = inner

    def search(self, query: str, top_k: int, document_ids=None):
        if query == "alpha":
            raise RuntimeError("case error")
        return self._inner.search(query, top_k, document_ids)


async def test_case_error_rate_can_fail_run(
    test_settings: Settings,
) -> None:
    write_dataset(test_settings)
    settings = test_settings.model_copy(
        update={"evaluation_max_error_rate": 0.2}
    )
    async with eval_client(settings) as context:
        await index_sample(context.client)
        service = context.app.state.evaluation_service
        from research_agent.evaluation.evaluator import EvaluationService
        from research_agent.evaluation.report_service import (
            EvaluationReportService,
        )

        flaky = EvaluationService(
            settings=settings,
            retrieval_service=FlakyRetrieval(context.app.state.retrieval_service),
            qa_service=context.app.state.qa_service,
            agent_service=context.app.state.agent_service,
            report_service=EvaluationReportService(settings),
        )
        with pytest.raises(EvaluationRunFailedError):
            await flaky.run_named("sample_eval.jsonl", "retrieval", 5)
        assert list(Path(settings.evaluation_dir).glob("eval-*.json"))
