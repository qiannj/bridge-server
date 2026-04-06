#!/bin/bash
# Bridge Server 扩缩容脚本
# 用法：./scale.sh <实例数量>

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.lb.yml"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印函数
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

# 检查参数
if [ $# -eq 0 ]; then
    echo "用法：$0 <实例数量>"
    echo "示例：$0 3  # 扩展到 3 个实例"
    exit 1
fi

TARGET_COUNT=$1

# 验证输入
if ! [[ "$TARGET_COUNT" =~ ^[0-9]+$ ]] || [ "$TARGET_COUNT" -lt 1 ]; then
    print_error "实例数量必须是正整数"
    exit 1
fi

print_info "目标实例数量：$TARGET_COUNT"

# 检查 docker-compose 是否存在
if ! command -v docker-compose &> /dev/null; then
    print_error "docker-compose 未安装"
    exit 1
fi

# 获取当前实例数量
CURRENT_COUNT=$(docker-compose -f "$COMPOSE_FILE" ps --services 2>/dev/null | grep -c "bridge-server" || echo "0")
print_info "当前实例数量：$CURRENT_COUNT"

# 执行扩缩容
print_info "开始扩缩容..."

if [ "$TARGET_COUNT" -gt "$CURRENT_COUNT" ]; then
    # 扩容
    print_info "扩容：$CURRENT_COUNT → $TARGET_COUNT"
    
    docker-compose -f "$COMPOSE_FILE" up -d --scale bridge-server=$TARGET_COUNT --no-recreate
    
    print_success "扩容完成"
    
elif [ "$TARGET_COUNT" -lt "$CURRENT_COUNT" ]; then
    # 缩容
    print_info "缩容：$CURRENT_COUNT → $TARGET_COUNT"
    print_warning "缩容会导致部分实例停止，确保不会影响服务"
    
    read -p "确认继续？[y/N]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_warning "操作已取消"
        exit 0
    fi
    
    docker-compose -f "$COMPOSE_FILE" up -d --scale bridge-server=$TARGET_COUNT
    
    print_success "缩容完成"
    
else
    print_info "实例数量无变化"
fi

# 等待服务稳定
print_info "等待服务稳定（10 秒）..."
sleep 10

# 检查服务状态
print_info "检查服务状态..."
docker-compose -f "$COMPOSE_FILE" ps

# 健康检查
print_info "执行健康检查..."

HEALTHY_COUNT=0
for i in $(seq 1 $TARGET_COUNT); do
    CONTAINER_NAME="bridge-server-$i"
    
    if docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_NAME" 2>/dev/null | grep -q "healthy"; then
        print_success "$CONTAINER_NAME 健康"
        ((HEALTHY_COUNT++))
    else
        print_warning "$CONTAINER_NAME 未就绪"
    fi
done

print_info "健康实例：$HEALTHY_COUNT / $TARGET_COUNT"

if [ "$HEALTHY_COUNT" -eq "$TARGET_COUNT" ]; then
    print_success "✅ 所有实例健康"
else
    print_warning "⚠️  部分实例未就绪，请稍后检查"
fi

# 显示负载均衡器状态
print_info "负载均衡器状态:"
docker-compose -f "$COMPOSE_FILE" ps nginx-lb

echo ""
print_success "🎉 扩缩容完成！"
echo ""
echo "查看日志：docker-compose -f $COMPOSE_FILE logs -f"
echo "查看状态：docker-compose -f $COMPOSE_FILE ps"
echo "停止服务：docker-compose -f $COMPOSE_FILE down"
