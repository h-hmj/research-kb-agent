"""基于 PyMuPDF 的 PDF 逐页文本解析。"""

import logging

import pymupdf

from ..schemas.documents import DocumentPage

logger = logging.getLogger(__name__)


class PDFParseError(Exception):
    """PDF 无法打开或无法提取文本。"""


class PDFService:
    """只负责打开 PDF 并按页提取文本。"""

    def parse(self, pdf_data: bytes) -> list[DocumentPage]:
        """解析已限制大小的 PDF 字节，页码从 1 开始，空白页保留为空文本。

        上传阶段始终流式落盘；这里只对已通过大小限制的文件做内存解析，
        避免 PyMuPDF 在 Windows 上因打开失败而持有文件锁。
        """
        try:
            with pymupdf.open(stream=pdf_data, filetype="pdf") as document:
                if document.needs_pass:
                    raise PDFParseError("PDF 文件已加密")

                pages: list[DocumentPage] = []
                for page_number, page in enumerate(document, start=1):
                    text = page.get_text("text") or ""
                    pages.append(
                        DocumentPage(
                            page_number=page_number,
                            text=text,
                            character_count=len(text),
                        )
                    )
                return pages
        except PDFParseError:
            raise
        except Exception as exc:
            logger.warning("PDF 解析失败: %s", type(exc).__name__)
            raise PDFParseError("PDF 文件损坏或无法解析") from exc
