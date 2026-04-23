from __future__ import annotations

from pathlib import Path

from tests.conftest import REPO_ROOT


def test_install_sh_always_links_cli_and_persists_user_bin_path():
    content = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    assert 'ln -sf "$INSTALL_DIR/bridge-server" ~/.local/bin/bridge-server' in content
    assert 'for shell_rc in ~/.profile ~/.bashrc ~/.zshrc; do' in content
    assert 'export PATH="$HOME/.local/bin:$PATH"' in content


def test_install_cli_standalone_always_links_cli_and_persists_user_bin_path():
    content = (REPO_ROOT / "cli" / "install-cli-standalone.sh").read_text(encoding="utf-8")
    assert 'ln -sf "$INSTALL_DIR/bridge-server" ~/.local/bin/bridge-server' in content
    assert 'for shell_rc in ~/.profile ~/.bashrc ~/.zshrc; do' in content
    assert 'export PATH="$HOME/.local/bin:$PATH"' in content


def test_ops_install_cli_uses_repo_root_wrapper_and_persists_path():
    content = (REPO_ROOT / "scripts" / "ops" / "install-cli.sh").read_text(encoding="utf-8")
    assert 'REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"' in content
    assert 'exec "\\$REPO_ROOT/.venv/bin/python" "\\$REPO_ROOT/cli/bridge-server.py" "\\$@"' in content
    assert 'export PATH="$HOME/.local/bin:$PATH"' in content
