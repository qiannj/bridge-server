#!/bin/bash
# Bridge Server 完整测试脚本
# 用法：./scripts/run-all-tests.sh

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

# 创建报告目录
mkdir -p reports

echo ""
echo "╔═══════════════════════════════════════════╗"
echo "║     Bridge Server 完整测试套件            ║"
echo "╚═══════════════════════════════════════════╝"
echo ""

# ============================================
# 阶段 1: 单元测试
# ============================================
log_info "阶段 1/4: 运行单元测试..."
echo ""

if pytest tests/unit/ \
    -v \
    --cov=app \
    --cov=services \
    --cov=providers \
    --cov-report=html:reports/unit-coverage \
    --cov-report=xml:reports/unit-coverage.xml \
    --junitxml=reports/unit-report.xml; then
    log_success "单元测试通过 ✅"
else
    log_error "单元测试失败 ❌"
    exit 1
fi

echo ""

# ============================================
# 阶段 2: 集成测试
# ============================================
log_info "阶段 2/4: 运行集成测试..."
echo ""

if pytest tests/integration/ \
    -v \
    --cov=app \
    --cov=services \
    --cov-report=html:reports/integration-coverage \
    --cov-append \
    --junitxml=reports/integration-report.xml; then
    log_success "集成测试通过 ✅"
else
    log_error "集成测试失败 ❌"
    exit 1
fi

echo ""

# ============================================
# 阶段 3: 安全扫描
# ============================================
log_info "阶段 3/4: 运行安全扫描..."
echo ""

# 3.1 Bandit 静态分析
log_info "运行 Bandit 静态分析..."
if bandit -c security/bandit.yaml -r app/ services/ providers/ -f json -o reports/bandit-report.json; then
    log_success "Bandit 检查通过 ✅"
else
    log_warning "Bandit 发现问题，检查 reports/bandit-report.json"
fi

# 3.2 依赖漏洞扫描
log_info "扫描依赖漏洞..."
if safety check -r requirements.txt --json --output reports/safety-report.json; then
    log_success "依赖安全检查通过 ✅"
else
    log_warning "发现依赖漏洞，检查 reports/safety-report.json"
    safety check -r requirements.txt --full-report
fi

# 3.3 密钥泄露扫描
log_info "扫描密钥泄露..."
if bash scripts/secret-scan.sh; then
    log_success "密钥扫描通过 ✅"
else
    log_error "发现密钥泄露 ❌"
    exit 1
fi

# 3.4 代码质量检查
log_info "代码质量检查..."
if black --check app/ services/ providers/ 2>/dev/null; then
    log_success "Black 格式检查通过 ✅"
else
    log_warning "代码格式不符合 Black 规范"
    log_info "运行 'black app/ services/ providers/' 自动修复"
fi

echo ""

# ============================================
# 阶段 4: E2E 测试（可选）
# ============================================
if [ "$1" == "--e2e" ]; then
    log_info "阶段 4/4: 运行 E2E 测试..."
    echo ""
    
    # 启动 Docker Compose 测试环境
    log_info "启动测试环境..."
    docker-compose -f docker-compose.test.yml up -d
    
    # 等待服务就绪
    log_info "等待服务启动..."
    sleep 10
    
    # 运行 E2E 测试
    if pytest tests/e2e/ \
        -v \
        --junitxml=reports/e2e-report.xml; then
        log_success "E2E 测试通过 ✅"
    else
        log_error "E2E 测试失败 ❌"
        docker-compose -f docker-compose.test.yml logs
        docker-compose -f docker-compose.test.yml down
        exit 1
    fi
    
    # 清理测试环境
    log_info "清理测试环境..."
    docker-compose -f docker-compose.test.yml down
    
    echo ""
fi

# ============================================
# 生成测试报告
# ============================================
log_info "生成测试报告..."

# 合并覆盖率报告
coverage combine || true
coverage html -d reports/total-coverage
coverage xml -o reports/total-coverage.xml

# 生成综合报告
cat > reports/test-summary.md << EOF
# Bridge Server 测试报告

**日期**: $(date +%Y-%m-%d)
**版本**: $(git describe --tags --always 2>/dev/null || echo "unknown")

## 测试结果

### 单元测试
- 状态：$( [ -f reports/unit-report.xml ] && echo "✅ 通过" || echo "❌ 失败" )
- 报告：reports/unit-report.xml
- 覆盖率：reports/unit-coverage/index.html

### 集成测试
- 状态：$( [ -f reports/integration-report.xml ] && echo "✅ 通过" || echo "❌ 失败" )
- 报告：reports/integration-report.xml
- 覆盖率：reports/integration-coverage/index.html

### 安全扫描
- Bandit: $( [ -f reports/bandit-report.json ] && echo "✅ 完成" || echo "❌ 未运行" )
- Safety: $( [ -f reports/safety-report.json ] && echo "✅ 完成" || echo "❌ 未运行" )
- Secret Scan: $( [ -f reports/secrets-report.json ] && echo "✅ 完成" || echo "❌ 未运行" )

### E2E 测试
- 状态：$( [ -f reports/e2e-report.xml ] && echo "✅ 通过" || echo "⏭️ 跳过" )
- 报告：reports/e2e-report.xml

### 总覆盖率
- HTML: reports/total-coverage/index.html
- XML: reports/total-coverage.xml

## 问题汇总

### 高危问题
$(cat reports/bandit-report.json 2>/dev/null | jq '.results[] | select(.issue_severity=="HIGH")' | head -20 || echo "无")

### 依赖漏洞
$(cat reports/safety-report.json 2>/dev/null | jq '.[]' | head -20 || echo "无")

---
*报告生成时间：$(date)*
EOF

log_success "测试报告已生成：reports/test-summary.md"

echo ""
echo "╔═══════════════════════════════════════════╗"
echo "║           测试完成！                      ║"
echo "╚═══════════════════════════════════════════╝"
echo ""
log_info "查看详细报告:"
echo "  - 测试总结：reports/test-summary.md"
echo "  - 覆盖率：reports/total-coverage/index.html"
echo "  - Bandit:  reports/bandit-report.json"
echo "  - Safety:  reports/safety-report.json"
echo ""
