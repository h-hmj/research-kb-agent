"""FAISS 本地向量索引与 manifest 持久化。"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from ..schemas.retrieval import DocumentChunk

logger = logging.getLogger(__name__)

_MANIFEST_VERSION = 1


class VectorStoreError(Exception):
    """向量索引读写失败的基类。"""


class VectorStoreCorruptionError(VectorStoreError):
    """索引或 manifest 不一致、损坏。"""


class VectorStoreWriteError(VectorStoreError):
    """索引或 manifest 写入失败。"""


@dataclass
class _Snapshot:
    dimension: int
    entries: list[dict[str, Any]]
    index: faiss.Index


class VectorStore:
    """使用 IndexFlatIP 保存归一化向量，并维护稳定的 manifest 映射。"""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).expanduser().resolve()
        self._index_path = self._root / "index.faiss"
        self._manifest_path = self._root / "manifest.json"
        self._lock = threading.RLock()

    @property
    def lock(self) -> threading.RLock:
        """进程内锁；索引编排层可用它保证 chunk 与索引的一致性。"""
        return self._lock

    def ensure_directory(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    def indexed_document_ids(self) -> set[str]:
        """返回 manifest 中当前已索引的文档 ID。"""
        with self._lock:
            snapshot = self._load_snapshot()
            if snapshot is None:
                return set()
            return {
                entry["chunk"]["document_id"]
                for entry in snapshot.entries
            }

    def upsert_document(
        self,
        document_id: str,
        chunks: list[DocumentChunk],
        vectors: np.ndarray,
    ) -> int:
        """替换某文档的全部向量，并返回索引维度。"""
        with self._lock:
            snapshot = self._load_snapshot()
            remaining_entries: list[dict[str, Any]] = []
            remaining_vectors: list[np.ndarray] = []

            if snapshot is not None:
                for position, entry in enumerate(snapshot.entries):
                    if entry["chunk"]["document_id"] == document_id:
                        continue
                    try:
                        vector = snapshot.index.reconstruct(position)
                    except Exception as exc:
                        raise VectorStoreCorruptionError(
                            "无法从 FAISS 索引还原向量"
                        ) from exc
                    remaining_entries.append(
                        {
                            "vector_position": len(remaining_entries),
                            "chunk": entry["chunk"],
                        }
                    )
                    remaining_vectors.append(
                        np.asarray(vector, dtype=np.float32)
                    )

            if vectors.ndim != 2 or vectors.shape[0] != len(chunks):
                raise VectorStoreCorruptionError("Embedding 向量数量不匹配")

            new_dimension = int(vectors.shape[1]) if chunks else 0
            existing_dimension = snapshot.dimension if snapshot else 0
            if (
                remaining_entries
                and chunks
                and existing_dimension != new_dimension
            ):
                raise VectorStoreCorruptionError("新旧向量维度不一致")
            dimension = existing_dimension if remaining_entries else new_dimension

            new_entries: list[dict[str, Any]] = []
            for offset, chunk in enumerate(chunks):
                new_entries.append(
                    {
                        "vector_position": len(remaining_entries) + offset,
                        "chunk": chunk.model_dump(mode="json"),
                    }
                )

            all_entries = remaining_entries + new_entries
            if not all_entries:
                self._remove_index_files()
                return 0

            parts: list[np.ndarray] = []
            if remaining_vectors:
                parts.append(np.vstack(remaining_vectors))
            if chunks:
                parts.append(np.asarray(vectors, dtype=np.float32))
            if not parts:
                raise VectorStoreCorruptionError("没有可写入的向量")

            all_vectors = np.ascontiguousarray(np.vstack(parts), dtype=np.float32)
            if all_vectors.shape != (len(all_entries), dimension):
                raise VectorStoreCorruptionError("向量矩阵与 manifest 数量不一致")

            index = faiss.IndexFlatIP(dimension)
            index.add(all_vectors)
            manifest = {
                "version": _MANIFEST_VERSION,
                "dimension": dimension,
                "entries": all_entries,
            }
            self._write_index_files(index, manifest)
            return dimension

    def delete_document(self, document_id: str) -> bool:
        """重建索引以移除某文档的全部向量。"""
        with self._lock:
            snapshot = self._load_snapshot()
            if snapshot is None:
                return False

            remaining_entries: list[dict[str, Any]] = []
            remaining_vectors: list[np.ndarray] = []
            removed = False

            for position, entry in enumerate(snapshot.entries):
                if entry["chunk"]["document_id"] == document_id:
                    removed = True
                    continue
                try:
                    vector = snapshot.index.reconstruct(position)
                except Exception as exc:
                    raise VectorStoreCorruptionError(
                        "无法从 FAISS 索引还原向量"
                    ) from exc
                remaining_entries.append(
                    {
                        "vector_position": len(remaining_entries),
                        "chunk": entry["chunk"],
                    }
                )
                remaining_vectors.append(np.asarray(vector, dtype=np.float32))

            if not removed:
                return False

            if not remaining_entries:
                self._remove_index_files()
                return True

            all_vectors = np.ascontiguousarray(
                np.vstack(remaining_vectors),
                dtype=np.float32,
            )
            index = faiss.IndexFlatIP(snapshot.dimension)
            index.add(all_vectors)
            manifest = {
                "version": _MANIFEST_VERSION,
                "dimension": snapshot.dimension,
                "entries": remaining_entries,
            }
            self._write_index_files(index, manifest)
            return True

    def search(
        self,
        query_vector: np.ndarray,
        top_k: int,
        document_ids: set[str] | None = None,
    ) -> list[tuple[float, dict[str, Any]]]:
        """返回 (score, chunk) 列表，按内积分数降序。"""
        with self._lock:
            snapshot = self._load_snapshot()
            if snapshot is None or snapshot.index.ntotal == 0:
                return []

            query = np.asarray(query_vector, dtype=np.float32).reshape(-1)
            if query.shape[0] != snapshot.dimension:
                raise VectorStoreCorruptionError("查询向量维度与索引不一致")

            try:
                scores, positions = snapshot.index.search(
                    np.ascontiguousarray(query.reshape(1, -1)),
                    snapshot.index.ntotal,
                )
            except Exception as exc:
                raise VectorStoreCorruptionError("FAISS 检索失败") from exc

            results: list[tuple[float, dict[str, Any]]] = []
            for score, position in zip(scores[0], positions[0]):
                position_int = int(position)
                if position_int < 0:
                    continue
                if position_int >= len(snapshot.entries):
                    raise VectorStoreCorruptionError("FAISS 返回越界位置")
                chunk = snapshot.entries[position_int]["chunk"]
                if document_ids is not None:
                    if chunk["document_id"] not in document_ids:
                        continue
                results.append((float(score), chunk))

            results.sort(key=lambda item: item[0], reverse=True)
            return results[:top_k]

    def _load_snapshot(self) -> _Snapshot | None:
        index_exists = self._index_path.is_file()
        manifest_exists = self._manifest_path.is_file()
        if not index_exists and not manifest_exists:
            return None
        if index_exists != manifest_exists:
            raise VectorStoreCorruptionError("index.faiss 与 manifest.json 不完整")

        try:
            manifest = json.loads(
                self._manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise VectorStoreCorruptionError("manifest.json 无法读取") from exc

        if not isinstance(manifest, dict):
            raise VectorStoreCorruptionError("manifest.json 格式错误")
        if manifest.get("version") != _MANIFEST_VERSION:
            raise VectorStoreCorruptionError("manifest 版本不支持")
        dimension = manifest.get("dimension")
        entries = manifest.get("entries")
        if not isinstance(dimension, int) or dimension <= 0:
            raise VectorStoreCorruptionError("manifest 维度无效")
        if not isinstance(entries, list):
            raise VectorStoreCorruptionError("manifest entries 无效")

        try:
            index = faiss.read_index(str(self._index_path))
        except Exception as exc:
            raise VectorStoreCorruptionError("FAISS 索引无法读取") from exc

        if index.ntotal != len(entries):
            raise VectorStoreCorruptionError("FAISS 数量与 manifest 不一致")
        if entries and index.d != dimension:
            raise VectorStoreCorruptionError("FAISS 维度与 manifest 不一致")

        for position, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise VectorStoreCorruptionError("manifest entry 格式错误")
            if entry.get("vector_position") != position:
                raise VectorStoreCorruptionError("manifest 向量位置不连续")
            chunk_payload = entry.get("chunk")
            if not isinstance(chunk_payload, dict):
                raise VectorStoreCorruptionError("manifest chunk 格式错误")
            try:
                DocumentChunk.model_validate(chunk_payload)
            except Exception as exc:
                raise VectorStoreCorruptionError("manifest chunk 内容无效") from exc

        return _Snapshot(dimension=dimension, entries=entries, index=index)

    def _write_index_files(
        self,
        index: faiss.Index,
        manifest: dict[str, Any],
    ) -> None:
        self.ensure_directory()
        index_temp: Path | None = None
        manifest_temp: Path | None = None

        old_index = (
            self._index_path.read_bytes() if self._index_path.is_file() else None
        )
        old_manifest = (
            self._manifest_path.read_bytes()
            if self._manifest_path.is_file()
            else None
        )

        try:
            fd, temp_name = tempfile.mkstemp(
                dir=self._root,
                prefix=".index.",
                suffix=".tmp",
            )
            os.close(fd)
            index_temp = Path(temp_name)
            faiss.write_index(index, str(index_temp))

            manifest_data = json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self._root,
                prefix=".manifest.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                manifest_temp = Path(handle.name)
                handle.write(manifest_data)
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(index_temp, self._index_path)
            os.replace(manifest_temp, self._manifest_path)
        except Exception as exc:
            if index_temp is not None:
                index_temp.unlink(missing_ok=True)
            if manifest_temp is not None:
                manifest_temp.unlink(missing_ok=True)
            self._restore_file(self._index_path, old_index)
            self._restore_file(self._manifest_path, old_manifest)
            raise VectorStoreWriteError("索引写入失败") from exc

    def _remove_index_files(self) -> None:
        self._index_path.unlink(missing_ok=True)
        self._manifest_path.unlink(missing_ok=True)

    def _restore_file(self, path: Path, data: bytes | None) -> None:
        try:
            if data is None:
                path.unlink(missing_ok=True)
                return
            fd, temp_name = tempfile.mkstemp(
                dir=self._root,
                prefix=f".{path.name}.",
                suffix=".restore",
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except OSError:
            logger.critical("恢复索引文件失败: %s", path.name)
