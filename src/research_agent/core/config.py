"""应用配置：从环境变量或 .env 文件读取设置。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 对外服务标识，保持稳定，不随环境变量变化。
SERVICE_NAME = "research-agent"

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """应用设置。

    每个字段均可通过同名的大写环境变量覆盖，例如 ``APP_NAME``、
    ``LOG_LEVEL``。项目根目录下的 ``.env`` 为可选文件；没有该文件时，
    所有字段使用下面的默认值，应用仍可正常启动。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "科研知识库与实验助理 Agent"
    app_version: str = "0.1.0"
    debug: bool = False
    api_prefix: str = "/api/v1"
    log_level: LogLevel = "INFO"
    data_dir: Path = Field(
        default=Path("./data"),
        description="本地数据根目录。",
    )
    max_upload_size_mb: int = Field(
        default=20,
        ge=1,
        le=1024,
        description="单个上传文件的最大大小，单位为 MB。",
    )
    documents_dir: Path = Field(
        default=Path("./data/documents"),
        description="上传 PDF 文件的本地保存目录。",
    )
    metadata_dir: Path = Field(
        default=Path("./data/metadata"),
        description="文档 JSON 元数据的本地保存目录。",
    )
    chunks_dir: Path = Field(
        default=Path("./data/chunks"),
        description="文档分块 JSON 的本地保存目录。",
    )
    vector_store_dir: Path = Field(
        default=Path("./data/vector_store"),
        description="FAISS 索引和 manifest 的本地保存目录。",
    )
    embedding_model_path: Path = Field(
        default=Path("./models/bge-small-zh-v1.5"),
        description="本地 sentence-transformers 模型目录。",
    )
    embedding_device: str = Field(
        default="cpu",
        description="Embedding 推理设备，默认 cpu。",
    )
    embedding_normalize: bool = Field(
        default=True,
        description="是否对 Embedding 结果做 L2 归一化。",
    )
    chunk_size: int = Field(
        default=500,
        ge=1,
        description="单个 chunk 的最大字符数。",
    )
    chunk_overlap: int = Field(
        default=80,
        ge=0,
        description="相邻 chunk 的重叠字符数。",
    )
    retrieval_top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="默认返回的检索结果数量。",
    )
    max_retrieval_text_length: int = Field(
        default=1000,
        ge=1,
        description="检索响应中原文片段的最大字符数。",
    )
    qa_top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="问答默认检索数量。",
    )
    min_retrieval_score: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        description="进入问答证据集的最低相似度。",
    )
    min_evidence_count: int = Field(
        default=1,
        ge=1,
        description="允许调用 LLM 的最少证据数量。",
    )
    max_context_chars: int = Field(
        default=6000,
        ge=1,
        description="送入 LLM 的证据文本总字符上限。",
    )
    max_citation_text_length: int = Field(
        default=500,
        ge=1,
        description="引用原文片段的最大字符数。",
    )
    llm_base_url: str = Field(
        default="http://127.0.0.1:11434/v1",
        description="本地 OpenAI-compatible LLM 服务地址。",
    )
    llm_model: str = Field(
        default="qwen2.5:3b-instruct",
        description="本地 LLM 模型名。",
    )
    llm_api_key: str = Field(
        default="",
        description="本地 LLM 可选 API Key，默认空。",
    )
    llm_timeout_seconds: float = Field(
        default=60.0,
        ge=1.0,
        description="调用本地 LLM 的超时时间。",
    )
    llm_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="LLM 温度。",
    )
    llm_max_tokens: int = Field(
        default=512,
        ge=1,
        description="LLM 最大输出 token 数。",
    )
    enable_query_rewrite: bool = Field(
        default=True,
        description="是否允许初次检索失败后改写问题。",
    )
    max_query_rewrite_attempts: int = Field(
        default=1,
        ge=0,
        le=1,
        description="最大问题改写次数，只允许 0 或 1。",
    )
    rewrite_max_chars: int = Field(
        default=500,
        ge=1,
        description="改写查询的最大字符数。",
    )
    agent_top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Agent 默认检索数量。",
    )
    agent_max_context_chars: int = Field(
        default=6000,
        ge=1,
        description="Agent 送入回答模型的证据文本总上限。",
    )
    agent_trace_enabled: bool = Field(
        default=True,
        description="是否返回安全的工作流摘要。",
    )

    @model_validator(mode="after")
    def validate_chunking(self) -> "Settings":
        """重叠长度必须小于分块长度，否则无法稳定前进。"""
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP 必须小于 CHUNK_SIZE")
        return self

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        """允许在环境变量中使用小写日志级别。"""
        return value.strip().upper()

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        """保证 API 前缀以斜杠开头，并移除末尾多余的斜杠。"""
        prefix = value.strip()
        if not prefix.startswith("/"):
            raise ValueError("API_PREFIX 必须以 '/' 开头")
        return prefix.rstrip("/") or "/"


@lru_cache
def get_settings() -> Settings:
    """返回进程级缓存的配置实例。"""
    return Settings()
