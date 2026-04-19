# Bridge Server 安装指南

## 环境要求

- Python 3.10+（已在 3.14 环境验证）
- 可选：Docker / Docker Compose
- 至少一个可用 Provider API Key

## 本地安装

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 设置 Provider API Key（至少一个）
export DASHSCOPE_API_KEY=sk-xxx    # Windows: $env:DASHSCOPE_API_KEY="sk-xxx"

python -m uvicorn bridge_server.runtime:app --app-dir src --host 127.0.0.1 --port 19377
```

**首次启动**时，服务会自动生成一个随机 Admin Token 并打印到控制台（仅显示一次）：

```
IMPORTANT: New admin token generated — save it now.
  Admin token : <64位十六进制字符串>
```

请立即保存该 token，后续所有请求均需携带。

## Docker Compose

```bash
cp .env.example .env
# 编辑 .env，填入真实的 API Key
docker compose up -d --build
```

首次启动后从日志取 token：

```bash
docker compose logs | grep "Admin token"
```

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DASHSCOPE_API_KEY` | 阿里云百炼 API Key | — |
| `MOONSHOT_API_KEY` | Moonshot (Kimi) API Key | — |
| `OPENAI_API_KEY` | OpenAI API Key | — |
| `CORS_ORIGINS` | 允许跨域的来源（逗号分隔），留空则不允许携带凭证的跨域请求 | 空 |
| `ENABLE_DOCS` | 设为 `true` 开启 `/docs`、`/redoc` 交互文档（仅开发环境使用） | `false` |
| `LOG_LEVEL` | 日志级别 | `INFO` |

## 配置文件

默认读取位置（按优先级）：

1. `~/.bridge-server/config.yaml`
2. 仓库根目录下的 `config.yaml`

参见 `config.yaml.secure-example` 了解所有可配置项。

## 启动方式

**推荐（主实现）：**

```bash
python -m uvicorn bridge_server.runtime:app --app-dir src --host 127.0.0.1 --port 19377
```

Bridge Server 现已收敛为单一运行入口，不再保留 `main_v2.py` / `main_v2_async.py` 并行启动方式。

## 验证

```bash
TOKEN=<首次启动获取的 token>

# 无需认证
curl http://127.0.0.1:19377/health
curl http://127.0.0.1:19377/ready
curl http://127.0.0.1:19377/v1/models

# 需要认证
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:19377/metrics
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:19377/api/usage
```

## 常见问题

### 没有可用模型

检查三项：

1. 对应 Provider 的环境变量 API Key 已设置
2. `config.yaml` 中 Provider `enabled: true`
3. `GET /health` 返回的 provider 状态不为空

### 服务启动但请求返回 401

Token 未正确携带或填写错误。确认格式：

```
Authorization: Bearer <token>
```

### 依赖安装失败

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```
