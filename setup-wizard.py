#!/usr/bin/env python3
"""
Bridge Server 交互式配置向导
"""

import os
import sys
import json
import time
import httpx
import yaml
from pathlib import Path
from typing import Dict, List, Optional

# 颜色定义
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_header(text: str):
    print(f"\n{Colors.HEADER}╔{'═' * 50}╗{Colors.ENDC}")
    print(f"{Colors.HEADER}║{Colors.ENDC} {text:^48} {Colors.HEADER}║{Colors.ENDC}")
    print(f"{Colors.HEADER}╚{'═' * 50}╝{Colors.ENDC}\n")

def print_step(step: int, total: int, text: str):
    print(f"\n{Colors.BLUE}【步骤 {step}/{total}】{text}{Colors.ENDC}\n")

def print_success(text: str):
    print(f"{Colors.GREEN}✓{Colors.ENDC} {text}")

def print_error(text: str):
    print(f"{Colors.RED}✗{Colors.ENDC} {text}")

def print_warning(text: str):
    print(f"{Colors.YELLOW}⚠{Colors.ENDC} {text}")

def input_with_default(prompt: str, default: str = "") -> str:
    if default:
        user_input = input(f"{prompt} [{default}]: ").strip()
        return user_input if user_input else default
    else:
        return input(f"{prompt}: ").strip()

def select_option(prompt: str, options: List[str], default: int = 0) -> int:
    print(f"\n{prompt}\n")
    for i, option in enumerate(options, 1):
        print(f"  [{i}] {option}")
    print()
    
    while True:
        try:
            choice = input(f"请选择 [{default + 1}]: ").strip()
            if not choice:
                return default
            choice_num = int(choice)
            if 1 <= choice_num <= len(options):
                return choice_num - 1
            else:
                print_error(f"请输入 1-{len(options)} 之间的数字")
        except ValueError:
            print_error("请输入有效的数字")

def test_api_key(provider: str, api_key: str, base_url: str) -> tuple[bool, str]:
    """测试 API Key 是否有效"""
    print(f"  测试连接...", end=" ", flush=True)
    
    test_payload = {
        "model": "qwen3.5-plus" if provider == "dashscope" else "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": "hi"}]
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            json=test_payload,
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            print_success("连接成功")
            return True, "OK"
        else:
            error_msg = response.json().get('error', {}).get('message', 'Unknown error')
            print_error(f"连接失败：{error_msg}")
            return False, error_msg
    except Exception as e:
        print_error(f"连接失败：{str(e)}")
        return False, str(e)

def configure_dashscope() -> Optional[Dict]:
    """配置阿里云百炼"""
    print(f"\n{Colors.CYAN}→ 阿里云百炼 (DashScope){Colors.ENDC}")
    print("  支持模型：qwen3.5-plus, qwen3.5-flash, qwen-max, qwen3-coder-plus 等\n")
    
    api_key = input_with_default("  API Key", "").strip()
    if not api_key:
        print_warning("跳过阿里云百炼配置")
        return None
    
    base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    success, message = test_api_key("dashscope", api_key, base_url)
    
    if success:
        return {
            "enabled": True,
            "provider": "dashscope",
            "base_url": base_url,
            "api_key": api_key,
            "models": {
                "qwen3.5-flash": {"cost": 0.002, "use_case": "简单任务"},
                "qwen3.5-plus": {"cost": 0.004, "use_case": "通用任务"},
                "qwen3-max": {"cost": 0.02, "use_case": "复杂推理"},
                "qwen3-coder-plus": {"cost": 0.008, "use_case": "代码生成"}
            }
        }
    else:
        print_warning("API Key 验证失败，但仍保存配置（您可以稍后修正）")
        return {
            "enabled": True,
            "provider": "dashscope",
            "base_url": base_url,
            "api_key": api_key
        }

def configure_moonshot() -> Optional[Dict]:
    """配置 Moonshot (Kimi)"""
    print(f"\n{Colors.CYAN}→ Moonshot (Kimi){Colors.ENDC}")
    print("  支持模型：kimi-chat, kimi-k2.5\n")
    
    api_key = input_with_default("  API Key", "").strip()
    if not api_key:
        print_warning("跳过 Moonshot 配置")
        return None
    
    base_url = "https://api.moonshot.cn/v1"
    success, message = test_api_key("moonshot", api_key, base_url)
    
    if success:
        return {
            "enabled": True,
            "provider": "moonshot",
            "base_url": base_url,
            "api_key": api_key,
            "models": {
                "kimi-chat": {"cost": 0.012, "use_case": "长文本"},
                "kimi-k2.5": {"cost": 0.025, "use_case": "创意写作"}
            }
        }
    else:
        return {
            "enabled": True,
            "provider": "moonshot",
            "base_url": base_url,
            "api_key": api_key
        }

def configure_openai() -> Optional[Dict]:
    """配置 OpenAI"""
    print(f"\n{Colors.CYAN}→ OpenAI{Colors.ENDC}")
    print("  支持模型：GPT-3.5-turbo, GPT-4-turbo, GPT-4o\n")
    
    api_key = input_with_default("  API Key", "").strip()
    if not api_key:
        print_warning("跳过 OpenAI 配置")
        return None
    
    base_url = "https://api.openai.com/v1"
    success, message = test_api_key("openai", api_key, base_url)
    
    if success:
        return {
            "enabled": True,
            "provider": "openai",
            "base_url": base_url,
            "api_key": api_key,
            "models": {
                "gpt-3.5-turbo": {"cost": 0.002, "use_case": "简单任务"},
                "gpt-4-turbo": {"cost": 0.01, "use_case": "复杂任务"},
                "gpt-4o": {"cost": 0.015, "use_case": "多模态"}
            }
        }
    else:
        return {
            "enabled": True,
            "provider": "openai",
            "base_url": base_url,
            "api_key": api_key
        }

def configure_minimax() -> Optional[Dict]:
    """配置 MiniMax"""
    print(f"\n{Colors.CYAN}→ MiniMax{Colors.ENDC}")
    print("  支持模型：MiniMax-M2.5\n")
    
    api_key = input_with_default("  API Key", "").strip()
    if not api_key:
        print_warning("跳过 MiniMax 配置")
        return None
    
    base_url = "https://api.minimax.io/v1"
    success, message = test_api_key("minimax", api_key, base_url)
    
    if success:
        return {
            "enabled": True,
            "provider": "minimax",
            "base_url": base_url,
            "api_key": api_key,
            "models": {
                "MiniMax-M2.5": {"cost": 0.005, "use_case": "通用任务"}
            }
        }
    else:
        return {
            "enabled": True,
            "provider": "minimax",
            "base_url": base_url,
            "api_key": api_key
        }

def select_routing_strategy() -> Dict:
    """选择路由策略"""
    strategies = [
        "平衡模式 (Balanced) - 根据任务自动选择，推荐",
        "成本优先 (Cost-First) - 优先使用便宜模型",
        "质量优先 (Quality-First) - 优先使用最强模型",
        "自定义配置"
    ]
    
    choice = select_option("选择路由策略", strategies, 0)
    
    if choice == 0:  # 平衡模式
        return {
            "simple": "qwen3.5-flash",
            "coding": "qwen3-coder-plus",
            "writing": "qwen3.5-plus",
            "analysis": "qwen3.5-plus",
            "creative": "kimi-k2.5",
            "complex": "qwen3-max",
            "general": "qwen3.5-plus"
        }
    elif choice == 1:  # 成本优先
        return {
            "simple": "qwen3.5-flash",
            "coding": "qwen3.5-plus",
            "writing": "qwen3.5-flash",
            "analysis": "qwen3.5-flash",
            "creative": "qwen3.5-plus",
            "complex": "qwen3.5-plus",
            "general": "qwen3.5-flash"
        }
    elif choice == 2:  # 质量优先
        return {
            "simple": "qwen3.5-plus",
            "coding": "qwen3-coder-plus",
            "writing": "qwen3.5-plus",
            "analysis": "qwen3-max",
            "creative": "kimi-k2.5",
            "complex": "qwen3-max",
            "general": "qwen3.5-plus"
        }
    else:  # 自定义
        print("\n自定义配置（直接 Enter 使用默认值）:")
        return {
            "simple": input_with_default("  简单任务模型", "qwen3.5-flash"),
            "coding": input_with_default("  代码任务模型", "qwen3-coder-plus"),
            "writing": input_with_default("  写作任务模型", "qwen3.5-plus"),
            "analysis": input_with_default("  分析任务模型", "qwen3.5-plus"),
            "creative": input_with_default("  创意任务模型", "kimi-k2.5"),
            "complex": input_with_default("  复杂推理模型", "qwen3-max"),
            "general": input_with_default("  默认模型", "qwen3.5-plus")
        }

def configure_budget() -> Optional[Dict]:
    """配置预算控制"""
    enable = input_with_default("是否启用预算控制 (y/N)", "N").strip().lower()
    
    if enable != 'y':
        return None
    
    daily = float(input_with_default("  每日预算上限 (元)", "50"))
    monthly = float(input_with_default("  每月预算上限 (元)", "1000"))
    
    actions = [
        "降级到最便宜模型",
        "停止服务",
        "仅发送告警"
    ]
    
    action_choice = select_option("超出预算时", actions, 0)
    
    return {
        "enabled": True,
        "daily_limit": daily,
        "monthly_limit": monthly,
        "over_budget_action": ["downgrade", "stop", "alert"][action_choice]
    }

def save_config(config: Dict):
    """保存配置文件"""
    config_dir = Path.home() / ".bridge-server"
    config_dir.mkdir(parents=True, exist_ok=True)
    
    config_file = config_dir / "config.yaml"
    
    with open(config_file, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    
    print_success(f"配置已保存：{config_file}")
    return config_file

def main():
    print_header("Welcome to Bridge Server Setup")
    print("这将引导您完成 Bridge Server 的配置。")
    print("预计需要 3-5 分钟。")
    input("\n按 Enter 继续...")
    
    config = {
        "version": "1.0.0",
        "server": {},
        "providers": {},
        "routing": {},
        "budget": None
    }
    
    # 步骤 1: 基础配置
    print_step(1, 5, "基础配置")
    config["server"]["host"] = input_with_default("服务监听地址", "127.0.0.1")
    config["server"]["port"] = int(input_with_default("服务端口", "8080"))
    config["server"]["debug"] = input_with_default("是否启用调试模式 (y/N)", "N").lower() == 'y'
    
    # 步骤 2: 选择模型提供商
    print_step(2, 5, "选择模型提供商")
    providers = [
        "阿里云百炼 (DashScope)",
        "Moonshot (Kimi)",
        "OpenAI",
        "MiniMax",
        "全部启用"
    ]
    
    provider_choice = select_option("请选择要配置的提供商", providers, 0)
    
    if provider_choice == 4:  # 全部启用
        if dashscope := configure_dashscope():
            config["providers"]["dashscope"] = dashscope
        if moonshot := configure_moonshot():
            config["providers"]["moonshot"] = moonshot
        if openai := configure_openai():
            config["providers"]["openai"] = openai
        if minimax := configure_minimax():
            config["providers"]["minimax"] = minimax
    else:
        provider_configs = [
            configure_dashscope,
            configure_moonshot,
            configure_openai,
            configure_minimax
        ]
        
        if provider_func := provider_configs[provider_choice]():
            config["providers"][provider_func.__name__.replace("configure_", "")] = provider_func
    
    # 步骤 3: 选择路由策略
    print_step(3, 5, "选择路由策略")
    config["routing"]["strategy"] = select_routing_strategy()
    
    # 步骤 4: 预算控制
    print_step(4, 5, "预算控制")
    config["budget"] = configure_budget()
    
    # 步骤 5: 完成配置
    print_step(5, 5, "保存配置")
    config_file = save_config(config)
    
    # 显示配置摘要
    print_header("配置完成！")
    print_success(f"服务地址：http://{config['server']['host']}:{config['server']['port']}")
    print_success(f"启用的提供商：{', '.join(config['providers'].keys())}")
    print_success(f"路由策略：已配置")
    if config["budget"]:
        print_success(f"预算控制：每日 {config['budget']['daily_limit']} 元")
    
    print("\n接下来：")
    print("  1. 启动服务：bridge-server start")
    print("  2. 测试连接：bridge-server test")
    print("  3. 查看状态：bridge-server status")
    print()
    
    # 询问是否启动服务
    start = input_with_default("现在启动服务？(Y/n)", "Y").strip().lower()
    if start != 'n':
        print("\n启动服务...")
        os.system("bridge-server start")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n配置已取消。")
        sys.exit(0)
