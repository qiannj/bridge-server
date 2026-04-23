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
import socket
import subprocess
from pathlib import Path
from typing import List, Optional

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
    1. PORT 环境变量
    2. BRIDGE_SERVER_PORT 环境变量（兼容旧配置）
    3. config.yaml 中的 server.port
    4. 默认值 19377
    
    Returns:
        int: 服务端口号
    """
    # 环境变量优先级最高
    for env_name in ("PORT", "BRIDGE_SERVER_PORT"):
        env_port = os.getenv(env_name)
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


def _discover_runtime_host() -> Optional[str]:
    """尽量推断当前机器对外可达的 IPv4 地址。"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        host = sock.getsockname()[0]
        sock.close()
        if host and not host.startswith("127."):
            return host
    except Exception:
        pass

    commands = [
        ["hostname", "-I"],
        ["hostname", "-i"],
    ]
    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=2)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if result.returncode != 0:
            continue
        for token in result.stdout.split():
            if token and token.count(".") == 3 and not token.startswith("127."):
                return token

    return None


def get_server_url_candidates() -> List[str]:
    """返回 CLI 可尝试的服务 URL 候选列表。"""
    candidates: List[str] = []

    def _add(url: Optional[str]):
        if not url:
            return
        url = url.rstrip('/')
        if url not in candidates:
            candidates.append(url)

    env_url = os.getenv("BRIDGE_SERVER_URL")
    if env_url:
        _add(env_url)
        return candidates

    port = get_default_port()
    host = get_default_host()

    if host in ("0.0.0.0", "127.0.0.1", "localhost"):
        _add(f"http://localhost:{port}")
        _add(f"http://127.0.0.1:{port}")
        runtime_host = _discover_runtime_host()
        if runtime_host:
            _add(f"http://{runtime_host}:{port}")
    else:
        _add(f"http://{host}:{port}")

    return candidates


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


def _is_port_listening(port: int) -> bool:
    """检查目标端口是否存在监听。"""
    commands = [
        ["lsof", "-i", f":{port}"],
        ["ss", "-tln"],
    ]

    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=2)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

        if command[0] == "lsof":
            if result.returncode == 0 and result.stdout.strip():
                return True
        else:
            needle = f":{port}"
            if result.returncode == 0 and needle in result.stdout:
                return True

    return False


def _has_bridge_server_process() -> bool:
    """检查是否存在 Bridge Server 运行进程。"""
    patterns = [
        "uvicorn bridge_server.runtime:app",
        "uvicorn app.main:app",
        "python -m bridge_server.runtime",
    ]

    for pattern in patterns:
        try:
            result = subprocess.run(
                ["pgrep", "-af", pattern],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

        if result.returncode == 0 and result.stdout.strip():
            return True

    return False


def get_service_runtime_status(timeout: float = 2.0) -> dict:
    """综合检查 Bridge Server 运行状态。"""
    status = {
        "api_ok": False,
        "api_error": None,
        "process_running": False,
        "port_listening": False,
        "server_version": None,
    }

    try:
        import httpx

        response = httpx.get(f"{get_server_url()}/health", timeout=timeout)
        if response.status_code == 200:
            status["api_ok"] = True
            try:
                status["server_version"] = response.json().get("version")
            except Exception:
                status["server_version"] = None
        else:
            status["api_error"] = f"HTTP {response.status_code}"
    except Exception as exc:
        status["api_error"] = str(exc)

    port = get_default_port()
    status["process_running"] = _has_bridge_server_process()
    status["port_listening"] = _is_port_listening(port)
    status["running"] = status["api_ok"] or (
        status["process_running"] and status["port_listening"]
    )
    return status


def is_service_running(timeout: float = 2.0) -> bool:
    """兼容旧接口：返回服务是否在运行。"""
    return get_service_runtime_status(timeout=timeout)["running"]


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
    'get_server_url_candidates',
    'get_api_base_url',
    'get_api_key_from_env',
    
    # 工具函数
    'ensure_config_dir',
    'config_exists',
    'is_service_running',
]
