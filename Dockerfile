# 与 pyproject.toml 的 requires-python（>=3.11,<3.12）保持同一版本：
# 本地验收、门禁、容器跑同一个解释器，否则「本地绿、容器崩」无从归因。
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY campusclaw/ ./campusclaw/
COPY app.py ./
COPY scripts/ ./scripts/
COPY mcp-server/ ./mcp-server/

# 数据与上传目录由 Compose 挂载为宿主机持久化目录。
RUN mkdir -p /app/data /app/uploads

# 同一镜像承载三种角色：app（8080）、index worker（无端口）、mcp 工具服务（8090）。
# 两个端口都声明，否则 `docker compose` 的端口映射与镜像声明对不上。
EXPOSE 8080 8090

# 单 worker：课程演示环境，不宣称高并发能力。
CMD ["gunicorn", "--workers", "1", "--bind", "0.0.0.0:8080", "app:app"]
