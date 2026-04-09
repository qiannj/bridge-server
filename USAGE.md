# Bridge Server 使用指南

---

## 📋 快速开始

### 三种使用模式

Bridge Server v2.1 支持三种请求模式：

| 模式 | model 参数 | 说明 | 适用场景 |
|------|-----------|------|---------|
| **智能路由** | `"smart"` | 系统自动选择最优模型 | 日常使用（推荐） |
| **指定模型** | `"provider/model-id"` | 使用指定模型 | 测试/特定需求 |
| **默认策略** | 不传或空值 | 使用配置的 routing.strategy | 向后兼容 |

---

## 🎯 使用模式详解

### 模式 A: 智能路由（推荐）⭐

```bash
curl -X POST http://localhost:19377/v1/chat/completions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "smart",
    "messages": [{"role": "user", "content": "用 Python 写个快速排序"}]
  }'
```

**行为：**
1. 系统分析消息内容，识别任务类型（coding/writing/analysis 等）
2. 根据配置的场景化模型映射，自动选择最优模型
3. 响应中包含路由信息，方便追踪

**响应示例：**
```json
{
  "choices": [...],
  "usage": {
    "routing": {
      "task_type": "coding",
      "selected_model": "dashscope/qwen3-coder-plus",
      "reason": "智能路由：coding"
    }
  }
}
```

---

### 模式 B: 指定具体模型

```bash
curl -X POST http://localhost:19377/v1/chat/completions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "dashscope/qwen3.5-plus",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

**行为：**
- 使用指定的模型，不进行智能路由
- 支持短名称（如 `qwen3.5-plus`）和完整名称（如 `dashscope/qwen3.5-plus`）
- 系统会自动查找匹配的 provider

**适用场景：**
- 测试特定模型效果
- 业务需要固定模型
- 对响应质量有明确要求

---

### 模式 C: 默认策略（不传 model）

```bash
curl -X POST http://localhost:19377/v1/chat/completions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

**行为：**
- 不传 `model` 参数或传空值
- 使用配置的 `routing.strategy` 默认策略
- 等同于旧版本行为，保持向后兼容

---

## 📊 路由决策流程

```
客户端请求
    ↓
检查 model 参数
    ↓
┌─────────────────┬─────────────────┬─────────────────┐
│  model="smart"  │ model="具体 ID" │   不传/空值     │
└─────────────────┴─────────────────┴─────────────────┘
        ↓                 ↓                    ↓
   智能场景路由       使用指定模型        默认策略
        ↓                 ↓                    ↓
  识别任务类型       验证模型存在        使用 routing.strategy
  匹配场景模型       直接调用            (balanced/cost-first...)
        ↓                 ↓                    ↓
    调用模型          调用模型            调用模型
```

---

## 🔧 配置场景化模型

### config.yaml - 智能路由映射

```yaml
routing:
  strategy: balanced  # 默认策略
  
  # 智能路由映射（model="smart" 时使用）
  model_mapping:
    simple: qwen3.5-flash      # 简单问候 → 经济模型
    coding: qwen3-coder-plus   # 代码任务 → 代码专用
    writing: qwen3.5-plus      # 写作 → 通用模型
    analysis: qwen3.5-plus     # 分析 → 通用模型
    creative: kimi-k2.5        # 创意 → 长文本模型
    complex: qwen3-max         # 复杂推理 → 最强模型
    general: qwen3.5-plus      # 默认 → 通用模型
```

### 任务类型识别关键词

系统通过关键词匹配识别任务类型：

| 任务类型 | 关键词 |
|---------|--------|
| **coding** | "代码"、"python"、"函数"、"算法"、"debug" |
| **writing** | "写"、"文章"、"邮件"、"报告"、"文案" |
| **analysis** | "分析"、"总结"、"对比"、"解释"、"为什么" |
| **creative** | "创意"、"故事"、"设计"、"诗歌"、"想象" |
| **complex** | "推理"、"证明"、"数学"、"逻辑"、"深入" |
| **simple** | "你好"、"hi"、"hello"、"谢谢"、"再见" |

---

## 💡 最佳实践

### 日常使用

```python
# 推荐：始终使用 smart
model = "smart"
```

### 生产环境

```yaml
# 关键业务：指定最强模型
model: "dashscope/qwen3-max"

# 一般业务：智能路由
model: "smart"
```

### 测试对比

```python
# 对比不同模型效果
models_to_test = [
    "smart",
    "dashscope/qwen3.5-plus",
    "dashscope/qwen3-max"
]

for model in models_to_test:
    response = call_llm(model=model, messages=messages)
    evaluate(response)
```

---

## 🎛️ 配置方式

### 配置向导（推荐）

```bash
python3 cli/setup-wizard.py
```

**优点：**
- ✅ 交互式界面
- ✅ 自动验证配置
- ✅ 防止输入错误
- ✅ 自动收集已配置模型

### 手动编辑

```bash
vi ~/.bridge-server/config.yaml
```

**优点：**
- ✅ 灵活定制
- ✅ 批量修改
- ✅ 版本控制

**推荐：** 首次使用配置向导，后续微调手动编辑 config.yaml。

---

## 📝 常见问题

### Q1: smart 模式如何识别任务类型？

系统通过关键词匹配识别任务类型（见上表）。支持中英文关键词。

### Q2: 如何自定义任务类型识别？

修改 `app/router.py` 中的 `TASK_KEYWORDS` 字典：

```python
TASK_KEYWORDS = {
    "coding": ["你的关键词", ...],
    "writing": ["你的关键词", ...],
    # ...
}
```

### Q3: 智能路由失败会怎样？

智能路由失败时，会降级到默认策略：
1. 优先使用 `model_mapping` 中对应任务类型的模型
2. 如果未配置，使用 `general` 默认模型
3. 最后降级到 `qwen3.5-plus`

### Q4: 如何查看路由决策日志？

每个请求都会记录详细的路由日志：

```
⏱️ 性能 | 请求解析：0.82ms
⏱️ 性能 | 路由决策：6.09ms | 任务类型=coding | 模型=dashscope/qwen3-coder-plus
⏱️ 性能 | 总耗时：4689.47ms | LLM 调用：4682.06ms | 其他：7.41ms
```

---

## 🚀 高级功能

### Stream 模式

支持 SSE 流式响应：

```bash
curl -X POST http://localhost:19377/v1/chat/completions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "smart",
    "messages": [...],
    "stream": true
  }'
```

**特性：**
- 每 20 秒发送心跳防止超时
- 支持最长 300 秒超时
- 禁用 Nginx 缓冲

### 自定义路由（JS 沙箱）

允许用户编写自定义路由逻辑：

```yaml
routing:
  strategy: custom
  custom_routing_enabled: true
  custom_route_code: |
    def route(context):
        message = context.get('message', '').lower()
        if 'code' in message:
            return {'model': 'qwen3-coder-plus', 'reason': '代码任务'}
        else:
            return {'model': 'qwen3.5-plus', 'reason': '通用任务'}
```

**安全特性：**
- ✅ 禁止 `import` / `eval` / `exec`
- ✅ 禁止文件系统访问
- ✅ 禁止网络请求
- ✅ 5 秒执行超时
- ✅ 128MB 内存限制

---

## 📊 版本对比

| 功能 | 旧版本 | v2.1 |
|------|--------|------|
| 场景模型配置 | 手动输入模型 ID | 从已配置模型选择 |
| 客户端请求 | 固定模型或默认策略 | 支持 smart 智能路由 |
| 路由透明度 | 日志查看 | 响应中直接返回路由信息 |
| 配置体验 | 易出错 | 防错、引导式 |
| Stream 模式 | ❌ | ✅ |
| 性能追踪 | ❌ | ✅ |

---

**祝您使用愉快！**
