"""基于 Python 标准库的日志配置。"""

import logging

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(log_level: str) -> None:
    """按配置初始化根日志器，并同步 Uvicorn 的日志级别。"""
    level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()

    if not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format=LOG_FORMAT,
            datefmt=DATE_FORMAT,
        )

    # 测试环境或 Uvicorn 可能已提前配置日志，这里仍确保级别生效。
    root_logger.setLevel(level)
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(logger_name).setLevel(level)
