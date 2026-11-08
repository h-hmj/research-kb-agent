"""generate_experiment_checklist 工具。"""

from __future__ import annotations

from ..schemas.tools import ChecklistToolArgs
from ..services.checklist_service import ChecklistService
from .base import ToolOutcome


class ChecklistTool:
    name = "generate_experiment_checklist"
    arguments_model = ChecklistToolArgs

    def __init__(self, service: ChecklistService) -> None:
        self._service = service

    async def run(self, arguments: ChecklistToolArgs) -> ToolOutcome:
        return await self._service.run(arguments)
