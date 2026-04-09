# Bridge Server v2.1.0 优化完成报告（简化版）

## 📋 优化需求

1. **场景模型配置优化** - 用户在配置各个场景使用的模型时，从手动输入改为选择已配置好的模型 ID
2. **智能路由支持** - 客户端请求时，只支持 `model: "smart"` 这一个值来启用智能场景路由

---

## ✅ 完成的修改

### 1. 配置向导优化 (`cli/setup-wizard.py`)

**修改内容：**
- `_configure_scenarios()` 方法重构
- 自动收集所有已配置的 Provider 和模型
- 生成完整模型 ID 列表（格式：`provider/model-id`）
- 添加 "smart" 选项作为默认推荐
- 提供友好的选择提示和示例

**用户体验提升：**
- ✅ 防止输入错误（拼写错误、不存在的模型）
- ✅ 一目了然看到所有可用选项
- ✅ 默认推荐 "smart" 智能路由
- ✅ 支持快速回车选择默认值

---

### 2. 路由逻辑增强 (`app/router.py`)

**修改内容：**
- `route_model()` 函数签名扩展，新增 `requested_model` 参数
- **只接受 `"smart"` 这一个值**来启用智能路由
- 其他值（包括不传）使用默认路由策略
- 优先使用配置中的 `model_mapping`

**路由决策流程：**
```
route_model(message, config, requested_model)
    ↓
┌──────────────────────────────────────┐
│   requested_model == "smart"?        │
└──────────────────────────────────────┘
         │                    │
        是                   否
         ↓                    ↓
   启用智能路由          使用默认策略
         ↓                    ↓
   detect_task_type()    routing.strategy
         ↓                    ↓
   匹配 model_mapping    默认策略映射
         ↓                    ↓
    调用模型            调用模型
```

**日志输出改进：**
```python
# 智能路由
logger.info(f"启用智能路由")

# 其他值（忽略）
logger.info(f"忽略未知模型参数：{requested_model}，使用默认路由")

# 路由决策
logger.info(f"路由决策 | 任务类型={task_type} | 模型={full_model_id} | 策略={strategy}")
```

---

### 3. 请求处理更新 (`app/main.py`)

**修改内容：**
- 从请求体中提取 `model` 参数
- 传递给 `route_model()` 函数
- 日志中区分智能路由和默认模式

**代码变更：**
```python
# 获取客户端请求的模型 ID（只支持"smart"）
requested_model = req_dict.get("model", None)

# 路由到合适的模型
if requested_model == "smart":
    logger.info(f"收到请求 | user={...} | text={text[:50]}... | 模式=智能路由")
else:
    logger.info(f"收到请求 | user={...} | text={text[:50]}... | 模式=默认")

selected_model, task_type, reason = route_model(text, config, requested_model)
```

**向后兼容：**
- ✅ 不传 `model` 参数 → 使用默认策略
- ✅ 传其他值（如 `"gpt-4"`）→ 忽略并使用默认策略
- ✅ 传空字符串 → 使用默认策略

---

### 4. 文档更新

#### 4.1 `README.md`
- 简化为两种使用方式：
  - 方式 1: `model: "smart"` (推荐)
  - 方式 2: 不传 model (默认策略)
- **明确说明：`model` 参数只接受 `"smart"` 这一个值**
- 删除了指定具体模型的示例

#### 4.2 `config.yaml.example`
- 添加注释说明 `model` 参数只支持 "smart"
- 说明 `model_mapping` 的用途

#### 4.3 新增 `USAGE-GUIDE-v2.1-SIMPLE.md`
- 简化版使用指南
- 强调"只支持 smart"的设计理念
- 添加 FAQ 解释为什么不能指定模型

---

## 🧪 测试验证

### 语法检查
```bash
✅ python3 -m py_compile cli/setup-wizard.py  # 通过
✅ python3 -m py_compile app/router.py        # 通过
✅ python3 -m py_compile app/main.py          # 通过
```

### 单元测试
```bash
✅ python3 test-v2.1-routing.py
  - 测试 1: smart 模式 - 代码任务 ✅
  - 测试 2: smart 模式 - 简单问候 ✅
  - 测试 3: 其他 model 值会被忽略 ✅
  - 测试 4: 空字符串 model 使用默认路由 ✅
  - 测试 5: 默认策略（不传 model） ✅
  
测试结果：5 通过，0 失败
```

---

## 📊 代码变更统计

| 文件 | 变更行数 | 变更类型 |
|------|----------|----------|
| `cli/setup-wizard.py` | +40 | 功能增强 |
| `app/router.py` | +20 | 功能简化 |
| `app/main.py` | +10 | 功能增强 |
| `config.yaml.example` | +3 | 文档 |
| `README.md` | +20 | 文档简化 |
| `USAGE-GUIDE-v2.1-SIMPLE.md` | +180 | 新增文档 |
| `test-v2.1-routing.py` | -30 | 测试简化 |
| **总计** | **~243 行** | - |

---

## 🎯 设计原则

### 1. 简单明确
- ✅ 只支持 "smart" 一个值，减少用户困惑
- ✅ 不需要记忆多个模型 ID
- ✅ 降低配置复杂度

### 2. 智能优先
- ✅ 让系统自动选择最优模型
- ✅ 避免用户误用昂贵模型
- ✅ 降低成本，提升效果

### 3. 向后兼容
- ✅ 不传 model 参数保持旧行为
- ✅ 传其他值会忽略并记录日志
- ✅ 不影响现有客户端

### 4. 可观测性
- ✅ 日志清晰区分智能路由和默认模式
- ✅ 响应中返回路由决策信息
- ✅ 便于调试和追踪

---

## 🚀 部署建议

### 升级步骤

```bash
# 1. 备份现有配置
cp ~/.bridge-server/config.yaml ~/.bridge-server/config.yaml.bak

# 2. 拉取最新代码
cd /home/pi/.openclaw/workspace/bridge-server-product
git pull origin main

# 3. 重新运行配置向导（可选，推荐）
python3 cli/setup-wizard.py

# 4. 重启服务
docker compose restart
# 或
bridge-server restart

# 5. 验证新版本
curl http://localhost:19377/health
```

### 配置迁移

**旧配置（兼容）：**
```yaml
scenarios:
  coding:
    enabled: true
    model: "qwen3-coder-plus"  # 短名称
```

**新配置（推荐）：**
```yaml
scenarios:
  coding:
    enabled: true
    model: "smart"  # 智能路由
```

---

## 📝 后续优化建议

### 短期（v2.2）
- [ ] 配置向导支持模型预览（价格、上下文长度）
- [ ] 添加模型测试功能（配置前测试响应速度）
- [ ] 支持场景模型权重配置

### 中期（v2.3）
- [ ] 基于历史用量的智能推荐
- [ ] A/B 测试框架（对比不同模型效果）
- [ ] 自定义任务类型识别规则

### 长期（v3.0）
- [ ] 机器学习路由模型（基于反馈优化）
- [ ] 多模型并行调用 + 结果融合
- [ ] 实时成本优化（动态选择性价比最优）

---

## ✅ 验收清单

- [x] 配置向导显示已配置模型列表
- [x] 支持选择 "smart" 智能路由
- [x] 客户端请求支持 `model: "smart"`
- [x] 其他 model 值会被忽略
- [x] 向后兼容（不传 model 参数）
- [x] 日志输出清晰
- [x] 文档完整更新
- [x] 语法检查通过
- [x] 配置示例更新
- [x] 单元测试通过 (5/5)

---

## 🎉 总结

本次优化在**最小改动范围**内实现了：

1. **配置体验提升** - 从手动输入改为选择，防错友好
2. **使用简化** - 只支持 "smart" 一个值，减少困惑
3. **智能路由升级** - 自动化最优选择，降低成本
4. **完整文档支持** - 使用指南、示例、FAQ

**核心理念：** 让 AI 更聪明，让用户更简单！

**状态：** ✅ 完成，测试通过，待部署

---

**版本：** v2.1.0 (简化版)  
**日期：** 2026-04-07  
**测试：** 5/5 通过
