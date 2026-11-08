"""工具执行结果与共享类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ToolOutcome:
    """工具运行后的安全结果，不包含 Prompt 或模型原始响应。"""

    status: Literal["success", "refused"]
    result: dict[str, Any] = field(default_factory=dict)
    llm_called: bool = False
    retrieval_count: int = 0
    evidence_count: int = 0
    refusal_reason: str | None = None
