"""PDF 文件的本地安全存储。"""

import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID


class FileTooLargeError(Exception):
    """上传内容超过配置的大小限制。"""


class FileStorage:
    """只负责 PDF 文件的保存、路径解析和删除。"""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).expanduser().resolve()

    @property
    def root(self) -> Path:
        """返回解析后的文档存储根目录。"""
        return self._root

    def ensure_directory(self) -> None:
        """确保文档目录存在。"""
        self._root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _canonical_document_id(document_id: str) -> str:
        """校验并规范化 UUID，阻止把任意字符串拼入文件路径。"""
        try:
            return str(UUID(document_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("无效的文档 ID") from exc

    def path_for(self, document_id: str) -> Path:
        """返回文档的预期路径，并确认它位于配置目录内。"""
        canonical_id = self._canonical_document_id(document_id)
        path = (self._root / f"{canonical_id}.pdf").resolve()
        if path.parent != self._root:
            raise ValueError("文档路径越界")
        return path

    async def save_chunks(
        self,
        chunks: AsyncIterator[bytes],
        document_id: str,
        max_bytes: int,
    ) -> int:
        """流式写入上传内容，超过限制时删除临时文件并拒绝上传。"""
        canonical_id = self._canonical_document_id(document_id)
        self.ensure_directory()
        final_path = self.path_for(canonical_id)
        temp_path = self._root / f".{canonical_id}.uploading"
        total_bytes = 0

        try:
            with temp_path.open("wb") as handle:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        raise FileTooLargeError("上传文件超过大小限制")
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())

            temp_path.replace(final_path)
            return total_bytes
        except BaseException:
            temp_path.unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)
            raise

    def read_bytes(self, document_id: str) -> bytes:
        """读取已保存的 PDF 字节；文件大小已在写入阶段受到限制。"""
        path = self.path_for(document_id)
        return path.read_bytes()

    def delete(self, document_id: str) -> bool:
        """根据 UUID 删除 PDF，不会接受用户提供的任意路径。"""
        path = self.path_for(document_id)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
