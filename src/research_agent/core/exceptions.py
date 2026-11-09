"""项目内部的可预期服务异常。"""


class ProjectError(Exception):
    """项目异常基类。"""


class EmbeddingModelUnavailableError(ProjectError):
    """本地 Embedding 模型缺失、加载失败或推理失败。"""


class LLMUnavailableError(ProjectError):
    """本地 OpenAI-compatible LLM 服务不可用或响应无效。"""


class QueryRewriteError(ProjectError):
    """问题改写服务不可用，或模型输出未通过安全校验。"""


class ToolValidationError(ProjectError):
    """工具名或工具参数不合法。"""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class ToolOutputInvalidError(ProjectError):
    """LLM 工具输出不是合法、符合 Schema 的 JSON。"""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class EvaluationDatasetError(ProjectError):
    """评测数据集格式、标签或安全路径不合法。"""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class EvaluationLimitError(ProjectError):
    """评测样例数超过配置上限。"""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class EvaluationRunFailedError(ProjectError):
    """评测错误率超过阈值。"""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class EvaluationNotFoundError(ProjectError):
    """评测报告不存在。"""


class EvaluationReportError(ProjectError):
    """评测报告写入或读取失败。"""
