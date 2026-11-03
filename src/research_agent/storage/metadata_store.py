"""文档 JSON 元数据的本地持久化。"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


class MetadataStoreError(Exception):
    """元数据读写失败。"""


class MetadataStore:
    """以 ``{document_id}.json`` 文件保存元数据的低层存储。"""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).expanduser().resolve()

    @property
    def root(self) -> Path:
        """返回解析后的元数据存储根目录。"""
        return self._root

    def ensure_directory(self) -> None:
        """确保元数据目录存在。"""
        self._root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _canonical_document_id(document_id: str) -> str:
        """校验并规范化 UUID。"""
        try:
            return str(UUID(document_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("无效的文档 ID") from exc

    def path_for(self, document_id: str) -> Path:
        """返回元数据文件路径，并确认它位于配置目录内。"""
        canonical_id = self._canonical_document_id(document_id)
        path = (self._root / f"{canonical_id}.json").resolve()
        if path.parent != self._root:
            raise ValueError("元数据路径越界")
        return path

    def write(self, document_id: str, payload: dict[str, Any]) -> None:
        """通过临时文件替换的方式原子写入 UTF-8 JSON。"""
        self.ensure_directory()
        canonical_id = self._canonical_document_id(document_id)
        path = self.path_for(canonical_id)
        temp_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._root,
                prefix=f".{canonical_id}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

            temp_path.replace(path)
        except Exception as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise MetadataStoreError("写入文档元数据失败") from exc

    def read(self, document_id: str) -> dict[str, Any] | None:
        """读取单个文档元数据；不存在时返回 None。"""
        path = self.path_for(document_id)
        if not path.is_file():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise MetadataStoreError("读取文档元数据失败") from exc

        if not isinstance(data, dict):
            raise MetadataStoreError("文档元数据格式错误")
        return data

    def iter_all(self) -> list[dict[str, Any]]:
        """读取全部合法 UUID 元数据；无法读取的文件跳过并记录警告。"""
        if not self._root.is_dir():
            return []

        records: list[dict[str, Any]] = []
        for path in sorted(self._root.glob("*.json")):
            try:
                UUID(path.stem)
            except ValueError:
                logger.warning("跳过文件名不是 UUID 的元数据: %s", path.name)
                continue

            try:
                data = self.read(path.stem)
            except MetadataStoreError:
                logger.warning("跳过无法读取的元数据文件: %s", path.name)
                continue

            if data is not None:
                records.append(data)
        return records

    def delete(self, document_id: str) -> bool:
        """删除元数据 JSON；不存在时返回 False。"""
        path = self.path_for(document_id)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise MetadataStoreError("删除文档元数据失败") from exc
