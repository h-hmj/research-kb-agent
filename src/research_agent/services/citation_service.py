"""基于实际证据生成服务端引用。"""

from __future__ import annotations

from ..schemas.qa import EvidenceChunk, QACitation


class CitationService:
    """从实际送入 LLM 的证据块生成引用，不解析模型输出。"""

    def __init__(self, max_text_length: int = 500) -> None:
        self._max_text_length = max_text_length

    def build(self, evidence: list[EvidenceChunk]) -> list[QACitation]:
        """按分数降序生成去重引用，文本只保留证据原文前缀。"""
        citations: list[QACitation] = []
        seen_chunks: set[str] = set()

        for item in sorted(evidence, key=lambda value: value.score, reverse=True):
            if item.chunk_id in seen_chunks:
                continue
            seen_chunks.add(item.chunk_id)
            citations.append(
                QACitation(
                    citation_id=f"citation-{len(citations) + 1}",
                    chunk_id=item.chunk_id,
                    document_id=item.document_id,
                    original_filename=item.original_filename,
                    page_number=item.page_number,
                    chunk_index=item.chunk_index,
                    text=item.text[: self._max_text_length],
                    char_start=item.char_start,
                    char_end=item.char_end,
                    score=item.score,
                )
            )

        return citations
