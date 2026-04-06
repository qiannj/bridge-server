#!/bin/bash
# Bridge Server 依赖安装检查脚本
# 用法：./check-dependencies.sh

# 不使用 set -e，让检查继续执行

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

CHECKS_PASSED=0
CHECKS_FAILED=0
CHECKS_WARNING=0

# 检查函数
check_pass() {
    echo -e "${GREEN}✅ PASS${NC}: $1"
    ((CHECKS_PASSED++))
}

check_fail() {
    echo -e "${RED}❌ FAIL${NC}: $1"
    ((CHECKS_FAILED++))
}

check_warning() {
    echo -e "${YELLOW}⚠️  WARN${NC}: $1"
    ((CHECKS_WARNING++))
}

check_info() {
    echo -e "${BLUE}ℹ️  INFO${NC}: $1"
}

echo "╔═══════════════════════════════════════════╗"
echo "║  Bridge Server 依赖安装检查               ║"
echo "╚═══════════════════════════════════════════╝"
echo ""

# ============================================
# 检查 Python
# ============================================
echo -e "${YELLOW}[1/6] 检查 Python...${NC}"

if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    check_pass "Python $PYTHON_VERSION 已安装"
    
    # 检查版本是否 >= 3.8
    major=$(echo "$PYTHON_VERSION" | cut -d'.' -f1)
    minor=$(echo "$PYTHON_VERSION" | cut -d'.' -f2)
    
    if [ "$major" -gt 3 ] || ([ "$major" -eq 3 ] && [ "$minor" -ge 8 ]); then
        check_pass "Python 版本 >= 3.8"
    else
        check_fail "Python 版本过低：$PYTHON_VERSION (需要 3.8+)"
    fi
else
    check_fail "Python 3 未安装"
fi

echo ""

# ============================================
# 检查 venv 模块
# ============================================
echo -e "${YELLOW}[2/6] 检查 python3-venv...${NC}"

if python3 -c "import venv" 2>/dev/null; then
    check_pass "python3-venv 模块可用"
else
    check_fail "python3-venv 模块未安装"
    echo ""
    echo "请安装 python3-venv:"
    echo "  Ubuntu/Debian: sudo apt install python3-venv"
    echo "  macOS: brew install python3"
    echo "  CentOS: sudo yum install python3-venv"
fi

echo ""

# ============================================
# 检查 pip
# ============================================
echo -e "${YELLOW}[3/6] 检查 pip...${NC}"

if command -v pip3 &> /dev/null; then
    PIP_VERSION=$(pip3 --version | awk '{print $2}')
    check_pass "pip3 $PIP_VERSION 已安装"
elif python3 -m pip --version &> /dev/null; then
    PIP_VERSION=$(python3 -m pip --version | awk '{print $2}')
    check_pass "pip (python3 -m pip) $PIP_VERSION 可用"
else
    check_fail "pip 未安装"
    echo ""
    echo "请安装 pip:"
    echo "  Ubuntu/Debian: sudo apt install python3-pip"
    echo "  macOS: brew install python3"
    echo "  或：curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py"
    echo "      python3 get-pip.py --user"
fi

echo ""

# ============================================
# 检查编译工具（可选）
# ============================================
echo -e "${YELLOW}[4/6] 检查编译工具（可选）...${NC}"

if command -v gcc &> /dev/null; then
    GCC_VERSION=$(gcc --version | head -1 | awk '{print $NF}')
    check_pass "gcc $GCC_VERSION 已安装"
else
    check_warning "gcc 未安装（某些包可能需要编译）"
fi

if command -v make &> /dev/null; then
    check_pass "make 已安装"
else
    check_warning "make 未安装（某些包可能需要编译）"
fi

echo ""

# ============================================
# 检查 Python 开发头文件（可选）
# ============================================
echo -e "${YELLOW}[5/6] 检查 Python 开发头文件（可选）...${NC}"

if python3 -c "import sysconfig; print(sysconfig.get_path('include'))" &> /dev/null; then
    check_pass "Python 头文件路径可访问"
else
    check_warning "Python 头文件可能缺失（某些包可能需要）"
    echo ""
    echo "如需安装:"
    echo "  Ubuntu/Debian: sudo apt install python3-dev"
    echo "  CentOS: sudo yum install python3-devel"
fi

echo ""

# ============================================
# 检查 libffi（可选）
# ============================================
echo -e "${YELLOW}[6/6] 检查 libffi（可选）...${NC}"

if pkg-config --exists libffi 2>/dev/null || [ -f /usr/include/ffi.h ] || [ -f /usr/local/include/ffi.h ]; then
    check_pass "libffi 已安装"
else
    check_warning "libffi 可能未安装（cryptography 等包需要）"
    echo ""
    echo "如需安装:"
    echo "  Ubuntu/Debian: sudo apt install libffi-dev"
    echo "  macOS: brew install libffi"
    echo "  CentOS: sudo yum install libffi-devel"
fi

echo ""

# ============================================
# 测试结果汇总
# ============================================
echo "╔═══════════════════════════════════════════╗"
echo "║            检查结果汇总                   ║"
echo "╚═══════════════════════════════════════════╝"
echo ""
echo -e "通过：${GREEN}$CHECKS_PASSED${NC}"
echo -e "失败：${RED}$CHECKS_FAILED${NC}"
echo -e "警告：${YELLOW}$CHECKS_WARNING${NC}"
echo ""

if [ $CHECKS_FAILED -eq 0 ]; then
    echo -e "${GREEN}🎉 所有必需依赖已就绪！${NC}"
    echo ""
    echo "接下来可以运行安装脚本:"
    echo "  curl -fsSL https://example.com/install.sh | bash"
    exit 0
else
    echo -e "${RED}⚠️  有 $CHECKS_FAILED 项必需依赖缺失，请先安装${NC}"
    echo ""
    echo "快速安装命令:"
    echo "  Ubuntu/Debian:"
    echo "    sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
    echo ""
    echo "  macOS:"
    echo "    brew install python3"
    echo ""
    echo "  CentOS:"
    echo "    sudo yum install -y python3 python3-venv python3-pip"
    exit 1
fi
