# OpenClaw ↔ Bridge Server 回复结构问题分析

日期：2026-04-22
分支：`qa`
范围：先分析问题并补日志，不急于继续改兼容逻辑

---

## 结论摘要

当前问题**不能简单归因为单一适配 bug**，更像是：

1. 上游 `MiniMax-M2.5` / `smart` 链路会在不同 prompt、场景、轮次下输出**多种不同的伪工具调用格式**。
2. OpenClaw 当前会把这些非标准格式直接当作普通文本保存和展示。
3. Bridge Server 之前虽然已经收口了几种格式，但**缺少系统化的“原始结构 vs 归一化后结构”日志**，导致定位时要靠人工复现，证据链不完整。

因此这次先做两件事：

- **确认现有证据**：OpenClaw 确实收到过非标准结构原文。
- **补日志能力**：Bridge Server 后续能记录每次响应的结构摘要，便于对照 request_id / trace_id 排查。

---

## 已确认的事实

### 1. OpenClaw 实际保存过非标准工具调用原文

OpenClaw 会话文件：

- `/home/pi/.openclaw/agents/main/sessions/95488f66-0d3f-438e-9850-6ce46855cb65.jsonl`

其中已确认 assistant 消息中存在原文：

```text
<minimax:tool_call>
<invoke name="lark-doc">
<parameter name="command">docs +search 花费 支出 账单</parameter>
</invoke>
</minimax:tool_call>
```

对应会话记录位置包括：

- line 6
- line 10
- line 14

这说明至少在这些回合里，OpenClaw 看到的并不是结构化 `tool_calls`，而是**纯文本里的标签格式**。

### 2. OpenClaw 现有日志能力偏弱

可见日志文件：

- `/home/pi/.openclaw/logs/commands.log`

该文件目前只记录会话启动一类动作，**不包含模型原始回复结构**。

换句话说：

- OpenClaw 侧没有足够强的“回复结构日志”
- 真正能拿到证据的是 session jsonl 存档
- 但 session jsonl 只适合事后排查，不适合服务端实时定位

### 3. Bridge Server 远端近期服务状态正常

远端：`103.143.81.95:19377`

近期检查结果：

- `/health` 返回 `healthy`
- `/v1/models` 包含 `smart`
- 日志中可见 `/v1/chat/completions` 正常 200 返回
- 没有大面积持续性 500
- `smart` 和 `scnet/MiniMax-M2.5` 路径均出现过正常成功请求

因此：

> 当前问题不是“服务不可用”，也不是老的“smart 不在 /v1/models”那类目录问题。

### 4. 上游输出结构确实存在漂移

已复现/观测到的非标准结构至少包括：

1. `minimax:tool_call + invoke + parameter`
2. `tool_code` 代码块风格
3. `<tool name="..."><param ...>` XML 风格
4. 直接返回标准 `tool_calls`

这意味着：

> 同一条兼容链路并不会稳定只输出一种格式。

所以如果用户体感是“怎么感觉还是有问题”，这是合理的：

- 某些请求已经被适配成功
- 某些请求可能仍会落到新的变体
- 如果日志不够，就很难判断究竟是哪一层出了偏差

---

## 这次新增的日志能力

本次在：

- `src/bridge_server/providers/base.py`

新增了**响应结构摘要日志**，目标不是打印全部回复正文，而是记录：

- `finish_reason`
- `content_preview`
- `content_length`
- `structure_flags`
- `tool_call_count`
- `tool_names`
- `has_reasoning`
- `reasoning_preview`

并且同时记录：

- `response_structure_before`
- `response_structure_after`

也就是：

- 上游原始结构摘要
- 归一化后的结构摘要

### 结构标记（flags）

当前会识别的特殊结构标记包括：

- `minimax_tool_call`
- `tool_call_tag`
- `invoke_tag`
- `tool_code_block`
- `tool_name_tag`
- `tool_param_tag`

### 记录位置

日志事件名：

- `provider_response_structure`

记录阶段：

- `provider_stage=response`
- `provider_stage=stream_chunk`

这样后续排查时可以直接在 `server.log` 里用：

- `request_id`
- `trace_id`
- `provider_response_structure`

把异常回复结构捞出来。

---

## 现阶段判断

### 高概率根因

#### 根因 A：上游模型输出格式不稳定
同一个 provider / model / smart 路由，在不同 prompt 和不同轮次，可能输出不同模板。

这是当前最像的根因。

### 中概率根因

#### 根因 B：`smart` 路由场景影响上游输出模板
已观察到：

- `task_type` 有时是 `search`
- 有时是 `coding`
- 有时是 `direct`

不同场景提示词可能改变上游模型的工具表达方式。

### 次一级根因

#### 根因 C：OpenClaw 对标准 `tool_calls` 之外的过渡形态不兼容
即使服务端返回内容中“同时存在解释文字 + 工具调用痕迹”，OpenClaw 仍可能把它当普通文本处理。

---

## 当前不建议直接做的事

在没有拿到更多最近异常样本前，**不建议继续盲补新的解析规则**。

原因：

1. 已知格式已经不止一种
2. 上游有漂移特征
3. 再继续纯靠猜测补解析，容易修偏

这次优先补日志，是为了让下一次异常能拿到**完整证据链**。

---

## 建议的下一步排查顺序

### Step 1
先把当前日志增强版本部署到测试环境/远端。

### Step 2
让用户再次通过 OpenClaw 触发真实问题。

### Step 3
同时抓三类证据：

1. OpenClaw 侧会话 jsonl
2. Bridge Server `server.log` 中对应 `request_id/trace_id`
3. 是否出现 `provider_response_structure` 日志事件

### Step 4
对比：

- OpenClaw 实际收到的文本/结构
- Bridge Server 原始上游结构摘要
- Bridge Server 归一化后结构摘要

如果三者仍不一致，再决定下一刀应补在哪：

- 继续扩展服务端适配器
- 调整 `smart` 路由目标
- 或者针对 OpenClaw 客户端做兼容侧处理

---

## 本次改动说明

本次**不是兼容逻辑大改**，而是为下一轮定位补了“结构证据日志”。

目标：

> 以后再出现“感觉还是有问题”，不再靠猜，而是靠日志里的结构摘要精确对比。

---

## 本地验证

已通过：

- `tests/test_provider_tool_call_adapter.py`
- `tests/test_runtime_routing.py`

如需上线前完整回归，可继续跑：

```bash
source .venv/bin/activate
python -m pytest tests -q
```

---

## 备注

OpenClaw 现有直接日志不足，真正有价值的证据源是：

- `~/.openclaw/agents/main/sessions/*.jsonl`

后续如果要增强客户端侧排查能力，可以再单独研究：

- 是否在 OpenClaw 插件层增加“原始 assistant 回复结构日志”
- 是否把工具调用解析前的 payload 写入独立调试日志
