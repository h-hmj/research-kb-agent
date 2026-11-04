FROM python:3.11-slim

# 避免生成 .pyc，并让容器日志实时输出。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

# 先安装依赖，利用 Docker 层缓存。
COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY src ./src

# 使用非 root 用户运行；数据目录保存 PDF 和 JSON 元数据。
RUN groupadd --system --gid 10001 appuser \
    && useradd --system --uid 10001 --gid appuser --create-home appuser \
    && mkdir -p /app/data/documents /app/data/metadata \
       /app/data/chunks /app/data/vector_store /app/models \
    && chown -R appuser:appuser /app/data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)"]

CMD ["uvicorn", "src.research_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
