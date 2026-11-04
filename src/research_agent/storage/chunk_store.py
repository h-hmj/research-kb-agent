"""每篇文档的 chunk JSON 本地存储。"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

from ..schemas.retrieval import DocumentChunk

logger = logging.getLogger(__name__)


class ChunkStoreError(Exception):
    """chunk 文件读写失败。"""


class ChunkStore:
    """使用 ``{document_id}.json`` 保存页码级 chunk。"""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).expanduser().resolve()

    @property
    def root(self) -> Path:
        return self._root

    def ensure_directory(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _canonical_document_id(document_id: str) -> str:
        try:
            return str(UUID(document_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("无效的文档 ID") from exc

    def path_for(self, document_id: str) -> Path:
        canonical_id = self._canonical_document_id(document_id)
        path = (self._root / f"{canonical_id}.json").resolve()
        if path.parent != self._root:
            raise ValueError("chunk 路径越界")
        return path

    def write(self, document_id: str, chunks: list[DocumentChunk]) -> None:
        """原子写入 UTF-8 JSON 数组。"""
        canonical_id = self._canonical_document_id(document_id)
        self.ensure_directory()
        payload = [chunk.model_dump(mode="json") for chunk in chunks]
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._atomic_write(self.path_for(canonical_id), data)

    def read(self, document_id: str) -> list[dict[str, Any]] | None:
        """读取 chunk JSON；不存在返回 None。"""
        path = self.path_for(document_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ChunkStoreError("读取 chunk 文件失败") from exc
        if not isinstance(payload, list):
            raise ChunkStoreError("chunk 文件格式错误")
        return payload

    def read_bytes(self, document_id: str) -> bytes | None:
        """读取原始 chunk 文件字节，供索引失败时回滚。"""
        path = self.path_for(document_id)
        try:
            return path.read_bytes() if path.is_file() else None
        except OSError as exc:
            raise ChunkStoreError("读取 chunk 文件失败") from exc

    def restore(self, document_id: str, data: bytes | None) -> None:
        """恢复旧 chunk 文件；data 为 None 时删除。"""
        path = self.path_for(document_id)
        if data is None:
            self.delete(document_id)
            return
        self.ensure_directory()
        self._atomic_write(path, data)

    def delete(self, document_id: str) -> bool:
        """删除 chunk 文件；不存在返回 False。"""
        path = self.path_for(document_id)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ChunkStoreError("删除 chunk 文件失败") from exc

    def list_document_ids(self) -> list[str]:
        """列出当前存在 chunk 文件的合法文档 ID。"""
        if not self._root.is_dir():
            return []
        ids: list[str] = []
        for path in sorted(self._root.glob("*.json")):
            try:
                ids.append(str(UUID(path.stem)))
            except ValueError:
                logger.warning("跳过文件名不是 UUID 的 chunk 文件: %s", path.name)
        return ids

    def _atomic_write(self, target: Path, data: bytes) -> None:
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self._root,
                prefix=f".{target.stem}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(target)
        except Exception as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise ChunkStoreError("写入 chunk 文件失败") from exc
