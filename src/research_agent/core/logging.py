"""基于 Python 标准库的日志配置。"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .request_context import current_request_id

LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | "
    "request_id=%(request_id)s | %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
FILE_HANDLER_MARKER = "_research_agent_file_handler"


class RequestIDFilter(logging.Filter):
    """给每条日志补充当前请求 ID，不存在时使用 '-'。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id()
        return True


def _formatter() -> logging.Formatter:
    return logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)


def _remove_file_handlers(root_logger: logging.Logger) -> None:
    for handler in list(root_logger.handlers):
        if getattr(handler, FILE_HANDLER_MARKER, False):
            root_logger.removeHandler(handler)
            handler.close()


def configure_logging(
    log_level: str,
    *,
    enable_file_logging: bool = False,
    log_dir: Path = Path("./data/logs"),
    log_max_bytes: int = 5242880,
    log_backup_count: int = 3,
) -> None:
    """初始化根日志器；文件日志默认关闭，启用时写入 LOG_DIR。"""
    level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    formatter = _formatter()
    request_filter = RequestIDFilter()

    if not root_logger.handlers:
        logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=DATE_FORMAT)

    for handler in root_logger.handlers:
        handler.setFormatter(formatter)
        if not any(isinstance(item, RequestIDFilter) for item in handler.filters):
            handler.addFilter(request_filter)

    _remove_file_handlers(root_logger)
    if enable_file_logging:
        log_dir = Path(log_dir).expanduser()
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "app.log",
            maxBytes=log_max_bytes,
            backupCount=log_backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(request_filter)
        setattr(file_handler, FILE_HANDLER_MARKER, True)
        root_logger.addHandler(file_handler)

    root_logger.setLevel(level)
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(logger_name).setLevel(level)
