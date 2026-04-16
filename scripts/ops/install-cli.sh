#!/bin/bash
# Bridge Server CLI 安装脚本

set -e

echo "正在安装 Bridge Server CLI 工具..."

# 确定安装位置
if [ "$EUID" -eq 0 ]; then
    INSTALL_DIR="/usr/local/bin"
else
    INSTALL_DIR="$HOME/.local/bin"
    mkdir -p $INSTALL_DIR
fi

# 复制 CLI 脚本
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$SCRIPT_DIR/cli/bridge-server.py" "$INSTALL_DIR/bridge-server"
chmod +x "$INSTALL_DIR/bridge-server"

echo ""
echo "✓ CLI 工具已安装到：$INSTALL_DIR/bridge-server"
echo ""

# 检查 PATH
if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
    echo "⚠ 警告：$INSTALL_DIR 不在 PATH 中"
    echo ""
    echo "请添加到 PATH:"
    echo "  export PATH=\$PATH:$INSTALL_DIR"
    echo ""
    echo "或添加到 ~/.bashrc:"
    echo "  echo 'export PATH=\$PATH:$INSTALL_DIR' >> ~/.bashrc"
    echo ""
fi

echo "使用方法:"
echo "  bridge-server --help"
echo "  bridge-server status"
echo "  bridge-server test"
echo ""
