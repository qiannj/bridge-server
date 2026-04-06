# Bridge Server 快速开始指南

**5 分钟完成部署和配置**

---

## 步骤 1: 安装

### 一键安装（推荐）

```bash
curl -fsSL https://example.com/install.sh | bash
```

安装完成后，系统会提示您运行配置向导。

### 手动安装

```bash
# 1. 克隆仓库
git clone https://github.com/your-org/bridge-server.git
cd bridge-server

# 2. 安装依赖
pip3 install -r requirements.txt

# 3. 运行配置向导
python3 setup-wizard.py
```

---

## 步骤 2: 配置向导

运行配置向导：

```bash
bridge-server setup
```

向导会引导您完成：

### 2.1 基础配置

```
【步骤 1/5】基础配置

服务监听地址 [127.0.0.1]: 
服务端口 [8080]: 
是否启用调试模式 [N]: 
```

**建议**：使用默认值即可。

### 2.2 选择模型提供商

```
【步骤 2/5】选择模型提供商

[1] 阿里云百炼 (DashScope)
[2] Moonshot (Kimi)
[3] OpenAI
[4] MiniMax
[5] 全部启用

请选择 [1-5, 可多选]: 
```

**建议**：
- 国内用户：选择 [1] 阿里云百炼
- 需要长文本：选择 [2] Moonshot (Kimi)
- 国际用户：选择 [3] OpenAI

### 2.3 配置 API Key

```
→ 阿里云百炼 (DashScope)
API Key: sk-************************
测试连接... ✅ 连接成功
```

**如何获取 API Key**：
- 阿里云百炼：https://dashscope.console.aliyun.com/apiKey
- Moonshot: https://platform.moonshot.cn/console/api-keys
- OpenAI: https://platform.openai.com/api-keys

### 2.4 选择路由策略

```
【步骤 4/5】选择路由策略

[1] 平衡模式 (Balanced) - 推荐
[2] 成本优先 (Cost-First)
[3] 质量优先 (Quality-First)
[4] 自定义配置

请选择 [1-4]: 
```

**建议**：选择 [1] 平衡模式

### 2.5 预算控制（可选）

```
【步骤 5/5】预算控制（可选）

是否启用预算控制 (y/N): 
每日预算上限 (元) [50]: 
每月预算上限 (元) [1000]: 
```

**建议**：初次使用可跳过，后续需要时再配置。

---

## 步骤 3: 启动服务

```bash
bridge-server start
```

查看服务状态：

```bash
bridge-server status
```

---

## 步骤 4: 测试连接

### 使用 curl 测试

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "你好"}]}'
```

### 使用 Python 测试

```python
from openai import OpenAI

# 配置客户端
client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="your-token"  # 任意值，仅用于兼容
)

# 发送请求
response = client.chat.completions.create(
    model="qwen3.5-plus",
    messages=[
        {"role": "user", "content": "用 Python 写个快速排序"}
    ]
)

print(response.choices[0].message.content)
```

### 使用 Bridge Server CLI 测试

```bash
bridge-server test
```

---

## 步骤 5: 查看路由效果

测试不同类型的请求，观察模型选择：

```bash
# 简单问候 → qwen3.5-flash
bridge-server route-test "你好"

# 代码任务 → qwen3-coder-plus
bridge-server route-test "用 Python 写个快速排序"

# 创意写作 → kimi-k2.5
bridge-server route-test "讲个科幻故事"

# 复杂推理 → qwen3-max
bridge-server route-test "请证明哥德巴赫猜想"
```

查看日志确认路由：

```bash
bridge-server logs | grep "路由决策"
```

---

## 下一步

- [配置指南](CONFIG.md) - 详细配置说明
- [路由策略](ROUTING.md) - 自定义路由规则
- [API 文档](API.md) - API 接口说明
- [监控与日志](MONITORING.md) - 用量统计和监控

---

## 常见问题

### Q: 服务启动失败？

```bash
# 检查端口占用
lsof -i :8080

# 查看日志
bridge-server logs
```

### Q: API Key 无效？

检查配置文件：

```bash
cat ~/.bridge-server/config.yaml | grep api_key
```

### Q: 如何切换模型？

编辑 `~/.bridge-server/config.yaml`，修改 `routing.model_mapping`，然后重启服务：

```bash
bridge-server restart
```

---

*恭喜！Bridge Server 已经就绪。* 🎉
