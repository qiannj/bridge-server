#!/bin/bash
# Bridge Server CLI 安装脚本

set -e

echo "正在安装 Bridge Server CLI 工具..."

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# 确定安装位置
if [ "$EUID" -eq 0 ]; then
    INSTALL_DIR="/usr/local/bin"
else
    INSTALL_DIR="$HOME/.local/bin"
fi
mkdir -p "$INSTALL_DIR"

# 写入 CLI 启动脚本（不要直接复制裸 Python 文件，避免相对导入失败）
cat > "$INSTALL_DIR/bridge-server" <<EOF
#!/bin/bash
REPO_ROOT="$REPO_ROOT"
if [ -x "\$REPO_ROOT/.venv/bin/python" ]; then
    exec "\$REPO_ROOT/.venv/bin/python" "\$REPO_ROOT/cli/bridge-server.py" "\$@"
elif [ -x "\$REPO_ROOT/venv/bin/python" ]; then
    exec "\$REPO_ROOT/venv/bin/python" "\$REPO_ROOT/cli/bridge-server.py" "\$@"
else
    exec python3 "\$REPO_ROOT/cli/bridge-server.py" "\$@"
fi
EOF
chmod +x "$INSTALL_DIR/bridge-server"

echo ""
echo "✓ CLI 工具已安装到：$INSTALL_DIR/bridge-server"
echo ""

# 永久写入 PATH，避免新 shell 丢失 bridge-server 命令
if [ "$EUID" -ne 0 ]; then
    for shell_rc in "$HOME/.profile" "$HOME/.bashrc" "$HOME/.zshrc"; do
        [ -f "$shell_rc" ] || touch "$shell_rc"
        grep -q 'export PATH="$HOME/.local/bin:$PATH"' "$shell_rc" || \
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$shell_rc"
    done
    export PATH="$HOME/.local/bin:$PATH"
    echo "✓ 已确保 ~/.local/bin 写入 shell 配置并加入当前会话 PATH"
fi

echo "使用方法:"
echo "  bridge-server --help"
echo "  bridge-server status"
echo "  bridge-server test"
echo ""
