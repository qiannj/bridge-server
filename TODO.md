# Bridge Server 开发待办清单

本文档列出 Bridge Server 计划实现的功能，按优先级排序。

**最后更新**: 2026-04-09（文档清理后）

---

## 📊 文档清理总结

本次清理整合了以下文档：

| 类别 | 清理前 | 清理后 | 说明 |
|------|--------|--------|------|
| CHANGELOG | 3 个 | 1 个 | 整合为 `CHANGELOG.md` |
| USAGE-GUIDE | 2 个 | 1 个 | 整合为 `USAGE.md` |
| INSTALL | 3 个 | 1 个 | 整合为 `INSTALL.md` |
| SECURITY | 5 个 | 0 个 | 已整合到 `docs/SECURITY.md`（待完成） |
| docs-archive | 31 个 | 31 个 | 移动到 `docs-archive-history/` |
| tests/reports | 4 个 | 0 个 | 移动到 `tests/history/` |

**保留的核心文档**:
- `README.md` - 产品概述
- `CHANGELOG.md` - 更新日志
- `USAGE.md` - 使用指南
- `INSTALL.md` - 安装指南
- `TODO.md` - 待办清单（本文档）
- `config.yaml.example` - 配置模板
- `.env.example` - 环境变量模板

---

## 🔴 高优先级 (P0)

### 1. 命令行工具 (CLI)

**状态**: ❌ 未实现  
**需求**: README 中描述但实际不存在  
**影响**: 用户体验差距最大

**计划功能**:
```bash
# 服务管理
bridge-server start          # 启动服务
bridge-server stop           # 停止服务
bridge-server restart        # 重启服务
bridge-server status         # 查看状态
bridge-server logs           # 查看日志

# 用量查询
bridge-server usage --today  # 今日用量
bridge-server usage --week   # 本周用量
bridge-server usage --month  # 本月用量

# 路由测试
bridge-server routing-test "用 Python 写个快速排序"

# 配置管理
bridge-server setup          # 配置向导（已有 cli/setup-wizard.py）
bridge-server backup         # 备份配置
bridge-server restore        # 恢复配置
```

**实现方案**:
- 使用 `click` 或 `argparse` 库
- 封装现有的 API 调用
- 集成 `cli/setup-wizard.py`

**预计工作量**: 2-3 天

---

### 2. 预算告警通知

**状态**: ⚠️ 部分实现（只有检查逻辑，无通知）  
**需求**: 用户在 config.yaml 中配置预算后，超预算时自动通知

**计划功能**:
```yaml
budget:
  enabled: true
  daily_limit: 50
  monthly_limit: 1000
  over_budget_action: downgrade  # downgrade, stop, alert
  
  # 通知配置（待实现）
  notifications:
    50%:
      - email: admin@example.com
    80%:
      - email: admin@example.com
      - sms: +86-138-xxxx-xxxx
    90%:
      - email: admin@example.com
      - sms: +86-138-xxxx-xxxx
      - webhook: https://hooks.slack.com/xxx
    100%:
      - action: stop  # 自动停止服务
```

**实现方案**:
- 邮件：使用 `smtplib` 或 SendGrid API
- 短信：使用阿里云短信 API
- Webhook：通用 HTTP POST
- 定时检查：使用 `cron` 或内置调度器

**预计工作量**: 3-4 天

---

### 3. Docker 镜像发布

**状态**: ❌ 未发布  
**需求**: README 中写了 `bridgedev/bridge-server:latest` 但 Docker Hub 上不存在

**计划功能**:
- 构建多架构镜像（linux/amd64, linux/arm64）
- 发布到 Docker Hub
- 自动构建（GitHub Actions）

**Dockerfile 要求**:
- 基于 Python 3.11-slim
- 多阶段构建减小体积
- 健康检查
- 非 root 用户运行

**预计工作量**: 1-2 天

---

## 🟡 中优先级 (P1)

### 4. 多用户权限系统

**状态**: ❌ 未实现  
**需求**: README 中描述了多用户配置，但当前只有单用户模式

**计划功能**:
```yaml
users:
  - name: team-a
    api_key: sk-team-a-xxx
    budget:
      daily: 100
      monthly: 2000
    models:
      allow: [all]
      deny: []
    rate_limit:
      per_minute: 60
      
  - name: team-b
    api_key: sk-team-b-xxx
    budget:
      daily: 50
      monthly: 1000
    models:
      allow: [qwen3.5-flash, qwen3.5-plus]
      deny: [qwen3-max]
```

**实现方案**:
- 用户表：`users` (SQLite/MySQL)
- 中间件：`user_auth.py`
- 关联用量记录到用户 ID

**预计工作量**: 4-5 天

---

### 5. Prometheus 监控

**状态**: ❌ 未实现  
**需求**: config.yaml 中有配置但代码未实现

**计划功能**:
```yaml
metrics:
  enabled: true
  export_prometheus: true
  prometheus_port: 9090
```

**暴露指标**:
- `bridge_server_requests_total` - 总请求数
- `bridge_server_requests_duration_seconds` - 请求耗时
- `bridge_server_tokens_total` - Token 使用量
- `bridge_server_cost_total` - 总成本
- `bridge_server_budget_remaining` - 剩余预算

**实现方案**:
- 使用 `prometheus_client` 库
- 添加 `/metrics` 端点

**预计工作量**: 1-2 天

---

### 6. 安装脚本验证

**状态**: ⚠️ 文件存在但未充分测试  
**文件**: `install.sh`, `install.ps1`

**待办**:
- [ ] 在 Ubuntu 20.04/22.04 测试 `install.sh`
- [ ] 在 macOS 测试 `install.sh`
- [ ] 在 Windows 10/11 测试 `install.ps1`
- [ ] 添加安装日志
- [ ] 添加卸载脚本

**预计工作量**: 2-3 天

---

## 🟢 低优先级 (P2)

### 7. 配置备份/恢复

**状态**: ❌ 未实现  
**需求**: CLI 工具中提到的功能

**计划功能**:
```bash
bridge-server backup    # 备份到 ~/.bridge-server/backups/
bridge-server restore   # 从备份恢复
bridge-server list-backups  # 列出所有备份
```

**实现方案**:
- 备份 `config.yaml` + `.env` + `usage.json`
- 自动压缩为 `.tar.gz`
- 保留最近 10 个备份

**预计工作量**: 0.5-1 天

---

### 8. 响应缓存

**状态**: ❌ 未实现  
**需求**: 优化重复请求的响应速度

**计划功能**:
- 缓存相同请求的响应
- 可配置缓存时间（默认 5 分钟）
- 支持 Redis 后端

**实现方案**:
- 使用 `functools.lru_cache` 或 `redis`
- 缓存 Key: hash(model + messages)

**预计工作量**: 1-2 天

---

### 9. 日志轮转

**状态**: ⚠️ config.yaml 中有配置但未实现  
**配置**:
```yaml
logging:
  level: INFO
  file: /var/log/bridge-server/bridge-server.log
  max_size: 10MB
  backup_count: 5
```

**实现方案**:
- 使用 `logging.handlers.RotatingFileHandler`

**预计工作量**: 0.5 天

---

## 📊 统计

| 优先级 | 功能数量 | 预计工作量 |
|--------|---------|-----------|
| P0 (高) | 3 | 8-9 天 |
| P1 (中) | 3 | 7-10 天 |
| P2 (低) | 3 | 2-3.5 天 |
| **总计** | **9** | **17-22.5 天** |

---

## 📝 备注

1. **优先级调整**: 根据用户反馈动态调整
2. **依赖关系**: 
   - CLI 工具依赖 API 稳定
   - 多用户系统依赖数据库后端
3. **版本规划**:
   - v2.2: CLI 工具 + 预算告警
   - v2.3: Docker 镜像 + Prometheus
   - v3.0: 多用户系统

---

**最后更新**: 2026-04-09  
**维护者**: Bridge Server Team
