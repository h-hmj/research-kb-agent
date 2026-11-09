"""评测 JSON/Markdown 报告的原子写入、读取和列表。"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from ..core.config import Settings
from ..core.exceptions import EvaluationNotFoundError, EvaluationReportError
from .schemas import EvaluationListItem, EvaluationReport

_RUN_ID_RE = re.compile(r"^eval-[A-Za-z0-9:-]+-[0-9a-f]{8}$")


class EvaluationReportService:
    def __init__(self, settings: Settings) -> None:
        self._dir = Path(settings.evaluation_dir)

    def save(self, report: EvaluationReport) -> None:
        if not _RUN_ID_RE.fullmatch(report.run_id):
            raise EvaluationReportError("非法 run_id")
        self._dir.mkdir(parents=True, exist_ok=True)
        json_text = json.dumps(
            report.model_dump(),
            ensure_ascii=False,
            indent=2,
        )
        markdown_text = self._markdown(report)
        self._atomic_write(self._dir / f"{report.run_id}.json", json_text)
        self._atomic_write(
            self._dir / f"{report.run_id}.md",
            markdown_text,
        )

    def load(self, run_id: str) -> EvaluationReport:
        if not _RUN_ID_RE.fullmatch(run_id):
            raise EvaluationNotFoundError("评测报告不存在")
        path = (self._dir / f"{run_id}.json").resolve()
        if path.parent != self._dir.resolve() or not path.is_file():
            raise EvaluationNotFoundError("评测报告不存在")
        try:
            return EvaluationReport.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise EvaluationReportError("评测报告读取失败") from exc

    def list_recent(self, limit: int = 20) -> list[EvaluationListItem]:
        if not self._dir.exists():
            return []
        reports: list[EvaluationReport] = []
        for path in self._dir.glob("eval-*.json"):
            try:
                report = EvaluationReport.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue
            reports.append(report)
        reports.sort(key=lambda item: item.created_at, reverse=True)
        return [
            EvaluationListItem(
                run_id=report.run_id,
                created_at=report.created_at,
                mode=report.mode,
                status=report.status,
                dataset_name=report.dataset.name,
                total_cases=report.dataset.total_cases,
                answerable_cases=report.dataset.answerable_cases,
                unanswerable_cases=report.dataset.unanswerable_cases,
                error_case_count=report.error_case_count,
                metrics=report.metrics,
            )
            for report in reports[:limit]
        ]

    def _atomic_write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                delete=False,
                prefix=f".{path.stem}.",
                suffix=".tmp",
            ) as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            os.replace(temp_path, path)
        except OSError as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise EvaluationReportError("评测报告写入失败") from exc

    def _markdown(self, report: EvaluationReport) -> str:
        lines = [
            "# 评测报告",
            "",
            "## 运行概览",
            "",
            f"- run_id：`{report.run_id}`",
            f"- 创建时间：{report.created_at}",
            f"- 模式：`{report.mode}`",
            f"- 状态：`{report.status}`",
            f"- 数据集：`{report.dataset.name}`",
            f"- 数据集 SHA-256：`{report.dataset.sha256}`",
            f"- 样例数：{report.dataset.total_cases}",
            f"- answerable：{report.dataset.answerable_cases}",
            f"- unanswerable：{report.dataset.unanswerable_cases}",
            f"- 内部错误样例数：{report.error_case_count}",
            "",
            "## 配置快照",
            "",
        ]
        for key, value in report.configuration.items():
            lines.append(f"- `{key}`：{value}")
        lines.extend(["", "## 指标", ""])
        if report.mode == "compare":
            for group in ("qa", "agent"):
                lines.extend(
                    [
                        f"### {group.upper()}",
                        "",
                        self._metrics_table(report.metrics.get(group, {})),
                        "",
                    ]
                )
        else:
            lines.extend([self._metrics_table(report.metrics), ""])
        failures = self._failure_results(report)
        lines.extend(["## 失败案例摘要", ""])
        if failures:
            lines.append("| case_id | 状态 | error_code |")
            lines.append("| --- | --- | --- |")
            for result in failures:
                lines.append(
                    f"| {result.case_id} | {result.actual_status} | "
                    f"{result.error_code or '-'} |"
                )
        else:
            lines.append("无内部错误样例。")
        lines.extend(["", "## 已知限制", ""])
        for limitation in report.limitations:
            lines.append(f"- {limitation}")
        lines.extend(
            [
                "",
                "## 复现命令",
                "",
                "```powershell",
                f"python -m eval.run_evaluation --dataset "
                f"eval/datasets/{report.dataset.name} "
                f"--mode {report.mode} --top-k "
                f"{report.configuration.get('top_k', 5)}",
                "```",
                "",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _metrics_table(metrics: dict) -> str:
        retrieval = metrics.get("retrieval", {})
        citation = metrics.get("citation", {})
        refusal = metrics.get("refusal", {})
        answer = metrics.get("answer", {})
        agent = metrics.get("agent", {})
        return "\n".join(
            [
                "| 指标 | 值 |",
                "| --- | --- |",
                f"| Recall@K | {retrieval.get('recall_at_k')} |",
                f"| MRR@K | {retrieval.get('mrr_at_k')} |",
                f"| Citation Precision | {citation.get('precision')} |",
                f"| Citation Recall | {citation.get('recall')} |",
                f"| Refusal Accuracy | {refusal.get('accuracy')} |",
                "| Hallucinated Answer Rate | "
                f"{refusal.get('hallucinated_answer_rate')} |",
                "| False Refusal Rate | "
                f"{refusal.get('false_refusal_rate')} |",
                "| Keyword Hit Rate（弱指标） | "
                f"{answer.get('keyword_hit_rate')} |",
                f"| Agent Rewrite Rate | {agent.get('rewrite_rate')} |",
                "| Agent Retry Success Rate | "
                f"{agent.get('retry_success_rate')} |",
            ]
        )

    @staticmethod
    def _failure_results(report: EvaluationReport):
        if isinstance(report.case_results, dict):
            results = [
                result
                for group in report.case_results.values()
                for result in group
            ]
        else:
            results = report.case_results
        return [result for result in results if result.error_code]
