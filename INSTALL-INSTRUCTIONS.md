# Bridge Server 安装说明

**版本**: v1.5.3  
**最后更新**: 2026-04-05

---

## ⚠️ 重要提示

**Bridge Server 是 Python 项目，不是 Node.js 项目！**

- ✅ 使用 `pip install` 安装依赖
- ✅ 使用 `requirements.txt` 管理依赖
- ❌ **不使用** `npm install`
- ❌ **没有** `package.json` 文件

---

## 📦 安装方式

### 方式 1: 从 tar.gz 安装包（推荐）

```bash
# 1. 解压安装包
tar -xzf bridge-server-v1.5.3.tar.gz
cd bridge-server-product

# 2. 运行安装脚本（自动检测本地源码）
./install.sh

# 3. 添加 CLI 到 PATH
export PATH="$HOME/.local/bin:$PATH"

# 4. 运行配置向导
bridge-server setup

# 5. 启动服务
bridge-server start
```

**说明**:
- ✅ 解压后的目录名是 `bridge-server-product/`
- ✅ 安装脚本会自动检测并使用本地源代码
- ✅ 无需从 GitHub 重新下载

---

### 方式 2: 一键安装（从 GitHub）

```bash
# 直接从 GitHub 下载安装
curl -fsSL https://example.com/install.sh | bash
```

**说明**:
- ✅ 自动从 GitHub 下载最新代码
- ✅ 适合首次安装
- ⚠️ 需要网络连接

---

### 方式 3: Docker 安装

```bash
# 1. 解压安装包
tar -xzf bridge-server-v1.5.3.tar.gz
cd bridge-server-product

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入 API Keys

# 3. 构建和启动
docker-compose -f docker/docker-compose.yml up -d

# 4. 查看状态
docker-compose ps

# 5. 测试连接
curl http://localhost:19377/health
```

---

## 🔍 目录结构说明

### tar.gz 安装包解压后

```
bridge-server-product/          ← 解压后的根目录
├── install.sh                  ← 安装脚本
├── requirements.txt            ← Python 依赖
├── app/                        ← 应用代码
├── cli/                        ← CLI 工具
├── docker/                     ← Docker 配置
└── ...
```

### 安装后的目录结构

```
~/.local/opt/bridge-server/     ← 安装目录
└── src/                        ← 源代码
    ├── app/
    ├── cli/
    ├── requirements.txt
    └── ...

~/.local/bin/
└── bridge-server               ← CLI 工具

~/.bridge-server/
└── config.yaml                 ← 配置文件
```

---

## 🐛 常见问题

### 问题 1: 找不到 package.json

**症状**:
```
npm ERR! code ENOENT
npm ERR! syscall open
npm ERR! path /path/to/package.json
npm ERR! errno -2
```

**原因**: Bridge Server 是 **Python 项目**，不是 Node.js 项目。

**解决**:
```bash
# ✅ 正确的方式：使用 Python 安装
./install.sh

# 或者手动安装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

### 问题 2: 目录名不匹配

**症状**:
```
mv: cannot stat 'bridge-server-main': No such file or directory
```

**原因**: 从 tar.gz 解压后，目录名是 `bridge-server-product`，不是 `bridge-server-main`。

**解决**:
```bash
# ✅ 方法 1: 使用本地安装模式（自动检测）
cd bridge-server-product
./install.sh
# 安装脚本会自动检测并使用本地源代码

# ✅ 方法 2: 从 GitHub 下载安装
curl -fsSL https://example.com/install.sh | bash
```

---

### 问题 3: python3-venv 未安装

**症状**:
```
ModuleNotFoundError: No module named 'venv'
```

**解决**:
```bash
# Ubuntu/Debian
sudo apt install python3-venv

# macOS
brew install python3

# CentOS
sudo yum install python3-venv
```

---

### 问题 4: pip 未安装

**症状**:
```
pip3: command not found
```

**解决**:
```bash
# Ubuntu/Debian
sudo apt install python3-pip

# macOS
brew install python3

# 或使用 get-pip.py
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
python3 get-pip.py --user
```

---

## 📋 安装检查清单

在安装之前，请确保：

- [ ] Python 3.8+ 已安装
- [ ] python3-venv 模块可用
- [ ] pip3 或 python3 -m pip 可用
- [ ] 解压了 bridge-server-v1.5.3.tar.gz
- [ ] 进入了 bridge-server-product 目录

**快速检查**:
```bash
# 检查 Python
python3 --version

# 检查 venv
python3 -c "import venv"

# 检查 pip
pip3 --version

# 检查源码
ls requirements.txt app/ cli/
```

---

## 🚀 安装后验证

```bash
# 1. 添加 CLI 到 PATH
export PATH="$HOME/.local/bin:$PATH"

# 2. 查看 CLI 版本
bridge-server --version

# 3. 查看服务状态
bridge-server status

# 4. 测试连接
bridge-server test
```

---

## 📚 相关文档

- [依赖安装指南](DEPENDENCY-INSTALL-GUIDE.md) - 详细依赖说明
- [跨平台部署指南](CROSS-PLATFORM-GUIDE.md) - 多平台安装
- [快速开始](docs/QUICKSTART.md) - 使用指南

---

## 💡 提示

1. **本地安装 vs 在线安装**:
   - 如果你有 tar.gz 安装包，使用**本地安装模式**（更快）
   - 如果没有，使用**在线安装模式**（从 GitHub 下载）

2. **虚拟环境**:
   - 安装脚本会自动创建虚拟环境
   - CLI 会自动激活虚拟环境
   - 无需手动操作

3. **目录名**:
   - tar.gz 解压后：`bridge-server-product/`
   - GitHub ZIP 下载：`bridge-server-main/`
   - 安装脚本会自动处理这两种情况

---

*最后更新：2026-04-05*
