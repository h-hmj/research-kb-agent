"""基于用户直接输入的组会记录生成结构化总结。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ..core.config import Settings
from ..core.exceptions import ToolOutputInvalidError, ToolValidationError
from ..schemas.tools import (
    MeetingActionItem,
    MeetingCitation,
    MeetingDecision,
    MeetingLLMOutput,
    MeetingOpenQuestion,
    MeetingRisk,
    MeetingSummaryResult,
    MeetingSummaryToolArgs,
)
from ..tools.base import ToolOutcome
from .llm_service import LLMService

MEETING_INVALID_DETAIL = (
    "本地 LLM 返回的组会总结格式无效，请稍后重试。"
)

MEETING_SYSTEM_PROMPT = """你是科研组会记录整理助手。
只能依据用户提供的组会记录整理总结。
不得虚构实验进展、结论、负责人、截止日期、风险或待办事项。
文本未明确出现负责人时，owner 必须为 null。
文本未明确出现截止日期时，deadline 必须为 null。
每一条结论、待办、风险或开放问题都必须关联一个或多个 source_segment_ids。
只输出合法 JSON，不要 Markdown、代码块、解释文字或虚构引用。"""


@dataclass(frozen=True)
class MeetingSegment:
    segment_id: str
    text: str
    char_start: int
    char_end: int


def _split_segments(meeting_text: str) -> list[MeetingSegment]:
    segments: list[MeetingSegment] = []
    cursor = 0
    for part in re.split(r"(\n\s*\n)", meeting_text):
        if not part:
            continue
        stripped = part.strip()
        if stripped:
            leading = len(part) - len(part.lstrip())
            start = cursor + leading
            segments.append(
                MeetingSegment(
                    segment_id=f"segment-{len(segments) + 1}",
                    text=stripped,
                    char_start=start,
                    char_end=start + len(stripped),
                )
            )
        cursor += len(part)
    return segments


def _parse_json_object(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw.strip())
    except (json.JSONDecodeError, TypeError) as exc:
        raise ToolOutputInvalidError(MEETING_INVALID_DETAIL) from exc
    if not isinstance(data, dict):
        raise ToolOutputInvalidError(MEETING_INVALID_DETAIL)
    return data


def build_meeting_messages(
    arguments: MeetingSummaryToolArgs,
    segments: list[MeetingSegment],
) -> list[dict[str, str]]:
    """只把服务端构造的段落送入 LLM。"""
    blocks = [
        f"[{segment.segment_id}]\n{segment.text}" for segment in segments
    ]
    user_prompt = (
        f"组会标题：{arguments.meeting_title or '未命名'}\n"
        f"关注重点：{arguments.focus or '无'}\n\n"
        "组会段落：\n"
        + "\n\n".join(blocks)
        + "\n\n只输出合法 JSON，格式严格为：\n"
        '{"summary":"不超过500字的客观摘要",'
        '"decisions":[{"content":"结论","source_segment_ids":["segment-1"]}],'
        '"action_items":[{"task":"待办","owner":null,"deadline":null,'
        '"source_segment_ids":["segment-2"]}],'
        '"risks":[{"content":"风险","source_segment_ids":["segment-3"]}],'
        '"open_questions":[{"content":"待讨论问题",'
        '"source_segment_ids":["segment-4"]}]}\n'
        "未明确出现的 owner 或 deadline 必须输出 null；"
        "source_segment_ids 只能引用上面实际存在的段落。"
    )
    return [
        {"role": "system", "content": MEETING_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


class MeetingSummaryService:
    """不检索知识库，只整理用户直接提交的组会文本。"""

    def __init__(self, settings: Settings, llm_service: LLMService) -> None:
        self._settings = settings
        self._llm = llm_service

    @staticmethod
    def split_segments(meeting_text: str) -> list[MeetingSegment]:
        return _split_segments(meeting_text)

    async def run(self, arguments: MeetingSummaryToolArgs) -> ToolOutcome:
        segments = _split_segments(arguments.meeting_text)
        if not segments:
            raise ToolValidationError("meeting_text 未包含有效段落。")

        total_chars = sum(len(segment.text) for segment in segments)
        if total_chars > self._settings.max_meeting_context_chars:
            raise ToolValidationError(
                "meeting_text 超过上下文上限，请分批提交。"
            )

        raw = await self._llm.complete(
            build_meeting_messages(arguments, segments)
        )
        data = _parse_json_object(raw)
        try:
            output = MeetingLLMOutput.model_validate(data)
        except ValidationError as exc:
            raise ToolOutputInvalidError(MEETING_INVALID_DETAIL) from exc

        segment_map = {
            segment.segment_id: segment for segment in segments
        }
        for item in (
            output.decisions
            + output.action_items
            + output.risks
            + output.open_questions
        ):
            if any(
                segment_id not in segment_map
                for segment_id in item.source_segment_ids
            ):
                raise ToolOutputInvalidError(MEETING_INVALID_DETAIL)

        def citations_for(ids: list[str]) -> list[MeetingCitation]:
            result: list[MeetingCitation] = []
            seen: set[str] = set()
            for segment_id in ids:
                if segment_id in seen:
                    continue
                seen.add(segment_id)
                segment = segment_map[segment_id]
                result.append(
                    MeetingCitation(
                        segment_id=segment.segment_id,
                        text=segment.text,
                        char_start=segment.char_start,
                        char_end=segment.char_end,
                    )
                )
            return result

        decisions = [
            MeetingDecision(
                content=item.content,
                citations=citations_for(item.source_segment_ids),
            )
            for item in output.decisions
        ]
        action_items = [
            MeetingActionItem(
                task=item.task,
                owner=item.owner,
                deadline=item.deadline,
                citations=citations_for(item.source_segment_ids),
            )
            for item in output.action_items
        ]
        risks = [
            MeetingRisk(
                content=item.content,
                citations=citations_for(item.source_segment_ids),
            )
            for item in output.risks
        ]
        open_questions = [
            MeetingOpenQuestion(
                content=item.content,
                citations=citations_for(item.source_segment_ids),
            )
            for item in output.open_questions
        ]

        result = MeetingSummaryResult(
            meeting_title=arguments.meeting_title,
            summary=output.summary,
            decisions=decisions,
            action_items=action_items,
            risks=risks,
            open_questions=open_questions,
        )
        return ToolOutcome(
            status="success",
            result=result.model_dump(),
            llm_called=True,
            retrieval_count=0,
            evidence_count=len(segments),
        )
