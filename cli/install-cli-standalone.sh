#!/bin/bash
# Bridge Server CLI 独立安装脚本
# 用于创建独立的 CLI 虚拟环境，与主服务隔离

set -e

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(dirname "$SCRIPT_DIR")"

echo ""
echo "🌉 Bridge Server CLI 独立安装程序"
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    log_error "Python 3 未安装"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
log_success "Python 已安装：$PYTHON_VERSION"

# 创建独立虚拟环境
log_info "创建 CLI 独立虚拟环境..."
cd "$SCRIPT_DIR"

if [ -d "venv-cli" ]; then
    log_warning "检测到已存在的 venv-cli，将重新创建"
    rm -rf venv-cli
fi

python3 -m venv venv-cli
log_success "虚拟环境创建完成：$SCRIPT_DIR/venv-cli"

# 激活虚拟环境
source venv-cli/bin/activate

# 安装依赖
log_info "安装 CLI 依赖..."
pip install --upgrade pip
pip install -r requirements.txt
log_success "依赖安装完成"

# 创建启动脚本
log_info "创建 CLI 启动脚本..."

cat > "$INSTALL_DIR/bridge-server" << EOF
#!/bin/bash
# Bridge Server CLI 启动脚本
# 自动检测并使用独立的 CLI 虚拟环境

SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
CLI_DIR="\$SCRIPT_DIR/cli"

# 优先使用独立虚拟环境
if [ -f "\$CLI_DIR/venv-cli/bin/python" ]; then
    "\$CLI_DIR/venv-cli/bin/python" "\$CLI_DIR/bridge-server.py" "\$@"
else
    # 回退到系统 Python
    python3 "\$CLI_DIR/bridge-server.py" "\$@"
fi
EOF

chmod +x "$INSTALL_DIR/bridge-server"
log_success "启动脚本创建完成：$INSTALL_DIR/bridge-server"

# 添加到 PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    log_info "将 CLI 添加到 PATH..."
    mkdir -p ~/.local/bin
    ln -sf "$INSTALL_DIR/bridge-server" ~/.local/bin/bridge-server
    
    # 添加到 shell 配置
    if [[ -f ~/.bashrc ]]; then
        grep -q "$HOME/.local/bin" ~/.bashrc || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
    fi
    if [[ -f ~/.zshrc ]]; then
        grep -q "$HOME/.local/bin" ~/.zshrc || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
    fi
    
    log_success "CLI 已添加到 PATH：~/.local/bin/bridge-server"
    log_info "请执行 'source ~/.bashrc' 或 'source ~/.zshrc' 使配置生效"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
log_success "🎉 CLI 独立安装完成！"
echo ""
echo "使用方法:"
echo ""
echo "  bridge-server status          # 查看服务状态"
echo "  bridge-server test            # 测试连接"
echo "  bridge-server usage --week    # 查看本周用量"
echo "  bridge-server help            # 显示帮助"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
