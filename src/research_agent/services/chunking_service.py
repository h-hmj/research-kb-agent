"""页码级文本分块。

分块只发生在单页内部，绝不跨页拼接。相同文档、页码和 chunk 序号会生成相同 ID。

三条约束：
- 不跨页：引用（citation）需要精确到页码，跨页 chunk 会让页码归属失真；
- ID 可复现：同一文档重复索引得到相同 chunk ID，便于覆盖写入和引用回溯；
- 空白内容不产出 chunk：空白页和页内的纯空白片段都不进索引。
"""

from collections.abc import Sequence

from ..schemas.documents import DocumentPage
from ..schemas.retrieval import DocumentChunk

# 可作为切分点的字符：换行 + 中英文句末标点，命中任意一个即视为自然边界。
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

    切分规则：
    - 每个 chunk 的目标长度是 chunk_size，相邻 chunk 重叠 chunk_overlap 个字符；
    - 句子边界只在窗口后半段寻找，避免为了对齐标点把 chunk 切得过短；
    - 找不到边界时退化为按字符硬切，保证 start 一定向前推进。
    """
    # 参数前置校验：overlap 必须严格小于窗口长度，
    # 否则滑动步长（end - overlap）会 <= 0，循环无法前进。
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap 必须大于等于 0 且小于 chunk_size")

    chunks: list[DocumentChunk] = []
    for page in pages:
        # 空白页（扫描件未识别、纯图片页等）直接跳过，避免索引里出现空 chunk。
        if not page.text or not page.text.strip():
            continue

        page_text = page.text
        page_chunk_index = 0
        start = 0

        while start < len(page_text):
            # 先按固定窗口取 [start, start + chunk_size)；页尾不足一个窗口时截到页尾。
            end = min(start + chunk_size, len(page_text))

            # 只有右侧还有剩余内容时才需要对边界，最后一个 chunk 允许直接到页尾。
            if end < len(page_text):
                # 边界搜索范围限制在窗口后半段：避免命中的标点太靠前，
                # 导致 chunk 长度明显短于 chunk_size。
                boundary_start = start + max(1, chunk_size // 2)
                boundary = _find_last_boundary(
                    page_text,
                    boundary_start,
                    end,
                )
                if boundary is not None:
                    # 对齐到自然边界；返回值已包含分隔符，即分隔符留在本 chunk 末尾。
                    end = boundary

            text = page_text[start:end]
            # 纯空白片段（例如整段换行）不产出 chunk，也不占用 chunk 序号，
            # 从而保证同一页内 chunk_index 连续。
            if text.strip():
                # ID = 文档ID + 页码 + 页内序号：
                # 同一文档重复索引会得到相同 ID（幂等覆盖），且能从 ID 反推引用页码。
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

            # 已经切到页尾，本页结束。
            if end >= len(page_text):
                break

            # 下一个窗口从 end 回退 chunk_overlap 开始，保留相邻 chunk 的上下文重叠。
            # 兜底：若回退后仍不大于 start（理论上已被前置校验拦住），
            # 就退化为从 end 开始，绝不允许 start 不前进。
            next_start = end - chunk_overlap
            start = next_start if next_start > start else end

    return chunks


def _find_last_boundary(text: str, min_end: int, max_end: int) -> int | None:
    """在 [min_end, max_end) 内寻找最后一个句末/换行边界，返回包含分隔符的 end。

    返回「分隔符下标 + 1」，即切分后分隔符留在左侧 chunk 的末尾，
    使 chunk 以句号/换行收尾，阅读和引用都更自然。
    """
    # 遍历所有边界字符，取最靠右（最接近 max_end）的那一个。
    best_position = -1
    for delimiter in _BOUNDARY_CHARS:
        position = text.rfind(delimiter, min_end, max_end)
        if position > best_position:
            best_position = position
    # 返回 -1 时表示窗口后半段没有自然边界，由调用方按字符硬切。
    return best_position + 1 if best_position >= 0 else None
