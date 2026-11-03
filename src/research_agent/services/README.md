# services

业务服务层。

当前已实现：

- `pdf_service.py`：使用 PyMuPDF 打开 PDF，按页提取文本并保留页码。
- `metadata_service.py`：在 JSON 元数据与 Pydantic 模型之间转换。
- `document_service.py`：协调上传校验、流式保存、PDF 解析、元数据写入和删除。

后续阶段在需求明确后再加入文本分块、检索、实验记录问答和模型编排；
当前不包含向量检索、RAG、LangChain、LangGraph 或大模型调用。
