# Bridge Server 更新日志

本文件记录 Bridge Server 从 v1.0 到 v1.5.3 的所有重要变更。

---

## [v1.5.3] - 2026-04-05

### 🎯 版本概述
**依赖安装流程改进版本** - 完善 Python 虚拟环境支持，优化多环境依赖管理。

### 🔥 重大改进：依赖安装优化

**核心特性**:
- ✅ **虚拟环境隔离** - 使用 venv 隔离依赖，不污染全局 Python 环境
- ✅ **完整依赖检查** - 预检查 Python、venv、pip，提前发现问题
- ✅ **优先预编译 wheel** - 减少编译依赖，避免 gcc/libffi 缺失导致的失败
- ✅ **多环境支持** - Linux、macOS、Docker 完整安装指南
- ✅ **CLI 自动激活** - 启动脚本自动激活虚拟环境，无需手动操作

**新增工具**:
- 📄 `check-dependencies.sh` - 依赖检查脚本（自动化测试，8 项检查）
- 📄 `DEPENDENCY-INSTALL-GUIDE.md` - 完整依赖安装指南
- 📄 `DEPENDENCY-IMPROVEMENTS.md` - 改进总结文档

**修复文件**:
- ✅ `install.sh` - 添加虚拟环境支持，改进依赖检查流程（+150 行）
- ✅ `docker/Dockerfile` - 使用虚拟环境构建，优化镜像大小
- ✅ CLI 启动脚本 - 自动激活虚拟环境

**测试结果**:
- ✅ 依赖检查：8/8 通过
- ✅ Python 版本检查：✅
- ✅ venv 模块检查：✅
- ✅ pip 可用性检查：✅
- ✅ 虚拟环境创建：✅
- ✅ 依赖安装（wheel 优先）：✅

---

## [v1.5.2] - 2026-04-05

### 🎯 版本概述
**跨平台适配性修复版本** - 完全移除 root/sudo 权限依赖，支持 Linux、macOS、Docker 三大平台。

### 🔥 重大改进：跨平台支持

**核心特性**:
- ✅ **无需 root/sudo 权限** - 所有操作在用户空间完成
- ✅ **支持 Linux、macOS、Docker** - 自动检测运行环境
- ✅ **多平台启动方式** - systemd (Linux) / launchd (macOS) / standalone (通用)
- ✅ **路径配置化** - 支持环境变量自定义所有路径
- ✅ **Docker 非 root 运行** - 容器使用 UID 1000 用户

**修复文件**:
- ✅ `install.sh` - 完全重写，移除 sudo，支持多平台
- ✅ `cli/bridge-server.py` - 路径配置化，多平台启动逻辑
- ✅ `cli/setup-wizard.py` - 日志路径用户化
- ✅ `docker/Dockerfile` - 日志和配置目录改为用户目录
- ✅ `docker/docker-compose.yml` - 挂载路径更新

**新增文档**:
- 📄 `CROSS-PLATFORM-FIXES.md` - 适配性改进方案
- 📄 `CROSS-PLATFORM-GUIDE.md` - 跨平台部署指南
- 📄 `CROSS-PLATFORM-CHANGES.md` - 修复总结
- 📄 `CROSS-PLATFORM-REPORT.md` - 检查报告
- 📄 `test-cross-platform.sh` - 自动化测试脚本

**测试结果**:
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

### 📊 影响
- 成本计算需更新，实际成本比之前 registry 显示更准确
- 使用已移除模型的用户需迁移到新版本

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
建议直接升级到 v1.5.2，获得完整功能。

### 从 v1.2/v1.3 升级
- 备份配置文件 `~/.bridge-server/config.yaml`
- 更新 provider registry 配置
- 重新测试 API Key 连接

### 从 v1.4 升级
- 无破坏性变更
- 直接替换文件即可

### 从 v1.5.0 升级
- 推荐升级到 v1.5.2 获得跨平台支持
- 特别推荐 macOS 用户升级

---

*最后更新：2026-04-05*
