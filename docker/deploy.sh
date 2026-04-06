#!/bin/bash
# Bridge Server Docker 部署脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印函数
print_info() { echo -e "${BLUE}ℹ${NC} $1"; }
print_success() { echo -e "${GREEN}✓${NC} $1"; }
print_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
print_error() { echo -e "${RED}✗${NC} $1"; }

# 项目根目录
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER_DIR="$PROJECT_ROOT/docker"
CONFIG_DIR="$HOME/.bridge-server/docker"

echo "╔═══════════════════════════════════════════╗"
echo "║  Bridge Server Docker 部署工具            ║"
echo "║  Version 1.3.0                            ║"
echo "╚═══════════════════════════════════════════╝"
echo ""

# ============ 检查依赖 ============
check_dependencies() {
    print_info "检查依赖..."
    
    if ! command -v docker &> /dev/null; then
        print_error "Docker 未安装"
        echo ""
        echo "请安装 Docker:"
        echo "  curl -fsSL https://get.docker.com | sh"
        exit 1
    fi
    
    if ! docker ps &> /dev/null; then
        print_error "Docker 未运行或无权限"
        echo ""
        echo "请启动 Docker 或添加用户到 docker 组:"
        echo "  sudo usermod -aG docker \$USER"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        print_warning "docker-compose 未安装，尝试使用 docker compose"
        COMPOSE_CMD="docker compose"
    else
        COMPOSE_CMD="docker-compose"
    fi
    
    print_success "依赖检查通过"
}

# ============ 创建目录结构 ============
setup_directories() {
    print_info "创建目录结构..."
    
    mkdir -p "$CONFIG_DIR"
    mkdir -p "$DOCKER_DIR/config"
    mkdir -p "$DOCKER_DIR/logs"
    mkdir -p "$DOCKER_DIR/data"
    
    print_success "目录创建完成"
}

# ============ 配置文件 ============
setup_config() {
    print_info "配置设置..."
    
    # 复制配置模板
    if [ ! -f "$DOCKER_DIR/config/config.yaml" ]; then
        cp "$PROJECT_ROOT/config.yaml.example" "$DOCKER_DIR/config/config.yaml"
        print_success "配置文件已创建：$DOCKER_DIR/config/config.yaml"
        print_warning "请编辑配置文件设置 API Keys 和认证 Tokens"
    else
        print_success "配置文件已存在"
    fi
    
    # 复制 .env 模板
    if [ ! -f "$DOCKER_DIR/.env" ]; then
        cp "$PROJECT_ROOT/.env.example" "$DOCKER_DIR/.env"
        chmod 600 "$DOCKER_DIR/.env"
        print_success "环境变量文件已创建：$DOCKER_DIR/.env"
        print_warning "请编辑 .env 文件设置 API Keys"
    else
        print_success "环境变量文件已存在"
    fi
    
    echo ""
    print_info "配置位置:"
    echo "  配置文件：$DOCKER_DIR/config/config.yaml"
    echo "  环境变量：$DOCKER_DIR/.env"
    echo "  默认端口：19377"
    echo ""
}

# ============ 构建镜像 ============
build_image() {
    print_info "构建 Docker 镜像..."
    
    cd "$DOCKER_DIR"
    
    if [ "$1" = "--no-cache" ]; then
        docker build -f Dockerfile -t bridge-server:1.3.0 --no-cache ..
    else
        docker build -f Dockerfile -t bridge-server:1.3.0 ..
    fi
    
    print_success "镜像构建完成"
    docker images bridge-server:1.3.0
}

# ============ 启动服务 ============
start_service() {
    print_info "启动 Bridge Server..."
    
    cd "$DOCKER_DIR"
    
    # 检查是否已运行
    if [ "$(docker ps -q -f name=bridge-server)" ]; then
        print_warning "服务已在运行"
        read -p "是否重启？[Y/n] " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            $COMPOSE_CMD restart
        else
            return
        fi
    else
        $COMPOSE_CMD up -d
    fi
    
    # 等待服务启动
    print_info "等待服务启动..."
    sleep 5
    
    # 检查健康状态
    sleep 3
    PORT=$(grep -oP 'BRIDGE_PORT=\K\d+' "$DOCKER_DIR/.env" 2>/dev/null || echo "19377")
    print_info "测试端口 $PORT ..."
    
    if curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PORT/health" | grep -q "200\|503"; then
        print_success "服务启动成功 (端口：$PORT)"
    else
        print_warning "服务可能未完全启动，请检查日志"
    fi
}

# ============ 停止服务 ============
stop_service() {
    print_info "停止服务..."
    
    cd "$DOCKER_DIR"
    $COMPOSE_CMD down
    
    print_success "服务已停止"
}

# ============ 查看日志 ============
view_logs() {
    cd "$DOCKER_DIR"
    
    if [ "$1" = "-f" ]; then
        $COMPOSE_CMD logs -f
    else
        LINES=${1:-100}
        $COMPOSE_CMD logs --tail=$LINES
    fi
}

# ============ 查看状态 ============
show_status() {
    print_info "服务状态"
    echo ""
    
    cd "$DOCKER_DIR"
    $COMPOSE_CMD ps
    
    echo ""
    print_info "资源使用"
    docker stats bridge-server --no-stream 2>/dev/null || print_warning "无法获取资源统计"
}

# ============ 清理 ============
cleanup() {
    print_warning "此操作将删除所有容器和数据"
    read -p "确认继续？[y/N] " -n 1 -r
    echo ""
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cd "$DOCKER_DIR"
        $COMPOSE_CMD down -v
        docker rmi bridge-server:1.3.0 2>/dev/null || true
        print_success "清理完成"
    else
        print_info "操作已取消"
    fi
}

# ============ 备份配置 ============
backup_config() {
    BACKUP_FILE="bridge-server-docker-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
    
    print_info "备份配置到 $BACKUP_FILE..."
    
    cd "$DOCKER_DIR"
    tar -czf "$BACKUP_FILE" config/ data/ .env 2>/dev/null || {
        # 如果某些文件不存在，继续备份
        tar -czf "$BACKUP_FILE" config/ data/ .env --ignore-failed-read 2>/dev/null || {
            print_warning "部分文件备份失败"
        }
    }
    
    print_success "备份完成：$BACKUP_FILE"
}

# ============ 帮助信息 ============
show_help() {
    cat << EOF
Bridge Server Docker 部署工具

用法: $0 <命令> [选项]

命令:
  setup       初始化配置（创建目录和配置文件）
  build       构建 Docker 镜像
  start       启动服务
  stop        停止服务
  restart     重启服务
  status      查看状态
  logs        查看日志（支持 -f 跟踪）
  backup      备份配置
  cleanup     清理所有容器和数据
  help        显示帮助

选项:
  --no-cache  构建时不使用缓存

示例:
  $0 setup              # 初始化配置
  $0 build              # 构建镜像
  $0 start              # 启动服务
  $0 logs -f            # 跟踪日志
  $0 status             # 查看状态
  $0 backup             # 备份配置

EOF
}

# ============ 主函数 ============
main() {
    if [ $# -eq 0 ]; then
        show_help
        exit 0
    fi
    
    command=$1
    shift
    
    case $command in
        setup)
            check_dependencies
            setup_directories
            setup_config
            ;;
        build)
            check_dependencies
            build_image "$@"
            ;;
        start)
            check_dependencies
            start_service
            ;;
        stop)
            check_dependencies
            stop_service
            ;;
        restart)
            check_dependencies
            stop_service
            start_service
            ;;
        status)
            show_status
            ;;
        logs)
            view_logs "$@"
            ;;
        backup)
            backup_config
            ;;
        cleanup)
            cleanup
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "未知命令：$command"
            show_help
            exit 1
            ;;
    esac
}

main "$@"
