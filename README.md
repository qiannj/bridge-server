# Bridge Server

**AI接口统一网关 - 解决多平台接入、成本控制、性能优化三大痛点**

[![License](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://python.org)
[![Version](https://img.shields.io/badge/version-2.0-green.svg)](https://github.com/qiannj/bridge-server)

---

## 🎯 解决的核心问题

### 问题1：多平台接入复杂
- 阿里云通义、OpenAI、月之暗面、MiniMax...每个平台API都不同
- 切换成本高，代码改动大

### 问题2：成本不可控
- 不知道哪个任务用了哪个模型
- 简单问题调用昂贵模型
- 月底账单成迷

### 问题3：性能瓶颈
- 同步I/O阻塞，并发能力差
- 无连接池复用，延迟高
- 缺少缓存，重复计算

## ✨ Bridge Server的解决方案

**一个接口，搞定所有AI平台**

```bash
# 统一的OpenAI格式接口
POST http://localhost:19377/v1/chat/completions

# 自动路由到最优模型
{
  "model": "smart",  # 智能路由
  "messages": [{"role": "user", "content": "写个Python快速排序"}]
}
# → 自动选择编程专用模型（成本可节省60%+）
```

---

## 🚀 核心特性

### 1. 智能模型路由
- **任务识别**: 自动识别编程、写作、翻译、分析等场景
- **成本优化**: 简单任务用便宜模型，复杂任务用高端模型
- **配置灵活**: 平衡/成本优先/质量优先三种策略

### 2. 成本透明控制
```bash
# 实时用量查询
GET /api/usage?period=today
{
  "total_requests": 1234,
  "total_cost": 12.34,
  "models": {
    "qwen3.5-flash": {"requests": 800, "cost": 3.20},
    "qwen3.5-plus": {"requests": 300, "cost": 6.40}
  }
}

# 预算检查
GET /api/budget
{
  "daily_used": 28.5,
  "daily_limit": 50.0,
  "remaining": 21.5
}
```

### 3. 高性能架构
- **异步I/O**: 消除阻塞等待，支持高并发
- **连接池**: HTTP连接复用，降低延迟
- **智能缓存**: 相同请求直接返回，节省成本
- **目标性能**: 从10 QPS提升到200+ QPS（20倍提升）

---

## 📊 支持的AI平台

| 平台 | 模型 | 成本等级 | 状态 |
|------|------|---------|------|
| **阿里云通义** | Qwen3.5系列 | 💰 (最便宜) | ✅ |
| **Moonshot** | Kimi | 💰💰 | ✅ |
| **OpenAI** | GPT-4/3.5 | 💰💰💰 | ✅ |
| **MiniMax** | M2.5 | 💰💰 | ✅ |
| **DeepSeek** | V4/R1 | 💰 | 🚧 即将支持 |

---

## ⚡ 快速开始

### 方式1: Docker Compose（推荐）

```bash
git clone https://github.com/qiannj/bridge-server.git
cd bridge-server

# 配置API Keys
cp .env.example .env
# 编辑 .env 填入你的API密钥

# 启动服务
docker compose up -d

# 验证
curl http://localhost:19377/health
```

### 方式2: Python直接运行

```bash
# 安装依赖
pip install -r requirements-v2.txt

# 配置
python setup-wizard.py  # 交互式配置

# 启动服务（v2异步版本）
python main_v2_async.py
```

### 测试接口

```bash
curl -X POST http://localhost:19377/v1/chat/completions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "smart",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

---

## 🛠️ 配置说明

### 基础配置 (config.yaml)

```yaml
# API Keys配置
providers:
  dashscope:
    api_key: "sk-xxx"
    enabled: true
  openai:
    api_key: "sk-xxx" 
    enabled: true

# 路由策略
routing:
  strategy: "balanced"  # balanced/cost_first/quality_first
  
# 预算控制
budget:
  enabled: true
  daily_limit: 50
  monthly_limit: 1000

# 性能优化
performance:
  enable_cache: true
  cache_ttl: 300
  max_concurrent: 100
```

### 智能路由配置

支持6种任务类型自动识别：
- **编程**: 自动选择代码专用模型
- **写作**: 选择文本生成能力强的模型  
- **翻译**: 选择多语言模型
- **分析**: 选择逻辑推理强的模型
- **摘要**: 选择长文本理解好的模型
- **对话**: 选择响应快的经济模型

---

## 📈 性能数据

### v1.0 vs v2.0 性能对比

| 指标 | v1.0 | v2.0 | 提升 |
|------|------|------|------|
| **QPS** | ~10 | 200+ | 20x |
| **平均延迟** | 800ms | 200ms | 4x |
| **并发连接** | 20 | 1000+ | 50x |
| **内存使用** | 200MB | 150MB | ↓25% |

### v2.0 架构优化

- ✅ **Provider抽象层**: 统一接口，易于扩展
- ✅ **异步I/O**: 消除阻塞，支持高并发
- ✅ **连接池**: HTTP连接复用，降低延迟
- ✅ **智能缓存**: HybridCache二级缓存系统
- ✅ **批量写入**: 异步批量写数据库，避免阻塞

---

## 🎯 使用场景

### 个人开发者
```python
# 只需对接一个接口，自动路由最优模型
import openai

client = openai.OpenAI(
    base_url="http://localhost:19377/v1",
    api_key="your-token"
)

# 编程任务自动选择便宜的代码模型
response = client.chat.completions.create(
    model="smart",
    messages=[{"role": "user", "content": "写个快速排序"}]
)
```

### 团队/企业
- 统一接口，降低接入成本
- 透明的用量和成本追踪
- 预算控制，避免超支
- 高性能，支撑业务增长

---

## 🔧 技术架构

```
┌─────────────────────────────────────────┐
│                客户端                    │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│            Bridge Server                │
│  ┌────────┐ ┌────────┐ ┌────────┐      │
│  │  认证  │ │智能路由│ │  缓存  │      │
│  └────────┘ └────────┘ └────────┘      │
│  ┌────────┐ ┌────────┐ ┌────────┐      │
│  │连接池  │ │用量统计│ │预算控制│      │
│  └────────┘ └────────┘ └────────┘      │
└─────────────────────────────────────────┘
          ↓       ↓       ↓       ↓
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│阿里通义│ │ OpenAI │ │Moonshot│ │MiniMax │
└────────┘ └────────┘ └────────┘ └────────┘
```

**核心组件**:
- **ProviderManager**: 统一的Provider管理器
- **SmartRouter**: 任务类型识别 + 智能路由
- **HybridCache**: 内存+文件二级缓存
- **ConnectionPools**: HTTP连接池优化
- **UsageTracker**: 精确的用量和成本统计

---

## 📊 管理接口

```bash
# 健康检查
GET /health

# 查看支持的模型
GET /api/models

# 用量统计（支持today/week/month/all）
GET /api/usage?period=today

# 预算状态
GET /api/budget

# 路由配置
GET /api/routing

# 导出用量报告
GET /api/export/usage?period=month&format=json
```

---

## 🛡️ 安全特性

- **API Key认证**: 支持多Key管理
- **JS沙箱**: 自定义路由代码安全隔离执行
- **限流保护**: 防止恶意请求
- **预算控制**: 防止意外超支

---

## 📝 开发状态

### ✅ 已实现
- Provider抽象层架构
- 智能模型路由（6种任务类型）
- 异步I/O + 连接池优化
- 用量统计和成本追踪
- 预算检查API
- Stream模式支持
- Docker部署

### 🚧 开发中
- Prometheus监控指标
- 预算告警通知
- 用户权限系统
- WebUI管理界面

---

## 📜 许可证

本项目采用 AGPL-3.0 许可证。详见 [LICENSE](LICENSE) 文件。

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📧 联系

- 项目主页: https://github.com/qiannj/bridge-server
- 问题反馈: https://github.com/qiannj/bridge-server/issues