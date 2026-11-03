"""应用配置：从环境变量或 .env 文件读取设置。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
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
