"""受控的问题改写服务，复用本地 LLM Provider。"""

from __future__ import annotations

import logging
import re

from ..core.config import Settings
from ..core.exceptions import QueryRewriteError
from ..services.llm_service import LLMService, QA_REFUSAL_ANSWER

logger = logging.getLogger(__name__)

_MARKDOWN_OR_JSON_PREFIXES = (
    "{",
    "[",
    "```",
    "#",
    "- ",
    "* ",
    "**",
    "> ",
    "问题：",
    "改写后：",
    "改写：",
)
_NUMBERED_LINE = re.compile(r"^\d+[.)、]\s*")


class QueryRewriteService:
    """把原始问题改写为检索查询，不回答问题。"""

    def __init__(self, settings: Settings, llm_service: LLMService) -> None:
        self._max_chars = settings.rewrite_max_chars
        self._llm = llm_service

    async def rewrite(self, original_question: str) -> str:
        """调用 LLM 并做严格输出校验；失败统一转为 QueryRewriteError。"""
        try:
            raw = await self._llm.rewrite(original_question)
        except Exception as exc:
            logger.warning(
                "Query rewrite LLM failed error=%s",
                type(exc).__name__,
            )
            raise QueryRewriteError("问题改写服务不可用") from exc

        try:
            return self._validate_output(raw)
        except QueryRewriteError as exc:
            logger.warning("Query rewrite output rejected reason=%s", str(exc))
            raise

    def _validate_output(self, raw: object) -> str:
        if not isinstance(raw, str):
            raise QueryRewriteError("改写结果不是文本")

        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lines:
            raise QueryRewriteError("改写结果为空")

        query = lines[0]
        if len(query) > self._max_chars:
            raise QueryRewriteError("改写结果过长")
        if any(query.startswith(prefix) for prefix in _MARKDOWN_OR_JSON_PREFIXES):
            raise QueryRewriteError("改写结果是 Markdown 或 JSON")
        if _NUMBERED_LINE.match(query):
            raise QueryRewriteError("改写结果包含编号")
        if query[0] in "\"'“”" or query[-1] in "\"'“”":
            raise QueryRewriteError("改写结果包含引号")
        if QA_REFUSAL_ANSWER in query:
            raise QueryRewriteError("改写结果是拒答句")
        if query.lower() in {"json", "markdown"}:
            raise QueryRewriteError("改写结果是格式标记")
        return query
