# Bridge Server 安装指南

## 环境要求

- Python 3.10+（已在 3.14 环境验证）
- 可选：Docker / Docker Compose
- 至少一个可用 Provider 凭证

## 本地安装

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-v2.txt
python cli/setup-wizard.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 19377
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-v2.txt
python cli\setup-wizard.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 19377
```

## Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
curl http://127.0.0.1:19377/health
```

## 配置

默认配置文件位置：

1. `~/.bridge-server/config.yaml`
2. 仓库根目录下的 `config.yaml`

推荐先运行：

```bash
python cli/setup-wizard.py
```

最小配置示例：

```yaml
auth:
  api_keys:
    - sk-your-token

providers:
  dashscope:
    enabled: true
    api_key_env: DASHSCOPE_API_KEY
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    models:
      qwen3.5-flash: {}

routing:
  strategy: balanced
```

## 启动方式

直接运行：

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 19377
```

兼容入口仍可用，但不再是主实现：

```bash
python -m uvicorn bridge_server.runtime:app --app-dir src --host 127.0.0.1 --port 19377
python -m uvicorn main_v2_async:app --host 127.0.0.1 --port 19377
python -m uvicorn main_v2:app --host 127.0.0.1 --port 19377
```

## 验证

```bash
curl http://127.0.0.1:19377/health
curl http://127.0.0.1:19377/ready
curl http://127.0.0.1:19377/api/models
curl http://127.0.0.1:19377/metrics/prometheus
```

## 常见问题

### 依赖安装失败

优先升级 pip 并重试：

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-v2.txt
```

### 没有可用模型

检查三项：

1. `config.yaml` 中 Provider 已启用
2. 对应环境变量中的 API Key 已设置
3. `GET /health` 返回的 provider 状态不是空列表

### 服务能启动但不可用

先看：

```bash
curl http://127.0.0.1:19377/health
curl http://127.0.0.1:19377/ready
```

`/health` 反映总体状态，`/ready` 更适合做探活和依赖检查。
