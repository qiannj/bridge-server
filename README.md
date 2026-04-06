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
# 你只需调用一次
POST /v1/chat/completions
{
  "messages": [{"role": "user", "content": "用 Python 写个快速排序"}]
}

# Bridge Server 自动选择 coding 专用模型
# 如果是问候，自动选择最便宜的模型
# 如果是复杂推理，自动选择最强模型
```

**三种路由策略，满足所有场景：**
- 🟢 **平衡模式** - 性价比最优（推荐）
- 🔵 **成本优先** - 能省则省，适合预算有限
- 🟣 **质量优先** - 全部最强模型，适合关键业务

---

### 💰 成本透明可控

**每一分钱都花得明明白白！**

```bash
# 实时查看用量
$ bridge-server usage --today

今日用量报告
━━━━━━━━━━━━━━━━━━━━━━━
总请求数：1,234
总花费：¥12.34
平均每次：¥0.01

按模型分布：
  qwen3.5-flash   800 次  ¥3.20  (26%)
  qwen3.5-plus    300 次  ¥6.40  (52%)
  qwen3-max       134 次  ¥2.74  (22%)
```

**预算告警，再也不怕超支：**
- 50% 使用量 → 邮件提醒
- 80% 使用量 → 邮件 + 短信
- 90% 使用量 → 全渠道告警
- 100% 使用量 → 自动降级或暂停

---

### 🔐 企业级安全

**生产环境级别的安全保障！**

- ✅ JWT Token 认证
- ✅ API Key 管理
- ✅ 速率限制（防滥用）
- ✅ JS 沙箱（安全执行自定义路由逻辑）
- ✅ 审计日志（所有操作可追溯）

---

### 🚀 跨平台一键部署

**Linux / macOS / Windows 全支持！**

```bash
# Linux/macOS
curl -fsSL https://example.com/install.sh | bash

# Windows PowerShell
Invoke-WebRequest -Uri https://example.com/install.ps1 -OutFile install.ps1
.\install.ps1

# Docker（推荐）
docker run -d -p 19377:19377 \
  -v ~/.bridge-server:/root/.bridge-server \
  bridgedev/bridge-server:latest
```

**3 分钟完成部署，开箱即用！**

---

## 🎓 快速开始

### 步骤 1: 安装

```bash
# Linux/macOS
curl -fsSL https://example.com/install.sh | bash

# Windows
powershell -Command "Invoke-WebRequest -Uri 'https://example.com/install.ps1' -OutFile 'install.ps1'; .\install.ps1"
```

### 步骤 2: 配置

```bash
# 运行配置向导（交互式）
bridge-server setup

# 或手动配置
vi ~/.bridge-server/.env
# 填入你的 API Key
```

### 步骤 3: 启动

```bash
bridge-server start
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

## 🛠️ 命令行工具

```bash
# 服务管理
bridge-server start          # 启动服务
bridge-server stop           # 停止服务
bridge-server restart        # 重启服务
bridge-server status         # 查看状态
bridge-server logs           # 查看日志

# 用量查询
bridge-server usage --today  # 今日用量
bridge-server usage --week   # 本周用量
bridge-server usage --month  # 本月用量

# 路由测试
bridge-server routing-test "用 Python 写个快速排序"
# 输出：将路由到 qwen3-coder-plus (代码任务)

# 配置管理
bridge-server setup          # 配置向导
bridge-server backup         # 备份配置
bridge-server restore        # 恢复配置
```

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
# 配置预算告警
budget:
  daily_limit: 50      # 每天 50 元
  monthly_limit: 1000  # 每月 1000 元
  over_budget_action: downgrade  # 超预算自动降级
```

**收益**: 预算可控，不再担心月底账单

---

### 场景 3: 企业用户

**问题**: 需要审计、权限控制、多团队管理

**Bridge Server 方案**:
```yaml
# 多用户 + 权限控制
users:
  - name: team-a
    token: token-abc
    budget: 5000
    models: [all]
  
  - name: team-b
    token: token-xyz
    budget: 2000
    models: [qwen3.5-flash, qwen3.5-plus]  # 限制可用模型
```

**收益**: 权限清晰，审计完整，成本分摊

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
│  └──────────┘  └──────────┘  └──────────┘              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │  用量    │  │  预算    │  │  日志    │              │
│  └──────────┘  └──────────┘  └──────────┘              │
└─────────────────────────────────────────────────────────┘
                          ↓ ↓ ↓
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│ 阿里云   │  │ OpenAI   │  │ Moonshot │  │ MiniMax  │
└──────────┘  └──────────┘  └──────────┘  └──────────┘
```

**技术栈**:
- 后端：FastAPI (Python 3.8+)
- 数据库：SQLite (默认) / MySQL (可选)
- 缓存：Redis (可选)
- 部署：Docker / Systemd / Standalone

---

## 📚 文档

- [🚀 快速开始](docs/QUICKSTART.md) - 3 分钟上手
- [⚙️ 配置指南](docs/CONFIG.md) - 详细配置说明
- [📖 API 参考](docs/API.md) - 完整 API 文档
- [🧠 路由策略](docs/ROUTING.md) - 路由算法详解
- [🔧 故障排查](docs/TROUBLESHOOTING.md) - 常见问题

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

- 🐛 **Bug 反馈**: [GitHub Issues](https://github.com/your-org/bridge-server/issues)
- 💬 **讨论交流**: [Discussions](https://github.com/your-org/bridge-server/discussions)
- 📧 **邮件联系**: support@example.com
- 📖 **文档**: https://docs.bridge-server.dev

---

## 🎉 致谢

感谢所有贡献者和用户！

Made with ❤️ by Bridge Server Team

---

**让 AI 更便宜、更易用！** 🚀
