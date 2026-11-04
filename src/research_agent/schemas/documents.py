"""文档上传、列表和详情的 Pydantic 模型。"""

from typing import Literal

from pydantic import BaseModel, Field

DocumentStatus = Literal["processed", "failed"]
IndexStatus = Literal["not_indexed", "indexed", "failed"]


class DocumentPage(BaseModel):
    """PDF 单页文本及其页码。"""

    page_number: int = Field(ge=1, description="从 1 开始的页码")
    text: str = Field(description="该页提取出的文本，空白页为空字符串")
    character_count: int = Field(ge=0, description="该页字符数")


class DocumentSummary(BaseModel):
    """文档列表项。"""

    id: str = Field(description="文档 UUID")
    original_filename: str = Field(description="清理后的原始文件名")
    stored_filename: str = Field(description="本地保存的 UUID 文件名")
    file_size: int = Field(ge=0, description="文件字节数")
    page_count: int = Field(ge=0, description="PDF 页数")
    created_at: str = Field(description="UTC ISO 8601 创建时间")
    status: DocumentStatus = Field(description="处理状态")
    index_status: IndexStatus = Field(
        default="not_indexed",
        description="向量索引状态",
    )


class DocumentDetail(DocumentSummary):
    """文档详情，包含逐页文本。"""

    pages: list[DocumentPage] = Field(description="按页码排序的页面列表")


class DocumentListResponse(BaseModel):
    """分页后的文档列表。"""

    items: list[DocumentSummary] = Field(description="当前页的文档")
    page: int = Field(ge=1, description="当前页码")
    page_size: int = Field(ge=1, description="每页数量")
    total: int = Field(ge=0, description="文档总数")
