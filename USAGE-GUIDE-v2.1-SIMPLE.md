# 🚀 Bridge Server v2.1 快速使用指南

## 📋 核心变更

v2.1 版本简化了模型使用方式：

**`model` 参数只接受一个值：`"smart"`**

- ✅ `model: "smart"` → 启用智能场景路由
- ✅ 不传 model 或其他值 → 使用默认路由策略

---

## 🎯 使用场景

### 场景 1: 配置向导 - 选择场景化模型

运行配置向导时，系统会自动列出所有已配置的模型供选择：

```bash
bridge-server setup
```

**配置界面示例：**

```
🎯 步骤 2/4: 配置场景化模型
------------------------------------------------------------

💻 编程辅助 (代码生成、调试):
  可用模型：smart (智能路由), dashscope/qwen3.5-flash, dashscope/qwen3.5-plus...
  选择模型 (输入 smart 或模型 ID，回车=smart): smart

✍️ 写作创作 (文章、邮件):
  可用模型：smart (智能路由), dashscope/qwen3.5-flash, dashscope/qwen3.5-plus...
  选择模型 (输入 smart 或模型 ID，回车=smart): smart
```

**选项说明：**
- **smart** - 智能路由（默认推荐），系统根据任务类型自动选择最优模型
- **具体模型 ID** - 仅用于场景配置内部使用，客户端不可直接调用

---

### 场景 2: 客户端请求 - 两种方式

#### 方式 A: 智能路由（推荐）⭐

```bash
curl -X POST http://localhost:19377/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "smart",
    "messages": [{"role": "user", "content": "用 Python 写个快速排序"}]
  }'
```

**行为：**
- 系统分析消息内容，识别任务类型（coding/writing/analysis 等）
- 根据配置的场景化模型映射，自动选择最优模型
- 响应中包含路由信息，方便追踪

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

#### 方式 B: 默认策略（不传 model）

```bash
curl -X POST http://localhost:19377/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

**行为：**
- 不传 `model` 参数或传其他值
- 使用配置的 `routing.strategy` 默认策略
- 等同于旧版本行为，保持向后兼容

**注意：** 如果传了非 "smart" 的值（如 `"model": "gpt-4"`），系统会忽略该值并使用默认路由策略，同时记录日志。

---

## 📊 路由决策流程

```
客户端请求
    ↓
检查 model 参数
    ↓
┌─────────────────┬─────────────────┐
│  model="smart"  │  其他值/不传    │
└─────────────────┴─────────────────┘
        ↓                 ↓
   智能场景路由       默认策略
        ↓                 ↓
  识别任务类型        使用 routing.strategy
  匹配场景模型        (balanced/cost-first...)
        ↓                 ↓
    调用模型          调用模型
```

---

## 🔧 配置文件说明

### config.yaml - 场景化模型映射

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

---

## 💡 最佳实践

### 1. 日常使用

```python
# 推荐：始终使用 smart
model = "smart"
```

### 2. 测试对比

```python
# 对比智能路由 vs 默认策略
response_smart = call_llm(model="smart", messages=messages)
response_default = call_llm(messages=messages)  # 不传 model
compare(response_smart, response_default)
```

### 3. 需要指定模型时

**注意：** Bridge Server v2.1 不支持客户端指定模型。如需使用特定模型：

- **方案 A:** 修改 config.yaml 中的 `model_mapping` 配置
- **方案 B:** 直接调用 Provider 的原生 API（绕过 Bridge Server）

---

## 🎛️ 配置向导 vs 手动配置

| 方式 | 优点 | 适用场景 |
|------|------|----------|
| **配置向导** | 交互式、自动验证、防错 | 首次配置、修改场景模型 |
| **手动编辑** | 灵活、批量修改、版本控制 | 高级用户、自动化部署 |

**推荐：** 首次使用配置向导，后续微调手动编辑 config.yaml。

---

## 📝 常见问题

### Q1: smart 模式如何识别任务类型？

系统通过关键词匹配识别：
- **coding**: "代码"、"python"、"函数"、"算法"等
- **writing**: "写"、"文章"、"邮件"、"报告"等
- **analysis**: "分析"、"总结"、"对比"、"解释"等
- **creative**: "创意"、"故事"、"设计"、"诗歌"等
- **complex**: "推理"、"证明"、"数学"、"逻辑"等
- **simple**: "你好"、"hi"、"谢谢"等

### Q2: 为什么不能指定具体模型？

Bridge Server 的设计理念是**让系统自动选择最优模型**，而不是让用户手动选择。这样做的好处：

- ✅ 降低成本 - 简单任务不会误用昂贵模型
- ✅ 提升效果 - 专业任务自动使用专用模型
- ✅ 减少配置 - 用户无需了解每个模型的特点

如需指定模型，建议直接调用 Provider 的原生 API。

### Q3: 如何自定义任务类型识别？

修改 `app/router.py` 中的 `TASK_KEYWORDS` 字典：

```python
TASK_KEYWORDS = {
    "coding": ["你的关键词", ...],
    "writing": ["你的关键词", ...],
    # ...
}
```

### Q4: 智能路由失败会怎样？

智能路由失败时，会降级到默认策略：
1. 优先使用 `model_mapping` 中对应任务类型的模型
2. 如果未配置，使用 `general` 默认模型
3. 最后降级到 `qwen3.5-plus`

---

## 🎉 总结

**v2.1 核心改进：**

| 功能 | 旧版本 | v2.1 |
|------|--------|------|
| 场景模型配置 | 手动输入模型 ID | 从已配置模型选择 |
| 客户端请求 | 多种模式 | 仅支持 "smart" |
| 路由透明度 | 日志查看 | 响应中直接返回路由信息 |
| 配置体验 | 易出错 | 防错、引导式 |

**设计理念：**
- **简单明确** - 只支持 "smart"，减少用户困惑
- **智能优先** - 让系统自动选择最优模型
- **成本优化** - 避免用户误用昂贵模型

**推荐使用方式：**
- 日常使用：`model: "smart"` - 让系统自动选择
- 遗留兼容：不传 model - 保持旧行为

---

**祝您使用愉快！** 🎊
