"""白名单工具注册表；不接受任意函数名或模块名。"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from ..core.exceptions import ToolValidationError
from ..schemas.tools import ToolName
from .base import ToolOutcome

ALLOWED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "search_knowledge_base",
        "generate_experiment_checklist",
        "summarize_meeting_notes",
    }
)


@dataclass(frozen=True)
class ToolDefinition:
    """一个被显式注册、带输入 Schema 的工具。"""

    name: ToolName
    arguments_model: type[BaseModel]
    runner: Callable[[BaseModel], ToolOutcome | Awaitable[ToolOutcome]]


class ToolRegistry:
    """只按白名单查找工具，每次调用一个工具。"""

    def __init__(self, tools: list[ToolDefinition]) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        for tool in tools:
            if tool.name not in ALLOWED_TOOL_NAMES:
                raise ValueError(f"未授权的工具: {tool.name}")
            if tool.name in self._tools:
                raise ValueError(f"重复注册工具: {tool.name}")
            self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolValidationError("不支持的工具名称。")
        return tool

    def parse_arguments(self, name: str, arguments: object) -> BaseModel:
        if not isinstance(arguments, dict):
            raise ToolValidationError("arguments 必须是 JSON 对象。")
        tool = self.get(name)
        try:
            return tool.arguments_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolValidationError("工具参数不合法。") from exc

    async def execute(
        self,
        name: str,
        parsed_arguments: BaseModel,
    ) -> ToolOutcome:
        tool = self.get(name)
        if not isinstance(parsed_arguments, tool.arguments_model):
            raise ToolValidationError("工具参数类型不匹配。")
        result = tool.runner(parsed_arguments)
        if inspect.isawaitable(result):
            return await result
        return result
