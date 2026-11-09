"""安全的 UTF-8 JSONL 评测数据集加载。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from ..core.exceptions import EvaluationDatasetError
from .schemas import EvalCase, EvalDataset, DatasetSummary


def _validation_detail(exc: ValidationError) -> str:
    messages: list[str] = []
    for error in exc.errors()[:3]:
        location = ".".join(str(item) for item in error.get("loc", ()))
        messages.append(f"{location}: {error.get('msg', '字段不合法')}")
    return "; ".join(messages)


def load_dataset(path: Path) -> EvalDataset:
    """加载并校验 JSONL；错误只报告行号和字段，不暴露绝对路径。"""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EvaluationDatasetError("无法读取评测数据集。") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvaluationDatasetError("评测数据集必须是 UTF-8。") from exc

    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationDatasetError(
                f"第 {line_number} 行 JSON 非法。"
            ) from exc
        try:
            case = EvalCase.model_validate(payload)
        except ValidationError as exc:
            raise EvaluationDatasetError(
                f"第 {line_number} 行字段不合法: {_validation_detail(exc)}"
            ) from exc
        if case.id in seen_ids:
            raise EvaluationDatasetError(
                f"第 {line_number} 行 id 重复: {case.id}"
            )
        seen_ids.add(case.id)
        cases.append(case)

    return EvalDataset(
        name=path.name,
        sha256=hashlib.sha256(raw).hexdigest(),
        cases=cases,
    )


def safe_dataset_path(base_dir: Path, dataset_name: str) -> Path:
    """只允许 base_dir 下的直接 .jsonl 文件名。"""
    if (
        not dataset_name
        or dataset_name in {".", ".."}
        or "/" in dataset_name
        or "\\" in dataset_name
        or Path(dataset_name).is_absolute()
        or Path(dataset_name).name != dataset_name
        or not dataset_name.lower().endswith(".jsonl")
    ):
        raise EvaluationDatasetError("dataset_name 必须是不含路径的 JSONL 文件名。")
    base = Path(base_dir).resolve()
    candidate = (base / dataset_name).resolve()
    if candidate.parent != base:
        raise EvaluationDatasetError("dataset_name 不允许路径穿越。")
    return candidate


def load_named_dataset(base_dir: Path, dataset_name: str) -> EvalDataset:
    return load_dataset(safe_dataset_path(base_dir, dataset_name))


def dataset_summary(dataset: EvalDataset) -> DatasetSummary:
    answerable = sum(1 for case in dataset.cases if case.answerable)
    return DatasetSummary(
        name=dataset.name,
        sha256=dataset.sha256,
        total_cases=len(dataset.cases),
        answerable_cases=answerable,
        unanswerable_cases=len(dataset.cases) - answerable,
    )
