"""页码级文本分块。

分块只发生在单页内部，绝不跨页拼接。相同文档、页码和 chunk 序号会生成相同 ID。
"""

from collections.abc import Sequence

from ..schemas.documents import DocumentPage
from ..schemas.retrieval import DocumentChunk

_BOUNDARY_CHARS = "\n。！？!?；;"


def build_chunks(
    pages: Sequence[DocumentPage],
    document_id: str,
    original_filename: str,
    chunk_size: int = 500,
    chunk_overlap: int = 80,
) -> list[DocumentChunk]:
    """将逐页文本切分为带页码和字符范围的 chunk。

    优先在换行和句末标点附近切分；找不到自然边界时按字符硬切。
    空白页不生成 chunk。
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap 必须大于等于 0 且小于 chunk_size")

    chunks: list[DocumentChunk] = []
    for page in pages:
        if not page.text or not page.text.strip():
            continue

        page_text = page.text
        page_chunk_index = 0
        start = 0

        while start < len(page_text):
            end = min(start + chunk_size, len(page_text))

            if end < len(page_text):
                boundary_start = start + max(1, chunk_size // 2)
                boundary = _find_last_boundary(
                    page_text,
                    boundary_start,
                    end,
                )
                if boundary is not None:
                    end = boundary

            text = page_text[start:end]
            if text.strip():
                chunks.append(
                    DocumentChunk(
                        id=f"{document_id}:p{page.page_number}:c{page_chunk_index}",
                        document_id=document_id,
                        original_filename=original_filename,
                        page_number=page.page_number,
                        chunk_index=page_chunk_index,
                        text=text,
                        char_start=start,
                        char_end=end,
                        character_count=len(text),
                    )
                )
                page_chunk_index += 1

            if end >= len(page_text):
                break

            next_start = end - chunk_overlap
            start = next_start if next_start > start else end

    return chunks


def _find_last_boundary(text: str, min_end: int, max_end: int) -> int | None:
    """在 [min_end, max_end) 内寻找最后一个句末/换行边界，返回包含分隔符的 end。"""
    best_position = -1
    for delimiter in _BOUNDARY_CHARS:
        position = text.rfind(delimiter, min_end, max_end)
        if position > best_position:
            best_position = position
    return best_position + 1 if best_position >= 0 else None
