#!/usr/bin/env python3
"""
Bridge Server Setup Wizard v2.1

改进的配置向导：
- 循环菜单式配置
- 每个 Provider 配置后立即测试连接
- 成功才保存配置（原子性）
- 支持跳过/追加/修改
- 自定义 Provider 支持
"""

import sys
import os
import yaml
import json
import secrets
import logging
import httpx
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from config import get_default_port

# 添加 src 到路径
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from bridge_server.provider_catalog import ProviderLoader, Provider, Model

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Colors:
    """终端颜色"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def select_from_list(title: str, options: list, default_index: int = 0) -> str:
    """
    终端箭头键选择菜单。
    返回选中的 option 字符串；若终端不支持 raw 模式则降级为数字输入。
    """
    import sys, os

    def _arrow_select():
        import tty, termios
        idx = default_index
        n = len(options)

        def out(s):
            sys.stdout.write(s)
            sys.stdout.flush()

        def render(first=False):
            if not first:
                # 上移 (n+1) 行回到标题行首，清屏到底
                out(f"\033[{n + 1}A\r\033[J")
            # 在 raw 模式下必须用 \r\n，不能用 print()
            out(f"  \033[36m{title}\033[0m\r\n")
            for i, opt in enumerate(options):
                if i == idx:
                    out(f"  \033[32m❯ {opt}\033[0m\r\n")
                else:
                    out(f"    {opt}\r\n")

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            render(first=True)
            while True:
                ch = sys.stdin.read(1)
                if ch in ('\r', '\n'):
                    break
                elif ch == '\x03':  # Ctrl+C
                    raise KeyboardInterrupt
                elif ch == '\x1b':  # ESC sequence
                    ch2 = sys.stdin.read(1)
                    if ch2 == '[':
                        ch3 = sys.stdin.read(1)
                        if ch3 == 'A':  # Up
                            idx = (idx - 1) % n
                        elif ch3 == 'B':  # Down
                            idx = (idx + 1) % n
                render()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        out("\r\n")
        return options[idx]

    def _numeric_select():
        print(f"  {Colors.CYAN}{title}{Colors.ENDC}")
        for i, opt in enumerate(options, 1):
            marker = " (默认)" if i - 1 == default_index else ""
            print(f"  {i}. {opt}{marker}")
        while True:
            raw = input(f"  请选择 [1-{len(options)}，回车={default_index+1}]: ").strip()
            if not raw:
                return options[default_index]
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return options[int(raw) - 1]
            print(f"  {Colors.RED}请输入 1-{len(options)} 之间的数字{Colors.ENDC}")

    # 仅在真实 TTY 下使用 raw 模式
    try:
        import tty, termios
        if sys.stdin.isatty() and sys.stdout.isatty():
            return _arrow_select()
    except (ImportError, Exception):
        pass
    return _numeric_select()


class SetupWizard:
    """配置向导 v2.1"""
    
    def __init__(self):
        """初始化向导"""
        self.loader = ProviderLoader()
        self.providers = self.loader.load()
        
        # 配置数据
        self.config = {
            'version': '2.1.0',
            'server': {
                'host': '0.0.0.0',
                'port': get_default_port(),
                'debug': False
            },
            'providers': [],  # 多个提供商配置
            'routing': {
                'strategy': 'fallback',
                'timeout': 30,
                'max_retries': 3
            },
            'auth': {
                'api_keys': []
            },
            'scenarios': {}
        }
        
        # 配置目录
        if sys.platform == 'win32':
            self.config_dir = Path(os.environ.get('USERPROFILE', '')) / '.bridge-server'
        else:
            self.config_dir = Path.home() / '.bridge-server'
        
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.env_path = self.config_dir / '.env'
        
        # 加载现有配置（如果存在）
        self._load_existing_config()
    
    def _load_existing_config(self):
        """加载现有配置"""
        config_path = self.config_dir / 'config.yaml'
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    existing = yaml.safe_load(f)
                    if existing:
                        self.config.update(self._normalize_existing_config(existing))
                        print(f"{Colors.GREEN}✓ 已加载现有配置{Colors.ENDC}")
            except Exception as e:
                logger.warning(f"加载配置失败：{e}")
        
        # 加载现有环境变量
        if self.env_path.exists():
            with open(self.env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        os.environ[k.strip()] = v.strip()

    def _normalize_existing_config(self, existing: Dict[str, Any]) -> Dict[str, Any]:
        """兼容旧版配置结构，避免配置向导因历史格式崩溃。"""
        normalized = dict(existing)
        providers = normalized.get('providers', [])

        if isinstance(providers, dict):
            converted_providers = []
            for provider_name, provider_data in providers.items():
                if not isinstance(provider_data, dict):
                    continue

                models_data = provider_data.get('models', {})
                converted_models = []

                if isinstance(models_data, dict):
                    for priority, (model_id, model_meta) in enumerate(models_data.items(), start=1):
                        model_name = model_id
                        if isinstance(model_meta, dict):
                            model_name = model_meta.get('name') or model_meta.get('alias') or model_id
                        converted_models.append({
                            'id': model_id,
                            'name': model_name,
                            'priority': priority,
                        })
                elif isinstance(models_data, list):
                    for priority, model in enumerate(models_data, start=1):
                        if isinstance(model, dict):
                            converted_models.append({
                                'id': model.get('id', model.get('name', f'model-{priority}')),
                                'name': model.get('name', model.get('id', f'model-{priority}')),
                                'priority': model.get('priority', priority),
                            })
                        else:
                            converted_models.append({
                                'id': str(model),
                                'name': str(model),
                                'priority': priority,
                            })

                converted_provider = {
                    'name': provider_data.get('name') or provider_name,
                    'api_key_env': provider_data.get('api_key_env', f"{provider_name.upper().replace('-', '_')}_API_KEY"),
                    'base_url': provider_data.get('base_url', ''),
                    'models': converted_models,
                }
                converted_providers.append(converted_provider)

            normalized['providers'] = converted_providers

        elif not isinstance(providers, list):
            normalized['providers'] = []

        return normalized
    
    def run(self):
        """运行配置向导"""
        self._print_header()
        
        try:
            # 主循环：配置 Provider
            self._provider_menu()
            
            # 配置场景化模型
            self._configure_scenarios()
            
            # 选择路由策略
            self._select_routing()
            
            # 生成认证信息
            self._generate_auth()
            
            # 保存并启动
            self._save_and_start()
            
        except KeyboardInterrupt:
            print(f"\n\n{Colors.YELLOW}⚠️  配置已取消{Colors.ENDC}")
            sys.exit(0)
        except Exception as e:
            print(f"\n{Colors.RED}❌ 错误：{e}{Colors.ENDC}")
            logger.exception("配置向导异常")
            sys.exit(1)
    
    def _print_header(self):
        """打印欢迎头"""
        print(f"\n{Colors.CYAN}{'='*60}{Colors.ENDC}")
        print(f"{Colors.CYAN}  Bridge Server 配置向导 v2.1{Colors.ENDC}")
        print(f"{Colors.CYAN}{'='*60}{Colors.ENDC}")
        print(f"\n{Colors.GREEN}👋 欢迎使用 Bridge Server 快速配置工具！{Colors.ENDC}")
        print(f"\n新功能：")
        print(f"  ✅ 循环菜单式配置，随时可修改")
        print(f"  ✅ 每个 Provider 配置后立即测试连接")
        print(f"  ✅ 成功才保存配置（原子性）")
        print(f"  ✅ 支持自定义 Provider (Base URL + 模型)")
        print(f"  ✅ 场景化模型推荐 (Coding/Writing/Search/Summary)")
        print(f"\n{Colors.YELLOW}提示：使用 Ctrl+C 可随时退出{Colors.ENDC}\n")
    
    def _provider_menu(self):
        """Provider 配置主菜单"""
        while True:
            print(f"\n{Colors.BOLD}🏢 Provider 配置菜单{Colors.ENDC}")
            print(f"{'-'*60}")
            
            # 显示已配置的 Provider
            if self.config['providers']:
                print(f"\n{Colors.GREEN}已配置的 Provider:{Colors.ENDC}")
                for i, p in enumerate(self.config['providers'], 1):
                    name = p.get('name', 'Unknown')
                    models = p.get('models', [])
                    model_count = len(models) if isinstance(models, list) else 0
                    print(f"  {i}. {name} ({model_count} 个模型)")
            else:
                print(f"\n{Colors.YELLOW}⚠️  尚未配置任何 Provider{Colors.ENDC}")
            
            print(f"\n{Colors.CYAN}请选择操作:{Colors.ENDC}")
            print(f"  1. 添加预设 Provider (阿里云/OpenAI/等)")
            print(f"  2. 添加自定义 Provider (Base URL + 模型)")
            if self.config['providers']:
                print(f"  3. 修改已有 Provider")
                print(f"  4. 删除已有 Provider")
            print(f"  5. 完成 Provider 配置，继续下一步")
            print(f"  0. 跳过/不修改，保持当前状态")
            
            choice = input(f"\n请选择 [0-5]: ").strip()
            
            if choice == '1':
                self._add_preset_provider()
            elif choice == '2':
                self._add_custom_provider()
            elif choice == '3':
                if self.config['providers']:
                    self._modify_provider()
                else:
                    print(f"{Colors.YELLOW}⚠️  暂无可修改的 Provider{Colors.ENDC}")
            elif choice == '4':
                if self.config['providers']:
                    self._delete_provider()
                else:
                    print(f"{Colors.YELLOW}⚠️  暂无可删除的 Provider{Colors.ENDC}")
            elif choice == '5':
                if not self.config['providers']:
                    print(f"{Colors.RED}❌ 至少配置一个 Provider 才能继续{Colors.ENDC}")
                else:
                    break
            elif choice == '0':
                if not self.config['providers']:
                    print(f"{Colors.RED}❌ 至少配置一个 Provider 才能继续{Colors.ENDC}")
                else:
                    break
            else:
                print(f"{Colors.RED}请输入 0-5 之间的数字{Colors.ENDC}")
    
    def _add_preset_provider(self):
        """添加预设 Provider"""
        print(f"\n{Colors.BOLD}选择预设 Provider{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        # 显示可用 Provider
        providers_list = list(self.providers.values())
        for i, p in enumerate(providers_list, 1):
            print(f"  {i}. {p.name} ({p.name_en})")
        
        choice = input(f"\n请选择 [1-{len(providers_list)}] (回车返回): ").strip()
        if not choice or not choice.isdigit():
            return
        
        idx = int(choice) - 1
        if not (0 <= idx < len(providers_list)):
            print(f"{Colors.RED}无效选择{Colors.ENDC}")
            return
        
        provider = providers_list[idx]
        
        # 配置 API Key
        print(f"\n配置 {provider.name}:")
        print(f"  Base URL: {provider.base_url}")
        print(f"  环境变量：{provider.api_key_env}")
        print(f"  获取地址：{provider.api_key_url}\n")
        
        api_key = input(f"请输入 API Key (回车返回): ").strip()
        if not api_key:
            return
        
        # 配置模型
        models = self._add_models_loop(provider)
        if not models:
            print(f"{Colors.RED}❌ 至少添加一个模型{Colors.ENDC}")
            return
        
        # 测试连接
        print(f"\n{Colors.CYAN}测试连接...{Colors.ENDC}")
        success = self._test_provider_connection(provider.base_url, api_key, models[0]['id'])
        
        if success:
            # 保存配置
            provider_config = {
                'name': provider.name,
                'api_key_env': provider.api_key_env,
                'base_url': provider.base_url,
                'models': models
            }
            self.config['providers'].append(provider_config)
            
            # 保存 API Key 到 .env
            self._save_env_var(provider.api_key_env, api_key)
            
            print(f"{Colors.GREEN}✅ {provider.name} 配置成功并已保存！{Colors.ENDC}")
        else:
            print(f"{Colors.RED}❌ 连接测试失败，配置未保存{Colors.ENDC}")
    
    def _add_custom_provider(self):
        """添加自定义 Provider"""
        print(f"\n{Colors.BOLD}自定义 Provider{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        # Provider 名称
        name = input("Provider 名称 (如 my-llm): ").strip()
        if not name:
            return
        
        # Base URL
        base_url = input("API Base URL (如 https://api.example.com/v1): ").strip()
        if not base_url:
            return
        
        # 自动派生环境变量名，无需用户输入
        api_key_env = f"{name.upper().replace('-', '_').replace(' ', '_')}_API_KEY"
        print(f"环境变量名（自动生成）：{Colors.CYAN}{api_key_env}{Colors.ENDC}")
        
        # API Key
        api_key = input(f"请输入 API Key: ").strip()
        if not api_key:
            return
        
        # 配置模型
        print(f"\n添加模型 (每次一个，空行结束):")
        models = []
        model_idx = 1
        while True:
            model_id = input(f"  模型{model_idx} ID: ").strip()
            if not model_id:
                break
            
            model_name = input(f"  模型{model_idx} 昵称 (回车同 ID): ").strip()
            if not model_name:
                model_name = model_id
            
            models.append({
                'id': model_id,
                'name': model_name,
                'priority': model_idx
            })
            model_idx += 1
        
        if not models:
            print(f"{Colors.RED}❌ 至少添加一个模型{Colors.ENDC}")
            return
        
        # 测试连接
        print(f"\n{Colors.CYAN}测试连接...{Colors.ENDC}")
        success = self._test_provider_connection(base_url, api_key, models[0]['id'])
        
        if success:
            provider_config = {
                'name': name,
                'api_key_env': api_key_env,
                'base_url': base_url,
                'models': models
            }
            self.config['providers'].append(provider_config)
            self._save_env_var(api_key_env, api_key)
            print(f"{Colors.GREEN}✅ {name} 配置成功并已保存！{Colors.ENDC}")
        else:
            print(f"{Colors.RED}❌ 连接测试失败，配置未保存{Colors.ENDC}")
    
    def _add_models_loop(self, provider: Provider) -> List[Dict]:
        """循环添加模型"""
        print(f"\n{provider.name} 可用模型:")
        
        # 获取模型列表
        if isinstance(provider.models, dict):
            models_list = list(provider.models.values())
        else:
            models_list = provider.models
        
        # 显示前 20 个模型
        for i, m in enumerate(models_list[:20], 1):
            price = f"¥{m.pricing.input_per_1k}/1K" if m.pricing else "N/A"
            print(f"  {i}. {m.name} (ctx: {m.context_length}, price: {price})")
        
        if len(models_list) > 20:
            print(f"  ... 还有 {len(models_list) - 20} 个模型")
        
        print(f"\n添加模型 (每次一个，空行结束):")
        print(f"  输入编号选择预设模型，或直接输入模型 ID")
        
        models = []
        model_idx = 1
        while True:
            choice = input(f"  模型{model_idx}: ").strip()
            if not choice:
                break
            
            # 检查是否是编号
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(models_list):
                    model = models_list[idx]
                    models.append({
                        'id': model.name,
                        'name': model.name,
                        'priority': model_idx
                    })
                    print(f"    ✓ 已添加：{model.name}")
                else:
                    print(f"    {Colors.RED}无效编号{Colors.ENDC}")
            else:
                # 自定义模型 ID
                model_name = input(f"    昵称 (回车同 ID): ").strip()
                if not model_name:
                    model_name = choice
                models.append({
                    'id': choice,
                    'name': model_name,
                    'priority': model_idx
                })
                print(f"    ✓ 已添加：{choice} ({model_name})")
            
            model_idx += 1
        
        return models
    
    def _test_provider_connection(self, base_url: str, api_key: str, model_id: str) -> bool:
        """测试 Provider 连接"""
        try:
            # 若 base_url 已以 /chat/completions 结尾则直接使用，否则拼接
            stripped = base_url.rstrip('/')
            if stripped.endswith('/chat/completions'):
                test_url = stripped
            else:
                test_url = stripped + '/chat/completions'
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}'
            }
            data = {
                'model': model_id,
                'messages': [
                    {'role': 'user', 'content': 'Hi'}
                ],
                'max_tokens': 1
            }
            
            print(f"  请求：POST {test_url}")
            print(f"  模型：{model_id}")
            
            # 先尝试正常 SSL 验证，失败后自动降级（企业代理场景）
            try:
                response = httpx.post(test_url, json=data, headers=headers, timeout=10)
            except httpx.ConnectError as ssl_err:
                if 'CERTIFICATE_VERIFY_FAILED' in str(ssl_err) or 'SSL' in str(ssl_err).upper():
                    print(f"  {Colors.YELLOW}⚠ SSL 验证失败（企业代理），尝试跳过证书验证...{Colors.ENDC}")
                    response = httpx.post(test_url, json=data, headers=headers, timeout=10, verify=False)
                else:
                    raise
            
            if response.status_code == 200:
                print(f"  {Colors.GREEN}✓ 连接成功 (HTTP {response.status_code}){Colors.ENDC}")
                return True
            else:
                print(f"  {Colors.RED}✗ 连接失败 (HTTP {response.status_code}): {response.text[:100]}{Colors.ENDC}")
                return False
                
        except httpx.TimeoutException:
            print(f"  {Colors.RED}✗ 连接超时 (10 秒){Colors.ENDC}")
            return False
        except Exception as e:
            print(f"  {Colors.RED}✗ 连接错误：{e}{Colors.ENDC}")
            return False
    
    def _modify_provider(self):
        """修改已有 Provider"""
        if not self.config['providers']:
            print(f"{Colors.RED}没有可修改的 Provider{Colors.ENDC}")
            return
        
        print(f"\n选择要修改的 Provider:")
        for i, p in enumerate(self.config['providers'], 1):
            print(f"  {i}. {p.get('name', 'Unknown')}")
        
        choice = input(f"请选择 [1-{len(self.config['providers'])}] (回车返回): ").strip()
        if not choice or not choice.isdigit():
            return
        
        idx = int(choice) - 1
        if not (0 <= idx < len(self.config['providers'])):
            print(f"{Colors.RED}无效选择{Colors.ENDC}")
            return
        
        # 删除旧的，重新添加
        provider = self.config['providers'].pop(idx)
        print(f"\n已移除 {provider['name']}，请重新配置:\n")
        
        # 根据是否有 base_url 判断是预设还是自定义
        if 'base_url' in provider and provider.get('name') not in [p.name for p in self.providers.values()]:
            self._add_custom_provider()
        else:
            self._add_preset_provider()
    
    def _delete_provider(self):
        """删除 Provider"""
        if not self.config['providers']:
            print(f"{Colors.RED}没有可删除的 Provider{Colors.ENDC}")
            return
        
        print(f"\n选择要删除的 Provider:")
        for i, p in enumerate(self.config['providers'], 1):
            print(f"  {i}. {p.get('name', 'Unknown')}")
        
        choice = input(f"请选择 [1-{len(self.config['providers'])}] (回车返回): ").strip()
        if not choice or not choice.isdigit():
            return
        
        idx = int(choice) - 1
        if not (0 <= idx < len(self.config['providers'])):
            print(f"{Colors.RED}无效选择{Colors.ENDC}")
            return
        
        provider = self.config['providers'].pop(idx)
        print(f"{Colors.GREEN}✓ 已删除 {provider['name']}{Colors.ENDC}")
    
    def _save_env_var(self, name: str, value: str):
        """保存环境变量到 .env 文件"""
        env_content = {}
        if self.env_path.exists():
            with open(self.env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        env_content[k.strip()] = v.strip()
        
        env_content[name] = value
        
        with open(self.env_path, 'w') as f:
            f.write(f"# Bridge Server 环境变量\n")
            f.write(f"# 生成时间：{datetime.now().isoformat()}\n\n")
            for k, v in env_content.items():
                f.write(f"{k}={v}\n")
    
    def _configure_scenarios(self):
        """配置场景化模型 - 箭头键选择菜单"""
        print(f"\n{Colors.BOLD}🎯 步骤 2/4: 配置场景化模型{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        use_scenarios = input("是否配置场景化模型？[y/N]: ").strip().lower()
        if use_scenarios != 'y':
            print(f"\n{Colors.YELLOW}⚠️  已跳过{Colors.ENDC}")
            return
        
        # 收集所有已配置的模型 ID（provider/model_id 格式）
        available_models = []
        for provider in self.config['providers']:
            provider_name = provider.get('name', 'unknown')
            models = provider.get('models', [])
            if isinstance(models, list):
                for model in models:
                    model_id = model.get('id', '') if isinstance(model, dict) else str(model)
                    available_models.append(f"{provider_name}/{model_id}")
            elif isinstance(models, dict):
                for model_id in models.keys():
                    available_models.append(f"{provider_name}/{model_id}")
        
        if not available_models:
            print(f"{Colors.RED}❌ 没有可用的模型，请先配置 Provider{Colors.ENDC}")
            return
        
        scenarios = [
            ('coding',      '💻 编程辅助',  '代码生成、调试'),
            ('writing',     '✍️  写作创作',  '文章、邮件'),
            ('search',      '🔍 搜索分析',  '信息检索'),
            ('summary',     '📝 摘要总结',  '长文摘要'),
            ('chat',        '💬 日常对话',  '聊天问答'),
            ('translation', '🌐 翻译',      '多语言互译'),
        ]
        
        for key, name, desc in scenarios:
            print(f"\n{Colors.BOLD}{name}  ({desc}){Colors.ENDC}")
            # 当前已保存的值作为默认
            current = self.config.get('scenarios', {}).get(key, {}).get('model', available_models[0])
            default_idx = available_models.index(current) if current in available_models else 0
            chosen = select_from_list(f"选择模型（↑↓ 移动，Enter 确认）", available_models, default_idx)
            self.config['scenarios'][key] = {'enabled': True, 'model': chosen}
            print(f"  {Colors.GREEN}✓ 已选择：{chosen}{Colors.ENDC}")
        
        print(f"\n{Colors.GREEN}✅ 场景化模型配置完成{Colors.ENDC}")
        print(f"   提示：场景配置只允许选择已配置的具体模型，避免路由配置自引用")
    
    def _select_routing(self):
        """选择路由策略"""
        print(f"\n{Colors.BOLD}🔀 步骤 3/4: 选择路由策略{Colors.ENDC}")
        print(f"{'-'*60}\n")

        self.config['routing']['strategy'] = 'fallback'
        print("  首次配置默认采用 Fallback（故障转移）策略。")
        print("  如需更高级的策略，请在配置文件或后续 CLI 中调整。")
        print(f"\n{Colors.GREEN}✅ 路由策略：fallback{Colors.ENDC}")
    
    def _generate_auth(self):
        """生成认证信息"""
        print(f"\n{Colors.BOLD}🔐 步骤 4/4: 生成认证信息{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        api_key = f"sk-{secrets.token_hex(16)}"
        self.config['auth']['api_keys'].append({
            'key': api_key,
            'name': 'Default Key',
            'created_at': datetime.now().isoformat()
        })
        
        print(f"{Colors.GREEN}✅ 已生成用户侧 API Key{Colors.ENDC}")
        print(f"\n连接信息：")
        print(f"  Base URL: http://localhost:{self.config['server']['port']}/v1")
        print(f"  API Key:  {Colors.YELLOW}{api_key}{Colors.ENDC}")
        
        # 保存 auth.yaml
        auth_path = self.config_dir / 'auth.yaml'
        with open(auth_path, 'w') as f:
            yaml.dump({'api_keys': self.config['auth']['api_keys']}, f, default_flow_style=False)
    
    def _save_and_start(self):
        """保存配置并启动服务"""
        print(f"\n{Colors.BOLD}📁 保存配置{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        config_path = self.config_dir / 'config.yaml'
        with open(config_path, 'w') as f:
            yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True)
        
        print(f"✅ 配置已保存:")
        print(f"   {config_path}")
        print(f"   {self.env_path}")
        print(f"   {self.config_dir / 'auth.yaml'}\n")
        
        # 询问是否启动服务
        start = input("是否立即启动服务？[Y/n]: ").strip().lower()
        if start != 'n':
            self._start_service()
        
        self._finish()
    
    def _start_service(self):
        """启动服务（先停止旧进程）"""
        import subprocess, signal, os, time
        
        print(f"\n{Colors.CYAN}启动服务...{Colors.ENDC}")
        
        python_exe = sys.executable
        host = self.config['server'].get('host', '0.0.0.0')
        port = str(self.config['server'].get('port', get_default_port()))

        # 先停止占用同一端口的旧进程
        try:
            result = subprocess.run(
                ['lsof', '-ti', f':{port}'],
                capture_output=True, text=True
            )
            pids = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]
            for pid_str in pids:
                try:
                    os.kill(int(pid_str), signal.SIGTERM)
                except (ValueError, ProcessLookupError):
                    pass
            if pids:
                time.sleep(1.5)
                print(f"{Colors.YELLOW}  已停止旧服务 (PID: {', '.join(pids)}){Colors.ENDC}")
        except Exception:
            pass

        try:
            log_file = open(self.config_dir / 'server.log', 'a')
            process = subprocess.Popen(
                [python_exe, '-m', 'uvicorn', 'bridge_server.runtime:app', '--app-dir', 'src', '--host', host, '--port', port],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=REPO_ROOT
            )
            log_file.close()
            
            print(f"{Colors.GREEN}✅ 服务已启动！{Colors.ENDC}")
            print(f"   PID: {process.pid}")
            print(f"   端口：{port}")
        except Exception as e:
            print(f"{Colors.YELLOW}⚠️  服务启动失败：{e}{Colors.ENDC}")
            print(f"   可以手动启动：python -m uvicorn bridge_server.runtime:app --app-dir src --host {host} --port {port}")
    
    def _finish(self):
        """完成"""
        print(f"\n{Colors.CYAN}{'='*60}{Colors.ENDC}")
        print(f"{Colors.GREEN}🎉 配置完成！{Colors.ENDC}")
        print(f"{Colors.CYAN}{'='*60}{Colors.ENDC}\n")
        
        print(f"连接信息：")
        print(f"  Base URL: http://localhost:{self.config['server']['port']}/v1")
        print(f"  API Key:  {self.config['auth']['api_keys'][0]['key']}")
        print(f"\n测试连接：")
        print(f"  curl http://localhost:{self.config['server']['port']}/health")
        print(f"\n管理命令：")
        print(f"  bridge-server start   - 启动服务")
        print(f"  bridge-server stop    - 停止服务")
        print(f"  bridge-server status  - 查看状态")
        print(f"\n{Colors.GREEN}祝您使用愉快！{Colors.ENDC}\n")


def main():
    """主函数"""
    wizard = SetupWizard()
    wizard.run()


if __name__ == "__main__":
    main()
