# Bridge Server Docker 快速启动指南

**版本**: v1.5.3  
**最后更新**: 2026-04-05

---

## 📦 目录结构

解压 `bridge-server-v1.5.3.tar.gz` 后的目录结构：

```
bridge-server-product/              ← 解压后的根目录
├── docker/
│   ├── Dockerfile                  ← Docker 构建文件
│   ├── docker-compose.yml          ← 单机部署配置
│   ├── nginx/
│   └── monitoring/
├── docker-compose.lb.yml           ← 负载均衡部署配置
├── install.sh                      ← 安装脚本
├── requirements.txt                ← Python 依赖
├── app/                            ← 应用代码
└── ...
```

---

## 🚀 Docker 安装方式

### 方式 1: 单机部署（推荐）

**配置文件**: `docker/docker-compose.yml`

```bash
# 1. 解压安装包
tar -xzf bridge-server-v1.5.3.tar.gz
cd bridge-server-product

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入 API Keys

# 3. 构建并启动
docker-compose -f docker/docker-compose.yml up -d

# 4. 查看状态
docker-compose ps

# 5. 查看日志
docker-compose logs -f

# 6. 测试连接
curl http://localhost:19377/health
```

**访问地址**:
- API: `http://localhost:19377`
- 健康检查：`http://localhost:19377/health`

---

### 方式 2: 负载均衡部署（多实例）

**配置文件**: `docker-compose.lb.yml`

```bash
# 1. 解压安装包
tar -xzf bridge-server-v1.5.3.tar.gz
cd bridge-server-product

# 2. 配置环境变量
cp .env.example .env

# 3. 构建并启动（3 个实例）
docker-compose -f docker-compose.lb.yml up -d --scale bridge-server=3

# 4. 查看状态
docker-compose ps

# 5. 查看日志
docker-compose logs -f

# 6. 测试连接（通过 Nginx 负载均衡器）
curl http://localhost:80/health
```

**访问地址**:
- API（通过 Nginx）: `http://localhost:80`
- HTTPS（如果启用 SSL）: `https://localhost:443`

---

## 🔧 Dockerfile 配置说明

### 位置

```
bridge-server-product/docker/Dockerfile
```

### 构建参数

```dockerfile
# 基础镜像
FROM python:3.11-slim

# 虚拟环境
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 非 root 用户
RUN groupadd --gid 1000 bridge && \
    useradd --uid 1000 --gid bridge --shell /bin/bash --create-home bridge
USER bridge

# 端口
EXPOSE 8080

# 启动命令
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "19377"]
```

---

## 📋 docker-compose.yml 配置说明

### 单机部署配置 (docker/docker-compose.yml)

```yaml
version: '3.8'

services:
  bridge-server:
    build:
      context: ..              # 构建上下文：父目录（bridge-server-product）
      dockerfile: docker/Dockerfile  # Dockerfile 路径
    image: bridge-server:1.5.3
    ports:
      - "19377:19377"
    volumes:
      - ./config:/home/bridge/.bridge-server:rw
      - ./logs:/home/bridge/.local/var/log/bridge-server
    environment:
      - DASHSCOPE_API_KEY=${DASHSCOPE_API_KEY:-}
      - OPENAI_API_KEY=${OPENAI_API_KEY:-}
```

### 负载均衡配置 (docker-compose.lb.yml)

```yaml
version: '3.8'

services:
  nginx-lb:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
  
  bridge-server:
    image: bridge-server:1.5.3
    build:
      context: .              # 构建上下文：当前目录（bridge-server-product）
      dockerfile: docker/Dockerfile  # Dockerfile 路径
    expose:
      - "19377"
```

---

## 🐛 常见问题

### 问题 1: Dockerfile 未找到

**症状**:
```
ERROR: Cannot locate specified Dockerfile: Dockerfile
```

**原因**: docker-compose 配置的 Dockerfile 路径不正确。

**解决**:
```bash
# ✅ 确认 Dockerfile 存在
ls -l docker/Dockerfile

# ✅ 使用正确的路径
docker-compose -f docker/docker-compose.yml up -d
# 或
docker-compose -f docker-compose.lb.yml up -d
```

---

### 问题 2: 构建上下文错误

**症状**:
```
ERROR: build path /path/to/somewhere does not exist
```

**原因**: docker-compose 的 `context` 配置指向了错误的目录。

**解决**:
```yaml
# ✅ docker/docker-compose.yml
build:
  context: ..              # 指向 bridge-server-product
  dockerfile: docker/Dockerfile

# ✅ docker-compose.lb.yml
build:
  context: .               # 指向 bridge-server-product
  dockerfile: docker/Dockerfile
```

---

### 问题 3: 端口冲突

**症状**:
```
Error starting userland proxy: listen tcp 0.0.0.0:19377: bind: address already in use
```

**解决**:
```bash
# 方法 1: 修改端口映射
docker-compose -f docker/docker-compose.yml up -d --build
# 编辑 docker/docker-compose.yml，修改端口：
# ports:
#   - "8080:19377"  # 使用其他端口

# 方法 2: 停止占用端口的服务
lsof -i :19377
kill <PID>
```

---

### 问题 4: 权限错误

**症状**:
```
PermissionError: [Errno 13] Permission denied: '/home/bridge/.bridge-server'
```

**解决**:
```bash
# 确保挂载的目录有正确权限
mkdir -p config logs data
chmod -R 755 config logs data

# 重新启动
docker-compose down
docker-compose up -d
```

---

## 🔍 调试技巧

### 查看构建日志

```bash
# 详细构建日志
docker-compose -f docker/docker-compose.yml build --progress=plain

# 查看构建缓存
docker builder prune
```

### 进入容器调试

```bash
# 进入运行中的容器
docker exec -it bridge-server /bin/bash

# 检查环境
python3 --version
pip list
env | grep BRIDGE
```

### 查看容器日志

```bash
# 实时日志
docker-compose logs -f

# 最近 100 条日志
docker-compose logs --tail=100

# 特定服务日志
docker-compose logs bridge-server
```

---

## 📊 Docker 部署对比

| 配置 | 适用场景 | 实例数 | 负载均衡 | 端口 |
|------|---------|--------|---------|------|
| **docker/docker-compose.yml** | 开发/测试/小规模 | 1 | ❌ | 19377 |
| **docker-compose.lb.yml** | 生产环境/高并发 | 2+ | ✅ Nginx | 80/443 |

---

## 🎯 最佳实践

### 1. 使用 .env 文件管理密钥

```bash
# 创建 .env 文件
cp .env.example .env

# 编辑 .env
DASHSCOPE_API_KEY=sk-xxx
OPENAI_API_KEY=sk-xxx
```

### 2. 数据持久化

```yaml
volumes:
  - ./config:/home/bridge/.bridge-server
  - ./logs:/home/bridge/.local/var/log/bridge-server
  - bridge_data:/home/bridge/data
```

### 3. 健康检查

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:19377/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
```

### 4. 资源限制

```yaml
deploy:
  resources:
    limits:
      cpus: '2.0'
      memory: 2G
    reservations:
      cpus: '0.5'
      memory: 512M
```

---

## 📚 相关文档

- [Dockerfile](docker/Dockerfile) - Docker 构建配置
- [docker-compose.yml](docker/docker-compose.yml) - 单机部署
- [docker-compose.lb.yml](docker-compose.lb.yml) - 负载均衡部署
- [跨平台部署指南](CROSS-PLATFORM-GUIDE.md) - 包含 Docker 部署

---

*最后更新：2026-04-05*
