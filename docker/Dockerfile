# 多阶段构建 - 生产优化
FROM python:3.11-slim as builder

WORKDIR /app

# 安装构建依赖（仅用于编译）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 创建虚拟环境并安装依赖
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 升级 pip 并安装依赖（优先使用 wheel）
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --only-binary :all: -r requirements.txt || \
    pip install --no-cache-dir -r requirements.txt

# ============ 运行阶段 ============
FROM python:3.11-slim

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BRIDGE_VERSION=1.5.3

# 从 builder 阶段复制虚拟环境
COPY --from=builder /opt/venv /opt/venv

# 创建非 root 用户
RUN groupadd --gid 1000 bridge && \
    useradd --uid 1000 --gid bridge --shell /bin/bash --create-home bridge

WORKDIR /app

# 复制应用代码
COPY --chown=bridge:bridge app/ ./app/
COPY --chown=bridge:bridge services/ ./services/
COPY --chown=bridge:bridge requirements.txt .

# 创建日志和配置目录（使用用户目录）
RUN mkdir -p /home/bridge/.local/var/log/bridge-server /home/bridge/.bridge-server && \
    chown -R bridge:bridge /home/bridge/.local/var/log/bridge-server /home/bridge/.bridge-server

# 切换到非 root 用户
USER bridge

# 使用虚拟环境 PATH
ENV PATH="/opt/venv/bin:$PATH"

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/health', timeout=5)" || exit 1

# 暴露端口
EXPOSE 8080

# 启动命令（端口可通过环境变量配置）
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "19377", "--workers", "1"]
