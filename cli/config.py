#!/usr/bin/env python3
"""
Bridge Server 共享配置模块
CLI 和主服务都通过此模块读取配置，避免不一致

设计原则：
- 零外部依赖（仅用 stdlib + pyyaml）
- 配置路径支持环境变量覆盖
- 提供统一的服务地址获取方法
"""

import os
from pathlib import Path
from typing import Optional

# ============ 配置路径 ============

# 配置目录（支持环境变量覆盖）
CONFIG_DIR = Path(os.getenv("BRIDGE_SERVER_CONFIG_DIR", Path.home() / ".bridge-server"))
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"

# 日志目录
LOG_DIR = Path(os.getenv("BRIDGE_SERVER_LOG_DIR", CONFIG_DIR / "logs"))
LOG_FILE = LOG_DIR / "bridge-server.log"

# 用量数据文件
USAGE_FILE = CONFIG_DIR / "usage.json"

# 备份目录
BACKUP_DIR = CONFIG_DIR / "backups"

# ============ 服务配置 ============

def _load_config_raw() -> dict:
    """原始加载配置文件（不处理异常）"""
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        import yaml
        return yaml.safe_load(f) or {}


def get_default_port() -> int:
    """
    获取服务默认端口
    
    优先级：
    1. BRIDGE_SERVER_PORT 环境变量
    2. config.yaml 中的 server.port
    3. 默认值 19377
    
    Returns:
        int: 服务端口号
    """
    # 环境变量优先级最高
    env_port = os.getenv("BRIDGE_SERVER_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass
    
    # 从配置文件读取
    if CONFIG_FILE.exists():
        try:
            config = _load_config_raw()
            port = config.get('server', {}).get('port', 19377)
            return int(port)
        except Exception:
            pass
    
    # 默认端口
    return 19377


def get_default_host() -> str:
    """
    获取服务默认监听地址
    
    Returns:
        str: 服务主机地址（默认 0.0.0.0）
    """
    if CONFIG_FILE.exists():
        try:
            config = _load_config_raw()
            return config.get('server', {}).get('host', '0.0.0.0')
        except Exception:
            pass
    return '0.0.0.0'


def get_server_url() -> str:
    """
    获取服务完整 URL（用于 CLI 调用 API）
    
    优先级：
    1. BRIDGE_SERVER_URL 环境变量
    2. 根据 host + port 自动构建
    
    Returns:
        str: 服务 URL（如 http://localhost:19377）
    """
    # 环境变量优先级最高
    env_url = os.getenv("BRIDGE_SERVER_URL")
    if env_url:
        return env_url.rstrip('/')
    
    # 自动构建
    host = get_default_host()
    port = get_default_port()
    
    # localhost 处理（0.0.0.0 → localhost）
    if host in ('0.0.0.0', '127.0.0.1'):
        host = 'localhost'
    
    return f"http://{host}:{port}"


def get_api_base_url() -> str:
    """
    获取 API 基础 URL（带 /v1 前缀）
    
    Returns:
        str: API 基础 URL（如 http://localhost:19377/v1）
    """
    return f"{get_server_url()}/v1"


# ============ 认证配置 ============

def get_api_key_from_env() -> Optional[str]:
    """
    从环境变量或配置文件获取 API Key
    
    Returns:
        Optional[str]: API Key，如果不存在则返回 None
    """
    # 环境变量优先级最高
    env_key = os.getenv("BRIDGE_SERVER_API_KEY")
    if env_key:
        return env_key
    
    # 从 .env 文件读取
    if ENV_FILE.exists():
        try:
            with open(ENV_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('BRIDGE_SERVER_API_KEY='):
                        return line.split('=', 1)[1].strip()
                    elif line.startswith('API_KEY='):
                        return line.split('=', 1)[1].strip()
        except Exception:
            pass
    
    # 从 config.yaml 读取（第一个 API Key）
    if CONFIG_FILE.exists():
        try:
            config = _load_config_raw()
            api_keys = config.get('auth', {}).get('api_keys', [])
            if api_keys:
                return api_keys[0].get('key')
        except Exception:
            pass
    
    return None


# ============ 工具函数 ============

def ensure_config_dir():
    """确保配置目录存在"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def config_exists() -> bool:
    """检查配置文件是否存在"""
    return CONFIG_FILE.exists()


def is_service_running(timeout: float = 2.0) -> bool:
    """
    检查服务是否运行
    
    Args:
        timeout: HTTP 请求超时时间（秒）
    
    Returns:
        bool: 服务是否可访问
    """
    try:
        import httpx
        response = httpx.get(f"{get_server_url()}/health", timeout=timeout)
        return response.status_code == 200
    except Exception:
        return False


# ============ 常量导出 ============

__all__ = [
    # 路径常量
    'CONFIG_DIR',
    'CONFIG_FILE',
    'ENV_FILE',
    'LOG_DIR',
    'LOG_FILE',
    'USAGE_FILE',
    'BACKUP_DIR',
    
    # 配置函数
    'get_default_port',
    'get_default_host',
    'get_server_url',
    'get_api_base_url',
    'get_api_key_from_env',
    
    # 工具函数
    'ensure_config_dir',
    'config_exists',
    'is_service_running',
]
