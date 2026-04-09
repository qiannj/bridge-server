# Bridge Server 安装指南

本文档提供 Bridge Server 的完整安装和部署指南。

---

## 📋 系统要求

| 组件 | 最低要求 | 推荐配置 |
|------|---------|---------|
| **Python** | 3.8+ | 3.11+ |
| **内存** | 512MB | 1GB+ |
| **磁盘** | 100MB | 500MB+ |
| **操作系统** | Linux/macOS/Windows | Linux/macOS |

---

## 🚀 安装方式

### 方式 A: Docker Compose（推荐）

**优点：**
- ✅ 环境隔离
- ✅ 一键部署
- ✅ 易于升级
- ✅ 跨平台一致

**步骤：**

```bash
# 1. 克隆仓库
git clone https://github.com/qiannj/bridge-server.git
cd bridge-server

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 API Key

# 3. 启动服务
docker compose up -d

# 4. 验证
curl http://localhost:19377/health
```

**输出：**
```json
{"status": "healthy", "timestamp": 1234567890, "version": "2.1.0"}
```

---

### 方式 B: Linux/macOS 直接运行

**步骤：**

```bash
# 1. 一键安装脚本
curl -fsSL https://raw.githubusercontent.com/qiannj/bridge-server/main/install.sh | bash

# 2. 运行配置向导
python3 cli/setup-wizard.py

# 3. 启动服务
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 19377

# 4. 验证
curl http://localhost:19377/health
```

**手动安装（可选）：**

```bash
# 1. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/macOS

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置
mkdir -p ~/.bridge-server
cp config.yaml.example ~/.bridge-server/config.yaml
# 编辑配置文件

# 4. 启动
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 19377
```

---

### 方式 C: Windows PowerShell

**步骤：**

```powershell
# 1. 下载安装脚本
Invoke-WebRequest -Uri https://raw.githubusercontent.com/qiannj/bridge-server/main/install.ps1 -OutFile install.ps1

# 2. 运行安装脚本
.\install.ps1

# 3. 配置
python3 cli/setup-wizard.py

# 4. 启动
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 19377
```

---

## 🔧 配置

### 运行配置向导

```bash
python3 cli/setup-wizard.py
```

**配置步骤：**
1. 配置 Provider 和 API Key
2. 配置场景化模型（选择已配置的模型）
3. 配置路由策略
4. 生成安全 Token

### 手动配置

编辑 `~/.bridge-server/config.yaml`：

```yaml
# 服务器配置
server:
  host: 127.0.0.1
  port: 19377
  
# 认证 Tokens
auth:
  api_keys:
    - sk-your-token-here

# Provider 配置
providers:
  dashscope:
    enabled: true
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key_env: DASHSCOPE_API_KEY
    models:
      qwen3.5-flash:
        cost: 0.002
        use_case: 简单任务

# 路由策略
routing:
  strategy: balanced
  model_mapping:
    simple: qwen3.5-flash
    coding: qwen3-coder-plus
    general: qwen3.5-plus
```

---

## 🎯 启动方式

### Docker Compose

```bash
# 启动
docker compose up -d

# 查看状态
docker compose ps

# 查看日志
docker compose logs -f

# 停止
docker compose down
```

### Systemd（Linux）

```bash
# 安装服务
sudo cp systemd/bridge-server.service /etc/systemd/system/

# 启动
sudo systemctl start bridge-server

# 开机自启
sudo systemctl enable bridge-server

# 查看状态
sudo systemctl status bridge-server
```

### 直接运行

```bash
# 前台运行
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 19377

# 后台运行（nohup）
nohup python3 -m uvicorn app.main:app --host 127.0.0.1 --port 19377 &

# 或使用 screen/tmux
screen -S bridge-server
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 19377
# Ctrl+A, D 分离
```

---

## ✅ 验证安装

### 健康检查

```bash
curl http://localhost:19377/health
```

**预期输出：**
```json
{"status": "healthy", "timestamp": 1234567890, "version": "2.1.0"}
```

### 测试请求

```bash
curl -X POST http://localhost:19377/v1/chat/completions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "smart",
    "messages": [{"role": "user", "content": "101+3 是多少"}]
  }'
```

### 查看用量

```bash
curl http://localhost:19377/api/usage?period=today
```

---

## 🐛 故障排查

### 问题 1: 端口冲突

**错误：** `Address already in use`

**解决：**
```bash
# 查看占用端口的进程
lsof -i :19377

# 或修改配置文件中的端口
vi ~/.bridge-server/config.yaml
# 修改 server.port
```

### 问题 2: 依赖安装失败

**错误：** `gcc failed` 或 `libffi.h: No such file`

**解决（Ubuntu/Debian）：**
```bash
sudo apt-get update
sudo apt-get install -y python3-dev libffi-dev build-essential
```

**解决（macOS）：**
```bash
xcode-select --install
brew install libffi
```

### 问题 3: API Key 无效

**错误：** `401 Unauthorized`

**解决：**
1. 检查 config.yaml 中的 `auth.api_keys`
2. 确认请求中的 Token 匹配
3. 重启服务

### 问题 4: Docker 权限问题

**错误：** `permission denied`

**解决：**
```bash
# 添加用户到 docker 组
sudo usermod -aG docker $USER

# 重新登录或重启
```

---

## 📊 安装后检查清单

- [ ] 服务正常运行（`curl /health`）
- [ ] 配置向导完成
- [ ] 至少配置一个 Provider
- [ ] 测试请求成功
- [ ] 日志文件可写
- [ ] （可选）配置 systemd 服务
- [ ] （可选）配置日志轮转

---

## 🔗 相关文档

- [使用指南](USAGE.md) - 如何使用 Bridge Server
- [更新日志](CHANGELOG.md) - 版本变更历史
- [待办清单](TODO.md) - 计划实现的功能

---

**安装完成后，请阅读 [使用指南](USAGE.md) 开始使用！**
