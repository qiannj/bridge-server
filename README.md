# Bridge Server

**AI 接口统一网关** - 解决多平台接入、成本控制、性能优化三大痛点。

[![License](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://python.org)
[![Version](https://img.shields.io/badge/version-2.2-green.svg)](https://github.com/qiannj/bridge-server)

## 当前状态

- **唯一运行时实现**：`src/bridge_server/runtime.py`
- **稳定启动入口**：`app.main:app`
- **兼容入口**：`main_v2.py`、`main_v2_async.py`
- **核心代码位置**：`src/bridge_server/`
- **脚本归类**：`scripts/ops`、`scripts/bench`、`scripts/verify`、`scripts/security`

## 解决的核心问题

### 1. 多平台接入复杂

- 不同 Provider 的 API 形态不一致
- 切换平台时客户端代码改动大
- 新增 Provider 时维护成本高

### 2. 成本不可控

- 不清楚请求实际落到哪个模型
- 简单任务可能误用昂贵模型
- 缺少统一的用量和预算视图

### 3. 性能与可观测性不足

- 同步 I/O 和无连接复用会拖慢吞吐
- 缺少缓存与批量写入
- 缺少统一 tracing 和 Prometheus 指标

## Bridge Server 的方案

- **统一 OpenAI 兼容接口**：`POST /v1/chat/completions`
- **智能模型路由**：根据任务类型自动选模型
- **用量与预算控制**：`/api/usage`、`/api/budget`
- **健康与观测**：`/health`、`/ready`、`/metrics`、`/metrics/prometheus`、`/stats`
- **兼容包装层**：保留原启动方式，但业务主线集中到 `src/bridge_server/`

## 快速开始

```bash
pip install -r requirements.txt -r requirements-v2.txt

# 设置至少一个 Provider API Key
export DASHSCOPE_API_KEY=sk-xxx

# 启动（首次运行会打印 Admin Token，请保存）
python -m uvicorn bridge_server.runtime:app --app-dir src --host 127.0.0.1 --port 19377
```

首次启动输出示例：

```
IMPORTANT: New admin token generated — save it now.
  Admin token : 71a63d726fbcfa80...
```

最小请求示例：

```bash
curl -X POST http://127.0.0.1:19377/v1/chat/completions \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "smart",
    "messages": [{"role": "user", "content": "写个 Python 快速排序"}]
  }'
```

## 架构概览

```text
Client
  -> app.main:app
  -> src/bridge_server/runtime.py
  -> src/bridge_server/providers/
  -> src/bridge_server/services/routing/
  -> src/bridge_server/auth.py
  -> src/bridge_server/usage.py
  -> src/bridge_server/observability/
  -> src/bridge_server/utils/
  -> scripts/{ops,bench,verify,security}/
```

## 主要接口

| 接口 | 说明 | 认证 |
| --- | --- | --- |
| `POST /v1/chat/completions` | OpenAI 兼容聊天接口 | ✅ 必须 |
| `GET /v1/models` | OpenAI 风格模型列表 | 否 |
| `GET /api/models` | 管理视角模型列表 | 否 |
| `GET /api/routing` | 当前路由策略与映射 | 否 |
| `GET /api/usage` | 用量统计 | ✅ 必须 |
| `GET /api/budget` | 预算状态 | ✅ 必须 |
| `GET /health` | 健康检查 | 否 |
| `GET /ready` | 就绪检查 | 否 |
| `GET /metrics` | JSON 指标 | ✅ 必须 |
| `GET /metrics/prometheus` | Prometheus 指标 | ✅ 必须 |
| `GET /stats` | 运行时汇总 | ✅ 必须 |

## 核心文档

| 文件 | 用途 |
| --- | --- |
| `README.md` | 项目概览、核心价值、架构说明 |
| `INSTALL.md` | 安装、部署、启动方式 |
| `USAGE.md` | API 与使用方式 |
| `CHANGELOG.md` | 重要变更记录 |
| `TODO.md` | 当前剩余工作 |

更多部署和调用示例见 `INSTALL.md` 与 `USAGE.md`。
