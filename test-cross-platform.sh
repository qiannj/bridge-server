#!/bin/bash
# Bridge Server 跨平台适配性测试脚本
# 用法：./test-cross-platform.sh

# 不使用 set -e，让测试继续执行

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

TESTS_PASSED=0
TESTS_FAILED=0

# 测试函数
test_pass() {
    echo -e "${GREEN}✅ PASS${NC}: $1"
    ((TESTS_PASSED++))
}

test_fail() {
    echo -e "${RED}❌ FAIL${NC}: $1"
    ((TESTS_FAILED++))
}

test_info() {
    echo -e "${BLUE}ℹ️  INFO${NC}: $1"
}

echo "╔═══════════════════════════════════════════╗"
echo "║  Bridge Server 跨平台适配性测试           ║"
echo "╚═══════════════════════════════════════════╝"
echo ""

# ============================================
# 测试 1: 路径配置检查
# ============================================
echo -e "${YELLOW}[1/6] 检查路径配置...${NC}"

# 检查 install.sh 中是否有绝对路径
if grep -q '"/opt/bridge-server"' install.sh || \
   grep -q '"/var/log/bridge-server"' install.sh || \
   grep -q '"/usr/local/bin"' install.sh; then
    test_fail "install.sh 包含系统级绝对路径"
else
    test_pass "install.sh 路径配置正确"
fi

# 检查 cli/bridge-server.py 中是否有绝对路径
if grep -q '"/var/log/bridge-server"' cli/bridge-server.py || \
   grep -q '"/opt/bridge-server"' cli/bridge-server.py; then
    test_fail "cli/bridge-server.py 包含系统级绝对路径"
else
    test_pass "cli/bridge-server.py 路径配置正确"
fi

# 检查 cli/setup-wizard.py 中是否有绝对路径
if grep -q "'/var/log/bridge-server" cli/setup-wizard.py; then
    test_fail "cli/setup-wizard.py 包含系统级绝对路径"
else
    test_pass "cli/setup-wizard.py 路径配置正确"
fi

echo ""

# ============================================
# 测试 2: sudo 权限检查
# ============================================
echo -e "${YELLOW}[2/6] 检查 sudo 使用情况...${NC}"

# 检查 install.sh 中是否有 sudo 命令
if grep -q "sudo mkdir" install.sh || \
   grep -q "sudo tee /etc" install.sh || \
   grep -q "sudo chmod" install.sh; then
    test_fail "install.sh 包含 sudo 命令"
else
    test_pass "install.sh 无需 sudo 权限"
fi

echo ""

# ============================================
# 测试 3: 多平台支持检查
# ============================================
echo -e "${YELLOW}[3/6] 检查多平台支持...${NC}"

# 检查 systemd 支持
if grep -q "systemctl --user" install.sh && \
   grep -q "systemd/user" install.sh; then
    test_pass "支持 Linux systemd 用户服务"
else
    test_fail "缺少 Linux systemd 用户服务支持"
fi

# 检查 launchd 支持
if grep -q "launchctl" install.sh && \
   grep -q "LaunchAgents" install.sh; then
    test_pass "支持 macOS launchd 用户代理"
else
    test_fail "缺少 macOS launchd 用户代理支持"
fi

# 检查 standalone 支持
if grep -q "nohup" install.sh && \
   grep -q "uvicorn app.main:app" install.sh; then
    test_pass "支持通用后台进程模式"
else
    test_fail "缺少通用后台进程模式支持"
fi

echo ""

# ============================================
# 测试 4: Docker 配置检查
# ============================================
echo -e "${YELLOW}[4/6] 检查 Docker 配置...${NC}"

# 检查 Dockerfile 是否使用非 root 用户
if grep -q "USER bridge" docker/Dockerfile; then
    test_pass "Dockerfile 使用非 root 用户"
else
    test_fail "Dockerfile 未使用非 root 用户"
fi

# 检查 Dockerfile 路径是否为用户目录
if grep -q "/home/bridge/.local" docker/Dockerfile; then
    test_pass "Dockerfile 使用用户目录"
else
    test_fail "Dockerfile 路径配置不正确"
fi

# 检查 docker-compose.yml 挂载路径
if grep -q "/home/bridge/.bridge-server" docker/docker-compose.yml; then
    test_pass "docker-compose.yml 挂载路径正确"
else
    test_fail "docker-compose.yml 挂载路径不正确"
fi

echo ""

# ============================================
# 测试 5: 环境变量支持检查
# ============================================
echo -e "${YELLOW}[5/6] 检查环境变量支持...${NC}"

# 检查 install.sh 是否支持环境变量
if grep -q 'INSTALL_DIR="${INSTALL_DIR:-' install.sh && \
   grep -q 'CONFIG_DIR="${CONFIG_DIR:-' install.sh && \
   grep -q 'LOG_DIR="${LOG_DIR:-' install.sh; then
    test_pass "install.sh 支持环境变量覆盖"
else
    test_fail "install.sh 不支持环境变量覆盖"
fi

# 检查 cli/bridge-server.py 是否支持环境变量
if grep -q 'os.getenv("INSTALL_DIR"' cli/bridge-server.py && \
   grep -q 'os.getenv("CONFIG_DIR"' cli/bridge-server.py && \
   grep -q 'os.getenv("LOG_DIR"' cli/bridge-server.py; then
    test_pass "cli/bridge-server.py 支持环境变量"
else
    test_fail "cli/bridge-server.py 不支持环境变量"
fi

echo ""

# ============================================
# 测试 6: 文档完整性检查
# ============================================
echo -e "${YELLOW}[6/6] 检查文档完整性...${NC}"

# 检查跨平台文档
if [ -f "CROSS-PLATFORM-FIXES.md" ]; then
    test_pass "存在适配性改进方案文档"
else
    test_fail "缺少适配性改进方案文档"
fi

if [ -f "CROSS-PLATFORM-GUIDE.md" ]; then
    test_pass "存在跨平台部署指南"
else
    test_fail "缺少跨平台部署指南"
fi

if [ -f "CROSS-PLATFORM-CHANGES.md" ]; then
    test_pass "存在修复总结文档"
else
    test_fail "缺少修复总结文档"
fi

# 检查 CHANGELOG 是否记录跨平台改进
if grep -q "跨平台" CHANGELOG.md || grep -q "无需 root" CHANGELOG.md; then
    test_pass "CHANGELOG 记录了跨平台改进"
else
    test_fail "CHANGELOG 未记录跨平台改进"
fi

echo ""

# ============================================
# 测试结果汇总
# ============================================
echo "╔═══════════════════════════════════════════╗"
echo "║            测试结果汇总                   ║"
echo "╚═══════════════════════════════════════════╝"
echo ""
echo -e "通过：${GREEN}$TESTS_PASSED${NC}"
echo -e "失败：${RED}$TESTS_FAILED${NC}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}🎉 所有测试通过！跨平台适配性良好${NC}"
    exit 0
else
    echo -e "${RED}⚠️  有 $TESTS_FAILED 项测试失败，请检查修复${NC}"
    exit 1
fi
