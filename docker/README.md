# Bridge Server Docker 部署指南

**版本**: v1.3.0  
**更新日期**: 2026-04-04

---

## 🎯 Docker 部署优势

| 特性 | 说明 |
|------|------|
| **隔离性** | 应用与系统环境完全隔离 |
| **可移植性** | 一次构建，到处运行 |
| **资源限制** | CPU/内存使用可控 |
| **快速部署** | 一键启动，无需复杂配置 |
| **易于回滚** | 镜像版本管理，随时回退 |

---

## 📦 快速开始

### 1. 检查环境

```bash
# 检查 Docker
docker --version
docker-compose --version  # 或 docker compose version

# 如果没有 docker-compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose
```

### 2. 初始化配置

```bash
cd /opt/bridge-server/docker

# 运行初始化
./deploy.sh setup
```

**输出**:
```
╔═══════════════════════════════════════════╗
║  Bridge Server Docker 部署工具            ║
║  Version 1.3.0                            ║
╚═══════════════════════════════════════════╝

ℹ 检查依赖...
✓ 依赖检查通过
ℹ 创建目录结构...
✓ 目录创建完成
ℹ 配置设置...
✓ 配置文件已创建
⚠ 请编辑配置文件设置 API Keys 和认证 Tokens
```

### 3. 编辑配置

```bash
# 编辑环境变量
nano config/.env

# 必须设置:
DASHSCOPE_API_KEY=sk-xxx
AUTH_TOKEN_1=your-secret-token
```

```bash
# 编辑配置文件（可选）
nano config/config.yaml
```

### 4. 构建镜像

```bash
# 首次构建
./deploy.sh build

# 或使用缓存加速
./deploy.sh build --no-cache
```

**构建时间**: ~3-5 分钟（首次）

### 5. 启动服务

```bash
./deploy.sh start
```

**验证**:
```bash
# 查看状态
./deploy.sh status

# 查看日志
./deploy.sh logs

# 测试 API
curl http://localhost:19377/health
```

---

## 🔧 常用命令

### 服务管理

```bash
# 启动
./deploy.sh start

# 停止
./deploy.sh stop

# 重启
./deploy.sh restart

# 查看状态
./deploy.sh status

# 查看日志
./deploy.sh logs          # 最近 100 行
./deploy.sh logs -f       # 实时跟踪
./deploy.sh logs 200      # 最近 200 行
```

### 镜像管理

```bash
# 构建镜像
./deploy.sh build

# 查看镜像
docker images bridge-server

# 删除镜像
docker rmi bridge-server:1.3.0
```

### 配置管理

```bash
# 备份配置
./deploy.sh backup

# 查看配置位置
ls -la ~/bridge-server-docker/config/
```

### 清理

```bash
# 清理所有（谨慎使用）
./deploy.sh cleanup
```

---

## 📁 目录结构

```
bridge-server-product/docker/
├── Dockerfile                 # 镜像构建文件
├── docker-compose.yml         # 容器编排配置
├── deploy.sh                  # 部署脚本
├── .dockerignore             # 构建排除文件
├── monitoring/
│   └── prometheus.yml        # Prometheus 配置（可选）
└── [运行时创建]
    ├── config/               # 配置文件
    │   ├── config.yaml
    │   └── .env
    ├── logs/                 # 日志文件
    └── data/                 # 数据文件
```

---

## ⚙️ 配置说明

### 环境变量 (.env)

```bash
# API Keys
DASHSCOPE_API_KEY=sk-xxx
MOONSHOT_API_KEY=sk-xxx
OPENAI_API_KEY=sk-xxx

# 服务器配置
BRIDGE_PORT=19377
BRIDGE_DEBUG=false
LOG_LEVEL=INFO

# 速率限制
RATE_LIMIT_PER_MINUTE=100
```

### 配置文件 (config.yaml)

```yaml
server:
  host: 0.0.0.0  # Docker 中必须监听所有接口
  port: 19377
  auth_tokens:
    - "your-secret-token"

providers:
  dashscope:
    enabled: true
    api_key_env: DASHSCOPE_API_KEY
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1

rate_limiting:
  enabled: true
  default:
    per_minute: 100
```

---

## 🔒 安全配置

### 1. 非 Root 用户

Dockerfile 中已创建 `bridge` 用户（UID 1000），容器以非 root 用户运行。

### 2. 资源限制

```yaml
# docker-compose.yml
deploy:
  resources:
    limits:
      cpus: '2.0'
      memory: 1G
```

### 3. 只读文件系统（可选）

```yaml
security_opt:
  - no-new-privileges:true
read_only: true
tmpfs:
  - /tmp:size=100M
```

### 4. 网络隔离

```yaml
networks:
  - bridge-network

networks:
  bridge-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16  # 私有网络
```

---

## 📊 监控配置（可选）

### 启用 Prometheus + Grafana

1. 编辑 `docker-compose.yml`，取消注释：

```yaml
# 取消以下服务的注释
prometheus:
  image: prom/prometheus:latest
  # ...

grafana:
  image: grafana/grafana:latest
  # ...
```

2. 启动服务：

```bash
./deploy.sh start
```

3. 访问：
   - Prometheus: http://localhost:9090
   - Grafana: http://localhost:3000 (admin/admin)

---

## 🐛 故障排查

### 容器无法启动

```bash
# 查看详细日志
docker logs bridge-server

# 检查配置
docker exec bridge-server cat /opt/bridge-server/config/config.yaml

# 检查环境变量
docker exec bridge-server env | grep DASHSCOPE
```

### 端口冲突

```bash
# 查看端口占用
lsof -i :19377

# 修改端口
# 编辑 docker-compose.yml
ports:
  - "8081:19377"  # 改为 8081
```

### 内存不足

```bash
# 查看资源使用
docker stats bridge-server

# 调整限制
# 编辑 docker-compose.yml
deploy:
  resources:
    limits:
      memory: 2G  # 增加限制
```

### 网络问题

```bash
# 测试容器网络
docker exec bridge-server ping -c 3 dashscope.aliyuncs.com

# 重启网络
docker network prune
./deploy.sh restart
```

---

## 🚀 生产部署

### 1. 使用 Docker Swarm

```bash
# 初始化 Swarm
docker swarm init

# 部署服务
docker stack deploy -c docker-compose.yml bridge

# 查看服务
docker service ls

# 扩展实例
docker service scale bridge_bridge-server=3
```

### 2. 使用 Kubernetes

创建 `k8s-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: bridge-server
spec:
  replicas: 3
  selector:
    matchLabels:
      app: bridge-server
  template:
    metadata:
      labels:
        app: bridge-server
    spec:
      containers:
      - name: bridge-server
        image: bridge-server:1.3.0
        ports:
        - containerPort: 8080
        env:
        - name: DASHSCOPE_API_KEY
          valueFrom:
            secretKeyRef:
              name: bridge-secrets
              key: dashscope-api-key
        resources:
          limits:
            memory: "1Gi"
            cpu: "2.0"
---
apiVersion: v1
kind: Service
metadata:
  name: bridge-server
spec:
  selector:
    app: bridge-server
  ports:
  - port: 80
    targetPort: 8080
  type: LoadBalancer
```

部署：

```bash
kubectl apply -f k8s-deployment.yaml
```

### 3. 使用 systemd 管理 Docker

创建 `/etc/systemd/system/bridge-server-docker.service`:

```ini
[Unit]
Description=Bridge Server Docker Container
Requires=docker.service
After=docker.service

[Service]
Restart=always
WorkingDirectory=/opt/bridge-server/docker
ExecStart=/usr/bin/docker-compose up
ExecStop=/usr/bin/docker-compose down

[Install]
WantedBy=multi-user.target
```

---

## 📝 升级指南

### 从 v1.2.x 升级

```bash
# 1. 备份配置
./deploy.sh backup

# 2. 停止旧版本
./deploy.sh stop

# 3. 拉取新代码
cd /opt/bridge-server
git pull

# 4. 构建新镜像
cd docker
./deploy.sh build

# 5. 启动新版本
./deploy.sh start

# 6. 验证
curl http://localhost:19377/health
```

---

## 🎯 性能优化

### 1. 多实例部署

```yaml
# docker-compose.yml
services:
  bridge-server:
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
```

### 2. 使用 Redis 缓存

```yaml
# 取消 Redis 服务注释
redis:
  image: redis:7-alpine
  volumes:
    - redis-data:/data
```

### 3. 调整日志级别

```yaml
# config.yaml
logging:
  level: WARNING  # 减少日志输出
```

---

## 📞 支持

**文档**: [README.md](../README.md)  
**Issues**: https://github.com/your-org/bridge-server/issues  
**Docker Hub**: https://hub.docker.com/r/your-org/bridge-server

---

*最后更新：2026-04-04*  
*Docker 镜像：bridge-server:1.3.0*
