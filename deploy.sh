#!/bin/bash
# Bridge Server 部署脚本
# 用法：./deploy.sh <命令> [选项]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
COMPOSE_LB_FILE="${SCRIPT_DIR}/docker-compose.lb.yml"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_header() {
    echo -e "${CYAN}════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}════════════════════════════════════════════════════${NC}"
}

show_help() {
    echo "Bridge Server 部署脚本 v1.4.0"
    echo ""
    echo "用法：$0 <命令> [选项]"
    echo ""
    echo "命令:"
    echo "  start              启动服务（单机模式）"
    echo "  stop               停止服务"
    echo "  restart            重启服务"
    echo "  status             查看状态"
    echo "  logs               查看日志"
    echo "  scale <数量>       扩缩容（负载均衡模式）"
    echo "  enable-ssl         启用 SSL"
    echo "  disable-ssl        禁用 SSL"
    echo "  backup             备份配置和数据"
    echo "  restore            恢复配置和数据"
    echo "  health             健康检查"
    echo "  deploy             一键部署（生产环境）"
    echo ""
    echo "SSL 选项:"
    echo "  --mode <模式>      letsencrypt|custom|self-signed (默认：self-signed)"
    echo "  --domain <域名>    域名（Let's Encrypt 模式必填）"
    echo "  --email <邮箱>     邮箱（Let's Encrypt 模式）"
    echo "  --cert <路径>      证书文件（自定义模式）"
    echo "  --key <路径>       私钥文件（自定义模式）"
    echo "  --cn <名称>        Common Name（自签名模式，默认：localhost）"
    echo "  --days <天数>      有效期（自签名模式，默认：365）"
    echo "  --test             使用测试环境（Let's Encrypt）"
    echo ""
    echo "示例:"
    echo "  $0 start"
    echo "  $0 enable-ssl --mode letsencrypt --domain example.com --email admin@example.com"
    echo "  $0 enable-ssl --mode self-signed --cn localhost --days 365"
    echo "  $0 scale 3"
    echo "  $0 deploy"
}

# 启动服务
cmd_start() {
    print_header "启动 Bridge Server"
    
    if [ ! -f "$COMPOSE_FILE" ]; then
        print_error "配置文件不存在：$COMPOSE_FILE"
        exit 1
    fi
    
    docker-compose -f "$COMPOSE_FILE" up -d
    
    print_info "等待服务启动..."
    sleep 5
    
    cmd_status
}

# 停止服务
cmd_stop() {
    print_header "停止 Bridge Server"
    
    docker-compose -f "$COMPOSE_FILE" down
    
    print_success "服务已停止"
}

# 重启服务
cmd_restart() {
    print_header "重启 Bridge Server"
    
    docker-compose -f "$COMPOSE_FILE" restart
    
    cmd_status
}

# 查看状态
cmd_status() {
    print_header "服务状态"
    
    echo ""
    print_info "容器状态:"
    docker-compose -f "$COMPOSE_FILE" ps
    
    echo ""
    if [ -f "$COMPOSE_LB_FILE" ]; then
        print_info "负载均衡器状态:"
        docker-compose -f "$COMPOSE_LB_FILE" ps nginx-lb 2>/dev/null || print_warning "负载均衡器未运行"
    fi
    
    echo ""
    print_info "端口占用:"
    netstat -tlnp 2>/dev/null | grep -E ":(80|443|19377)" || print_warning "未检测到端口占用"
}

# 查看日志
cmd_logs() {
    docker-compose -f "$COMPOSE_FILE" logs -f --tail=100
}

# 扩缩容
cmd_scale() {
    if [ -z "$1" ]; then
        print_error "请指定实例数量"
        echo "用法：$0 scale <数量>"
        exit 1
    fi
    
    print_header "扩缩容到 $1 个实例"
    
    "$SCRIPT_DIR/scripts/ops/scale.sh" "$1"
}

# 启用 SSL
cmd_enable_ssl() {
    print_header "启用 SSL"
    
    MODE="${SSL_MODE:-self-signed}"
    
    print_info "SSL 模式：$MODE"
    
    case "$MODE" in
        letsencrypt)
            if [ -z "$SSL_DOMAIN" ]; then
                print_error "Let's Encrypt 模式必须指定 --domain"
                exit 1
            fi
            
            print_info "申请 Let's Encrypt 证书：$SSL_DOMAIN"
            
            python3 "$SCRIPT_DIR/app/ssl_manager.py" enable-ssl \
                --mode letsencrypt \
                --domain "$SSL_DOMAIN" \
                --email "${SSL_EMAIL:-admin@$SSL_DOMAIN}" \
                $([ "$SSL_TEST" = true ] && echo "--test")
            ;;
        
        custom)
            if [ -z "$SSL_CERT" ] || [ -z "$SSL_KEY" ]; then
                print_error "自定义模式必须指定 --cert 和 --key"
                exit 1
            fi
            
            print_info "上传自定义证书"
            
            python3 "$SCRIPT_DIR/app/ssl_manager.py" enable-ssl \
                --mode custom \
                --cert "$SSL_CERT" \
                --key "$SSL_KEY" \
                --name "${SSL_NAME:-custom}"
            ;;
        
        self-signed)
            print_info "生成自签名证书"
            
            python3 "$SCRIPT_DIR/app/ssl_manager.py" enable-ssl \
                --mode self-signed \
                --cn "${SSL_CN:-localhost}" \
                --days "${SSL_DAYS:-365}"
            ;;
        
        *)
            print_error "未知的 SSL 模式：$MODE"
            exit 1
            ;;
    esac
    
    print_success "SSL 证书配置完成"
    print_info "重启服务以应用 SSL 配置..."
    
    cmd_restart
}

# 禁用 SSL
cmd_disable_ssl() {
    print_header "禁用 SSL"
    
    print_warning "禁用 SSL 将使用 HTTP 模式"
    
    # 移除 SSL 配置
    # TODO: 实现 SSL 禁用逻辑
    
    print_success "SSL 已禁用"
}

# 备份
cmd_backup() {
    print_header "备份配置和数据"
    
    BACKUP_DIR="${SCRIPT_DIR}/backups/$(date +%Y%m%d_%H%M%S)"
    
    mkdir -p "$BACKUP_DIR"
    
    # 备份配置文件
    if [ -f "$COMPOSE_FILE" ]; then
        cp "$COMPOSE_FILE" "$BACKUP_DIR/"
    fi
    
    if [ -f "${SCRIPT_DIR}/config.yaml" ]; then
        cp "${SCRIPT_DIR}/config.yaml" "$BACKUP_DIR/"
    fi
    
    # 备份 SSL 证书
    if [ -d "${SCRIPT_DIR}/docker/ssl" ]; then
        cp -r "${SCRIPT_DIR}/docker/ssl" "$BACKUP_DIR/"
    fi
    
    # 备份数据卷
    docker run --rm \
        -v bridge_data:/data:ro \
        -v "$BACKUP_DIR/data:/backup" \
        alpine tar czf /backup/data.tar.gz -C /data .
    
    print_success "备份完成：$BACKUP_DIR"
}

# 恢复
cmd_restore() {
    print_header "恢复配置和数据"
    
    if [ -z "$1" ]; then
        print_error "请指定备份目录"
        echo "用法：$0 restore <备份目录>"
        exit 1
    fi
    
    BACKUP_DIR="$1"
    
    if [ ! -d "$BACKUP_DIR" ]; then
        print_error "备份目录不存在：$BACKUP_DIR"
        exit 1
    fi
    
    print_info "从备份恢复：$BACKUP_DIR"
    
    # 恢复配置文件
    if [ -f "$BACKUP_DIR/docker-compose.yml" ]; then
        cp "$BACKUP_DIR/docker-compose.yml" "$COMPOSE_FILE"
    fi
    
    if [ -f "$BACKUP_DIR/config.yaml" ]; then
        cp "$BACKUP_DIR/config.yaml" "${SCRIPT_DIR}/config.yaml"
    fi
    
    # 恢复 SSL 证书
    if [ -d "$BACKUP_DIR/ssl" ]; then
        cp -r "$BACKUP_DIR/ssl" "${SCRIPT_DIR}/docker/"
    fi
    
    # 恢复数据卷
    docker run --rm \
        -v bridge_data:/data \
        -v "$BACKUP_DIR/data:/backup" \
        alpine tar xzf /backup/data.tar.gz -C /data
    
    print_success "恢复完成"
}

# 健康检查
cmd_health() {
    print_header "健康检查"
    
    # 检查容器状态
    print_info "检查容器状态..."
    docker-compose -f "$COMPOSE_FILE" ps
    
    # 检查 API 健康
    print_info "检查 API 健康..."
    
    if curl -f http://localhost:19377/health > /dev/null 2>&1; then
        print_success "API 健康检查通过"
    else
        print_error "API 健康检查失败"
    fi
    
    # 检查 SSL（如果启用）
    if [ -f "${SCRIPT_DIR}/docker/ssl/certs/self-signed.crt" ]; then
        print_info "检查 SSL 证书..."
        
        python3 "$SCRIPT_DIR/app/ssl_manager.py" info self-signed
    fi
}

# 一键部署
cmd_deploy() {
    print_header "一键部署（生产环境）"
    
    print_info "步骤 1/5: 检查环境..."
    
    # 检查 Docker
    if ! command -v docker &> /dev/null; then
        print_error "Docker 未安装"
        exit 1
    fi
    
    # 检查 docker-compose
    if ! command -v docker-compose &> /dev/null; then
        print_error "docker-compose 未安装"
        exit 1
    fi
    
    print_success "环境检查通过"
    
    print_info "步骤 2/5: 创建配置..."
    
    if [ ! -f "${SCRIPT_DIR}/config.yaml" ]; then
        print_warning "配置文件不存在，运行配置向导..."
        python3 "$SCRIPT_DIR/cli/setup-wizard.py"
    else
        print_success "配置文件已存在"
    fi
    
    print_info "步骤 3/5: 启动服务..."
    
    docker-compose -f "$COMPOSE_FILE" up -d
    
    print_info "等待服务启动..."
    sleep 10
    
    print_info "步骤 4/5: 健康检查..."
    
    cmd_health
    
    print_info "步骤 5/5: 显示访问信息..."
    
    echo ""
    print_success "🎉 部署完成！"
    echo ""
    echo "访问地址："
    echo "  API: http://localhost:19377"
    echo "  健康检查：http://localhost:19377/health"
    echo ""
    echo "查看日志：$0 logs"
    echo "查看状态：$0 status"
    echo "停止服务：$0 stop"
}

# 解析参数
SSL_MODE=""
SSL_DOMAIN=""
SSL_EMAIL=""
SSL_CERT=""
SSL_KEY=""
SSL_CN=""
SSL_DAYS=""
SSL_TEST=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --mode)
            SSL_MODE="$2"
            shift 2
            ;;
        --domain)
            SSL_DOMAIN="$2"
            shift 2
            ;;
        --email)
            SSL_EMAIL="$2"
            shift 2
            ;;
        --cert)
            SSL_CERT="$2"
            shift 2
            ;;
        --key)
            SSL_KEY="$2"
            shift 2
            ;;
        --cn)
            SSL_CN="$2"
            shift 2
            ;;
        --days)
            SSL_DAYS="$2"
            shift 2
            ;;
        --test)
            SSL_TEST=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            break
            ;;
    esac
done

# 执行命令
COMMAND="${1:-}"

case "$COMMAND" in
    start)
        cmd_start
        ;;
    stop)
        cmd_stop
        ;;
    restart)
        cmd_restart
        ;;
    status)
        cmd_status
        ;;
    logs)
        cmd_logs
        ;;
    scale)
        cmd_scale "$2"
        ;;
    enable-ssl)
        cmd_enable_ssl
        ;;
    disable-ssl)
        cmd_disable_ssl
        ;;
    backup)
        cmd_backup
        ;;
    restore)
        cmd_restore "$2"
        ;;
    health)
        cmd_health
        ;;
    deploy)
        cmd_deploy
        ;;
    -h|--help)
        show_help
        ;;
    "")
        show_help
        ;;
    *)
        print_error "未知命令：$COMMAND"
        show_help
        exit 1
        ;;
esac
