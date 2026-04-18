# Bridge Server 使用指南

## 获取 Token

首次启动时服务会自动生成 Admin Token 并打印到控制台（仅一次），形如：

```
Admin token : 71a63d726fbcfa80c98befaffa432ce1ce4b06e920be755aecef10d3c05bff50
```

保存后即可用于所有需要认证的请求。

## 认证

所有受保护接口使用：

```http
Authorization: Bearer <your-token>
```

**无需认证**：`/health`、`/ready`、`/v1/models`

**需要认证**：`/v1/chat/completions`、`/metrics`、`/stats`、`/metrics/prometheus`、`/api/usage`、`/api/budget`

## Chat Completions

最小请求：

```bash
curl -X POST http://127.0.0.1:19377/v1/chat/completions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "用 Python 写个快速排序"}]
  }'
```

显式使用智能路由：

```json
{
  "model": "smart",
  "messages": [{"role": "user", "content": "写一个邮件回复模板"}]
}
```

显式指定模型：

```json
{
  "model": "dashscope/qwen3.5-plus",
  "messages": [{"role": "user", "content": "你好"}]
}
```

## 流式响应

```bash
curl -N -X POST http://127.0.0.1:19377/v1/chat/completions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "stream": true,
    "messages": [{"role": "user", "content": "给我一个三点总结"}]
  }'
```

## 模型与路由

```bash
# 无需认证
curl http://127.0.0.1:19377/v1/models
curl http://127.0.0.1:19377/api/models
curl http://127.0.0.1:19377/api/routing
```

`/v1/models` 面向 OpenAI 兼容客户端，`/api/models` 面向管理和排障。

## 用量与预算

```bash
TOKEN=your-token

curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:19377/api/usage?period=today
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:19377/api/usage?period=month
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:19377/api/budget
```

## 健康检查与观测

```bash
TOKEN=your-token

# 无需认证
curl http://127.0.0.1:19377/health
curl http://127.0.0.1:19377/ready

# 需要认证
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:19377/metrics
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:19377/metrics/prometheus
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:19377/stats
```

说明：

- `/health`：总体健康状态
- `/ready`：依赖就绪状态（适合 k8s readiness probe）
- `/metrics`：JSON 指标快照
- `/metrics/prometheus`：Prometheus 文本格式
- `/stats`：运行时汇总视图

## 请求追踪

服务会为每个请求生成并回传：

- `X-Request-ID`
- `X-Trace-ID`

如果上游已传入 `traceparent` 或 `X-Request-ID`，服务会沿用并继续向 Provider 透传。

## 常见调用约定

1. 默认不传 `model` 时，使用当前路由策略。
2. 传 `model: "smart"` 时，启用智能路由。
3. 传具体模型时，直接走指定模型。
4. Provider 不可用或预算受限时，健康和指标端点会反映降级状态。
