#!/bin/bash
# 密钥泄露扫描脚本
# 用法：./scripts/secret-scan.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

echo ""
echo "╔═══════════════════════════════════════════╗"
echo "║     Bridge Server 密钥泄露扫描            ║"
echo "╚═══════════════════════════════════════════╝"
echo ""

# 创建报告目录
mkdir -p reports

# ============================================
# 方法 1: 使用 truffleHog（如果已安装）
# ============================================
if command -v trufflehog &> /dev/null; then
    log_info "使用 truffleHog 扫描..."
    
    if trufflehog filesystem . \
        --json \
        --output reports/secrets-report.json \
        --fail \
        --only-verified 2>/dev/null; then
        log_success "truffleHog 未发现泄露密钥 ✅"
    else
        log_error "truffleHog 发现潜在密钥泄露 ❌"
        cat reports/secrets-report.json | jq '.' | head -50
        exit 1
    fi
else
    log_info "truffleHog 未安装，使用 grep 扫描..."
fi

# ============================================
# 方法 2: 使用 grep 扫描常见密钥模式
# ============================================
log_info "扫描常见密钥模式..."

FOUND_SECRETS=0

# 扫描目录
SCAN_DIRS="app/ services/ providers/ cli/"

# 1. API Key 模式 (sk-xxx)
log_info "检查 API Key 模式 (sk-...)..."
if grep -r "sk-[a-zA-Z0-9]\{20,\}" $SCAN_DIRS --include="*.py" 2>/dev/null | \
   grep -v "test" | grep -v "# " | grep -v "example" | grep -v "your-" | grep -v "xxx"; then
    log_error "发现可能的 API Key！"
    FOUND_SECRETS=1
fi

# 2. Bearer Token 模式
log_info "检查 Bearer Token 模式..."
if grep -r "Bearer [a-zA-Z0-9_-]\{20,\}" $SCAN_DIRS --include="*.py" 2>/dev/null | \
   grep -v "test" | grep -v "# " | grep -v "example"; then
    log_error "发现硬编码的 Bearer Token！"
    FOUND_SECRETS=1
fi

# 3. 密码模式
log_info "检查密码模式..."
if grep -rE "(password|passwd|pwd)\s*=\s*['\"][^'\"]+['\"]" $SCAN_DIRS --include="*.py" 2>/dev/null | \
   grep -v "test" | grep -v "# " | grep -v "example" | grep -v "''" | grep -v '""'; then
    log_error "发现硬编码密码！"
    FOUND_SECRETS=1
fi

# 4. 私钥模式
log_info "检查私钥模式..."
if grep -r "BEGIN.*PRIVATE KEY" $SCAN_DIRS --include="*.py" 2>/dev/null; then
    log_error "发现私钥！"
    FOUND_SECRETS=1
fi

# 5. AWS Access Key 模式
log_info "检查 AWS Access Key 模式..."
if grep -rE "AKIA[0-9A-Z]{16}" $SCAN_DIRS --include="*.py" 2>/dev/null; then
    log_error "发现 AWS Access Key！"
    FOUND_SECRETS=1
fi

# 6. GitHub Token 模式
log_info "检查 GitHub Token 模式..."
if grep -rE "gh[pousr]_[A-Za-z0-9_]{36,}" $SCAN_DIRS --include="*.py" 2>/dev/null; then
    log_error "发现 GitHub Token！"
    FOUND_SECRETS=1
fi

# 7. 阿里云 Access Key 模式
log_info "检查阿里云 Access Key 模式..."
if grep -rE "LTAI[a-zA-Z0-9]{12,}" $SCAN_DIRS --include="*.py" 2>/dev/null; then
    log_error "发现阿里云 Access Key！"
    FOUND_SECRETS=1
fi

# 8. 检查配置文件中的明文密钥
log_info "检查配置文件..."
if [ -f "config.yaml" ]; then
    if grep -E "api_key:\s*sk-[a-zA-Z0-9]+" config.yaml 2>/dev/null; then
        log_error "配置文件中存在明文 API Key！"
        log_info "建议使用 api_key_env 环境变量方式"
        FOUND_SECRETS=1
    fi
fi

# 9. 检查 .env 文件是否被提交
log_info "检查 .env 文件..."
if git ls-files | grep -E "\.env$" 2>/dev/null; then
    log_error ".env 文件被提交到版本控制！"
    log_info "请将 .env 添加到 .gitignore"
    FOUND_SECRETS=1
fi

# ============================================
# 生成报告
# ============================================
if [ $FOUND_SECRETS -eq 0 ]; then
    log_success "密钥扫描通过 ✅"
    
    # 生成成功报告
    cat > reports/secrets-report.json << EOF
{
  "scan_time": "$(date -Iseconds)",
  "status": "passed",
  "secrets_found": 0,
  "scan_dirs": "$SCAN_DIRS"
}
EOF
    
    echo ""
    echo "╔═══════════════════════════════════════════╗"
    echo "║         扫描完成 - 未发现密钥             ║"
    echo "╚═══════════════════════════════════════════╝"
    echo ""
    exit 0
else
    log_error "发现密钥泄露 ❌"
    
    # 生成失败报告
    cat > reports/secrets-report.md << EOF
# 密钥泄露扫描报告

**扫描时间**: $(date)
**状态**: ❌ 失败

## 发现的问题

请检查上方输出，移除所有硬编码的密钥。

## 修复建议

1. **API Key**: 使用环境变量存储
   ```python
   # ❌ 错误
   api_key = "sk-xxx"
   
   # ✅ 正确
   api_key = os.getenv("API_KEY")
   ```

2. **密码**: 使用密钥管理服务
   ```python
   # ❌ 错误
   password = "secret123"
   
   # ✅ 正确
   password = os.getenv("DB_PASSWORD")
   ```

3. **配置文件**: 使用占位符
   ```yaml
   # ❌ 错误
   api_key: sk-xxx
   
   # ✅ 正确
   api_key_env: API_KEY
   ```

4. **.env 文件**: 添加到 .gitignore
   ```bash
   echo ".env" >> .gitignore
   ```

---
*扫描完成时间：$(date)*
EOF
    
    echo ""
    echo "╔═══════════════════════════════════════════╗"
    echo "║      扫描完成 - 发现密钥泄露              ║"
    echo "╚═══════════════════════════════════════════╝"
    echo ""
    log_info "详细报告：reports/secrets-report.md"
    echo ""
    exit 1
fi
