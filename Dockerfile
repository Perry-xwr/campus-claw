# 与 pyproject.toml 的 requires-python（>=3.11,<3.12）保持同一版本：
# 本地验收、门禁、容器跑同一个解释器，否则「本地绿、容器崩」无从归因。
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# pip 源做成构建参数，不写死在命令里。
# 2026-11-12 实测：本机容器内直连 pypi.org 为 TCP 超时（同为容器的百度 / 阿里云 / 清华镜像均通），
# 默认源下 `docker compose up --build` 必然失败在 pip 一步，故默认走清华镜像。
# 换到能直连官方源的网络时，改回默认值或显式覆盖：
#   docker build --build-arg PIP_INDEX_URL=https://pypi.org/simple .
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

COPY requirements.txt ./
# --timeout / --retries：容器内网络抖动时不至于 370 秒后整体失败，给重试留时间。
RUN pip install --no-cache-dir --timeout 60 --retries 3 \
        --index-url "${PIP_INDEX_URL}" \
        -r requirements.txt

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
