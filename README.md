# 🌉 Bridge Server

**让 AI 更聪明、更便宜、更易用！**

[![License](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://python.org)
[![Version](https://img.shields.io/badge/version-1.0.0-green.svg)](https://github.com/your-org/bridge-server)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)](https://github.com/your-org/bridge-server)

---

## 🎯 为什么选择 Bridge Server？

**你是否有这些烦恼？**
- 😫 需要在多个 AI 平台间切换，API 各不相同
- 💸 总是用错模型，简单任务也调用昂贵模型
- 📊 不知道钱花在哪了，月底账单吓一跳
- 🔧 想加个新功能，要改很多地方

**Bridge Server 一次解决所有问题！**

```
┌─────────────────────────────────────────────────────────┐
│  你的应用                                                │
│      ↓                                                   │
│  Bridge Server (统一接口)                                │
│      ↓ ↓ ↓                                               │
│  阿里云  OpenAI  Moonshot  MiniMax  ...                 │
└─────────────────────────────────────────────────────────┘
```

---

## ✨ 核心特性

### 🧠 智能模型路由

**根据任务自动选择最优模型，节省 60%+ 成本！**

```python
# 方式 1: 智能路由（推荐）- 自动识别任务类型
POST /v1/chat/completions
{
  "model": "smart",  # 👈 唯一支持的模型参数，启用智能场景路由
  "messages": [{"role": "user", "content": "用 Python 写个快速排序"}]
}
# Bridge Server 自动选择 coding 专用模型

# 方式 2: 不传 model - 使用默认策略（向后兼容）
POST /v1/chat/completions
{
  "messages": [{"role": "user", "content": "你好"}]
}
# 根据配置的 routing.strategy 自动选择
```

**注意：** `model` 参数只接受 `"smart"` 这一个值。如需指定具体模型，请直接调用对应 Provider 的 API。

**三种路由策略，满足所有场景：**
- 🟢 **平衡模式** - 性价比最优（推荐）
- 🔵 **成本优先** - 能省则省，适合预算有限
- 🟣 **质量优先** - 全部最强模型，适合关键业务

**场景化模型配置：**
- 💻 编程辅助 → 自动选择代码专用模型
- ✍️ 写作创作 → 选择擅长文案的模型
- 🔍 搜索分析 → 选择逻辑分析强的模型
- 📝 摘要总结 → 选择长文本理解好的模型
- 💬 日常对话 → 选择响应快的经济模型
- 🌐 翻译 → 选择多语言能力强的模型

---

### 💰 成本透明可控

**每一分钱都花得明明白白！**

```bash
# API 查询用量
GET /api/usage?period=today

# 响应示例
{
  "total_requests": 1234,
  "total_cost": 12.34,
  "models": {
    "qwen3.5-flash": {"requests": 800, "cost": 3.20},
    "qwen3.5-plus": {"requests": 300, "cost": 6.40}
  }
}
```

**预算控制：**
- ✅ 实时用量追踪（按日/周/月）
- ✅ 按模型和 Provider 统计
- ✅ 预算检查 API（`GET /api/budget`）
- ⚠️ 预算告警通知功能开发中

---

### 🚀 跨平台一键部署

**Linux / macOS / Windows 全支持！**

```bash
# Docker Compose（推荐）
git clone https://github.com/qiannj/bridge-server.git
cd bridge-server
docker compose up -d

# Linux/macOS 直接运行
curl -fsSL https://raw.githubusercontent.com/qiannj/bridge-server/main/install.sh | bash

# Windows PowerShell
Invoke-WebRequest -Uri https://raw.githubusercontent.com/qiannj/bridge-server/main/install.ps1 -OutFile install.ps1
.\\install.ps1
```

**注意**: Docker 镜像发布计划中，当前使用 docker-compose 本地构建。

---

## 🎓 快速开始

### 步骤 1: 安装

**方式 A: Docker Compose（推荐）**

```bash
# 克隆仓库
git clone https://github.com/qiannj/bridge-server.git
cd bridge-server

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 API Key

# 启动服务
docker compose up -d

# 验证
curl http://localhost:19377/health
```

**方式 B: 直接运行**

```bash
# Linux/macOS
curl -fsSL https://raw.githubusercontent.com/qiannj/bridge-server/main/install.sh | bash

# Windows
powershell -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/qiannj/bridge-server/main/install.ps1' -OutFile 'install.ps1'; .\\install.ps1"
```

**方式 C: 手动部署**

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置
cp config.yaml.example ~/.bridge-server/config.yaml
# 编辑配置文件

# 3. 启动
python -m uvicorn app.main:app --host 127.0.0.1 --port 19377
```

### 步骤 2: 配置

```bash
# 运行配置向导（交互式）
python3 cli/setup-wizard.py

# 或手动配置
vi ~/.bridge-server/config.yaml
# 填入你的 API Key
```

**配置向导功能**:
- ✅ 交互式配置 Provider 和 API Key
- ✅ 自动选择可用模型
- ✅ 场景化模型映射配置
- ✅ 自动生成安全 Token

### 步骤 3: 启动

```bash
# Docker Compose 方式
docker compose up -d

# 或直接运行
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 19377

# Systemd 方式（Linux）
sudo systemctl start bridge-server
```

### 步骤 4: 测试

```bash
curl -X POST http://localhost:19377/v1/chat/completions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "你好"}]}'
```

**完成！🎉**

---

## 📊 支持的 AI 平台

| 平台 | 模型 | 成本优势 | 状态 |
|------|------|---------|------|
| **阿里云百炼** | Qwen 系列 | 💰💰💰💰💰 | ✅ 已支持 |
| **Moonshot** | Kimi | 💰💰💰💰 | ✅ 已支持 |
| **OpenAI** | GPT 系列 | 💰💰💰 | ✅ 已支持 |
| **MiniMax** | M2.5 | 💰💰💰💰 | ✅ 已支持 |
| **DeepSeek** | V4/R1 | 💰💰💰💰💰 | 🚧 即将支持 |

---

## 🛠️ 管理接口

Bridge Server 提供 REST API 进行管理操作：

```bash
# 服务健康检查
curl http://localhost:19377/health

# 查看可用模型
curl http://localhost:19377/api/models

# 查看用量统计
curl http://localhost:19377/api/usage?period=today

# 查看预算状态
curl http://localhost:19377/api/budget

# 查看路由配置
curl http://localhost:19377/api/routing

# 导出用量报告
curl http://localhost:19377/api/export/usage?period=month\&format=json
```

**命令行工具开发中** - 计划支持 `bridge-server start/stop/restart/status` 等命令。

---

## 📖 使用场景

### 场景 1: 个人开发者

**问题**: 想试试不同 AI 平台，但每个都要单独接入

**Bridge Server 方案**:
```python
# 只需对接一个接口
import openai

client = openai.OpenAI(
    base_url="http://localhost:19377/v1",
    api_key="your-token"
)

# 自动使用最优模型
response = client.chat.completions.create(
    model="auto",  # 🎯 自动路由
    messages=[{"role": "user", "content": "帮我写个爬虫"}]
)
```

**收益**: 节省 60% 成本，代码量减少 80%

---

### 场景 2: 创业团队

**问题**: 预算有限，需要精打细算

**Bridge Server 方案**:
```yaml
# 配置预算限制
budget:
  enabled: true
  daily_limit: 50      # 每天 50 元
  monthly_limit: 1000  # 每月 1000 元
  over_budget_action: downgrade  # 超预算自动降级

# 检查预算状态
GET /api/budget
```

**已实现**:
- ✅ 预算配置（每日/每月上限）
- ✅ 预算检查 API（`GET /api/budget`）
- ✅ 超预算降级策略配置

**计划中**:
- ⚠️ 预算告警通知（邮件/短信）
- ⚠️ 超预算自动执行降级

**收益**: 预算可控，通过 API 实时监控用量

---

### 场景 3: 小型团队

**问题**: 需要简单的认证和用量追踪

**Bridge Server 方案**:
```yaml
# 配置多个 API Key（单用户模式）
auth:
  api_keys:
    - key: sk-team-a-xxx
      name: team-a
    - key: sk-team-b-xxx
      name: team-b
```

**收益**: 简单的 Key 管理，完整的用量追踪，成本分摊

**多用户权限系统开发中** - 计划支持用户级预算限制和模型访问控制。

---

## 🔧 技术架构

```
┌─────────────────────────────────────────────────────────┐
│                    客户端应用                            │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│              Bridge Server API Gateway                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │   认证   │  │   路由   │  │  限流    │              │
│  │ (JWT/Key)│  │(智能/JS) │  │(SlowAPI) │              │
│  └──────────┘  └──────────┘  └──────────┘              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │  用量    │  │  预算    │  │  日志    │              │
│  │(SQLite/DB)│  │ (检查)  │  │(性能追踪)│              │
│  └──────────┘  └──────────┘  └──────────┘              │
└─────────────────────────────────────────────────────────┘
                          ↓ ↓ ↓
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│ 阿里云   │  │ OpenAI   │  │ Moonshot │  │ MiniMax  │
└──────────┘  └──────────┘  └──────────┘  └──────────┘
```

**技术栈**:
- 后端：FastAPI (Python 3.8+)
- 数据库：SQLite (默认) / MySQL (可选，通过 DATABASE_URL 环境变量)
- 认证：JWT + API Key
- 限流：SlowAPI
- 部署：Docker Compose / Systemd / Standalone

**核心特性**:
- ✅ 智能模型路由（6 种任务类型自动识别）
- ✅ JS 沙箱自定义路由（安全隔离执行用户代码）
- ✅ Stream 模式支持（20 秒心跳防止超时）
- ✅ 高并发写入器（异步批量写入数据库）
- ✅ 性能追踪日志（请求解析/路由决策/LLM 调用）
- ✅ 双后端用量统计（文件/数据库自动切换）
- ✅ 预算检查 API（`GET /api/budget`）
- ⚠️ Prometheus 监控（计划中）
- ⚠️ 预算告警通知（计划中）

---

## 📦 已实现功能详解

### 1. 数据库后端支持

Bridge Server 支持两种用量存储后端：

**文件存储（默认）**:
- 数据位置：`~/.bridge-server/usage.json`
- 适合：个人使用、低并发场景
- 无需额外配置

**数据库存储（可选）**:
- 支持：SQLite / MySQL / PostgreSQL
- 配置：设置 `DATABASE_URL` 环境变量
- 适合：高并发、多用户场景

```bash
# 启用数据库后端
export DATABASE_URL=sqlite:///./bridge-server.db
# 或
export DATABASE_URL=mysql://user:pass@localhost/bridge_server
```

**高并发写入器**: `services/high_concurrency_writer.py` 提供异步批量写入，避免阻塞请求。

---

### 2. JS 沙箱自定义路由

允许用户编写自定义路由逻辑，安全隔离执行：

**配置方式** (`config.yaml`):
```yaml
routing:
  strategy: custom
  custom_routing_enabled: true
  custom_route_code: |
    # 你的自定义路由逻辑
    def route(context):
        message = context.get('message', '').lower()
        if 'code' in message:
            return {'model': 'qwen3-coder-plus', 'reason': '代码任务'}
        else:
            return {'model': 'qwen3.5-plus', 'reason': '通用任务'}
```

**安全特性**:
- ✅ 禁止 `import` / `eval` / `exec`
- ✅ 禁止文件系统访问
- ✅ 禁止网络请求
- ✅ 5 秒执行超时
- ✅ 128MB 内存限制

详见：`services/sandbox.py`

---

### 3. Stream 模式 + 心跳机制

支持 SSE (Server-Sent Events) 流式响应，防止代理超时：

**请求示例**:
```bash
curl -X POST http://localhost:19377/v1/chat/completions \
  -H "Authorization: Bearer ***" \
  -H "Content-Type: application/json" \
  -d '{"model": "smart", "messages": [...], "stream": true}'
```

**心跳机制**:
- 每 20 秒发送 SSE 注释行 `: heartbeat`
- 防止负载均衡/代理切断空闲连接
- 支持最长 300 秒超时

详见：`app/main.py:chat_completions_stream()`

---

### 4. 性能追踪日志

每个请求自动记录 3 个阶段的耗时：

```
⏱️ 性能 | 请求解析：0.82ms
⏱️ 性能 | 路由决策：6.09ms | 任务类型=general | 模型=aliyun-coding-plan/qwen3.5-plus
⏱️ 性能 | 总耗时：4689.47ms | LLM 调用：4682.06ms | 其他：7.41ms
```

**追踪阶段**:
1. 请求解析 - JSON 解析 + 参数验证
2. 路由决策 - 任务识别 + 模型选择
3. LLM 调用 - HTTP POST + 等待响应

详见：`app/main.py:181-262`

---

### 5. 双后端用量统计

自动检测并使用最佳存储后端：

**自动切换逻辑**:
```
有 DATABASE_URL? 
    ↓ 是
使用数据库后端 (SQLAlchemy)
    ↓ 失败
降级到文件后端
    ↓
无 DATABASE_URL?
    ↓
使用文件后端 (JSON)
```

**统计维度**:
- 按日/周/月/全部
- 按模型汇总
- 按 Provider 汇总
- 每日明细
- 成功率统计

详见：`services/usage.py`

---

### 6. 多种认证方式

支持两种认证方式：

**Bearer Token** (推荐):
```bash
Authorization: Bearer sk-client-xxx
```

**X-API-Key 头**:
```bash
X-API-Key: sk-client-xxx
```

**Token 格式**:
- API Key: 简单字符串
- JWT: `xxx.xxx.xxx` 格式（3 段式）

详见：`app/auth.py`

---

## 📚 文档

- [📖 使用指南](USAGE.md) - 完整的使用说明和最佳实践
- [📥 安装指南](INSTALL.md) - 安装和部署指南
- [📝 更新日志](CHANGELOG.md) - 版本变更历史
- [📋 待办清单](TODO.md) - 计划实现的功能
- [⚙️ 配置模板](config.yaml.example) - 配置示例
- [🔒 安全策略](docs/SECURITY-POLICY.md) - 安全说明

**历史归档**:
- [docs-archive-history/](docs-archive-history/) - 旧版本文档归档

---

## 🤝 贡献

欢迎贡献代码、文档或建议！

```bash
# 1. Fork 本仓库
# 2. 创建特性分支
git checkout -b feature/amazing-feature

# 3. 提交更改
git commit -m 'Add amazing feature'

# 4. 推送分支
git push origin feature/amazing-feature

# 5. 开启 Pull Request
```

详见 [贡献指南](CONTRIBUTING.md)

---

## 📄 许可证

AGPL-3.0 License - 详见 [LICENSE](LICENSE) 文件

---

## 📞 支持

遇到问题？我们来帮你！

- 🐛 **Bug 反馈**: [GitHub Issues](https://github.com/qiannj/bridge-server/issues)
- 💬 **讨论交流**: [Discussions](https://github.com/qiannj/bridge-server/discussions)
- 📧 **邮件联系**: qxy19921026@gmail.com
- 📖 **文档**: https://github.com/qiannj/bridge-server#readme

---

## 🎉 致谢

感谢所有贡献者和用户！

Made with ❤️ by Bridge Server Team

---

**让 AI 更便宜、更易用！** 🚀
