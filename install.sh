#!/bin/bash
# Bridge Server 一键安装脚本 (Linux/macOS)
# 使用方法：curl -fsSL https://example.com/install.sh | bash

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
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

# 检测操作系统
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        OS="linux"
        log_info "检测到 Linux 系统"
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        OS="macos"
        log_info "检测到 macOS 系统"
    else
        log_error "不支持的操作系统：$OSTYPE"
        exit 1
    fi
}

# 检查 Python
check_python() {
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
        log_success "Python 已安装：$PYTHON_VERSION"
    else
        log_error "Python 3 未安装，请先安装 Python 3.8+"
        exit 1
    fi
}

# 检查 pip
check_pip() {
    if command -v pip3 &> /dev/null; then
        log_success "pip3 已安装"
    else
        log_warning "pip3 未安装，尝试安装..."
        if [[ "$OS" == "linux" ]]; then
            sudo apt-get update && sudo apt-get install -y python3-pip || {
                log_error "pip 安装失败，请手动安装"
                exit 1
            }
        else
            log_error "pip 安装失败，请手动安装"
            exit 1
        fi
    fi
}

# 创建目录
create_directories() {
    log_info "创建安装目录..."
    mkdir -p ~/.bridge-server
    mkdir -p ~/.bridge-server/logs
    log_success "目录创建完成"
}

# 下载代码
download_code() {
    INSTALL_DIR="$HOME/.local/opt/bridge-server"
    
    if [ -d "$INSTALL_DIR" ]; then
        log_warning "Bridge Server 已安装，将覆盖安装"
        rm -rf "$INSTALL_DIR"
    fi
    
    log_info "下载 Bridge Server..."
    mkdir -p "$INSTALL_DIR"
    
    # 这里使用本地文件，实际发布时应该从 GitHub 下载
    # curl -fsSL https://github.com/your-org/bridge-server/archive/refs/tags/v1.0.0.tar.gz | tar -xz -C "$INSTALL_DIR" --strip-components=1
    
    # 临时使用本地文件
    cp -r /home/pi/.openclaw/workspace/bridge-server-product/* "$INSTALL_DIR/"
    
    log_success "代码下载完成：$INSTALL_DIR"
}

# 创建虚拟环境
create_venv() {
    log_info "创建 Python 虚拟环境..."
    cd "$INSTALL_DIR"
    python3 -m venv venv
    source venv/bin/activate
    log_success "虚拟环境创建完成"
}

# 安装依赖
install_dependencies() {
    log_info "安装 Python 依赖..."
    pip install --upgrade pip
    pip install -r requirements.txt
    log_success "依赖安装完成"
}

# 创建配置文件
create_config() {
    log_info "创建配置文件..."
    
    if [ ! -f ~/.bridge-server/config.yaml ]; then
        cp "$INSTALL_DIR/config.yaml.example" ~/.bridge-server/config.yaml
        log_success "配置文件已创建：~/.bridge-server/config.yaml"
    else
        log_warning "配置文件已存在，跳过"
    fi
    
    if [ ! -f ~/.bridge-server/.env ]; then
        cp "$INSTALL_DIR/.env.example" ~/.bridge-server/.env
        log_success ".env 文件已创建：~/.bridge-server/.env"
        log_warning "请编辑 ~/.bridge-server/.env，填入你的 API Key"
    else
        log_warning ".env 文件已存在，跳过"
    fi
}

# 安装 CLI 工具
install_cli() {
    log_info "安装 CLI 工具..."
    
    # 创建启动脚本
    cat > "$INSTALL_DIR/bridge-server" << 'EOF'
#!/bin/bash
INSTALL_DIR="$HOME/.local/opt/bridge-server"
source "$INSTALL_DIR/venv/bin/activate"
python3 "$INSTALL_DIR/cli/bridge-server.py" "$@"
EOF
    
    chmod +x "$INSTALL_DIR/bridge-server"
    
    # 添加到 PATH
    if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
        mkdir -p ~/.local/bin
        ln -sf "$INSTALL_DIR/bridge-server" ~/.local/bin/bridge-server
        log_info "已将 CLI 添加到 PATH：~/.local/bin/bridge-server"
        
        # 添加到 shell 配置
        if [[ -f ~/.bashrc ]]; then
            grep -q "$HOME/.local/bin" ~/.bashrc || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
        fi
        if [[ -f ~/.zshrc ]]; then
            grep -q "$HOME/.local/bin" ~/.zshrc || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
        fi
    fi
    
    log_success "CLI 工具安装完成"
}

# 显示完成信息
show_completion_message() {
    echo ""
    log_success "🎉 Bridge Server 安装完成！"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "下一步："
    echo ""
    echo "  1. 配置 API Key"
    echo "     vi ~/.bridge-server/.env"
    echo ""
    echo "  2. 运行配置向导（可选）"
    echo "     bridge-server setup"
    echo ""
    echo "  3. 启动服务"
    echo "     bridge-server start"
    echo ""
    echo "  4. 测试连接"
    echo "     bridge-server test"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    log_info "文档：https://docs.bridge-server.dev"
    log_info "支持：support@example.com"
    echo ""
}

# 主函数
main() {
    echo ""
    echo "🌉 Bridge Server 安装程序"
    echo "版本：v1.0.0 Community Edition"
    echo ""
    
    detect_os
    check_python
    check_pip
    create_directories
    download_code
    create_venv
    install_dependencies
    create_config
    install_cli
    show_completion_message
}

# 运行主函数
main
