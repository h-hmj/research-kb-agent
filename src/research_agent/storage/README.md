# storage

本地存储层。

当前已实现：

- `file_storage.py`：PDF 流式写入、读取和安全删除。
- `metadata_store.py`：文档元数据 JSON 原子读写。
- `chunk_store.py`：每篇文档的 chunk JSON 原子读写与回滚。
- `vector_store.py`：FAISS `IndexFlatIP` 索引、manifest 映射、重建和进程内锁。

所有路径都从配置读取，使用 `pathlib`、UUID 和父目录校验限制在配置目录内。
向量索引只保存在本机，不连接云端数据库。
