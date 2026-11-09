"""本地评测 CLI：与 API 复用同一个 EvaluationService。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from research_agent.core.config import Settings  # noqa: E402
from research_agent.core.exceptions import (  # noqa: E402
    EmbeddingModelUnavailableError,
    EvaluationDatasetError,
    EvaluationLimitError,
    EvaluationRunFailedError,
    LLMUnavailableError,
)
from research_agent.main import create_app  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行本地 JSONL 评测；评测指标只对当前数据集和配置有效。"
    )
    parser.add_argument("--dataset", required=True, help="JSONL 数据集路径")
    parser.add_argument(
        "--mode",
        required=True,
        choices=("retrieval", "qa", "agent", "compare"),
    )
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    settings = Settings()
    app = create_app(settings)
    service = app.state.evaluation_service
    try:
        report = await service.run_path(
            Path(args.dataset),
            args.mode,
            args.top_k,
        )
    except EvaluationDatasetError as exc:
        print(f"数据集错误: {exc.detail}", file=sys.stderr)
        return 2
    except EvaluationLimitError as exc:
        print(f"评测限制: {exc.detail}", file=sys.stderr)
        return 2
    except EmbeddingModelUnavailableError:
        print("Embedding 模型不可用，未生成评测报告。", file=sys.stderr)
        return 3
    except LLMUnavailableError:
        print("LLM 服务不可用，未生成评测报告。", file=sys.stderr)
        return 4
    except EvaluationRunFailedError as exc:
        print(f"评测失败: {exc.detail}", file=sys.stderr)
        return 5
    except Exception as exc:
        print(f"评测运行失败: {type(exc).__name__}", file=sys.stderr)
        return 1

    print(f"run_id: {report.run_id}")
    print(f"status: {report.status}")
    print(f"mode: {report.mode}")
    print("metrics:")
    print(json.dumps(report.metrics, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    args = parse_args()
    if not 1 <= args.top_k <= 20:
        print("--top-k 必须在 1 到 20 之间。", file=sys.stderr)
        return 2
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
