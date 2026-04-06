# 🚀 Bridge Server v1.0.0 Windows 安装指南

**适用系统**: Windows 10/11  
**安装时间**: 约 5 分钟  
**难度**: ⭐⭐☆☆☆ (简单)

---

## 📋 前置要求

### 系统要求

- ✅ Windows 10 版本 1903+ 或 Windows 11
- ✅ Python 3.8 - 3.12
- ✅ 管理员权限（首次安装需要）
- ✅ 至少 500MB 可用磁盘空间
- ✅ 网络连接（下载依赖）

### 检查 Python

打开 **PowerShell** 或 **命令提示符**：

```powershell
python --version
```

**如果显示版本号**（如 `Python 3.11.5`）✅ 继续下一步

**如果提示"不是内部或外部命令"** ❌ 先安装 Python

---

## 📥 步骤 1: 安装 Python（如未安装）

### 方式 1: 从官网下载（推荐）

1. 访问：https://www.python.org/downloads/
2. 下载 **Python 3.11.x**（推荐 3.11）
3. **重要**: 安装时勾选 ✅ **Add Python to PATH**
4. 点击 **Install Now**
5. 安装完成后重启终端

### 方式 2: 使用 winget（Windows 10/11）

```powershell
winget install Python.Python.3.11
```

### 验证安装

```powershell
python --version
# 应显示：Python 3.11.x

pip --version
# 应显示：pip 23.x.x
```

---

## 📦 步骤 2: 下载 Bridge Server

### 方式 1: 下载预构建包（推荐）

1. 访问 GitHub Releases: https://github.com/your-org/bridge-server/releases
2. 下载 `bridge-server-v1.0.0.tar.gz`
3. 解压到 `C:\Users\你的用户名\bridge-server`

### 方式 2: 使用 Git

```powershell
# 安装 Git（如未安装）
winget install Git.Git

# 克隆仓库
git clone https://github.com/your-org/bridge-server.git C:\Users\你的用户名\bridge-server
cd C:\Users\你的用户名\bridge-server
```

### 方式 3: 直接下载 ZIP

1. 访问：https://github.com/your-org/bridge-server/archive/refs/tags/v1.0.0.zip
2. 下载并解压到 `C:\Users\你的用户名\bridge-server`

---

## 🔧 步骤 3: 创建虚拟环境

打开 **PowerShell**（建议以管理员身份运行首次）：

```powershell
# 进入安装目录
cd C:\Users\你的用户名\bridge-server

# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
.\venv\Scripts\Activate.ps1
```

**成功后，命令行前会出现 `(venv)` 前缀**

> 💡 **如果提示"无法加载脚本"**：
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

---

## 📥 步骤 4: 安装依赖

```powershell
# 确保虚拟环境已激活（看到 (venv) 前缀）
# 升级 pip
python -m pip install --upgrade pip

# 安装依赖
pip install -r requirements.txt
```

**安装过程约 2-3 分钟**，会安装：
- FastAPI
- Uvicorn
- Pydantic
- PyJWT
- 等其他依赖

**看到 "Successfully installed ..."** ✅ 安装成功

---

## ⚙️ 步骤 5: 配置 Bridge Server

### 创建配置目录

```powershell
# 在用户目录创建配置文件夹
New-Item -ItemType Directory -Path "$env:USERPROFILE\.bridge-server" -Force
```

### 生成随机密钥

```powershell
# 生成 JWT 密钥
$jwt_secret = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 64 | ForEach-Object {[char]$_})
echo "JWT Secret: $jwt_secret"

# 生成 API Key
$api_key = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object {[char]$_})
echo "API Key: $api_key"
```

**复制输出的 JWT Secret 和 API Key，后面要用！**

### 创建配置文件

```powershell
# 复制配置模板
Copy-Item "config.yaml.example" "$env:USERPROFILE\.bridge-server\config.yaml"

# 复制环境变量模板
Copy-Item ".env.example" "$env:USERPROFILE\.bridge-server\.env"
```

### 编辑配置文件

用 **记事本** 或 **VS Code** 打开：

```powershell
notepad "$env:USERPROFILE\.bridge-server\config.yaml"
```

**修改以下内容**：

```yaml
server:
  host: 127.0.0.1
  port: 19377
  debug: false  # 🔒 生产环境设为 false
  
auth:
  # 🔒 粘贴刚才生成的 JWT Secret
  jwt_secret: "粘贴你的 JWT Secret"
  
  api_keys:
    - "粘贴你的 API Key"

rate_limit:
  enabled: true
  requests_per_minute: 30
  requests_per_hour: 500
  requests_per_second: 10

logging:
  level: WARNING  # 🔒 生产环境使用 WARNING
  audit_enabled: true
```

**保存并关闭** ✅

### 编辑 .env 文件

```powershell
notepad "$env:USERPROFILE\.bridge-server\.env"
```

**填入你的 API Keys**（从各平台获取）：

```bash
# 阿里云百炼（推荐）
DASHSCOPE_API_KEY=sk-your-dashscope-key-here

# Moonshot (Kimi)
MOONSHOT_API_KEY=sk-your-moonshot-key-here

# OpenAI（可选）
OPENAI_API_KEY=sk-your-openai-key-here

# 认证 Token（用于访问 Bridge Server）
AUTH_TOKEN_1=你的随机 TOKEN
```

**保存并关闭** ✅

---

## 🚀 步骤 6: 启动 Bridge Server

### 方式 1: 直接启动（推荐测试用）

```powershell
# 确保在 bridge-server 目录
cd C:\Users\你的用户名\bridge-server

# 激活虚拟环境
.\venv\Scripts\Activate.ps1

# 启动服务
python -m uvicorn app.main:app --host 127.0.0.1 --port 19377 --reload
```

**看到以下输出表示成功**：
```
INFO:     Uvicorn running on http://127.0.0.1:19377
INFO:     Application startup complete.
```

### 方式 2: 使用 CLI 工具

```powershell
# 安装 CLI 工具
pip install -e .

# 启动服务
bridge-server start
```

### 方式 3: 创建批处理脚本（方便下次启动）

创建 `start-bridge.bat`：

```batch
@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 127.0.0.1 --port 19377
pause
```

**双击 `start-bridge.bat` 即可启动** ✅

---

## ✅ 步骤 7: 验证安装

### 测试 1: 健康检查

打开 **新的 PowerShell 窗口**：

```powershell
curl http://localhost:19377/health
```

**预期输出**：
```json
{"status":"healthy","timestamp":1234567890.123,"version":"1.0.0"}
```

### 测试 2: API 文档

浏览器访问：http://localhost:19377/docs

**应该看到 Swagger UI 界面** ✅

### 测试 3: 测试聊天接口

```powershell
curl -X POST http://localhost:19377/v1/chat/completions `
  -H "Authorization: Bearer 你的 AUTH_TOKEN_1" `
  -H "Content-Type: application/json" `
  -d "{\"messages\": [{\"role\": \"user\", \"content\": \"你好\"}]}"
```

**预期输出**：
```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "你好！有什么我可以帮助你的吗？"
    }
  }]
}
```

### 测试 4: 查看用量

```powershell
curl http://localhost:19377/api/v1/usage/summary `
  -H "Authorization: Bearer 你的 AUTH_TOKEN_1"
```

**预期输出**：
```json
{
  "period": "today",
  "total_requests": 0,
  "total_cost": 0.0
}
```

---

## 🔧 常见问题排查

### 问题 1: 端口被占用

**错误**: `Address already in use`

**解决**:
```powershell
# 查找占用端口的进程
netstat -ano | findstr :19377

# 杀死进程（替换 PID）
taskkill /PID 12345 /F

# 或修改端口
# 编辑 config.yaml，将 port: 19377 改为 port: 19378
```

### 问题 2: 虚拟环境激活失败

**错误**: `无法加载文件，因为在此系统上禁止运行脚本`

**解决**:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 问题 3: Python 未找到

**错误**: `'python' 不是内部或外部命令`

**解决**:
1. 重新安装 Python
2. 安装时勾选 ✅ **Add Python to PATH**
3. 重启终端

### 问题 4: 依赖安装失败

**错误**: `Could not find a version that satisfies the requirement`

**解决**:
```powershell
# 升级 pip
python -m pip install --upgrade pip

# 使用清华镜像源
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 问题 5: API Key 验证失败

**错误**: `401 Unauthorized`

**解决**:
1. 检查 `.env` 文件中的 API Key 是否正确
2. 检查 `config.yaml` 中的 `auth_tokens` 是否配置
3. 确保请求时使用了正确的 Token：`Authorization: Bearer 你的 TOKEN`

---

## 🛠️ 高级配置

### 配置开机自启动

1. 按 `Win + R`，输入 `shell:startup`
2. 创建快捷方式指向 `start-bridge.bat`
3. 下次开机自动启动

### 配置防火墙

```powershell
# 允许端口（如需远程访问）
netsh advfirewall firewall add rule name="Bridge Server" dir=in action=allow protocol=TCP localport=19377
```

### 配置日志

编辑 `config.yaml`：

```yaml
logging:
  level: INFO  # DEBUG | INFO | WARNING | ERROR
  file: C:\Users\你的用户名\.bridge-server\bridge-server.log
  audit_enabled: true
  audit_file: C:\Users\你的用户名\.bridge-server\audit.log
```

---

## 📊 性能优化

### 使用 MySQL（高并发场景）

1. 安装 MySQL: https://dev.mysql.com/downloads/installer/
2. 创建数据库：
```sql
CREATE DATABASE bridge_server;
```
3. 编辑 `config.yaml`：
```yaml
database:
  url: mysql+mysqlconnector://root:password@localhost:3306/bridge_server
```

### 使用 Redis（缓存加速）

1. 下载 Redis for Windows: https://github.com/microsoftarchive/redis/releases
2. 启动 Redis:
```powershell
redis-server.exe
```
3. 编辑 `config.yaml`：
```yaml
redis:
  enabled: true
  url: redis://localhost:6379
```

---

## 📝 下一步

安装完成后：

1. ✅ 查看 API 文档：http://localhost:19377/docs
2. ✅ 测试聊天接口
3. ✅ 配置路由策略
4. ✅ 查看用量统计
5. ✅ 设置预算告警

---

## 📞 获取帮助

遇到问题？

- 📖 **文档**: https://docs.bridge-server.dev
- 🐛 **Issues**: https://github.com/your-org/bridge-server/issues
- 💬 **讨论**: https://github.com/your-org/bridge-server/discussions
- 📧 **邮件**: support@bridge-server.dev

---

**安装完成！🎉**

祝你使用愉快！如有问题随时反馈。
