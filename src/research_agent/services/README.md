# services

业务服务层。

当前已实现：

- `document_service.py`：上传校验、PDF 解析、元数据保存、查询、删除和索引清理回调。
- `pdf_service.py`：使用 PyMuPDF 按页提取文本。
- `metadata_service.py`：文档元数据与 Pydantic 模型互转。
- `chunking_service.py`：页码级纯函数分块，支持自然边界、overlap 和稳定 chunk ID。
- `embedding_service.py`：可替换 Embedding 接口；本地 sentence-transformers 懒加载。
- `indexing_service.py`：分块、向量化、chunk JSON、FAISS 索引和删除同步。
- `retrieval_service.py`：查询向量化、FAISS 检索和引用结果组装。
- `llm_service.py`：本地 OpenAI-compatible LLM Provider 和受控 Prompt。
- `citation_service.py`：只根据实际 evidence 生成服务端引用。
- `qa_service.py`：证据过滤、拒答、LLM 调用和引用编排。
- `query_rewrite_service.py`：复用本地 LLM 改写检索问题，并校验输出。
- `agent_service.py`：构建 LangGraph 工作流、隔离请求状态、组装安全摘要。

当前不包含多轮对话、流式输出、多 Agent 或工具调用。
