"""项目内部的可预期服务异常。"""


class ProjectError(Exception):
    """项目异常基类。"""


class EmbeddingModelUnavailableError(ProjectError):
    """本地 Embedding 模型缺失、加载失败或推理失败。"""


class LLMUnavailableError(ProjectError):
    """本地 OpenAI-compatible LLM 服务不可用或响应无效。"""
