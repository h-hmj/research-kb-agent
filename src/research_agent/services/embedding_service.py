"""本地 Embedding 抽象与 sentence-transformers 实现。"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from ..core.exceptions import EmbeddingModelUnavailableError

logger = logging.getLogger(__name__)

EMBEDDING_UNAVAILABLE_DETAIL = (
    "本地 Embedding 模型不可用，请检查 EMBEDDING_MODEL_PATH 配置和模型文件。"
)


class EmbeddingService(Protocol):
    """可替换的 Embedding 接口，测试可注入确定性 Fake。"""

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """返回形状为 (len(texts), dimension) 的 float32 向量。"""

    def embed_query(self, query: str) -> np.ndarray:
        """返回形状为 (dimension,) 的 float32 查询向量。"""


class SentenceTransformerEmbeddingService:
    """懒加载本地 sentence-transformers 模型。"""

    def __init__(
        self,
        model_path: Path,
        device: str = "cpu",
        normalize: bool = True,
    ) -> None:
        self._model_path = Path(model_path).expanduser()
        self._device = device
        self._normalize = normalize
        self._model: Any = None
        self._lock = threading.Lock()

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        with self._lock:
            if self._model is not None:
                return self._model

            if not self._model_path.is_dir():
                raise EmbeddingModelUnavailableError("模型目录不存在")

            # 必须在导入/加载模型前显式关闭 Hugging Face 网络访问。
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

            try:
                from sentence_transformers import SentenceTransformer
            except Exception as exc:
                logger.error("sentence-transformers 不可用: %s", type(exc).__name__)
                raise EmbeddingModelUnavailableError("Embedding 依赖不可用") from exc

            try:
                self._model = SentenceTransformer(
                    str(self._model_path),
                    device=self._device,
                    local_files_only=True,
                )
            except Exception as exc:
                logger.error("本地 Embedding 模型加载失败: %s", type(exc).__name__)
                raise EmbeddingModelUnavailableError("Embedding 模型加载失败") from exc

            return self._model

    def _encode(self, texts: list[str]) -> np.ndarray:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("Embedding 输入不能为空")

        model = self._load_model()
        try:
            vectors = model.encode(
                texts,
                convert_to_numpy=True,
                normalize_embeddings=self._normalize,
                show_progress_bar=False,
            )
        except Exception as exc:
            logger.error("Embedding 推理失败: %s", type(exc).__name__)
            raise EmbeddingModelUnavailableError("Embedding 推理失败") from exc

        array = np.asarray(vectors, dtype=np.float32)
        if array.ndim == 1:
            array = array.reshape(1, -1)
        if array.shape[0] != len(texts):
            raise EmbeddingModelUnavailableError("Embedding 返回数量不匹配")

        if self._normalize:
            norms = np.linalg.norm(array, axis=1, keepdims=True)
            array = np.divide(
                array,
                norms,
                out=np.zeros_like(array),
                where=norms > 0,
            )

        return np.ascontiguousarray(array, dtype=np.float32)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """批量编码文本。"""
        return self._encode(texts)

    def embed_query(self, query: str) -> np.ndarray:
        """编码单条查询。"""
        if not query.strip():
            raise ValueError("query 不能为空")
        return self._encode([query])[0]
