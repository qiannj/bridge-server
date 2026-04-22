# Bridge Server 更新日志

本文件记录 Bridge Server 的所有重要变更。

---

## [Unreleased] - QA

### 🔧 OpenAI 兼容性修复

- ✅ `/v1/models` 和 `/api/models` 增加 `smart` 伪模型，支持 OpenAI 兼容客户端先校验模型目录再发请求。
- ✅ 模型目录返回稳定的 `provider/model-id` 规范 ID，并为不冲突的裸模型名提供兼容别名。
- ✅ `/v1/chat/completions` 显式尊重请求里的 `model` 字段：`smart`/缺省走智能路由，`provider/model-id` 直接调用指定模型。
- ✅ 未知模型和冲突裸模型名返回 400，避免静默路由到其他模型造成 verification 失败。

---

## [v2.2.0] - 2026-04-16

### 🧹 仓库收敛与文档整合

- ✅ 将 `src/bridge_server/runtime.py` 固化为唯一运行时实现
- ✅ 将 `bridge_server.runtime:app` 固化为唯一启动入口，并删除 `app.main:app` / `main_v2*.py` 并行包装层
- ✅ 在主运行时补齐 `/ready`、`/api/models`、`/api/routing`、`/api/usage`、`/api/budget`
- ✅ 删除阶段性脚本、历史总结文档、过期 quickstart 与旧版测试
- ✅ 将仓库文档收敛为 `README / INSTALL / USAGE / CHANGELOG / TODO`
- ✅ 将 bench / verify / security / ops 脚本拆分到 `scripts/` 子目录

### 🏗️ 架构影响

- 活跃代码路径集中到 `src/bridge_server/` 与 `scripts/{ops,bench,verify,security}/`
- 旧版 `app.auth`、`app.router`、`services/*` 和 `app/api/v1` 不再保留
- 外部启动方式统一为 `bridge_server.runtime:app`

---

## [v2.1.0] - 2026-04-07

### 🎯 版本概述

**智能路由简化版本** - 简化模型使用方式，只支持 `model: "smart"` 一个值，降低用户困惑。

### ✨ 新增功能

- ✅ **智能路由简化** - `model` 参数只接受 `"smart"` 一个值
- ✅ **配置向导增强** - 自动收集已配置模型，提供选择界面
- ✅ **Stream 模式支持** - SSE 流式响应 + 20 秒心跳防止超时
- ✅ **性能追踪日志** - 记录请求解析/路由决策/LLM 调用 3 个阶段耗时

### 🔧 主要变更

#### 配置向导 (`cli/setup-wizard.py`)
- ✅ 自动收集所有已配置的 Provider 和模型
- ✅ 生成完整模型 ID 列表（格式：`provider/model-id`）
- ✅ 场景配置只允许选择已配置的具体模型，不再暴露 `smart` 伪模型
- ✅ 首次安装默认采用 `fallback`，隐藏不必要的复杂路由选择

#### 路由逻辑 (`app/router.py`)
- ✅ `route_model()` 支持 `requested_model` 参数
- ✅ 只接受 `"smart"` 启用智能路由
- ✅ 其他值使用默认路由策略（向后兼容）
- ✅ 优先使用配置中的 `model_mapping`

#### 请求处理 (`src/bridge_server/runtime.py`)
- ✅ 支持 `stream: true` 参数
- ✅ 性能追踪日志（3 个阶段）
- ✅ 错误响应返回详细 JSON 信息

### 📦 新增文件

- `USAGE-GUIDE-v2.1.md` - v2.1 完整使用指南
- `USAGE-GUIDE-v2.1-SIMPLE.md` - v2.1 简化版使用指南
- `test-v2.1-routing.py` - 路由单元测试

### 📊 测试结果

- ✅ 语法检查：3/3 通过
- ✅ 单元测试：5/5 通过
- ✅ Stream 模式测试：通过

---

## [v2.0.0] - 2026-04-06

### 🎯 版本概述

**安全加固版本** - 全面的安全审计和修复，增强认证机制。

### 🔐 安全改进

- ✅ **JWT Token 认证** - 支持 JWT 和 API Key 双认证
- ✅ **速率限制** - SlowAPI 限流（30/分钟，500/小时）
- ✅ **CORS 配置** - 可配置跨域策略
- ✅ **错误信息脱敏** - 生产环境不泄露内部细节
- ✅ **日志级别控制** - 支持 LOG_LEVEL 环境变量

### 📦 新增文件

- `app/auth.py` - 认证模块（JWT + API Key）
- `services/sandbox.py` - JS 沙箱（自定义路由）
- `SECURITY-AUDIT-v1.0.0.md` - 安全审计报告

---

## [v1.5.3] - 2026-04-05

### 🎯 版本概述

**依赖安装流程改进版本** - 完善 Python 虚拟环境支持，优化多环境依赖管理。

### 🔧 依赖安装优化

- ✅ **虚拟环境隔离** - 使用 venv 隔离依赖，不污染全局 Python 环境
- ✅ **完整依赖检查** - 预检查 Python、venv、pip，提前发现问题
- ✅ **优先预编译 wheel** - 减少编译依赖，避免 gcc/libffi 缺失
- ✅ **多环境支持** - Linux、macOS、Docker 完整安装指南
- ✅ **CLI 自动激活** - 启动脚本自动激活虚拟环境

### 📦 新增文件

- `check-dependencies.sh` - 依赖检查脚本（8 项检查）
- `DEPENDENCY-INSTALL-GUIDE.md` - 完整依赖安装指南
- `DEPENDENCY-IMPROVEMENTS.md` - 改进总结文档

### 🐛 Bug 修复

- ✅ `install.sh` - 添加虚拟环境支持（+150 行）
- ✅ `docker/Dockerfile` - 使用虚拟环境构建
- ✅ CLI 启动脚本 - 自动激活虚拟环境

---

## [v1.5.2] - 2026-04-05

### 🎯 版本概述

**跨平台适配性修复版本** - 完全移除 root/sudo 权限依赖，支持 Linux、macOS、Docker 三大平台。

### 🔧 跨平台支持

- ✅ **无需 root/sudo 权限** - 所有操作在用户空间完成
- ✅ **支持 Linux、macOS、Docker** - 自动检测运行环境
- ✅ **多平台启动方式** - systemd (Linux) / launchd (macOS) / standalone (通用)
- ✅ **路径配置化** - 支持环境变量自定义所有路径
- ✅ **Docker 非 root 运行** - 容器使用 UID 1000 用户

### 📦 修复文件

- ✅ `install.sh` - 完全重写，移除 sudo，支持多平台
- ✅ `cli/bridge-server.py` - 路径配置化，多平台启动逻辑
- ✅ `cli/setup-wizard.py` - 日志路径用户化
- ✅ `docker/Dockerfile` - 日志和配置目录改为用户目录
- ✅ `docker/docker-compose.yml` - 挂载路径更新

### 📦 新增文档

- `CROSS-PLATFORM-FIXES.md` - 适配性改进方案
- `CROSS-PLATFORM-GUIDE.md` - 跨平台部署指南
- `test-cross-platform.sh` - 自动化测试脚本

### 📊 测试结果

- ✅ 自动化测试：16/16 通过
- ✅ Linux (Ubuntu): 无需 sudo
- ✅ macOS (Ventura): 无需 sudo
- ✅ Docker: 非 root 用户运行

---

## [v1.5.0] - 2026-04-05

### 🎯 版本概述

Provider Registry 重大更新，完成对全球 15 家 AI 提供商的深度验证和配置更新。

### ✨ 新增功能

- ✅ 验证并更新 **6 家高优先级 Provider**
- ✅ 新增 **11 个最新模型** (2025-2026 年发布)
- ✅ 添加 **验证状态标记**，便于后续维护

### 🔧 主要变更

#### OpenAI (美国)
- ❌ 移除 `gpt-4-turbo` (已淘汰)
- ❌ 移除 `o1-preview` (已升级为正式版)
- ✅ 新增 `o1` - 强化推理模型正式版 (200K 上下文)
- ✅ 新增 `o1-mini` - o1 轻量版 (128K 上下文)
- 💰 价格修正：gpt-4o 系列价格更新为市场价格

#### Anthropic (美国)
- ❌ 移除 `claude-3-5-sonnet-20241022` (已弃用)
- ❌ 移除 `claude-3-5-haiku-20241022` (已弃用)
- ❌ 移除 `claude-3-opus-20240229` (已弃用)
- ✅ 新增 `claude-sonnet-4-6` - 2026 年 2 月新版
- ✅ 新增 `claude-opus-4-6` - 2026 年 2 月新旗舰
- ✅ 新增 `claude-haiku-4-5` - 2025 年 11 月轻量版

#### DeepSeek (中国)
- ✅ 更新 `deepseek-chat` 标注为 V4 版本
- ✅ 新增 `deepseek-reasoner` (R1) - 强化推理模型
- 💰 价格修正：修正为实际市场价格
- 📝 上下文长度：32K → 64K

#### 阿里云百炼 (中国)
- ❌ 移除 `qwen3-coder-plus` (未找到官方信息)
- ✅ 新增 `qwen3.6-plus` - 2026 年 4 月新版本
- 💰 价格修正：修正为官方定价

#### Moonshot (Kimi)
- ✅ 新增 `kimi-k2.5` - 2026 年 1 月新版
- 💰 价格修正：修正为官方定价

#### MiniMax
- ✅ 新增 `MiniMax-M2.5` - 2025 年 10 月新版
- 💰 价格修正：修正为官方定价

---

## [v1.4.0] - 2026-04-04

### 🎯 版本概述

系统稳定性增强和性能优化版本。

### ✨ 新增功能

- ✅ Docker Compose 支持（负载均衡配置）
- ✅ 系统服务集成（systemd）
- ✅ 批量测试工具

### 🔧 主要变更

- 🐛 修复多 provider 并发请求时的竞态条件
- 🐛 修复预算统计跨天计算错误
- ⚡ 优化路由决策速度（减少 30% 延迟）
- 📝 改进日志格式，便于排查问题

### 📦 新增文件

- `docker-compose.lb.yml` - 负载均衡配置
- `systemd/bridge-server.service` - 系统服务配置
- `tests/batch-test.py` - 批量测试工具

---

## [v1.3.0] - 2026-04-04

### 🎯 版本概述

安全审计和预算控制增强版本。

### ✨ 新增功能

- ✅ 预算控制系统（每日/每月上限）
- ✅ 用量统计和告警
- ✅ 安全审计日志
- ✅ 超出预算自动降级

### 🔧 主要变更

- 🔐 增强 API Token 认证机制
- 🔐 添加请求速率限制
- 🔐 敏感配置加密存储
- 📊 改进用量统计精度

### 📦 新增文件

- `services/budget.py` - 预算控制服务
- `services/audit.py` - 审计日志服务
- `SECURITY-AUDIT.md` - 安全审计文档
- `SECURITY-SUMMARY.md` - 安全摘要

---

## [v1.2.1] - 2026-04-04

### 🎯 版本概述

Bug 修复版本。

### 🐛 Bug 修复

- 🐛 修复配置向导中 API Key 验证逻辑错误
- 🐛 修复日志文件路径权限问题
- 🐛 修复 CLI 状态查询显示异常

### 🔧 改进

- 📝 改进错误提示信息
- 📝 优化安装脚本兼容性

---

## [v1.2.0] - 2026-04-04

### 🎯 版本概述

命令行工具增强版本。

### ✨ 新增功能

- ✅ 完整的 CLI 工具集
- ✅ 交互式配置向导
- ✅ 一键安装脚本
- ✅ 服务管理命令（start/stop/restart/status）

### 🔧 主要变更

- 📦 重构 CLI 模块结构
- 📝 改进用户安装体验
- 📝 添加配置示例文件

### 📦 新增文件

- `cli/` - 命令行工具目录
- `install.sh` - 一键安装脚本
- `setup-wizard.py` - 配置向导
- `.env.example` - 环境变量示例

---

## [v1.1.0] - 2026-04-04

### 🎯 版本概述

核心路由功能完善版本。

### ✨ 新增功能

- ✅ 三种路由策略（平衡/成本优先/质量优先）
- ✅ 任务类型自动识别
- ✅ 模型降级机制
- ✅ OpenAI 兼容接口

### 🔧 主要变更

- ⚡ 优化路由决策算法
- 📝 改进模型选择逻辑
- 📊 添加路由决策日志

---

## [v1.0.0] - 2026-04-04

### 🎯 版本概述

首个公开发布版本。

### ✨ 核心功能

- ✅ FastAPI 服务框架
- ✅ 多 Provider 支持（阿里云、Moonshot、OpenAI、MiniMax）
- ✅ 基础认证机制
- ✅ 基础路由逻辑
- ✅ 产品文档

### 📦 核心文件

- `app/main.py` - FastAPI 入口
- `app/auth.py` - 认证模块
- `app/router.py` - 模型路由逻辑
- `config.yaml.example` - 配置模板
- `requirements.txt` - Python 依赖
- `README.md` - 产品文档

---

## 版本命名规则

- **主版本号 (Major)**: 架构级变更或不兼容更新
- **次版本号 (Minor)**: 新功能添加，向后兼容
- **修订号 (Patch)**: Bug 修复和小幅改进

## 升级建议

### 从 v1.0/v1.1 升级
建议直接升级到 v2.1.0，获得完整功能。

### 从 v1.2/v1.3 升级
- 备份配置文件 `~/.bridge-server/config.yaml`
- 更新 provider registry 配置
- 重新测试 API Key 连接

### 从 v1.4/v1.5 升级
- 无破坏性变更
- 直接替换文件即可

### 从 v2.0 升级
- 推荐升级到 v2.1.0 获得 Stream 模式支持
- 重新运行配置向导更新模型列表

---

*最后更新：2026-04-09*
