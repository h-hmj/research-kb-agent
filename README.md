# 科研知识库与实验助理 Agent

一个面向论文与实验记录的知识库 Agent 后端。项目采用 FastAPI、Pydantic Settings、
本地文件存储、FAISS 和本地 LLM，按可扩展的分层结构搭建。

当前已完成：

- **第一阶段**：项目骨架、配置、日志、健康检查、测试和 Docker 配置。
- **第二阶段**：PDF 上传、类型与大小校验、本地保存、PyMuPDF 逐页解析、
  页码保留、JSON 元数据管理、文档列表/详情/删除 API。
- **第三阶段**：页码级分块、本地 Embedding 抽象、FAISS 向量索引、
  索引持久化、检索接口、引用回溯与删除同步。
- **第四阶段**：证据过滤、本地 OpenAI-compatible LLM 单轮问答、
  服务端页码级引用、无证据拒答和模型不可用 503。

当前不调用任何在线 API，不使用数据库或云端向量库。向量化和 LLM 均只使用
本机服务或本地模型目录；代码不会自动下载模型，LLM 也不会在启动时被探测。

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

### 第四阶段（受控问答与引用）

- [x] 复用第三阶段 FAISS 检索，不绕过向量检索直接读全文
- [x] 按 `MIN_RETRIEVAL_SCORE` 过滤证据，按 `MIN_EVIDENCE_COUNT` 判断是否回答
- [x] 证据不足直接返回 `refused`，完全不调用 LLM
- [x] 证据足够才调用本地 OpenAI-compatible `/chat/completions`
- [x] System Prompt 只允许依据证据回答，禁止外部知识和虚构引用
- [x] 服务端从实际送入 LLM 的 evidence 生成引用，不解析模型输出引用
- [x] 引用包含文档名、文档 ID、页码、chunk 序号、原文前缀和分数
- [x] LLM 输出固定拒答句时统一转为 `refused` 且清空 citations
- [x] 模型缺失/LLM 服务不可用时优雅返回 503
- [x] 使用 FakeLLMService 测试；检索、筛选、拒答、引用流程真实执行
- [x] 不记录完整问题、证据正文或模型回答到 INFO 日志

**尚未实现**：OCR、LangChain、LangGraph、问题改写、二次检索、多 Agent、
流式输出、Chat 历史/多轮记忆、Web 前端或在线模型 API。扫描型 PDF 可以上传，
但没有文字层时提取结果为空，当前不会自动 OCR。

## 第三、四阶段数据流

```text
上传 PDF
  → PyMuPDF 按页提取文本
  → POST /documents/{id}/index
  → 单页内分块 → 本地 Embedding → FAISS IndexFlatIP
  → POST /retrieval/search
  → POST /qa/ask
  → 按分数过滤证据 → 证据不足则拒答
  → 证据足够则调用本地 LLM
  → 服务端根据实际证据附加 citations
```

上传成功后不会自动索引；用户必须显式调用索引接口。索引、检索和问答均不调用
在线 API，也不会自动下载模型。没有证据的问答不会调用 LLM。

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
│       │   ├── exceptions.py             # Embedding / LLM 内部异常
│       │   └── logging.py                # 标准日志初始化
│       ├── api/
│       │   ├── __init__.py
│       │   └── routes/
│       │       ├── __init__.py
│       │       ├── health.py             # 健康检查
│       │       ├── documents.py          # 上传/列表/详情/删除/索引
│       │       ├── retrieval.py          # 自然语言检索
│       │       └── qa.py                 # 单轮问答
│       ├── schemas/
│       │   ├── __init__.py
│       │   ├── common.py                 # 通用响应
│       │   ├── documents.py              # 文档与 index_status
│       │   ├── retrieval.py              # chunk、索引和检索模型
│       │   └── qa.py                     # 问答、证据和引用模型
│       ├── services/
│       │   ├── __init__.py
│       │   ├── README.md
│       │   ├── document_service.py       # 文档生命周期协调
│       │   ├── metadata_service.py       # 元数据领域服务
│       │   ├── pdf_service.py            # PyMuPDF 逐页解析
│       │   ├── chunking_service.py       # 页码级纯函数分块
│       │   ├── embedding_service.py      # 本地 Embedding 抽象与实现
│       │   ├── indexing_service.py       # 索引重建与删除同步
│       │   ├── retrieval_service.py      # 检索结果组装
│       │   ├── llm_service.py            # 本地 OpenAI-compatible LLM
│       │   ├── citation_service.py       # 服务端引用生成
│       │   └── qa_service.py             # 证据判断、拒答与问答编排
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
│   ├── test_retrieval.py                 # 第三阶段分块/索引/检索测试
│   └── test_qa.py                        # 第四阶段问答/引用/拒答测试
├── scripts/
│   └── download_embedding_model.py       # 有网环境模型下载（规避 hf_xet 坑）
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
python scripts/download_embedding_model.py
```

脚本等价于手工执行 `snapshot_download('BAAI/bge-small-zh-v1.5',
local_dir='models/bge-small-zh-v1.5')`，并额外做了两件事：

- 在导入下载库之前关闭 hf_xet 后端。Windows 上该后端拉取权重会报
  `xet_get ... os error 5 拒绝访问`，换镜像源无效，走普通 HTTP 才能成功。
- 把 HF 缓存目录固定为项目内 `.hf-cache`，不写入用户主目录的系统缓存。

可选参数：`--repo` 换模型仓库，`--endpoint https://hf-mirror.com` 走镜像，
`--local-dir` 换保存目录。默认跳过 `*.bin`/`*.onnx` 等重复权重格式（同份权重
约 91 MB，`sentence-transformers` 只需要 `model.safetensors`），需要时可加
`--with-other-weights`。

上述下载脚本只应在有网环境执行；本项目运行代码不会调用它。

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

### 5. 本地 LLM 准备

第四阶段使用本地 **OpenAI-compatible HTTP 接口**，不引入 OpenAI SDK。
默认配置兼容 Ollama：

```text
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=qwen2.5:3b-instruct
LLM_API_KEY=
```

Ollama 仅作为示例。需要在有网环境由用户自行启动服务并准备模型：

```powershell
ollama serve
ollama pull qwen2.5:3b-instruct
```

项目代码**不会自动下载模型**，也不会在启动时主动请求 LLM 服务。
只有用户发起有足够证据的问答时，才请求 `POST {LLM_BASE_URL}/chat/completions`。

- `LLM_BASE_URL` 应指向本机、Docker 内部服务或 `host.docker.internal` 的本地服务。
- `LLM_API_KEY` 为空时不发送 Authorization；非空时发送 Bearer Header。
- 连接失败、超时、非 2xx、响应 JSON 缺 content 时统一返回 503。
- LLM 不可用时，有证据的问答返回 503；无证据问题仍正常 `refused`，不调用 LLM。
- Docker 容器内不能直接使用宿主机的 `127.0.0.1`，Compose 示例使用
  `host.docker.internal`，可按实际本地服务地址覆盖。
- 离线学校环境不得把 `LLM_BASE_URL` 指向在线大模型 API。

### 6. 可选：创建本地配置

不创建 `.env` 也可以启动，因为 `Settings` 提供了完整默认值。需要自定义时：

```powershell
Copy-Item .env.example .env
```

`.env` 已被 `.gitignore` 忽略，禁止提交任何密钥。`LLM_API_KEY` 默认为空，
只有本地服务确实需要鉴权时才设置。

### 7. 启动服务

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

### 8. 运行测试

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
第四阶段额外注入 FakeLLMService；FAISS 检索、证据过滤、拒答和引用逻辑真实执行。

预期结果（具体以实际执行为准）：

```text
60 passed
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
| `QA_TOP_K` | `5` | 问答默认检索数量，最大 20 |
| `MIN_RETRIEVAL_SCORE` | `0.35` | 进入证据集的最低相似度 |
| `MIN_EVIDENCE_COUNT` | `1` | 调用 LLM 的最少证据数量 |
| `MAX_CONTEXT_CHARS` | `6000` | 送入 LLM 的证据文本总上限 |
| `MAX_CITATION_TEXT_LENGTH` | `500` | 引用原文最大长度 |
| `LLM_BASE_URL` | `http://127.0.0.1:11434/v1` | 本地 OpenAI-compatible 服务 |
| `LLM_MODEL` | `qwen2.5:3b-instruct` | 本地模型名 |
| `LLM_API_KEY` | 空 | 仅本地服务需要时设置 |
| `LLM_TIMEOUT_SECONDS` | `60` | 调用超时 |
| `LLM_TEMPERATURE` | `0.0` | 生成温度 |
| `LLM_MAX_TOKENS` | `512` | 最大输出 token |

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
$env:QA_TOP_K = "5"
$env:MIN_RETRIEVAL_SCORE = "0.35"
$env:LLM_BASE_URL = "http://127.0.0.1:11434/v1"
$env:LLM_MODEL = "qwen2.5:3b-instruct"
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
  "description": "面向论文与实验记录的知识库与实验助理后端（第四阶段：本地 LLM 问答与可追溯引用）。"
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

### 单轮问答

```powershell
$body = @{
    question = "实验中为什么要设置空白对照？"
    top_k = 5
} | ConvertTo-Json -Depth 4

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/qa/ask" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body
```

有足够证据时返回：

```json
{
  "status": "answered",
  "answer": "根据资料，设置空白对照可用于……",
  "citations": [
    {
      "citation_id": "citation-1",
      "chunk_id": "uuid:p2:c0",
      "document_id": "uuid",
      "original_filename": "experiment.pdf",
      "page_number": 2,
      "chunk_index": 0,
      "text": "原文片段……",
      "char_start": 0,
      "char_end": 300,
      "score": 0.83
    }
  ],
  "retrieval": {
    "query": "实验中为什么要设置空白对照？",
    "retrieved_count": 3,
    "evidence_count": 2,
    "top_k": 5
  },
  "refusal_reason": null
}
```

没有足够证据时，接口仍返回 200，但不调用 LLM：

```json
{
  "status": "refused",
  "answer": "无法根据已检索到的资料回答该问题。",
  "citations": [],
  "retrieval": {
    "query": "不存在的问题",
    "retrieved_count": 0,
    "evidence_count": 0,
    "top_k": 5
  },
  "refusal_reason": "未检索到足够相关的文档证据。"
}
```

引用完全由服务端根据实际送入 LLM 的证据块生成，不解析模型回答中的引用。
模型如果输出固定拒答句，也会被统一转换为 `refused` 且 citations 为空。

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
| `422` | multipart 缺文件、分页参数非法、query 为空、question/top_k 非法 |
| `500` | 本地文件、元数据或 FAISS 索引读写失败，不返回服务器绝对路径 |
| `503` | 本地 Embedding 模型或本地 LLM 服务不可用 |

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

第四阶段新增 16 个测试，测试覆盖：

- 有证据回答、LLM 只调用一次、引用字段和来源正确
- 引用去重并按分数降序
- 无索引、低分、证据数不足时拒答且不调用 LLM
- LLM 输出固定拒答句时归一化为 refused
- Embedding 不可用、LLM 不可用分别返回 503
- 无证据且 LLM 不可用时仍返回 200 refused
- 空问题、纯空白、超长问题、非法 top_k/document_ids 返回 422
- document_ids 严格过滤，未索引文档不参与问答
- 上下文长度限制、引用文本前缀限制
- Prompt 只包含实际筛选出的 evidence
- FakeLLM 替代真实模型，但检索、筛选、拒答和引用流程真实执行

完整运行：

```powershell
python -m pytest -vv -s
```

真实 Embedding 与 LLM 不随仓库提交，自动化测试使用 FakeEmbedding/FakeLLM；
真实模型/服务需要按上面的步骤在本地准备，因此不纳入 pytest 测试依赖。
模型/LLM 不可用 503 路径和完整问答编排已由自动化测试覆盖。

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
挂载 `./models:/app/models`，容器不会下载模型。服务不依赖外部数据库或在线 API。

第四阶段通过环境变量覆盖 `QA_TOP_K`、`MIN_RETRIEVAL_SCORE`、`LLM_BASE_URL`、
`LLM_MODEL` 等配置。Compose 默认把 `LLM_BASE_URL` 设为
`http://host.docker.internal:11434/v1`，便于容器访问宿主机 Ollama；
如使用 Docker 内部服务名，可自行覆盖。`LLM_API_KEY` 默认为空。

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
- 问答只允许使用经过分数过滤且实际送入 LLM 的证据，不允许绕过向量检索读全文。
- 引用由 `CitationService` 从 evidence 生成，不解析模型输出中的引用。
- LLM 调用只在证据足够时发生；启动时不探测 LLM 服务。
- INFO 日志只记录 request id、检索/证据数量、状态和耗时，不记录问题或证据正文。
- 单机 JSON + FAISS 仅面向课程项目的小规模知识库，不适合多实例并发写入。

## 已知限制

- 扫描型 PDF 没有文字层时 chunk 为空，当前不支持 OCR。
- 真实 Embedding 模型不随仓库提交，需要按准备步骤在本地下载。
- 真实 LLM 回答依赖本机 Ollama 服务和 `LLM_MODEL` 配置，不纳入自动化测试。
- 无 Embedding 模型时索引/检索/问答返回 503；上传和文档管理仍可用。
- LLM 不可用时，有证据问答返回 503；无证据问题仍返回 200 refused，不调用 LLM。
- 本地 JSON + FAISS 是单机小规模方案，不适合多进程并发写入或大规模语料。
- 没有问题改写、二次检索、流式输出、多轮记忆、LangGraph 或 Agent 工作流。
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

## 第四阶段验收标准

- [x] 前三个阶段 44 个测试仍然全部通过
- [x] 第四阶段新增 16 个测试全部通过，总计 60 passed
- [x] 有足够证据时返回 answered，回答带服务端页码级引用
- [x] 引用来自实际送入 LLM 的 evidence，不解析模型虚构引用
- [x] 无索引、低分或证据不足时返回 200 refused，且不调用 LLM
- [x] LLM 输出固定拒答句时归一化为 refused，citations 为空
- [x] Embedding 不可用、证据足够但 LLM 不可用时返回 503
- [x] 无证据且 LLM 不可用时仍正常 refused
- [x] 空问题、超长问题、非法 top_k/document_ids 返回 422
- [x] document_ids 过滤和未索引文档隔离生效
- [x] Prompt 只包含筛选后的 evidence，上下文和引用文本有长度上限
- [x] 不自动下载模型，不调用在线 API，未引入 LangGraph

## 第五阶段计划

1. 检索与问答质量
   - chunk 参数、相似度阈值和 top_k 的评测
   - 检索召回率、引用准确率和拒答准确率测试集
   - 真实本地 Embedding 与 LLM 的端到端验证
2. 问答能力增强
   - 在明确需求后再考虑多轮对话、问题改写或二次检索
   - 更严格的证据冲突处理和回答格式约束
3. 工程化
   - 增加 Ruff、mypy、覆盖率和 CI
   - Docker 镜像构建、模型挂载和容器接口回归验证
   - 本地 LLM 健康状态的安全摘要接口（可选）

当前仍未实现 OCR、LangGraph、问题改写、二次检索、多 Agent、流式输出、
Chat 历史/多轮记忆或 Web 前端。
