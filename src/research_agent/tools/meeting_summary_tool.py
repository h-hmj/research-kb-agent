"""summarize_meeting_notes 工具。"""

from __future__ import annotations

from ..schemas.tools import MeetingSummaryToolArgs
from ..services.meeting_summary_service import MeetingSummaryService
from .base import ToolOutcome


class MeetingSummaryTool:
    name = "summarize_meeting_notes"
    arguments_model = MeetingSummaryToolArgs

    def __init__(self, service: MeetingSummaryService) -> None:
        self._service = service

    async def run(self, arguments: MeetingSummaryToolArgs) -> ToolOutcome:
        return await self._service.run(arguments)
