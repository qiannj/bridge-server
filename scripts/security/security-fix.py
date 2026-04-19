#!/usr/bin/env python3
"""
Bridge Server 安全修复脚本 v1.0.0
修复所有 P0 和 P1 安全问题
"""

import os
import re
import stat
import secrets
from pathlib import Path

def fix_jwt_secret_in_auth_py():
    """修复 auth.py 中的 JWT 密钥硬编码问题"""
    print("🔒 修复 auth.py 中的 JWT 密钥硬编码...")
    
    auth_file = Path("/home/pi/.openclaw/workspace/bridge-server-product/app/auth.py")
    content = auth_file.read_text(encoding='utf-8')
    
    # 修复 1: verify_token 函数中的 JWT 密钥
    content = re.sub(
        r'secret_key = auth_config\.get\("jwt_secret", "bridge-server-secret-key-change-me"\)',
        'secret_key = auth_config.get("jwt_secret")\n        \n            # 🔒 安全：强制要求配置密钥\n            if not secret_key:\n                logger.critical("未配置 jwt_secret，无法使用 JWT 认证")\n                raise HTTPException(\n                    status_code=503, \n                    detail="服务未配置 jwt_secret，请在 config.yaml 中配置"\n                )',
        content
    )
    
    # 修复 2: create_jwt_token 函数签名
    content = re.sub(
        r'def create_jwt_token\(username: str, expires_days: int = 30\)',
        'def create_jwt_token(username: str, expires_days: int = 7)  # 🔒 安全：缩短为 7 天',
        content
    )
    
    # 修复 3: create_jwt_token 函数中的密钥处理
    content = re.sub(
        r'secret_key = auth_config\.get\("jwt_secret", "bridge-server-secret-key-change-me"\)',
        'secret_key = auth_config.get("jwt_secret")\n    \n    # 🔒 安全：强制要求配置密钥\n    if not secret_key:\n        logger.critical("未配置 jwt_secret，无法创建 JWT Token")\n        raise ValueError("服务未配置 jwt_secret，请在 config.yaml 中配置")',
        content
    )
    
    # 修复 4: 添加 jti 到 payload
    old_payload = '"type": "access"'
    new_payload = '"type": "access",\n        "jti": secrets.token_hex(16)  # 🔒 安全：唯一标识，支持吊销'
    content = content.replace(old_payload, new_payload, 1)
    
    # 添加 secrets 导入
    if 'import secrets' not in content:
        content = content.replace('from datetime import datetime, timedelta', 
                                  'from datetime import datetime, timedelta\nimport secrets')
    
    auth_file.write_text(content, encoding='utf-8')
    print("✅ auth.py 修复完成")

def fix_rate_limit_in_main_py():
    """修复 runtime.py 中的速率限制问题"""
    print("🔒 修复 runtime.py 中的速率限制...")
    
    main_file = Path("/home/pi/.openclaw/workspace/bridge-server-product/src/bridge_server/runtime.py")
    content = main_file.read_text(encoding='utf-8')
    
    # 修复速率限制配置
    old_limit = 'default_limits=["100/minute", "1000/hour"]'
    new_limit = 'default_limits=["30/minute", "500/hour", "10/second"]  # 🔒 安全：更严格的限制'
    content = content.replace(old_limit, new_limit)
    
    main_file.write_text(content, encoding='utf-8')
    print("✅ runtime.py 修复完成")

def fix_cors_in_main_py():
    """修复 runtime.py 中的 CORS 配置"""
    print("🔒 修复 runtime.py 中的 CORS 配置...")
    
    main_file = Path("/home/pi/.openclaw/workspace/bridge-server-product/src/bridge_server/runtime.py")
    content = main_file.read_text(encoding='utf-8')
    
    # 修复 CORS 配置 - 默认禁止所有
    old_cors = '''allowed_origins = server_config.get(
    "cors_origins", ["http://localhost:3000", "http://localhost:19377"]
)'''
    
    new_cors = '''# 🔒 安全：默认禁止所有跨域请求
allowed_origins = server_config.get("cors_origins", [])

if not allowed_origins:
    logger.warning("未配置 CORS，默认禁止所有跨域请求")'''
    
    content = content.replace(old_cors, new_cors)
    
    main_file.write_text(content, encoding='utf-8')
    print("✅ CORS 配置修复完成")

def generate_jwt_secret():
    """生成随机 JWT 密钥"""
    print("🔑 生成随机 JWT 密钥...")
    return secrets.token_hex(32)

def generate_api_key():
    """生成随机 API Key"""
    print("🔑 生成随机 API Key...")
    return secrets.token_hex(16)

def fix_config_permissions():
    """修复配置文件权限"""
    print("🔒 修复配置文件权限...")
    
    config_dir = Path.home() / ".bridge-server"
    config_dir.mkdir(parents=True, exist_ok=True)
    
    config_file = config_dir / "config.yaml"
    if config_file.exists():
        # 设置为仅所有者可读写
        os.chmod(config_file, stat.S_IRUSR | stat.S_IWUSR)  # 600
        print(f"✅ config.yaml 权限已设置为 600")
    
    env_file = config_dir / ".env"
    if env_file.exists():
        os.chmod(env_file, stat.S_IRUSR | stat.S_IWUSR)  # 600
        print(f"✅ .env 权限已设置为 600")

def create_security_config():
    """创建安全配置模板"""
    print("📝 创建安全配置模板...")
    
    config_dir = Path.home() / ".bridge-server"
    config_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成随机密钥
    jwt_secret = generate_jwt_secret()
    api_key = generate_api_key()
    
    # 创建安全配置
    config_content = f"""# Bridge Server 安全配置
# 生成时间：{Path().cwd().strftime('%Y-%m-%d %H:%M:%S')}

server:
  host: 127.0.0.1  # 🔒 安全：仅监听本地
  port: 19377
  debug: false     # 🔒 安全：生产环境禁用调试

auth:
  # 🔒 安全：随机生成的 JWT 密钥（请勿泄露）
  jwt_secret: "{jwt_secret}"
  
  # 🔒 安全：API Keys
  api_keys:
    - "{api_key}"

# 🔒 安全：速率限制
rate_limit:
  enabled: true
  requests_per_minute: 30
  requests_per_hour: 500
  requests_per_second: 10

# 🔒 安全：CORS（默认禁用）
cors:
  enabled: false
  # allowed_origins: ["https://your-domain.com"]

# 🔒 安全：日志
logging:
  level: WARNING  # 🔒 安全：生产环境使用 WARNING
  audit_enabled: true
"""
    
    config_file = config_dir / "config.yaml"
    if not config_file.exists():
        config_file.write_text(config_content, encoding='utf-8')
        print("✅ 安全配置已创建")
    else:
        print("⚠️  config.yaml 已存在，跳过创建")
    
    # 设置权限
    os.chmod(config_file, stat.S_IRUSR | stat.S_IWUSR)  # 600

def create_security_check_script():
    """创建安全检查脚本"""
    print("📝 创建安全检查脚本...")
    
    config_dir = Path.home() / ".bridge-server"
    
    script_content = '''#!/bin/bash
# Bridge Server 安全检查脚本

echo "🔒 Bridge Server 安全检查"
echo ""

# 1. 检查配置文件权限
CONFIG_PERM=$(stat -c %a ~/.bridge-server/config.yaml 2>/dev/null || stat -f %Lp ~/.bridge-server/config.yaml 2>/dev/null)
if [ "$CONFIG_PERM" != "600" ]; then
    echo "❌ 配置文件权限不正确：$CONFIG_PERM"
    echo "   建议：chmod 600 ~/.bridge-server/config.yaml"
else
    echo "✅ 配置文件权限正确"
fi

# 2. 检查 JWT 密钥
JWT_SECRET=$(grep "jwt_secret" ~/.bridge-server/config.yaml 2>/dev/null | grep -v "change-me" | grep -v '""')
if [ -z "$JWT_SECRET" ]; then
    echo "❌ JWT 密钥未配置或使用默认值，请立即修改"
else
    echo "✅ JWT 密钥已配置"
fi

# 3. 检查调试模式
DEBUG_MODE=$(grep "debug:" ~/.bridge-server/config.yaml 2>/dev/null | grep "true")
if [ -n "$DEBUG_MODE" ]; then
    echo "❌ 生产环境不应启用调试模式"
else
    echo "✅ 调试模式已禁用"
fi

# 4. 检查日志级别
LOG_LEVEL=$(grep "level:" ~/.bridge-server/config.yaml 2>/dev/null | grep -i "DEBUG")
if [ -n "$LOG_LEVEL" ]; then
    echo "⚠️  生产环境不建议使用 DEBUG 日志级别"
else
    echo "✅ 日志级别配置合理"
fi

# 5. 检查速率限制
RATE_LIMIT=$(grep "requests_per_minute" ~/.bridge-server/config.yaml 2>/dev/null | grep -oE "[0-9]+")
if [ -n "$RATE_LIMIT" ] && [ "$RATE_LIMIT" -le 30 ]; then
    echo "✅ 速率限制配置合理：$RATE_LIMIT 次/分钟"
else
    echo "⚠️  建议设置速率限制 <= 30 次/分钟"
fi

echo ""
echo "安全检查完成"
'''
    
    script_file = config_dir / "security-check.sh"
    script_file.write_text(script_content, encoding='utf-8')
    os.chmod(script_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)  # 700
    print("✅ 安全检查脚本已创建")

def main():
    print("")
    print("🔒 Bridge Server 安全修复程序")
    print("版本：v1.0.0")
    print("")
    
    # 1. 修复代码
    fix_jwt_secret_in_auth_py()
    fix_rate_limit_in_main_py()
    fix_cors_in_main_py()
    
    # 2. 创建安全配置
    create_security_config()
    
    # 3. 修复文件权限
    fix_config_permissions()
    
    # 4. 创建安全检查脚本
    create_security_check_script()
    
    print("")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("")
    print("✅ 安全修复完成！")
    print("")
    print("下一步：")
    print("")
    print("  1. 检查安全配置")
    print("     cat ~/.bridge-server/config.yaml")
    print("")
    print("  2. 运行安全检查")
    print("     ~/.bridge-server/security-check.sh")
    print("")
    print("  3. 重启服务")
    print("     bridge-server restart")
    print("")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("")

if __name__ == "__main__":
    main()
