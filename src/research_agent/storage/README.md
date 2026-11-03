# storage

本地存储层。

当前已实现：

- `file_storage.py`：将 PDF 以 UUID 文件名流式写入本地目录，限制大小并安全删除。
- `metadata_store.py`：将文档元数据以 UTF-8 JSON 原子写入 `{document_id}.json`。

不连接数据库或外部存储服务。所有路径都从配置读取，并使用
`pathlib` 与 UUID 校验防止路径穿越。
