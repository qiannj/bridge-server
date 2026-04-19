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
    get_default_port,
    get_api_key_from_env,
    is_service_running,
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
    
    # 检查服务状态
    try:
        server_url = get_server_url()
        response = httpx.get(f"{server_url}/health", timeout=2)
        if response.status_code == 200:
            print_success("服务状态：运行中")
            data = response.json()
            print_info(f"版本：{data.get('version', 'unknown')}")
        else:
            print_error("服务状态：异常")
    except Exception:
        print_warning("服务状态：未运行")
    
    # 检查端口
    import subprocess
    try:
        port = get_default_port()
        result = subprocess.run(["lsof", "-i", f":{port}"], capture_output=True, text=True)
        if result.returncode == 0:
            print_success(f"端口 {port}：已监听")
        else:
            print_warning(f"端口 {port}：未监听")
    except Exception:
        pass
    
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
    
    server_url = get_server_url()
    
    # 测试健康检查
    print("1. 健康检查...", end=" ")
    try:
        response = httpx.get(f"{server_url}/health", timeout=5)
        if response.status_code == 200:
            print_success("OK")
        else:
            print_error(f"失败：{response.status_code}")
    except Exception as e:
        print_error(f"失败：{e}")
    
    # 测试 API
    print("2. API 测试...", end=" ")
    try:
        response = httpx.post(
            f"{server_url}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer test", "Content-Type": "application/json"},
            timeout=10
        )
        if response.status_code in [200, 401]:  # 401 表示认证正常
            print_success("OK")
        else:
            print_error(f"失败：{response.status_code}")
    except Exception as e:
        print_error(f"失败：{e}")
    
    # 测试路由
    print("3. 路由配置...", end=" ")
    try:
        response = httpx.get(f"{server_url}/api/routing", timeout=5)
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
        import httpx
        server_url = get_server_url()
        response = httpx.get(f"{server_url}/api/v1/routing/strategy", timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            print(f"策略：{data.get('strategy', 'unknown')}")
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
        import httpx
        server_url = get_server_url()
        response = httpx.get(f"{server_url}/api/v1/providers/list", timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            providers = data.get("providers", [])
            
            if not providers:
                print_info("暂无 Provider")
                return
            
            for prov in providers:
                status = "✓" if prov.get("enabled") else "✗"
                print(f"{status} {prov.get('name', 'unknown')}")
                models = prov.get("models", [])
                for model in models[:5]:  # 只显示前 5 个
                    print(f"    - {model.get('id')} (¥{model.get('cost', 0):.4f}/K tokens)")
                if len(models) > 5:
                    print(f"    ... 还有 {len(models) - 5} 个模型")
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

def print_help():
    """显示帮助"""
    help_text = f"""
{Colors.BOLD}Bridge Server CLI v1.6.0{Colors.ENDC}

{Colors.CYAN}用法:{Colors.ENDC}
  bridge-server <command> [options]

{Colors.CYAN}命令:{Colors.ENDC}
  服务管理:
    status          查看服务状态
    start           启动服务
    stop            停止服务
    restart         重启服务
    logs [n]        查看日志（默认 50 条）
    health          健康检查（v1.6.0 新增）

  用量统计:
    usage           查看用量统计
    usage-records   查看用量记录（v1.6.0 新增）

  路由管理:
    test            测试连接
    route-test      测试路由
    routing         查看路由策略（v1.6.0 新增）
    routing-test    测试路由决策（v1.6.0 新增）
    providers       列出 Provider（v1.6.0 新增）

  认证管理:
    login           登录获取 JWT Token（v1.6.0 新增）

  配置管理:
    backup          备份配置
    restore         恢复配置
    setup           运行配置向导

  其他:
    help            显示帮助

{Colors.CYAN}示例:{Colors.ENDC}
  bridge-server status
  bridge-server logs 100
  bridge-server usage --week
  bridge-server route-test "用 Python 写个快速排序"
  bridge-server routing
  bridge-server providers
  bridge-server login
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
