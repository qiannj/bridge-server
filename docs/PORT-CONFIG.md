# Bridge Server 端口配置指南

**默认端口**: **19377**  
**最后更新**: 2026-04-04

---

## 🎯 端口说明

### 为什么选择 19377？

| 端口 | 说明 |
|------|------|
| ~~8080~~ | 太常见，容易冲突 |
| ~~8000~~ | Python 开发常用 |
| **19377** | ✅ 不易冲突，好记 |

**记忆方法**: `19` (世纪) + `377` (黄金分割数 0.618 的近似值 × 1000)

---

## ⚙️ 配置方式

### 方式 1: Docker 部署（推荐）

#### 使用默认端口（19377）

```bash
# 无需额外配置，默认就是 19377
./deploy.sh start

# 访问
curl http://localhost:19377/health
```

#### 自定义端口

```bash
# 1. 编辑 .env 文件
nano docker/.env

# 2. 修改端口
BRIDGE_PORT=20000

# 3. 重启服务
./deploy.sh restart

# 4. 验证
curl http://localhost:20000/health
```

---

### 方式 2: docker-compose.yml 直接修改

```yaml
# docker/docker-compose.yml
services:
  bridge-server:
    ports:
      - "19377:19377"  # 宿主机端口：容器端口
```

**修改后**:
```bash
docker-compose up -d
```

---

### 方式 3: systemd 部署

```bash
# 1. 编辑服务文件
sudo nano /etc/systemd/system/bridge-server.service

# 2. 修改 ExecStart
ExecStart=/usr/bin/python3 -m uvicorn bridge_server.runtime:app --app-dir src \
  --host 0.0.0.0 \
  --port 19377 \
  --workers 1

# 3. 重载并重启
sudo systemctl daemon-reload
sudo systemctl restart bridge-server

# 4. 验证
curl http://localhost:19377/health
```

---

### 方式 4: 源码部署

```bash
# 方式 A: 命令行参数
python -m uvicorn bridge_server.runtime:app --app-dir src --host 0.0.0.0 --port 19377

# 方式 B: 配置文件
# 编辑 ~/.bridge-server/config.yaml
server:
  port: 19377

# 方式 C: 环境变量
export PORT=19377
python -m uvicorn bridge_server.runtime:app --app-dir src
```

---

## 🔍 端口检查

### 检查端口占用

```bash
# Linux
lsof -i :19377
netstat -tlnp | grep 19377
ss -tlnp | grep 19377

# macOS
lsof -i :19377

# Windows
netstat -ano | findstr 19377
```

### 测试端口连通性

```bash
# curl 测试
curl http://localhost:19377/health

# telnet 测试
telnet localhost 19377

# nc 测试
nc -zv localhost 19377
```

---

## 🔒 防火墙配置

### Linux (UFW)

```bash
# 开放端口
sudo ufw allow 19377/tcp

# 验证
sudo ufw status

# 重启防火墙
sudo ufw reload
```

### Linux (firewalld)

```bash
# 开放端口
sudo firewall-cmd --add-port=19377/tcp --permanent

# 重载
sudo firewall-cmd --reload

# 验证
sudo firewall-cmd --list-ports
```

### macOS

```bash
# 系统偏好设置 → 安全性与隐私 → 防火墙
# 添加 Bridge Server 或允许特定端口
```

### Windows

```powershell
# PowerShell 管理员权限
New-NetFirewallRule -DisplayName "Bridge Server" \
  -Direction Inbound -LocalPort 19377 \
  -Protocol TCP -Action Allow
```

---

## 🌐 外部访问配置

### 局域网访问

```bash
# 1. 修改配置（监听所有接口）
# config.yaml
server:
  host: 0.0.0.0  # 不是 127.0.0.1

# 2. 获取本机 IP
ip addr show | grep "inet "  # Linux
ifconfig | grep "inet "      # macOS

# 3. 从其他机器访问
curl http://192.168.1.100:19377/health
```

### 公网访问（需要路由器配置）

```bash
# 1. 路由器端口转发
# 登录路由器 → 端口转发/虚拟服务器
# 外部端口：19377
# 内部 IP：192.168.1.100
# 内部端口：19377

# 2. 获取公网 IP
curl ifconfig.me

# 3. 从外网访问
curl http://你的公网IP:19377/health
```

**⚠️ 安全警告**: 公网暴露需配置强认证和 HTTPS！

---

## 🔐 安全建议

### 1. 生产环境配置

```yaml
# config.yaml
server:
  host: 127.0.0.1  # 仅本地访问
  port: 19377
  auth_tokens:
    - "strong-random-token-here"
  
  # 如果必须外部访问，配置 CORS
  cors_origins:
    - "https://your-domain.com"
```

### 2. 使用反向代理（推荐）

**Nginx 配置**:

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:19377;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**优势**:
- ✅ HTTPS 加密
- ✅ 隐藏真实端口
- ✅ 负载均衡
- ✅ 限流保护

### 3. Docker 网络隔离

```yaml
# docker-compose.yml
services:
  bridge-server:
    ports:
      - "127.0.0.1:19377:19377"  # 仅本地访问
```

---

## 🐛 故障排查

### 问题 1: 端口被占用

```bash
# 查找占用进程
lsof -i :19377

# 杀死进程（谨慎）
kill -9 <PID>

# 或修改 Bridge Server 端口
BRIDGE_PORT=19378
```

### 问题 2: 无法访问

```bash
# 1. 检查服务状态
docker ps | grep bridge-server
systemctl status bridge-server

# 2. 检查端口监听
netstat -tlnp | grep 19377

# 3. 检查防火墙
sudo ufw status
sudo firewall-cmd --list-ports

# 4. 查看日志
docker logs bridge-server
journalctl -u bridge-server -f
```

### 问题 3: Docker 端口映射失败

```bash
# 检查 docker-compose.yml
cat docker/docker-compose.yml | grep ports

# 重启容器
docker-compose down
docker-compose up -d

# 验证映射
docker port bridge-server
```

---

## 📊 常用端口参考

| 端口 | 服务 | 建议 |
|------|------|------|
| **19377** | Bridge Server | ✅ 推荐 |
| 8080 | HTTP 代理 | ⚠️ 易冲突 |
| 8000 | Python 开发 | ⚠️ 易冲突 |
| 3000 | Grafana | - |
| 9090 | Prometheus | - |
| 5432 | PostgreSQL | - |
| 6379 | Redis | - |

---

## 🎯 快速参考

### 默认配置

```bash
# Docker
BRIDGE_PORT=19377

# 访问
curl http://localhost:19377/health
```

### 修改端口（3 步）

```bash
# 1. 编辑 .env
nano docker/.env

# 2. 修改
BRIDGE_PORT=20000

# 3. 重启
./deploy.sh restart
```

### 验证命令

```bash
# 检查端口
lsof -i :19377

# 测试 API
curl http://localhost:19377/health

# 查看日志
docker logs bridge-server
```

---

## 📞 支持

**文档**: [README.md](../README.md)  
**Issues**: https://github.com/your-org/bridge-server/issues

---

*最后更新：2026-04-04*  
*默认端口：19377*
