#!/usr/bin/env python3
"""
Bridge Server CLI 工具
命令行管理界面
"""

import sys
import os
import json
import time
import httpx
import yaml
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

# 导入共享配置模块
from config import (
    CONFIG_DIR,
    CONFIG_FILE,
    LOG_DIR,
    LOG_FILE,
    USAGE_FILE,
    get_server_url,
    get_server_url_candidates,
    get_default_port,
    get_api_key_from_env,
    is_service_running,
    get_service_runtime_status,
)

# 安装目录
INSTALL_DIR = Path(os.getenv("INSTALL_DIR", Path.home() / ".local" / "opt" / "bridge-server"))

# 颜色定义
class Colors:
    HEADER = '\\033[95m'
    BLUE = '\\033[94m'
    CYAN = '\\033[96m'
    GREEN = '\\033[92m'
    YELLOW = '\\033[93m'
    RED = '\\033[91m'
    ENDC = '\\033[0m'
    BOLD = '\\033[1m'

def print_success(text): print(f"{Colors.GREEN}✓{Colors.ENDC} {text}")
def print_error(text): print(f"{Colors.RED}✗{Colors.ENDC} {text}")
def print_warning(text): print(f"{Colors.YELLOW}⚠{Colors.ENDC} {text}")
def print_info(text): print(f"{Colors.BLUE}ℹ{Colors.ENDC} {text}")


def _iter_server_urls():
    """按优先级返回可尝试的服务地址。"""
    return get_server_url_candidates()


def _request_with_fallback(method: str, path: str, retry_statuses=None, **kwargs):
    """对多个候选服务地址执行请求，直到成功或命中最后一个错误。"""
    last_error = None
    retry_statuses = set(retry_statuses or [])
    candidates = list(_iter_server_urls())
    for index, base_url in enumerate(candidates):
        url = f"{base_url.rstrip('/')}{path}"
        try:
            response = getattr(httpx, method.lower())(url, **kwargs)
            if response.status_code in retry_statuses and index < len(candidates) - 1:
                continue
            return response
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("未找到可用的 Bridge Server 地址")

def load_config() -> dict:
    """加载配置文件"""
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def save_usage(usage_data: dict):
    """保存用量数据"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(USAGE_FILE, 'w', encoding='utf-8') as f:
        json.dump(usage_data, f, indent=2, ensure_ascii=False)

def load_usage() -> dict:
    """加载用量数据"""
    if not USAGE_FILE.exists():
        return {"days": {}}
    with open(USAGE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def record_usage(model: str, tokens: int, cost: float):
    """记录用量"""
    usage = load_usage()
    today = datetime.now().strftime("%Y-%m-%d")
    
    if today not in usage["days"]:
        usage["days"][today] = {"requests": 0, "tokens": 0, "cost": 0.0, "models": {}}
    
    usage["days"][today]["requests"] += 1
    usage["days"][today]["tokens"] += tokens
    usage["days"][today]["cost"] += cost
    
    if model not in usage["days"][today]["models"]:
        usage["days"][today]["models"][model] = {"requests": 0, "tokens": 0, "cost": 0.0}
    
    usage["days"][today]["models"][model]["requests"] += 1
    usage["days"][today]["models"][model]["tokens"] += tokens
    usage["days"][today]["models"][model]["cost"] += cost
    
    save_usage(usage)

# ============ CLI 命令 ============

def cmd_status():
    """查看服务状态"""
    print(f"\n{Colors.BOLD}Bridge Server 状态{Colors.ENDC}\n")

    # 检查配置文件
    if CONFIG_FILE.exists():
        print_success(f"配置文件：{CONFIG_FILE}")
    else:
        print_error("配置文件不存在")

    status = get_service_runtime_status(timeout=2)

    if status["api_ok"]:
        print_success("服务状态：运行中")
        if status.get("server_version"):
            print_info(f"版本：{status['server_version']}")
    elif status["running"]:
        print_success("服务状态：运行中（本地健康检查不可达）")
        if status["process_running"]:
            print_info("进程：已检测到 Bridge Server 运行进程")
        if status["api_error"]:
            print_warning(f"本地 /health 检查失败：{status['api_error']}")
    else:
        print_warning("服务状态：未运行")

    # 检查端口
    port = get_default_port()
    if status["port_listening"]:
        print_success(f"端口 {port}：已监听")
    else:
        print_warning(f"端口 {port}：未监听")

    print()

def cmd_start():
    """启动服务"""
    print("启动 Bridge Server...")
    
    import subprocess
    
    # 检测运行环境
    def detect_env():
        if Path("/.dockerenv").exists():
            return "docker"
        try:
            result = subprocess.run(["systemctl", "--user", "status"], capture_output=True, text=True)
            if result.returncode == 0:
                return "linux-systemd"
        except Exception:
            pass
        try:
            result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
            if result.returncode == 0:
                return "macos-launchd"
        except Exception:
            pass
        return "standalone"
    
    env = detect_env()
    
    if env == "linux-systemd":
        try:
            result = subprocess.run(["systemctl", "--user", "start", "bridge-server"], capture_output=True, text=True)
            if result.returncode == 0:
                print_success("服务已启动（systemd）")
                return
        except Exception:
            pass
    elif env == "macos-launchd":
        try:
            result = subprocess.run(["launchctl", "start", "com.bridge-server.app"], capture_output=True, text=True)
            if result.returncode == 0:
                print_success("服务已启动（launchd）")
                return
        except Exception:
            pass
    
    # 备用方案：直接启动
    print_warning("系统服务不可用，使用后台进程方式...")
    src_dir = INSTALL_DIR / "src"
    if not src_dir.exists():
        src_dir = Path(__file__).parent
    
    # 确保日志目录存在
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    os.chdir(src_dir)
    # 安全修复：使用 subprocess.run 替代 os.system，防止命令注入
    import subprocess
    import sys
    log_file = open(LOG_FILE, 'a')
    port = str(get_default_port())
    subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "bridge_server.runtime:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", port],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True
    )
    log_file.close()
    print_success("服务已启动（后台）")

def cmd_stop():
    """停止服务"""
    import subprocess
    
    # 检测运行环境
    def detect_env():
        if Path("/.dockerenv").exists():
            return "docker"
        try:
            result = subprocess.run(["systemctl", "--user", "status"], capture_output=True, text=True)
            if result.returncode == 0:
                return "linux-systemd"
        except Exception:
            pass
        try:
            result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
            if result.returncode == 0:
                return "macos-launchd"
        except Exception:
            pass
        return "standalone"
    
    env = detect_env()
    
    if env == "linux-systemd":
        try:
            result = subprocess.run(["systemctl", "--user", "stop", "bridge-server"], capture_output=True, text=True)
            if result.returncode == 0:
                print_success("服务已停止（systemd）")
                return
        except Exception:
            pass
    elif env == "macos-launchd":
        try:
            result = subprocess.run(["launchctl", "stop", "com.bridge-server.app"], capture_output=True, text=True)
            if result.returncode == 0:
                print_success("服务已停止（launchd）")
                return
        except Exception:
            pass
    
    # 备用方案：kill 进程
    print_warning("系统服务不可用，尝试停止后台进程...")
    
    # 尝试通过 PID 文件停止
    pid_file = CONFIG_DIR / "bridge-server.pid"
    if pid_file.exists():
        try:
            with open(pid_file, 'r') as f:
                pid = f.read().strip()
            os.kill(int(pid), 9)
            pid_file.unlink()
            print_success("服务已停止（PID file）")
            return
        except Exception:
            pass
    
    # 最后手段：pkill（静态命令，无用户输入）
    subprocess.run(["pkill", "-f", "uvicorn bridge_server.runtime:app"], check=False, capture_output=True, text=True)
    subprocess.run(["pkill", "-f", "uvicorn app.main:app"], check=False, capture_output=True, text=True)
    print_success("服务已停止")

def cmd_restart():
    """重启服务"""
    cmd_stop()
    time.sleep(2)
    cmd_start()

def cmd_logs(tail: int = 50, follow: bool = False):
    """查看日志"""
    print(f"\n{Colors.BOLD}最近 {tail} 条日志{Colors.ENDC}\n")
    
    # 尝试 systemd 日志
    import subprocess
    try:
        cmd = ["journalctl", "-u", "bridge-server", "-n", str(tail)]
        if follow:
            cmd.append("-f")
        result = subprocess.run(cmd)
        if result.returncode == 0:
            return
    except Exception:
        pass
    
    # 备用方案：查看文件日志
    if LOG_FILE.exists():
        with open(LOG_FILE, 'r') as f:
            lines = f.readlines()[-tail:]
            for line in lines:
                print(line.strip())
    else:
        print_warning("日志文件不存在")

def cmd_test():
    """测试连接"""
    print(f"\n{Colors.BOLD}测试 Bridge Server 连接{Colors.ENDC}\n")

    # 测试健康检查
    print("1. 健康检查...", end=" ")
    try:
        response = _request_with_fallback("GET", "/health", timeout=5)
        if response.status_code == 200:
            print_success("OK")
        else:
            print_error(f"失败：{response.status_code}")
    except Exception as e:
        print_error(f"失败：{e}")

    # 测试 API
    print("2. API 测试...", end=" ")
    try:
        response = _request_with_fallback(
            "GET",
            "/v1/models",
            headers={"Authorization": "Bearer test"},
            timeout=10,
        )
        if response.status_code in [200, 401]:
            print_success("OK")
        else:
            print_error(f"失败：{response.status_code}")
    except Exception as e:
        print_error(f"失败：{e}")

    # 测试路由
    print("3. 路由配置...", end=" ")
    try:
        response = _request_with_fallback("GET", "/api/routing", timeout=5)
        if response.status_code == 200:
            print_success("OK")
            data = response.json()
            print_info(f"策略：{data.get('strategy', 'unknown')}")
        else:
            print_error(f"失败：{response.status_code}")
    except Exception as e:
        print_error(f"失败：{e}")

    print()

def cmd_usage(period: str = "today"):
    """查看用量统计"""
    print(f"\n{Colors.BOLD}用量统计{Colors.ENDC}\n")
    
    usage = load_usage()
    days = usage.get("days", {})
    
    if period == "today":
        target_date = datetime.now().strftime("%Y-%m-%d")
        days_data = {target_date: days.get(target_date, {})}
    elif period == "week":
        target_dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
        days_data = {d: days.get(d, {}) for d in target_dates}
    elif period == "month":
        target_dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(30)]
        days_data = {d: days.get(d, {}) for d in target_dates}
    else:
        days_data = days
    
    # 统计总量
    total_requests = sum(d.get("requests", 0) for d in days_data.values())
    total_tokens = sum(d.get("tokens_in", 0) + d.get("tokens_out", 0) for d in days_data.values())
    total_cost = sum(d.get("cost", 0) for d in days_data.values())
    
    print(f"{Colors.CYAN}总计{Colors.ENDC}")
    print(f"  请求数：{total_requests:,}")
    print(f"  Token 数：{total_tokens:,}")
    print(f"  总费用：¥{total_cost:.2f}")
    print()
    
    # 按天统计
    if period != "today":
        print(f"{Colors.CYAN}按天统计{Colors.ENDC}")
        for date, data in sorted(days_data.items(), reverse=True):
            if data:
                print(f"  {date}: {data.get('requests', 0):,} 请求 | ¥{data.get('cost', 0):.2f}")
        print()
    
    # 模型分布
    all_models = {}
    for data in days_data.values():
        for model, model_data in data.get("models", {}).items():
            if model not in all_models:
                all_models[model] = {"requests": 0, "cost": 0.0}
            all_models[model]["requests"] += model_data.get("requests", 0)
            all_models[model]["cost"] += model_data.get("cost", 0.0)
    
    if all_models:
        print(f"{Colors.CYAN}模型分布{Colors.ENDC}")
        for model, data in sorted(all_models.items(), key=lambda x: x[1]["requests"], reverse=True):
            print(f"  {model}: {data['requests']:,} 请求 | ¥{data['cost']:.2f}")
    
    print()


def cmd_usage_records(period: str = "today"):
    """查看用量记录（v1.6.0 新增）"""
    print(f"\n{Colors.BOLD}用量记录 ({period}){Colors.ENDC}\n")
    
    try:
        import httpx
        server_url = get_server_url()
        response = httpx.get(
            f"{server_url}/api/v1/usage/records?period={period}",
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            records = data.get("records", [])
            
            if not records:
                print_info("暂无记录")
                return
            
            print(f"{'日期':<12} {'请求数':>10} {'费用':>10}")
            print("-" * 34)
            for record in records[:20]:  # 只显示最新 20 条
                date = record.get("date", "N/A")
                requests = record.get("requests", 0)
                cost = record.get("cost", 0)
                print(f"{date:<12} {requests:>10} ¥{cost:>9.2f}")
        else:
            print_error(f"获取失败：{response.status_code}")
    except Exception as e:
        print_error(f"获取失败：{e}")
    
    print()

def cmd_backup(backup_file: Optional[str] = None):
    """备份配置"""
    if not backup_file:
        backup_file = f"bridge-server-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.tar.gz"
    
    print(f"备份配置到 {backup_file}...")
    
    import subprocess
    try:
        # 备份配置文件
        if CONFIG_DIR.exists():
            subprocess.run(["tar", "-czf", backup_file, "-C", str(CONFIG_DIR.parent), CONFIG_DIR.name])
            print_success(f"备份完成：{backup_file}")
        else:
            print_error("配置目录不存在")
    except Exception as e:
        print_error(f"备份失败：{e}")

def cmd_restore(backup_file: str):
    """恢复配置"""
    print(f"从 {backup_file} 恢复配置...")
    
    import subprocess
    try:
        subprocess.run(["tar", "-xzf", backup_file, "-C", str(Path.home())])
        print_success("恢复完成")
    except Exception as e:
        print_error(f"恢复失败：{e}")

def cmd_setup():
    """运行配置向导"""
    print("启动配置向导...")
    wizard_path = Path(__file__).parent / "setup-wizard.py"
    if wizard_path.exists():
        # 安全修复：使用 subprocess.run 替代 os.system，防止命令注入
        import subprocess
        import sys
        # 使用当前 Python 解释器路径（跨平台兼容）
        result = subprocess.run(
            [sys.executable, str(wizard_path)],
            check=False
        )
        if result.returncode != 0:
            print_error(f"配置向导执行失败，返回码：{result.returncode}")
    else:
        print_error("配置向导不存在")

def cmd_panel_token(reset: bool = False):
    """生成或显示面板访问 Token"""
    sys.path.insert(0, str(INSTALL_DIR / 'src'))
    try:
        from bridge_server.admin_api import get_panel_token, generate_panel_token
    except ImportError:
        import yaml as _yaml
        config_dir = Path.home() / ".bridge-server"
        auth_file = config_dir / "auth.yaml"
        auth = {}
        if auth_file.exists():
            with open(auth_file) as f:
                auth = _yaml.safe_load(f) or {}
        if reset or 'panel_token' not in auth:
            import secrets as _secrets
            _token = "pt-" + _secrets.token_hex(24)
            auth['panel_token'] = _token
            config_dir.mkdir(parents=True, exist_ok=True)
            with open(auth_file, 'w') as f:
                _yaml.safe_dump(auth, f)
        _stored = auth.get('panel_token', '')
        get_panel_token = lambda: _stored
        generate_panel_token = lambda: _stored

    token = get_panel_token()
    if not token or reset:
        token = generate_panel_token()
        print_success("已生成新的 Panel Token")

    config = load_config()
    port = config.get('server', {}).get('port', 19377)

    print()
    print(f"{Colors.BOLD}Bridge Server 管理面板{Colors.ENDC}")
    print()
    print(f"  面板地址：{Colors.CYAN}http://localhost:{port}/ui{Colors.ENDC}")
    print(f"  Panel Token：{Colors.GREEN}{token}{Colors.ENDC}")
    print()


def _parse_cli_value(prefix: str, default=None):
    for arg in sys.argv:
        if arg.startswith(prefix + "="):
            return arg.split("=", 1)[1]
    return default


def cmd_api_key(args):
    """管理外部连接 API Keys。"""
    sub = args[0].lower() if args else "list"
    try:
        if sub == "list":
            resp = _admin_api("GET", "/api-keys")
            resp.raise_for_status()
            keys = resp.json().get("api_keys", [])
            print(f"\n{Colors.BOLD}外部连接 API Keys{Colors.ENDC}\n")
            if not keys:
                print_info("暂无 API Key")
                return
            for item in keys:
                expires = item.get("expires_at_iso") or "永不过期"
                active = f"{Colors.GREEN}启用{Colors.ENDC}" if item.get("active") else f"{Colors.RED}停用{Colors.ENDC}"
                models = ", ".join(item.get("model_permissions") or ["*"])
                print(f"  {item['id']}  {Colors.BOLD}{item['name']}{Colors.ENDC}  {active}")
                print(f"      Key: {item.get('key_preview', 'sk-****')}  截止: {expires}")
                print(f"      模型权限: {models}")
            print()
            return

        if sub == "create":
            if len(args) < 2:
                print_error("用法: bridge-server api-key create <名称> [--models=a,b] [--expires=YYYY-MM-DDTHH:MM:SS]")
                return
            name = args[1]
            models = _parse_cli_value("--models", "*")
            expires = _parse_cli_value("--expires", None)
            body = {
                "name": name,
                "model_permissions": [m.strip() for m in models.split(",") if m.strip()],
            }
            if expires:
                body["expires_at_iso"] = expires
            resp = _admin_api("POST", "/api-keys", json_data=body)
            resp.raise_for_status()
            item = resp.json()["api_key"]
            print_success(f"已创建 API Key: {item['name']}")
            print_warning("请立即保存，明文 Key 只显示这一次。")
            print(f"\n  API Key: {Colors.GREEN}{item['token']}{Colors.ENDC}\n")
            return

        if sub == "update":
            if len(args) < 2:
                print_error("用法: bridge-server api-key update <id> [--name=新名称] [--models=a,b] [--expires=YYYY-MM-DDTHH:MM:SS] [--clear-expires] [--active=true|false]")
                return
            key_id = args[1]
            body = {}
            name = _parse_cli_value("--name", None)
            models = _parse_cli_value("--models", None)
            expires = _parse_cli_value("--expires", None)
            active = _parse_cli_value("--active", None)
            if name is not None:
                body["name"] = name
            if models is not None:
                body["model_permissions"] = [m.strip() for m in models.split(",") if m.strip()]
            if expires is not None:
                body["expires_at_iso"] = expires
            if "--clear-expires" in sys.argv:
                body["clear_expires_at"] = True
            if active is not None:
                body["active"] = active.lower() in ("1", "true", "yes", "y", "on")
            resp = _admin_api("PUT", f"/api-keys/{key_id}", json_data=body)
            resp.raise_for_status()
            print_success("API Key 已更新")
            return

        if sub in ("delete", "revoke"):
            if len(args) < 2:
                print_error("用法: bridge-server api-key delete <id>")
                return
            resp = _admin_api("DELETE", f"/api-keys/{args[1]}")
            resp.raise_for_status()
            print_success("API Key 已停用")
            return

        print_error(f"未知 api-key 子命令: {sub}  (可用: list, create, update, delete)")
    except Exception as e:
        print_error(str(e))

def cmd_route_test(text: str):
    """测试路由"""
    print(f"\n{Colors.BOLD}路由测试{Colors.ENDC}\n")
    print(f"输入：{text[:50]}...")
    
    try:
        server_url = get_server_url()
        response = httpx.post(
            f"{server_url}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": text}]},
            headers={"Authorization": "Bearer test", "Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            routing = data.get("usage", {}).get("routing", {})
            print_success(f"路由成功")
            print_info(f"任务类型：{routing.get('task_type', 'unknown')}")
            print_info(f"选择模型：{routing.get('selected_model', 'unknown')}")
            print_info(f"路由原因：{routing.get('reason', 'unknown')}")
        else:
            print_error(f"失败：{response.status_code}")
    except Exception as e:
        print_error(f"失败：{e}")
    
    print()


def cmd_routing_strategy():
    """查看路由策略（v1.6.0 新增）"""
    print(f"\n{Colors.BOLD}路由策略{Colors.ENDC}\n")

    try:
        response = _request_with_fallback("GET", "/api/routing", retry_statuses={404}, timeout=5)
        if response.status_code == 404:
            response = _request_with_fallback("GET", "/api/v1/routing/strategy", timeout=5)

        if response.status_code == 200:
            data = response.json()
            print(f"策略：{data.get('strategy', 'unknown')}")
            effective = data.get('effective_strategy')
            if effective:
                print(f"生效策略：{effective}")
            print(f"模型映射：{json.dumps(data.get('model_mapping', {}), indent=2, ensure_ascii=False)}")
        else:
            print_error(f"获取失败：{response.status_code}")
    except Exception as e:
        print_error(f"获取失败：{e}")

    print()


def cmd_routing_test(message: str):
    """测试路由决策（v1.6.0 新增）"""
    print(f"\n{Colors.BOLD}路由决策测试{Colors.ENDC}\n")
    print(f"消息：{message[:50]}...")
    
    try:
        import httpx
        server_url = get_server_url()
        response = httpx.post(
            f"{server_url}/api/v1/routing/test",
            json={"message": message},
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            print_success(f"路由决策完成")
            print_info(f"任务类型：{data.get('task_type', 'unknown')}")
            print_info(f"选择模型：{data.get('selected_model', 'unknown')}")
            print_info(f"原因：{data.get('reason', 'unknown')}")
        else:
            print_error(f"失败：{response.status_code}")
    except Exception as e:
        print_error(f"失败：{e}")
    
    print()


def cmd_providers_list():
    """列出 Provider（v1.6.0 新增）"""
    print(f"\n{Colors.BOLD}可用 Provider{Colors.ENDC}\n")

    try:
        response = _request_with_fallback("GET", "/api/models", retry_statuses={404}, timeout=5)
        legacy_provider_payload = False
        if response.status_code == 404:
            response = _request_with_fallback("GET", "/api/v1/providers/list", timeout=5)
            legacy_provider_payload = True

        if response.status_code == 200:
            data = response.json()
            if legacy_provider_payload:
                providers = data.get("providers", [])
                provider_map = {
                    prov.get("name", "unknown"): prov.get("models", [])
                    for prov in providers
                }
            else:
                models = data.get("models", [])
                provider_map = {}
                for model in models:
                    provider_name = model.get("provider") or model.get("owned_by") or "unknown"
                    provider_map.setdefault(provider_name, []).append(model)

            if not provider_map:
                print_info("暂无 Provider")
                return

            for provider_name in sorted(provider_map.keys()):
                print(f"✓ {provider_name}")
                for model in provider_map[provider_name][:5]:
                    model_id = model.get("id", "unknown")
                    cost = model.get("input_cost_per_1k")
                    if cost is None:
                        cost = model.get("cost")
                    if cost is None:
                        print(f"    - {model_id}")
                    else:
                        print(f"    - {model_id} (¥{float(cost):.4f}/K tokens)")
                if len(provider_map[provider_name]) > 5:
                    print(f"    ... 还有 {len(provider_map[provider_name]) - 5} 个模型")
        else:
            print_error(f"获取失败：{response.status_code}")
    except Exception as e:
        print_error(f"获取失败：{e}")

    print()


def cmd_health():
    """健康检查（v1.6.0 新增）"""
    print(f"\n{Colors.BOLD}健康检查{Colors.ENDC}\n")
    
    server_url = get_server_url()
    checks = [
        ("/health", "健康检查"),
        ("/ready", "就绪检查"),
        ("/api/v1/info", "API 信息"),
    ]
    
    for endpoint, name in checks:
        try:
            import httpx
            response = httpx.get(f"{server_url}{endpoint}", timeout=5)
            
            if response.status_code == 200:
                print_success(f"{name}: OK")
            else:
                print_warning(f"{name}: {response.status_code}")
        except Exception as e:
            print_error(f"{name}: {e}")
    
    print()


def cmd_auth_login(username: str, password: str):
    """登录获取 JWT Token（v1.6.0 新增）"""
    print(f"\n{Colors.BOLD}登录{Colors.ENDC}\n")
    
    try:
        import httpx
        server_url = get_server_url()
        response = httpx.post(
            f"{server_url}/api/v1/auth/token",
            json={"username": username, "password": password},
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            print_success(f"登录成功")
            print_info(f"Token: {data.get('access_token', '')[:50]}...")
            print_info(f"过期时间：{data.get('expires_in', 0) / 86400:.0f} 天")
            
            # 保存 token 到配置文件
            config = load_config()
            if 'auth' not in config:
                config['auth'] = {}
            config['auth']['last_token'] = data.get('access_token')
            
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                yaml.safe_dump(config, f, allow_unicode=True)
            
            print_success("Token 已保存")
        else:
            print_error(f"登录失败：{response.status_code}")
    except Exception as e:
        print_error(f"登录失败：{e}")
    
    print()

def cmd_benchmark():
    """运行模型能力基准测试"""
    import subprocess
    benchmark_script = Path(__file__).parent / "model-benchmark.py"
    if not benchmark_script.exists():
        print_error("benchmark 模块未找到，请确认 cli/model-benchmark.py 存在")
        sys.exit(1)
    subprocess.run([sys.executable, str(benchmark_script)] + sys.argv[2:])


# ============ 管理 API 鉴权辅助 ============

def _get_panel_token() -> str:
    """从 auth.yaml 读取 Panel Token"""
    auth_file = Path.home() / ".bridge-server" / "auth.yaml"
    if auth_file.exists():
        with open(auth_file, encoding="utf-8") as f:
            auth = yaml.safe_load(f) or {}
        return auth.get("panel_token", "")
    return ""


def _admin_api(method: str, path: str, json_data=None):
    """携带鉴权调用管理 API"""
    token = _get_panel_token()
    if not token:
        raise RuntimeError("未找到 Panel Token，请先运行: bridge-server panel-token")
    server_url = get_server_url()
    headers = {"X-Panel-Token": token}
    resp = httpx.request(
        method, f"{server_url}/api/admin{path}",
        headers=headers, json=json_data, timeout=5
    )
    if resp.status_code == 401:
        raise RuntimeError("Panel Token 无效，请运行: bridge-server panel-token --reset")
    return resp


def cmd_model_list():
    """列出所有 Provider 及其模型"""
    try:
        resp = _admin_api("GET", "/config")
        resp.raise_for_status()
        data = resp.json()
        providers = data.get("providers", [])
        print(f"\n{Colors.BOLD}Provider 模型列表{Colors.ENDC}\n")
        if not providers:
            print_info("暂无 Provider 配置")
            return
        for p in providers:
            auth_type = p.get("auth_type", "api_key")
            print(f"  {Colors.BOLD}{p['name']}{Colors.ENDC}  ({auth_type})  {Colors.CYAN}{p.get('base_url', '')}{Colors.ENDC}")
            for m in p.get("models", []):
                mid = m.get("id", m) if isinstance(m, dict) else str(m)
                ic = m.get("input_cost", 0) if isinstance(m, dict) else 0
                oc = m.get("output_cost", 0) if isinstance(m, dict) else 0
                cost_str = f"  {Colors.YELLOW}输入¥{ic:.4f}/K  输出¥{oc:.4f}/K{Colors.ENDC}" if (ic or oc) else ""
                print(f"      {mid}{cost_str}")
        print()
    except Exception as e:
        print_error(str(e))


def cmd_scenario_list():
    """列出所有场景路由配置"""
    try:
        resp = _admin_api("GET", "/routing")
        resp.raise_for_status()
        data = resp.json()
        strategy = data.get("strategy", "fallback")
        scenarios = data.get("scenarios", {})
        print(f"\n{Colors.BOLD}场景路由配置{Colors.ENDC}  策略: {Colors.CYAN}{strategy}{Colors.ENDC}\n")
        if not scenarios:
            print_info("暂无场景配置")
            return
        for name, cfg in scenarios.items():
            enabled = cfg.get("enabled", True)
            model = cfg.get("model") or f"{Colors.YELLOW}(未设置){Colors.ENDC}"
            mark = f"{Colors.GREEN}✓{Colors.ENDC}" if enabled else f"{Colors.RED}✗{Colors.ENDC}"
            print(f"  {mark}  {Colors.BOLD}{name:<20}{Colors.ENDC}  →  {model}")
        print()
    except Exception as e:
        print_error(str(e))


def cmd_scenario_set(name: str, model_str: str):
    """设置某个场景使用的模型 (provider/model-id)"""
    try:
        resp = _admin_api("PATCH", f"/routing/scenarios/{name}",
                          json_data={"model": model_str, "enabled": True, "patterns": []})
        resp.raise_for_status()
        print_success(f"场景 '{name}' 已更新 → {model_str}")
        print_info("路由已热重载，无需重启服务")
    except Exception as e:
        print_error(str(e))


def cmd_reload():
    """热重载服务器配置（无需重启）"""
    try:
        resp = _admin_api("POST", "/reload")
        resp.raise_for_status()
        data = resp.json()
        reloaded = data.get("reloaded", [])
        print_success(f"配置已热重载: {', '.join(reloaded) if reloaded else '路由'}")
    except Exception as e:
        print_error(str(e))


# ============ 自定义路由器管理 ============

def cmd_router(args):
    """自定义路由器管理"""
    sub = args[0].lower() if args else "list"

    if sub == "list":
        try:
            resp = _admin_api("GET", "/router/list")
            resp.raise_for_status()
            data = resp.json()
            active = data.get("active")
            routers = data.get("routers", [])
            print(f"\n{Colors.BOLD}自定义路由器列表{Colors.ENDC}\n")
            if not routers:
                print_info("未安装任何自定义路由器")
            else:
                for r in routers:
                    mark = f"{Colors.GREEN}● 激活{Colors.ENDC}" if r.get("active") else f"{Colors.YELLOW}○ 未激活{Colors.ENDC}"
                    print(f"  {mark}  {Colors.BOLD}{r['name']}{Colors.ENDC}  v{r.get('version','?')}")
                    if r.get("description"):
                        print(f"         {r['description']}")
            if active:
                print(f"\n  当前激活: {Colors.GREEN}{active}{Colors.ENDC}")
            else:
                print(f"\n  当前使用: {Colors.CYAN}内置 SmartRouter{Colors.ENDC}")
            print()
        except Exception as e:
            print_error(str(e))

    elif sub == "import":
        if not args[1:]:
            print_error("用法: bridge-server router import <路径>  (目录或 .bspkg 文件)")
            sys.exit(1)
        path = " ".join(args[1:])
        try:
            resp = _admin_api("POST", "/router/import", json_data={"path": path})
            resp.raise_for_status()
            data = resp.json()
            print_success(f"路由器 '{data['name']}' v{data['version']} 安装成功")
            if data.get("description"):
                print_info(data["description"])
            print_info(f"激活命令: bridge-server router activate {data['name']}")
        except Exception as e:
            resp_data = {}
            if hasattr(e, "response") and e.response is not None:
                try:
                    resp_data = e.response.json()
                except Exception:
                    pass
            print_error(resp_data.get("detail") or str(e))

    elif sub == "activate":
        if not args[1:]:
            print_error("用法: bridge-server router activate <路由器名>")
            sys.exit(1)
        name = args[1]
        try:
            resp = _admin_api("PUT", "/router/activate", json_data={"name": name})
            resp.raise_for_status()
            print_success(f"路由器 '{name}' 已激活，后续请求将使用自定义路由")
        except Exception as e:
            print_error(str(e))

    elif sub == "deactivate":
        try:
            resp = _admin_api("POST", "/router/deactivate")
            resp.raise_for_status()
            print_success("自定义路由器已停用，回退到内置 SmartRouter")
        except Exception as e:
            print_error(str(e))

    elif sub == "rollback":
        name = args[1] if args[1:] else None
        if not name:
            # rollback active router
            try:
                resp = _admin_api("GET", "/router/active")
                name = resp.json().get("active")
            except Exception:
                pass
        if not name:
            print_error("用法: bridge-server router rollback <路由器名>")
            sys.exit(1)
        try:
            resp = _admin_api("POST", f"/router/rollback/{name}")
            resp.raise_for_status()
            print_success(resp.json().get("message", f"'{name}' 已回滚"))
        except Exception as e:
            print_error(str(e))

    elif sub == "remove":
        if not args[1:]:
            print_error("用法: bridge-server router remove <路由器名>")
            sys.exit(1)
        name = args[1]
        try:
            resp = _admin_api("DELETE", f"/router/{name}")
            resp.raise_for_status()
            print_success(f"路由器 '{name}' 已卸载")
        except Exception as e:
            print_error(str(e))

    elif sub == "test":
        name = args[1] if args[1:] else None
        if not name:
            # test active router
            try:
                resp = _admin_api("GET", "/router/active")
                name = resp.json().get("active")
            except Exception:
                pass
        if not name:
            print_error("用法: bridge-server router test <路由器名> [消息]")
            sys.exit(1)
        message = " ".join(args[2:]) if args[2:] else "帮我写一个快速排序算法"
        try:
            resp = _admin_api("POST", "/router/test", json_data={"name": name, "message": message})
            resp.raise_for_status()
            result = resp.json()
            if result.get("success"):
                d = result["decision"]
                print_success(f"路由成功  ({result['elapsed_ms']}ms)")
                print(f"  Provider: {Colors.BOLD}{d['provider']}{Colors.ENDC}")
                print(f"  Model:    {Colors.CYAN}{d['model']}{Colors.ENDC}")
                print(f"  置信度:   {d['confidence']:.2f}")
                print(f"  原因:     {d['reason']}")
            else:
                print_error(f"路由失败: {result.get('error')}")
        except Exception as e:
            print_error(str(e))

    else:
        print_error(f"未知 router 子命令: {sub}")
        print("  可用子命令: list, import, activate, deactivate, rollback, remove, test")


def print_help():
    """显示帮助"""
    help_text = f"""
{Colors.BOLD}Bridge Server CLI v1.7.0{Colors.ENDC}

{Colors.CYAN}用法:{Colors.ENDC}
  bridge-server <command> [options]

{Colors.CYAN}命令:{Colors.ENDC}
  服务管理:
    status          查看服务状态
    start           启动服务
    stop            停止服务
    restart         重启服务
    logs [n]        查看日志（默认 50 条）
    health          健康检查
    reload          热重载配置（无需重启）

  模型 & 场景管理（需要 Panel Token）:
    model list      列出所有 Provider 及模型
    scenario list   列出所有场景路由配置
    scenario set <scene> <provider/model>  设置场景模型并热重载

  用量统计:
    usage           查看用量统计（--week / --month）
    usage-records   查看原始用量记录

  路由管理:
    test            测试连接
    route-test      测试路由
    routing         查看路由策略
    routing-test    测试路由决策
    providers       列出 Provider（旧版）

  配置管理:
    backup          备份配置
    restore         恢复配置
    setup           运行配置向导
    benchmark       模型能力基准测试
    panel-token     显示/生成管理面板 Token（--reset 重新生成）
    api-key        管理外部连接 API Keys

  自定义路由器（需要 Panel Token）:
    router list                       列出所有已安装路由器
    router import <路径>               安装路由器（目录或 .bspkg 文件）
    router activate <名称>             激活指定路由器
    router deactivate                  停用，回退到内置 SmartRouter
    router rollback [名称]             回滚到上一个版本
    router remove <名称>               卸载路由器
    router test [名称] [消息]          测试路由器路由决策

  其他:
    help            显示帮助

{Colors.CYAN}示例:{Colors.ENDC}
  bridge-server status
  bridge-server model list
  bridge-server scenario list
  bridge-server scenario set coding my-provider/gpt-4o-mini
  bridge-server reload
  bridge-server panel-token
  bridge-server api-key list
  bridge-server api-key create app-a --models=scnet/Qwen3-235B-A22B,scnet/MiniMax-M2.5 --expires=2026-05-01T00:00:00
  bridge-server logs 100
  bridge-server route-test "用 Python 写个快速排序"
  bridge-server router import ./my-router
  bridge-server router activate my-router
  bridge-server router test my-router "写个快速排序"
  bridge-server router deactivate
"""
    print(help_text)

# ============ 主函数 ============

def main():
    if len(sys.argv) < 2:
        print_help()
        sys.exit(0)
    
    command = sys.argv[1].lower()
    
    if command == "status":
        cmd_status()
    elif command == "start":
        cmd_start()
    elif command == "stop":
        cmd_stop()
    elif command == "restart":
        cmd_restart()
    elif command == "logs":
        tail = int(sys.argv[2]) if len(sys.argv) > 2 else 50
        follow = "-f" in sys.argv
        cmd_logs(tail, follow)
    elif command == "test":
        cmd_test()
    elif command == "usage":
        period = "today"
        if "--week" in sys.argv:
            period = "week"
        elif "--month" in sys.argv:
            period = "month"
        cmd_usage(period)
    elif command == "usage-records" or command == "records":
        period = "today"
        if "--week" in sys.argv:
            period = "week"
        elif "--month" in sys.argv:
            period = "month"
        cmd_usage_records(period)
    elif command == "backup":
        backup_file = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_backup(backup_file)
    elif command == "restore":
        if len(sys.argv) < 3:
            print_error("请指定备份文件")
            sys.exit(1)
        cmd_restore(sys.argv[2])
    elif command == "setup":
        cmd_setup()
    elif command == "panel-token":
        reset = "--reset" in sys.argv
        cmd_panel_token(reset)
    elif command == "api-key":
        cmd_api_key(sys.argv[2:])
    elif command == "benchmark":
        cmd_benchmark()
    elif command == "route-test":
        text = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "你好"
        cmd_route_test(text)
    elif command == "routing":
        cmd_routing_strategy()
    elif command == "routing-test":
        message = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "你好"
        cmd_routing_test(message)
    elif command == "providers":
        cmd_providers_list()
    elif command == "health":
        cmd_health()
    elif command == "reload":
        cmd_reload()
    elif command == "model":
        sub = sys.argv[2].lower() if len(sys.argv) > 2 else "list"
        if sub == "list":
            cmd_model_list()
        else:
            print_error(f"未知 model 子命令: {sub}  (可用: list)")
    elif command == "scenario":
        sub = sys.argv[2].lower() if len(sys.argv) > 2 else "list"
        if sub == "list":
            cmd_scenario_list()
        elif sub == "set":
            if len(sys.argv) < 5:
                print_error("用法: bridge-server scenario set <场景名> <provider/model>")
                sys.exit(1)
            cmd_scenario_set(sys.argv[3], sys.argv[4])
        else:
            print_error(f"未知 scenario 子命令: {sub}  (可用: list, set)")
    elif command == "router":
        cmd_router(sys.argv[2:])
    elif command == "login":
        username = sys.argv[2] if len(sys.argv) > 2 else "admin"
        password = sys.argv[3] if len(sys.argv) > 3 else ""
        cmd_auth_login(username, password)
    elif command == "help" or command == "--help" or command == "-h":
        print_help()
    else:
        print_error(f"未知命令：{command}")
        print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
