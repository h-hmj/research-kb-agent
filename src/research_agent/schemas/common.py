"""通用 API 响应模型。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """健康检查响应。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = Field(description="当前服务状态")
    service: str = Field(description="服务标识")
    version: str = Field(description="应用版本")


class RootResponse(BaseModel):
    """项目根路径响应。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="项目名称")
    version: str = Field(description="应用版本")
    description: str = Field(description="项目说明")
