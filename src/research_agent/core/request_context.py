"""请求 ID 的上下文与安全字符串校验。"""

from __future__ import annotations

import re
from contextvars import ContextVar, Token
from uuid import uuid4

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def safe_request_id(value: str | None) -> str:
    """接受短且字符集安全的客户端 request ID，否则生成 UUID4。"""
    if value and _REQUEST_ID_RE.fullmatch(value.strip()):
        return value.strip()
    return str(uuid4())


def set_request_id(request_id: str) -> Token:
    return _request_id_var.set(request_id)


def reset_request_id(token: Token) -> None:
    _request_id_var.reset(token)


def current_request_id() -> str:
    return _request_id_var.get()
