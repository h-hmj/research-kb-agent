"""基于知识库证据生成结构化实验 checklist。"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from ..core.config import Settings
from ..core.exceptions import ToolOutputInvalidError
from ..schemas.qa import EvidenceChunk
from ..schemas.tools import (
    ChecklistItem,
    ChecklistLLMOutput,
    ChecklistResult,
    ChecklistToolArgs,
)
from ..tools.base import ToolOutcome
from .citation_service import CitationService
from .llm_service import LLMService
from .qa_service import QAService
from .retrieval_service import RetrievalService

CHECKLIST_INVALID_DETAIL = (
    "本地 LLM 返回的 checklist 格式无效，请稍后重试。"
)
CHECKLIST_NO_EVIDENCE_REASON = (
    "未检索到足够的资料证据，无法生成基于知识库的实验 checklist。"
)
CHECKLIST_MODEL_REFUSAL_REASON = "无法根据已检索到的资料生成 checklist。"

CHECKLIST_SYSTEM_PROMPT = """你是科研实验准备助手。
只能基于提供的资料证据、用户实验目标和用户约束生成 checklist。
不得补充未在证据中出现的实验参数、试剂浓度、温度、时长、仪器型号、安全结论或实验结果。
如果证据不足，必须输出：
{"status":"refused","reason":"无法根据已检索到的资料生成 checklist。"}
若生成 checklist，只能输出合法 JSON，不要使用 Markdown、代码块、解释文字或虚构引用。
每个条目应简洁、可执行，并区分准备、操作、记录和复核。"""


def _parse_json_object(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw.strip())
    except (json.JSONDecodeError, TypeError) as exc:
        raise ToolOutputInvalidError(CHECKLIST_INVALID_DETAIL) from exc
    if not isinstance(data, dict):
        raise ToolOutputInvalidError(CHECKLIST_INVALID_DETAIL)
    return data


def build_checklist_messages(
    arguments: ChecklistToolArgs,
    evidence: list[EvidenceChunk],
) -> list[dict[str, str]]:
    """构造只包含筛选后证据的 checklist 消息。"""
    blocks: list[str] = []
    for index, item in enumerate(evidence, start=1):
        blocks.append(
            f"[evidence-{index}]\n"
            f"文档：{item.original_filename}\n"
            f"页码：{item.page_number}\n"
            f"内容：\n{item.text}"
        )
    constraints = "\n".join(
        f"- {item}" for item in (arguments.constraints or [])
    ) or "无"
    user_prompt = (
        f"实验目标：\n{arguments.experiment_goal}\n\n"
        f"用户约束：\n{constraints}\n\n"
        "资料证据：\n"
        + "\n\n".join(blocks)
        + "\n\n"
        "只输出合法 JSON，格式严格为：\n"
        '{"title":"实验准备 checklist","items":['
        '{"id":"item-1","category":"preparation",'
        '"content":"准备……","priority":"high",'
        '"evidence_ids":["evidence-1"]}],'
        '"notes":[]}\n'
        "category 只能是 preparation/operation/recording/review；"
        "priority 只能是 high/medium/low；"
        "evidence_ids 只能使用上面实际出现的 evidence-N。"
    )
    return [
        {"role": "system", "content": CHECKLIST_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


class ChecklistService:
    """检索证据、调用 LLM、校验 JSON 并生成服务端引用。"""

    def __init__(
        self,
        settings: Settings,
        retrieval_service: RetrievalService,
        qa_service: QAService,
        citation_service: CitationService,
        llm_service: LLMService,
    ) -> None:
        self._settings = settings
        self._retrieval = retrieval_service
        self._qa = qa_service
        self._citations = citation_service
        self._llm = llm_service

    async def run(self, arguments: ChecklistToolArgs) -> ToolOutcome:
        retrieved = self._retrieval.search(
            query=arguments.experiment_goal,
            top_k=arguments.top_k,
            document_ids=arguments.document_ids,
        )
        evidence = self._qa.select_evidence(
            retrieved.results,
            max_context_chars=self._settings.max_context_chars,
        )
        retrieval_count = len(retrieved.results)
        evidence_count = len(evidence)

        if evidence_count < self._settings.min_evidence_count:
            return ToolOutcome(
                status="refused",
                result={"checklist": []},
                llm_called=False,
                retrieval_count=retrieval_count,
                evidence_count=evidence_count,
                refusal_reason=CHECKLIST_NO_EVIDENCE_REASON,
            )

        raw = await self._llm.complete(
            build_checklist_messages(arguments, evidence)
        )
        data = _parse_json_object(raw)
        if data.get("status") == "refused":
            return ToolOutcome(
                status="refused",
                result={"checklist": []},
                llm_called=True,
                retrieval_count=retrieval_count,
                evidence_count=evidence_count,
                refusal_reason=CHECKLIST_MODEL_REFUSAL_REASON,
            )

        try:
            output = ChecklistLLMOutput.model_validate(data)
        except ValidationError as exc:
            raise ToolOutputInvalidError(CHECKLIST_INVALID_DETAIL) from exc

        item_ids: set[str] = set()
        evidence_map = {
            f"evidence-{index}": item
            for index, item in enumerate(evidence, start=1)
        }
        referenced_ids: list[str] = []
        for item in output.items:
            if item.id in item_ids:
                raise ToolOutputInvalidError(CHECKLIST_INVALID_DETAIL)
            item_ids.add(item.id)
            for evidence_id in item.evidence_ids:
                if evidence_id not in evidence_map:
                    raise ToolOutputInvalidError(CHECKLIST_INVALID_DETAIL)
                if evidence_id not in referenced_ids:
                    referenced_ids.append(evidence_id)

        citations = self._citations.build(
            [evidence_map[evidence_id] for evidence_id in referenced_ids]
        )
        citations_by_chunk = {
            citation.chunk_id: citation for citation in citations
        }
        items: list[ChecklistItem] = []
        has_citation = False
        for item in output.items:
            item_citations = []
            for evidence_id in item.evidence_ids:
                citation = citations_by_chunk.get(
                    evidence_map[evidence_id].chunk_id
                )
                if citation is not None:
                    item_citations.append(citation)
            if item_citations:
                has_citation = True
            items.append(
                ChecklistItem(
                    id=item.id,
                    category=item.category,
                    content=item.content,
                    priority=item.priority,
                    citations=item_citations,
                )
            )

        if not has_citation:
            raise ToolOutputInvalidError(CHECKLIST_INVALID_DETAIL)

        result = ChecklistResult(
            title=output.title,
            items=items,
            notes=output.notes,
        )
        return ToolOutcome(
            status="success",
            result=result.model_dump(),
            llm_called=True,
            retrieval_count=retrieval_count,
            evidence_count=evidence_count,
        )
