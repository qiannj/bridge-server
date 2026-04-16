#!/bin/bash
# Tavily 验证脚本启动器

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_ROOT"
python3 "$REPO_ROOT/scripts/verify/verify-with-tavily.py"
