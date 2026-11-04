# 科研知识库与实验助理 Agent

一个面向论文与实验记录的知识库 Agent 后端。项目采用 FastAPI、Pydantic Settings、
本地文件存储和 JSON 元数据，按可扩展的分层结构搭建，后续将逐步接入检索和模型编排。

当前已完成：

- **第一阶段**：项目骨架、配置、日志、健康检查、测试和 Docker 配置。
- **第二阶段**：PDF 上传、类型与大小校验、本地保存、PyMuPDF 逐页解析、
  页码保留、JSON 元数据管理、文档列表/详情/删除 API。
- **第三阶段**：页码级分块、本地 Embedding 抽象、FAISS 向量索引、
  索引持久化、检索接口、引用回溯与删除同步。

当前不调用任何外部网络 API，不使用数据库或云端向量库。向量化仅允许从
本地模型目录加载，代码不会自动下载模型。

## 当前阶段实现范围

### 第一阶段（保留）

- [x] `src` 布局的 Python 项目骨架与全部包 `__init__.py`
- [x] FastAPI 应用工厂、生命周期日志与全局异常日志
- [x] `GET /api/v1/health` 健康检查（Pydantic 响应模型）
- [x] `GET /` 项目信息
- [x] 基于 `pydantic-settings` 的环境变量配置，无 `.env` 也能启动
- [x] Python 标准库日志，级别由 `LOG_LEVEL` 控制
- [x] pytest + httpx ASGITransport 异步测试
- [x] Dockerfile、docker-compose.yml 和 Windows 使用说明

### 第二阶段（文档接入基础）

- [x] 检查文件名、扩展名、Content-Type 和文件大小
- [x] 使用 UUID 保存 PDF，禁止将用户文件名直接用作路径
- [x] 使用 PyMuPDF 打开 PDF，按页提取文本
- [x] 页码从 1 开始，空白页保留，字符数逐页记录
- [x] 使用本地 JSON 保存文档元数据和逐页文本
- [x] 元数据原子写入，UTF-8 编码，`ensure_ascii=False`
- [x] 查询文档列表（分页）与文档详情
- [x] 删除文档时同时删除 PDF 和元数据，并限制在配置目录内
- [x] 损坏/伪造 PDF 返回明确 400 错误且不保留成功元数据
- [x] 所有测试使用临时目录，不污染真实 `data` 目录

### 第三阶段（文本分块与本地向量检索）

- [x] 按单页分块，空白页不生成 chunk
- [x] chunk 保留文档 ID、文件名、页码、页内序号和字符范围
- [x] 自然边界优先 + 字符硬切；`CHUNK_OVERLAP < CHUNK_SIZE`
- [x] 可替换 Embedding 接口；真实实现懒加载本地 sentence-transformers
- [x] 强制 `local_files_only=True` 和离线环境变量，不联网下载模型
- [x] FAISS `IndexFlatIP` 本地索引，保存 `index.faiss` 与 `manifest.json`
- [x] 每篇文档保存 `chunks/{document_id}.json`
- [x] 单文档索引、重建索引、自然语言检索 API
- [x] 检索结果返回文档名、文档 ID、页码、chunk 序号、原文和分数
- [x] 删除文档时同步删除 chunk、FAISS 向量和 manifest 记录
- [x] 模型缺失时索引/检索返回 503，其余文档接口正常工作
- [x] 使用 FakeEmbedding 执行真实 FAISS 分块、持久化、重建和检索测试

**尚未实现**：OCR、大模型回答、问题改写、流式输出、Agent 工作流、
LangChain、LangGraph、Web 前端、远程 Embedding API。扫描型 PDF 可以上传，
但没有文字层时提取结果为空，当前不会自动 OCR。

## 第三阶段数据流

```text
上传 PDF
  → PyMuPDF 按页提取文本（第二阶段）
  → POST /documents/{id}/index
  → 单页内分块（500 字符，重叠 80）
  → 本地 sentence-transformers Embedding（默认 bge-small-zh-v1.5）
  → FAISS IndexFlatIP + manifest.json
  → POST /retrieval/search
  → 返回文档名、文档 ID、页码、chunk 序号、原文前缀和分数
```

上传成功后不会自动索引；用户必须显式调用索引接口。索引和检索均不调用
在线 API，也不会自动下载模型。

## 项目目录结构

```text
research-agent/
├── src/
│   └── research_agent/
│       ├── __init__.py
│       ├── main.py                       # FastAPI 应用、服务装配、生命周期
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config.py                 # Settings 与配置校验
│       │   └── logging.py                # 标准日志初始化
│       ├── api/
│       │   ├── __init__.py
│       │   └── routes/
│       │       ├── __init__.py
│       │       ├── health.py             # 健康检查
│       │       ├── documents.py          # 上传/列表/详情/删除/索引
│       │       └── retrieval.py          # 自然语言检索
│       ├── schemas/
│       │   ├── __init__.py
│       │   ├── common.py                 # 通用响应
│       │   ├── documents.py              # 文档与 index_status
│       │   └── retrieval.py              # chunk、索引和检索模型
│       ├── services/
│       │   ├── __init__.py
│       │   ├── README.md
│       │   ├── document_service.py       # 文档生命周期协调
│       │   ├── metadata_service.py       # 元数据领域服务
│       │   ├── pdf_service.py            # PyMuPDF 逐页解析
│       │   ├── chunking_service.py       # 页码级纯函数分块
│       │   ├── embedding_service.py      # 本地 Embedding 抽象与实现
│       │   ├── indexing_service.py       # 索引重建与删除同步
│       │   └── retrieval_service.py      # 检索结果组装
│       └── storage/
│           ├── __init__.py
│           ├── README.md
│           ├── file_storage.py           # PDF 流式保存与安全删除
│           ├── metadata_store.py         # 元数据 JSON 原子读写
│           ├── chunk_store.py            # 每文档 chunk JSON
│           └── vector_store.py           # FAISS + manifest 持久化
├── tests/
│   ├── __init__.py
│   ├── conftest.py                       # 临时目录与应用测试客户端
│   ├── test_health.py                    # 第一阶段测试
│   ├── test_documents.py                 # 第二阶段测试
│   └── test_retrieval.py                 # 第三阶段分块/索引/检索测试
├── data/                                 # 启动时自动创建，已被 .gitignore 忽略
│   ├── documents/                        # UUID.pdf
│   ├── metadata/                         # UUID.json
│   ├── chunks/                           # UUID.json（页码级 chunk）
│   └── vector_store/                     # index.faiss + manifest.json
├── models/                               # 本地 Embedding 模型，不提交
│   └── bge-small-zh-v1.5/
├── .dockerignore
├── .env.example
├── .gitignore
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── README.md
└── pyproject.toml
```

## 环境要求

- Python 3.11 或更高版本（已在 Python 3.12 上验证）
- Windows 10/11
- Windows PowerShell 5.1 或 PowerShell 7+（推荐）
- pip
- Docker Desktop（仅在需要容器运行时安装）

项目运行时不访问外网，不依赖数据库或外部 API。

## Windows 本地安装

### 1. 进入项目目录

```powershell
cd E:\Documents\deepseek-harness\default-workspace\research-agent
```

### 2. 创建并激活虚拟环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

如果 PowerShell 提示禁止运行脚本，可仅对当前终端临时放开：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 3. 安装依赖

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果 pip 在本机解析索引时长时间无输出，可禁用缓存重试：

```powershell
python -m pip install --no-cache-dir -r requirements.txt
```

`sentence-transformers` 会安装 PyTorch。若默认 PyPI 下载 torch 很慢，可以先装 CPU 版本：

```powershell
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
```

主要依赖：

- `PyMuPDF`：PDF 打开和逐页文本提取
- `python-multipart`：FastAPI `multipart/form-data` 上传解析
- `numpy`：Embedding 向量与数值处理
- `faiss-cpu`：本地向量索引（`IndexFlatIP`）
- `sentence-transformers`：从本地目录加载 Embedding 模型

### 4. 本地 Embedding 模型准备

代码**不会自动下载模型**。需要在有网环境预先下载模型，再把整个目录复制到离线环境：

```powershell
pip install -U huggingface_hub
python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-small-zh-v1.5', local_dir='models/bge-small-zh-v1.5')"
```

上述下载命令只应在有网环境执行；本项目运行代码不会调用它。

默认读取：

```text
./models/bge-small-zh-v1.5
```

也可以通过 `EMBEDDING_MODEL_PATH` 指向其他本地目录。模型目录至少应包含
`sentence-transformers` 能识别的配置、权重和 tokenizer 文件。

- 服务启动不会加载模型；只有建立索引或检索时才懒加载。
- 模型目录不存在或加载失败时，索引/检索返回 `503`，上传和文档管理仍然可用。
- 运行库强制 `local_files_only=True`，并设置 Hugging Face 离线环境变量。
- 测试使用确定性 FakeEmbedding，不加载真实模型，也不需要下载模型。

### 4. 可选：创建本地配置

不创建 `.env` 也可以启动，因为 `Settings` 提供了完整默认值。需要自定义时：

```powershell
Copy-Item .env.example .env
```

`.env` 已被 `.gitignore` 忽略，禁止提交任何密钥。当前阶段不需要 API Key。

### 5. 启动服务

```powershell
uvicorn src.research_agent.main:app --reload --host 127.0.0.1 --port 8000
```

启动后会自动创建：

```text
data/documents/
data/metadata/
data/chunks/
data/vector_store/
```

访问地址：

- 项目信息：<http://127.0.0.1:8000/>
- 健康检查：<http://127.0.0.1:8000/api/v1/health>
- Swagger 文档：<http://127.0.0.1:8000/docs>
- OpenAPI：<http://127.0.0.1:8000/openapi.json>

> Swagger UI 的 JS/CSS 默认从外部 CDN 加载；在无法访问该 CDN 的网络中，
> `/docs` 可能显示空白，但 API 本身不受影响。可以直接访问接口或 `/openapi.json`。

启动日志示例：

```text
应用启动: 科研知识库与实验助理 Agent v0.1.0 (debug=False, api_prefix=/api/v1)
```

### 6. 运行测试

```powershell
python -m pytest
```

完整输出：

```powershell
python -m pytest -vv -s
```

测试使用 `httpx.AsyncClient` + `ASGITransport`，通过 AnyIO 的 asyncio 后端运行，
不创建真实测试服务器，也不访问外部服务。测试中的应用配置会把 PDF、元数据、
chunk 和向量索引写入 pytest 临时目录。第三阶段使用 FakeEmbeddingService，
但 FAISS 的写入、持久化、重载、重建和检索逻辑都是真实执行的。

预期结果（具体以实际执行为准）：

```text
44 passed
```

## 数据目录说明

默认布局：

```text
data/
├── documents/
│   └── {document_id}.pdf
├── metadata/
│   └── {document_id}.json
├── chunks/
│   └── {document_id}.json
└── vector_store/
    ├── index.faiss
    └── manifest.json
```

- PDF 与元数据使用同一个 UUID 关联。
- 用户原始文件名只保存在元数据中，不参与保存路径。
- `chunks/{id}.json` 保存该文档的页码级 chunk 数组。
- `manifest.json` 保存向量位置到 chunk 元数据的映射，FAISS 位置与数组顺序一致。
- `documents`、`metadata`、`chunks`、`vector_store` 目录都可以在 `.env` 中覆盖。
- 应用启动时会自动创建配置的目录。
- `data/` 和 `models/` 已被 `.gitignore` 忽略。

元数据示例：

```json
{
  "id": "a9d1a1da-3c22-4bf0-8ef5-6dc8e7e0a111",
  "original_filename": "paper.pdf",
  "stored_filename": "a9d1a1da-3c22-4bf0-8ef5-6dc8e7e0a111.pdf",
  "file_size": 12345,
  "page_count": 2,
  "created_at": "2026-11-03T10:00:00+00:00",
  "status": "processed",
  "index_status": "not_indexed",
  "pages": [
    {
      "page_number": 1,
      "text": "第一页文本",
      "character_count": 6
    },
    {
      "page_number": 2,
      "text": "",
      "character_count": 0
    }
  ]
}
```

写入元数据时先写同目录临时文件，再替换目标 JSON，降低写入中断留下半个文件的风险。
`status` 包含 `processed` 和 `failed`；上传失败会直接返回错误且不保留成功元数据。
`index_status` 包含 `not_indexed`、`indexed`、`failed`，上传后默认
`not_indexed`，索引成功后更新为 `indexed`。

## 配置说明

配置读取优先级：进程环境变量 > 项目根目录 `.env` > 代码默认值。
所有字段均不要求存在，缺少时使用下列默认值。

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_NAME` | `科研知识库与实验助理 Agent` | 应用标题与项目名称 |
| `APP_VERSION` | `0.1.0` | 应用版本 |
| `DEBUG` | `false` | FastAPI 调试模式 |
| `API_PREFIX` | `/api/v1` | API 路由统一前缀 |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `DATA_DIR` | `./data` | 本地数据根目录 |
| `MAX_UPLOAD_SIZE_MB` | `20` | 单个上传文件最大大小（MB） |
| `DOCUMENTS_DIR` | `./data/documents` | PDF 保存目录 |
| `METADATA_DIR` | `./data/metadata` | JSON 元数据保存目录 |
| `CHUNKS_DIR` | `./data/chunks` | 每文档 chunk JSON 目录 |
| `VECTOR_STORE_DIR` | `./data/vector_store` | FAISS 索引与 manifest 目录 |
| `EMBEDDING_MODEL_PATH` | `./models/bge-small-zh-v1.5` | 本地模型目录，不会自动下载 |
| `EMBEDDING_DEVICE` | `cpu` | Embedding 推理设备 |
| `EMBEDDING_NORMALIZE` | `true` | 是否做 L2 归一化 |
| `CHUNK_SIZE` | `500` | 单 chunk 最大字符数 |
| `CHUNK_OVERLAP` | `80` | 相邻 chunk 重叠字符数，必须小于 `CHUNK_SIZE` |
| `RETRIEVAL_TOP_K` | `5` | 默认检索返回数量，最大 20 |
| `MAX_RETRIEVAL_TEXT_LENGTH` | `1000` | 返回原文片段最大长度 |

示例：

```powershell
$env:LOG_LEVEL = "DEBUG"
$env:MAX_UPLOAD_SIZE_MB = "10"
$env:DOCUMENTS_DIR = "./data/documents"
$env:METADATA_DIR = "./data/metadata"
$env:CHUNKS_DIR = "./data/chunks"
$env:VECTOR_STORE_DIR = "./data/vector_store"
$env:EMBEDDING_MODEL_PATH = "./models/bge-small-zh-v1.5"
$env:CHUNK_SIZE = "500"
$env:CHUNK_OVERLAP = "80"
uvicorn src.research_agent.main:app --reload --port 8000
```

注意：环境变量在启动服务的终端中设置，重启终端后失效；持久配置请使用 `.env`。

## API 示例

所有业务接口统一使用配置中的 `API_PREFIX`，默认为 `/api/v1`。

### 根路径

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/ | ConvertTo-Json
```

响应：

```json
{
  "name": "科研知识库与实验助理 Agent",
  "version": "0.1.0",
  "description": "面向论文与实验记录的知识库与实验助理后端（第三阶段：文本分块与本地向量检索）。"
}
```

### 健康检查

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/health | ConvertTo-Json
```

响应：

```json
{
  "status": "ok",
  "service": "research-agent",
  "version": "0.1.0"
}
```

### 上传 PDF

PowerShell 7+：

```powershell
$form = @{
    file = Get-Item .\example.pdf
}
Invoke-RestMethod `
    -Uri http://127.0.0.1:8000/api/v1/documents `
    -Method Post `
    -Form $form
```

如果使用 Windows PowerShell 5.1（不支持 `-Form`），可以使用：

```powershell
curl.exe -X POST `
    -F "file=@.\example.pdf;type=application/pdf" `
    http://127.0.0.1:8000/api/v1/documents
```

成功返回 `201 Created` 和完整文档详情：

```json
{
  "id": "a9d1a1da-3c22-4bf0-8ef5-6dc8e7e0a111",
  "original_filename": "example.pdf",
  "stored_filename": "a9d1a1da-3c22-4bf0-8ef5-6dc8e7e0a111.pdf",
  "file_size": 12345,
  "page_count": 2,
  "created_at": "2026-11-03T10:00:00+00:00",
  "status": "processed",
  "index_status": "not_indexed",
  "pages": [
    {
      "page_number": 1,
      "text": "...",
      "character_count": 1234
    },
    {
      "page_number": 2,
      "text": "",
      "character_count": 0
    }
  ]
}
```

请求使用 `multipart/form-data`，字段名必须是 `file`。

### 为文档建立或重建索引

先获取文档 ID：

```powershell
$documents = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/documents?page=1&page_size=20"
$documentId = $documents.items[0].id
```

为文档建立索引：

```powershell
Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/documents/$documentId/index" `
    -Method Post
```

成功响应：

```json
{
  "document_id": "a9d1a1da-3c22-4bf0-8ef5-6dc8e7e0a111",
  "status": "indexed",
  "page_count": 2,
  "chunk_count": 7,
  "embedding_dimension": 512
}
```

- 重复调用会重建该文档索引，不会产生重复 chunk。
- 文档不存在返回 `404`。
- 本地模型缺失或加载失败返回 `503`：

```json
{
  "detail": "本地 Embedding 模型不可用，请检查 EMBEDDING_MODEL_PATH 配置和模型文件。"
}
```

### 检索相关文本块

```powershell
$body = @{
    query = "实验中为什么需要空白对照？"
    top_k = 5
} | ConvertTo-Json

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/retrieval/search" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body
```

可选地按文档过滤：

```powershell
$body = @{
    query = "实验中为什么需要空白对照？"
    top_k = 5
    document_ids = @($documentId)
} | ConvertTo-Json

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/retrieval/search" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body
```

响应示例：

```json
{
  "query": "实验中为什么需要空白对照？",
  "results": [
    {
      "chunk_id": "a9d1a1da-3c22-4bf0-8ef5-6dc8e7e0a111:p2:c0",
      "document_id": "a9d1a1da-3c22-4bf0-8ef5-6dc8e7e0a111",
      "original_filename": "experiment.pdf",
      "page_number": 2,
      "chunk_index": 0,
      "text": "原文片段……",
      "char_start": 0,
      "char_end": 300,
      "score": 0.82
    }
  ]
}
```

检索只返回原文片段和引用信息，**不生成回答**。没有索引或没有匹配结果时返回
`200` 和空 `results`。`MAX_RETRIEVAL_TEXT_LENGTH` 只截断返回文本的前缀，
不改变页码、chunk ID 和分数。

### 查询文档列表

```powershell
Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/documents?page=1&page_size=20" `
    | ConvertTo-Json -Depth 10
```

响应：

```json
{
  "items": [
    {
      "id": "a9d1a1da-3c22-4bf0-8ef5-6dc8e7e0a111",
      "original_filename": "example.pdf",
      "stored_filename": "a9d1a1da-3c22-4bf0-8ef5-6dc8e7e0a111.pdf",
      "file_size": 12345,
      "page_count": 2,
      "created_at": "2026-11-03T10:00:00+00:00",
      "status": "processed",
      "index_status": "indexed"
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1
}
```

- `page` 默认 `1`
- `page_size` 默认 `20`，最大 `100`

### 查询文档详情

```powershell
$documents = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/documents?page=1&page_size=20"
$documentId = $documents.items[0].id

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/documents/$documentId" `
    | ConvertTo-Json -Depth 10
```

不存在时返回 `404`：

```json
{
  "detail": "文档不存在"
}
```

### 删除文档

```powershell
$response = Invoke-WebRequest `
    -Uri "http://127.0.0.1:8000/api/v1/documents/$documentId" `
    -Method Delete `
    -UseBasicParsing
$response.StatusCode
```

成功返回 `204 No Content`，同时删除：

```text
data/documents/{document_id}.pdf
data/metadata/{document_id}.json
data/chunks/{document_id}.json
FAISS 中该文档的全部向量
manifest 中该文档的全部记录
```

删除路径由 UUID 派生并校验为配置目录内的文件，不使用用户提供的原始文件名。
即使文档尚未索引，也会正常删除 PDF 和元数据。

## 文件校验与错误码

只接受 PDF：

- 文件名不能为空
- 扩展名必须为 `.pdf`（不区分大小写）
- `Content-Type` 如果存在，不能明确表示非 PDF；允许 `application/pdf`、
  `application/x-pdf` 和 `application/octet-stream`
- 文件大小不能超过 `MAX_UPLOAD_SIZE_MB`，默认 20 MB
- 文件内容必须能被 PyMuPDF 正常打开
- 原始文件名中的路径部分会被移除，保存文件名始终为 `{uuid}.pdf`
- 损坏、伪造、加密或无法解析的 PDF 返回 400，不留下成功元数据

| 状态码 | 场景 |
| --- | --- |
| `400` | 文件名为空、非 PDF、Content-Type 非 PDF、PDF 损坏或无法解析 |
| `413` | 文件超过大小限制 |
| `404` | 文档不存在或文档 ID 非法 |
| `422` | multipart 请求缺少文件字段、分页参数非法、query 为空等 |
| `500` | 本地文件、元数据或 FAISS 索引读写失败，不返回服务器绝对路径 |
| `503` | 本地 Embedding 模型缺失、加载失败或推理失败 |

错误响应统一使用：

```json
{
  "detail": "错误说明"
}
```

## 测试说明

第二阶段测试覆盖：

1. 有效 PDF 上传返回 201
2. 上传后可查询详情
3. 页码从 1 开始
4. 页面文本和字符数被保存
5. 列表返回正确 `total`
6. 不存在的文档返回 404
7. 删除返回 204
8. 删除后查询返回 404
9. TXT 文件返回 400
10. 伪造 PDF 返回 400
11. 超过大小限制返回 413
12. 路径字符不能造成路径穿越
13. 空白 PDF 页面不导致崩溃
14. 删除文档不影响其他文档
15. 元数据 JSON 使用 UTF-8 且中文不转义
16. 列表分页正确
17. Content-Type 明确为非 PDF 时返回 400
18. 空文件名返回 400

第一阶段 3 个健康检查/根路径测试继续保留。

第三阶段新增 23 个测试，测试覆盖：

- 页码级分块、字符范围、overlap、空白页和稳定 chunk ID
- 有效 PDF 上传后建立索引、chunk 文件和 manifest
- 检索字段、分数排序、`document_ids` 过滤和 `top_k`
- 空索引、未索引文档、重复索引去重
- 删除文档后的 chunk/FAISS/manifest 同步
- 删除一个文档不影响其他文档
- 新应用实例从磁盘恢复索引
- 模型不可用时 index/search 返回 503
- 空 query 拒绝
- FakeEmbedding 替代真实模型，但真实执行 FAISS 写入、重载、重建和检索

完整运行：

```powershell
python -m pytest -vv -s
```

当前环境没有下载真实模型，因此**真实模型推理未验证**；模型缺失时的 503
路径有自动化测试覆盖。

## Docker 启动

需要已安装并启动 Docker Desktop，然后在项目根目录执行：

```powershell
docker compose up --build
```

后台运行：

```powershell
docker compose up --build -d
```

检查状态并访问接口：

```powershell
docker compose ps
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/health | ConvertTo-Json
```

查看日志或停止：

```powershell
docker compose logs -f research-agent
docker compose down
```

容器内使用 Uvicorn 监听 `0.0.0.0:8000`，宿主机映射到 `8000`。
`docker-compose.yml` 使用命名卷 `research_data` 挂载 `/app/data`，
PDF、元数据、chunk 和 FAISS 索引在容器重建后仍可保留；同时以只读方式
挂载 `./models:/app/models`，容器不会下载模型。服务不依赖外部数据库或外部 API。

如果当前环境无法执行 Docker，可先验证 Compose 配置语法：

```powershell
docker compose config
```

**没有实际构建和运行容器时，不应声称 Docker 验证通过。**

## 安全与健壮性

- 不信任上传文件名，不使用其拼接保存路径。
- 保存文件名使用 UUID，扩展名固定为 `.pdf`。
- 文档 ID 经过 UUID 校验，文件路径解析后必须位于配置目录内。
- 上传按块写入，超过大小限制立即终止并清理临时文件。
- 解析失败时删除已保存的 PDF，且不会写入成功元数据。
- 元数据通过临时文件替换，UTF-8 编码，`ensure_ascii=False`。
- API 错误不返回服务器绝对路径。
- 日志不记录上传文件内容。
- Embedding 模型只能从本地目录加载，并强制离线模式，不自动下载。
- FAISS 索引和 manifest 通过临时文件原子替换；索引操作使用进程内锁。
- 删除文档会重建索引并移除对应向量，再删除 chunk 文件。
- 单机 JSON + FAISS 仅面向课程项目的小规模知识库，不适合多实例并发写入。

## 已知限制

- 扫描型 PDF 没有文字层时 chunk 为空，当前不支持 OCR。
- 真实 Embedding 模型未随仓库提供；当前环境没有下载模型，真实模型推理未验证。
- 无模型或模型加载失败时 index/search 返回 503；上传和文档管理仍可用。
- 本地 JSON + FAISS 是单机小规模方案，不适合多进程并发写入或大规模语料。
- 当前只返回检索片段，不生成大模型回答，也没有问题改写、流式输出或 Agent 工作流。
- Docker 镜像未在本环境实际构建，因 Docker Desktop 引擎未启动；仅验证了 Compose 语法。

## 第二阶段验收标准

- [x] 第一阶段 3 个测试仍然通过
- [x] 第二阶段 18 个测试全部通过
- [x] 有效 PDF 可以上传
- [x] PDF 每页文本和页码被保存
- [x] 文档详情可以查询
- [x] 文档可以删除
- [x] 非 PDF 和损坏 PDF 会被拒绝
- [x] 使用临时目录测试，不污染真实 `data`
- [x] 不使用外部 API
- [x] README 与实际代码一致

## 第三阶段验收标准

- [x] 前两个阶段测试仍然全部通过（21 个）
- [x] 第三阶段新增 23 个测试全部通过
- [x] 页码级分块，chunk 不跨页，空白页不产生 chunk
- [x] 字符范围、overlap、chunk ID 和 chunk_count 正确
- [x] 本地 FakeEmbedding + 真实 FAISS 索引、重载、重建和检索测试通过
- [x] 索引结果可回溯文档名、文档 ID、页码、chunk 序号和原文
- [x] 删除文档同步删除 chunk、FAISS 向量和 manifest
- [x] 没有本地模型时业务接口正常，index/search 返回 503
- [x] 不依赖外网或在线 API，不自动下载模型
- [x] README 与代码、配置和 Docker 挂载一致

## 第四阶段计划

1. 检索质量增强
   - chunk 参数实验与召回评估
   - 混合检索、重排或过滤策略
   - 检索测试集和引用准确率指标
2. 文档管理增强
   - 索引状态失败记录与可重试任务
   - 文档标签、摘要和批量索引
3. Agent 能力
   - 在需求明确后再引入大模型回答、LangGraph 或 Agent 工作流
   - 回答必须基于检索结果并附带页码引用
   - 密钥仅从环境变量读取
4. 工程化
   - 增加 Ruff、mypy、覆盖率和 CI
   - Docker 镜像构建、模型挂载和容器接口回归验证

当前仍未实现 OCR、大模型回答、问题改写、流式输出、LangChain、LangGraph
或 Agent 工作流。
