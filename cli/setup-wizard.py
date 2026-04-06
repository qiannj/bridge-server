#!/usr/bin/env python3
"""
Bridge Server Setup Wizard v2.0

全新的配置向导：
- 支持配置多个模型/提供商
- 支持自定义 Provider（Base URL + 多个模型）
- 自动选择路由规则场景
- 配置完成后自动启动服务
- 生成用户侧 API Key 和 Base URL
"""

import sys
import os
import yaml
import json
import secrets
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from providers.loader import ProviderLoader, Provider, Model

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


class SetupWizard:
    """配置向导 v2.0"""
    
    def __init__(self):
        """初始化向导"""
        self.loader = ProviderLoader()
        self.providers = self.loader.load()
        
        # 配置数据
        self.config = {
            'version': '2.0.0',
            'server': {
                'host': '0.0.0.0',
                'port': 8080,
                'debug': False
            },
            'providers': [],  # 多个提供商配置
            'routing': {
                'strategy': 'fallback',
                'timeout': 30,
                'max_retries': 3
            },
            'auth': {
                'api_keys': []  # 用户侧 API Keys
            }
        }
        
        self.config_dir: Optional[Path] = None
        self.env_path: Optional[Path] = None
    
    def run(self):
        """运行配置向导"""
        self._print_header()
        
        try:
            # 1. 选择配置模式
            self._select_mode()
            
            # 2. 配置提供商和模型
            self._configure_providers()
            
            # 3. 选择路由策略
            self._select_routing()
            
            # 4. 生成用户侧 API Key
            self._generate_auth()
            
            # 5. 保存配置
            self._save_config()
            
            # 6. 启动服务
            self._start_service()
            
            # 7. 完成
            self._finish()
            
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
        print(f"{Colors.CYAN}  Bridge Server 配置向导 v2.0{Colors.ENDC}")
        print(f"{Colors.CYAN}{'='*60}{Colors.ENDC}")
        print(f"\n{Colors.GREEN}👋 欢迎使用 Bridge Server 快速配置工具！{Colors.ENDC}")
        print(f"\n新功能：")
        print(f"  ✅ 支持配置多个模型/提供商")
        print(f"  ✅ 支持自定义 Provider (Base URL + 模型)")
        print(f"  ✅ 自动选择路由策略")
        print(f"  ✅ 配置完成后自动启动服务")
        print(f"  ✅ 生成用户侧 API Key 和连接信息")
        print(f"\n{Colors.YELLOW}提示：使用 Ctrl+C 可随时退出{Colors.ENDC}\n")
    
    def _select_mode(self):
        """选择配置模式"""
        print(f"\n{Colors.BOLD}📋 步骤 1/5: 选择配置模式{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        print("请选择配置模式：")
        print("  1. 快速配置（推荐）- 自动配置主流模型")
        print("  2. 自定义配置 - 手动选择提供商和模型")
        print("  3. 高级配置 - 完全自定义（包括自定义 Base URL）")
        
        while True:
            try:
                choice = input("\n请选择 [1-3]: ").strip()
                if choice in ['1', '2', '3']:
                    self.config['mode'] = ['quick', 'custom', 'advanced'][int(choice) - 1]
                    print(f"\n✅ 已选择：{['快速配置', '自定义配置', '高级配置'][int(choice) - 1]}")
                    break
                else:
                    print(f"{Colors.RED}请输入 1-3 之间的数字{Colors.ENDC}")
            except EOFError:
                sys.exit(0)
    
    def _configure_providers(self):
        """配置提供商和模型"""
        print(f"\n{Colors.BOLD}🏢 步骤 2/5: 配置提供商和模型{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        mode = self.config.get('mode', 'custom')
        
        if mode == 'quick':
            # 快速配置：自动选择通义千问
            self._quick_config()
        elif mode == 'custom':
            # 自定义配置：从预设列表选择
            self._custom_config()
        else:
            # 高级配置：完全自定义
            self._advanced_config()
    
    def _quick_config(self):
        """快速配置"""
        print(f"\n{Colors.CYAN}快速配置模式{Colors.ENDC}")
        print("自动配置以下模型：")
        print("  - 通义千问 qwen-plus (主力)")
        print("  - 通义千问 qwen-turbo (备用)")
        
        provider = self.providers.get('dashscope')
        if not provider:
            print(f"{Colors.RED}错误：无法加载提供商配置{Colors.ENDC}")
            return
        
        # 配置提供商
        api_key = self._input_api_key(provider.api_key_env, provider.api_key_url)
        
        self.config['providers'].append({
            'name': 'dashscope',
            'api_key_env': provider.api_key_env,
            'models': [
                {'id': 'qwen-plus', 'name': 'Qwen Plus', 'priority': 1},
                {'id': 'qwen-turbo', 'name': 'Qwen Turbo', 'priority': 2}
            ]
        })
        
        # 保存 API Key 到 .env
        self._save_env_var(provider.api_key_env, api_key)
    
    def _custom_config(self):
        """自定义配置"""
        print(f"\n{Colors.CYAN}自定义配置模式{Colors.ENDC}")
        print("从预设列表选择提供商和模型\n")
        
        # 显示可用提供商
        providers_list = list(self.providers.values())
        for i, p in enumerate(providers_list, 1):
            print(f"  {i}. {p.name} ({len(p.models)} 个模型)")
        
        while True:
            try:
                choice = input(f"\n请选择提供商 [1-{len(providers_list)}] (回车跳过): ").strip()
                if not choice:
                    break
                if not choice.isdigit():
                    print(f"{Colors.RED}请输入数字{Colors.ENDC}")
                    continue
                
                idx = int(choice) - 1
                if 0 <= idx < len(providers_list):
                    provider = providers_list[idx]
                    
                    # 输入 API Key
                    api_key = self._input_api_key(provider.api_key_env, provider.api_key_url)
                    
                    # 选择模型
                    models = self._select_models(provider)
                    
                    if models:
                        self.config['providers'].append({
                            'name': provider.name,
                            'api_key_env': provider.api_key_env,
                            'models': models
                        })
                        self._save_env_var(provider.api_key_env, api_key)
                    
                    # 询问是否继续添加
                    more = input("\n继续添加其他提供商？[y/N]: ").strip().lower()
                    if more != 'y':
                        break
                else:
                    print(f"{Colors.RED}请输入 1-{len(providers_list)} 之间的数字{Colors.ENDC}")
            except EOFError:
                sys.exit(0)
    
    def _advanced_config(self):
        """高级配置"""
        print(f"\n{Colors.CYAN}高级配置模式{Colors.ENDC}")
        print("支持自定义 Base URL 和模型\n")
        
        while True:
            try:
                print("\n请选择配置类型：")
                print("  1. 使用预设提供商")
                print("  2. 自定义 Provider (Base URL + 模型)")
                
                choice = input("\n请选择 [1-2]: ").strip()
                
                if choice == '1':
                    # 预设提供商
                    providers_list = list(self.providers.values())
                    for i, p in enumerate(providers_list, 1):
                        print(f"  {i}. {p.name}")
                    
                    idx = input(f"选择 [1-{len(providers_list)}]: ").strip()
                    if idx.isdigit() and 0 <= int(idx) - 1 < len(providers_list):
                        provider = providers_list[int(idx) - 1]
                        api_key = self._input_api_key(provider.api_key_env, provider.api_key_url)
                        models = self._select_models(provider)
                        
                        if models:
                            self.config['providers'].append({
                                'name': provider.name,
                                'api_key_env': provider.api_key_env,
                                'models': models
                            })
                            self._save_env_var(provider.api_key_env, api_key)
                
                elif choice == '2':
                    # 自定义 Provider
                    print(f"\n{Colors.GREEN}自定义 Provider{Colors.ENDC}")
                    
                    name = input("Provider 名称 (如 my-llm): ").strip()
                    if not name:
                        print(f"{Colors.RED}名称不能为空{Colors.ENDC}")
                        continue
                    
                    base_url = input("API Base URL (如 https://api.example.com/v1): ").strip()
                    if not base_url:
                        print(f"{Colors.RED}Base URL 不能为空{Colors.ENDC}")
                        continue
                    
                    api_key_env = input("环境变量名 (如 MY_LLM_API_KEY): ").strip()
                    if not api_key_env:
                        api_key_env = f"{name.upper().replace('-', '_')}_API_KEY"
                    
                    api_key = self._input_api_key(api_key_env, "")
                    
                    # 添加多个模型
                    models = []
                    print(f"\n添加模型 (输入空行结束):")
                    model_idx = 1
                    while True:
                        model_id = input(f"  模型{model_idx} ID: ").strip()
                        if not model_id:
                            break
                        
                        model_name = input(f"  模型{model_idx} 名称 (可选): ").strip()
                        if not model_name:
                            model_name = model_id
                        
                        priority = input(f"  优先级 (1=最高，回车=1): ").strip()
                        if not priority:
                            priority = 1
                        
                        models.append({
                            'id': model_id,
                            'name': model_name,
                            'priority': int(priority)
                        })
                        model_idx += 1
                    
                    if models:
                        provider_config = {
                            'name': name,
                            'api_key_env': api_key_env,
                            'base_url': base_url,
                            'models': models
                        }
                        self.config['providers'].append(provider_config)
                        self._save_env_var(api_key_env, api_key)
                        print(f"\n✅ 已添加自定义 Provider: {name}")
                
                # 询问是否继续
                more = input("\n继续添加其他 Provider？[y/N]: ").strip().lower()
                if more != 'y':
                    break
                    
            except EOFError:
                sys.exit(0)
    
    def _select_models(self, provider: Provider) -> List[Dict]:
        """选择模型"""
        print(f"\n{provider.name} 可用模型:")
        
        models = list(provider.models.values())
        for i, m in enumerate(models[:10], 1):  # 最多显示 10 个
            price = f"¥{m.pricing.input_per_1k}/1K" if m.pricing else "N/A"
            print(f"  {i}. {m.name} (ctx: {m.context_length}, price: {price})")
        
        if len(models) > 10:
            print(f"  ... 还有 {len(models) - 10} 个模型")
        
        print(f"\n输入模型编号，多个用逗号分隔 (如 1,2,3)")
        choice = input("选择: ").strip()
        
        if not choice:
            return []
        
        selected = []
        for c in choice.split(','):
            c = c.strip()
            if c.isdigit():
                idx = int(c) - 1
                if 0 <= idx < len(models):
                    selected.append({
                        'id': models[idx].name,
                        'name': models[idx].name,
                        'priority': idx + 1
                    })
        
        return selected
    
    def _input_api_key(self, env_name: str, url: str) -> str:
        """输入 API Key"""
        print(f"\n配置 API Key:")
        print(f"  环境变量：{Colors.YELLOW}{env_name}{Colors.ENDC}")
        if url:
            print(f"  获取地址：{url}")
        
        print(f"\n{Colors.CYAN}提示：直接粘贴 API Key 后按回车{Colors.ENDC}")
        
        # Windows 兼容性：清空输入缓冲区
        if sys.platform == 'win32':
            try:
                import msvcrt
                while msvcrt.kbhit():
                    msvcrt.getch()
            except ImportError:
                pass
        
        while True:
            try:
                api_key = input("\n请输入 API Key: ").strip()
                if api_key:
                    return api_key
                else:
                    print(f"{Colors.RED}API Key 不能为空{Colors.ENDC}")
            except EOFError:
                sys.exit(0)
    
    def _save_env_var(self, name: str, value: str):
        """保存环境变量到 .env 文件"""
        if self.env_path is None:
            self.env_path = self.config_dir / '.env'
        
        # 读取现有内容
        env_content = {}
        if self.env_path.exists():
            with open(self.env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        env_content[k.strip()] = v.strip()
        
        # 更新
        env_content[name] = value
        
        # 写入
        with open(self.env_path, 'w') as f:
            f.write(f"# Bridge Server 环境变量\n")
            f.write(f"# 生成时间：{datetime.now().isoformat()}\n\n")
            for k, v in env_content.items():
                f.write(f"{k}={v}\n")
    
    def _select_routing(self):
        """选择路由策略"""
        print(f"\n{Colors.BOLD}🔀 步骤 3/5: 选择路由策略{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        print("路由策略决定如何分发请求到多个模型：\n")
        print("  1. Fallback (故障转移) - 主模型失败时自动切换到备用")
        print("  2. Load Balance (负载均衡) - 均匀分发到所有模型")
        print("  3. Priority (优先级) - 按优先级顺序使用模型")
        print("  4. Round Robin (轮询) - 轮流使用每个模型")
        
        strategies = {
            '1': 'fallback',
            '2': 'load_balance',
            '3': 'priority',
            '4': 'round_robin'
        }
        
        while True:
            try:
                choice = input("\n请选择 [1-4] (推荐 1): ").strip()
                if choice in strategies:
                    self.config['routing']['strategy'] = strategies[choice]
                    print(f"\n✅ 已选择：{strategies[choice]}")
                    break
                else:
                    print(f"{Colors.RED}请输入 1-4 之间的数字{Colors.ENDC}")
            except EOFError:
                sys.exit(0)
        
        # 配置超时和重试
        timeout = input("\n请求超时时间 (秒，回车=30): ").strip()
        if timeout:
            self.config['routing']['timeout'] = int(timeout)
        
        retries = input("最大重试次数 (回车=3): ").strip()
        if retries:
            self.config['routing']['max_retries'] = int(retries)
    
    def _generate_auth(self):
        """生成用户侧认证信息"""
        print(f"\n{Colors.BOLD}🔐 步骤 4/5: 生成认证信息{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        # 生成用户侧 API Key
        api_key = f"sk-{secrets.token_hex(16)}"
        self.config['auth']['api_keys'].append({
            'key': api_key,
            'name': 'Default Key',
            'created_at': datetime.now().isoformat(),
            'permissions': ['chat', 'embeddings']
        })
        
        print(f"{Colors.GREEN}✅ 已生成用户侧 API Key{Colors.ENDC}")
        print(f"\n连接信息：")
        print(f"  Base URL: http://localhost:{self.config['server']['port']}/v1")
        print(f"  API Key:  {Colors.YELLOW}{api_key}{Colors.ENDC}")
        print(f"\n{Colors.CYAN}提示：可以将此 API Key 分发给应用使用{Colors.ENDC}")
        
        # 保存到 auth.yaml
        auth_path = self.config_dir / 'auth.yaml'
        with open(auth_path, 'w') as f:
            yaml.dump({'api_keys': self.config['auth']['api_keys']}, f, default_flow_style=False)
    
    def _save_config(self):
        """保存配置文件"""
        print(f"\n{Colors.BOLD}📁 步骤 5/6: 保存配置{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        # 确定配置目录
        if sys.platform == 'win32':
            self.config_dir = Path(os.environ.get('USERPROFILE', '')) / '.bridge-server'
        else:
            self.config_dir = Path.home() / '.bridge-server'
        
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存 config.yaml
        config_path = self.config_dir / 'config.yaml'
        with open(config_path, 'w') as f:
            yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True)
        
        print(f"✅ 配置文件已保存:")
        print(f"   {config_path}")
        print(f"\n✅ 环境变量已保存:")
        print(f"   {self.env_path}")
        print(f"\n✅ 认证信息已保存:")
        print(f"   {self.config_dir / 'auth.yaml'}")
    
    def _start_service(self):
        """启动服务"""
        print(f"\n{Colors.BOLD}🚀 启动服务{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        try:
            import subprocess
            
            # 使用虚拟环境的 Python
            if sys.platform == 'win32':
                python_exe = self.config_dir.parent / 'opt' / 'bridge-server' / 'venv' / 'Scripts' / 'python.exe'
            else:
                python_exe = self.config_dir.parent / 'opt' / 'bridge-server' / 'venv' / 'bin' / 'python'
            
            if not python_exe.exists():
                python_exe = sys.executable
            
            print(f"启动 Uvicorn 服务...")
            
            # 启动服务
            log_file = open(self.config_dir / 'server.log', 'a')
            process = subprocess.Popen(
                [
                    str(python_exe), '-m', 'uvicorn',
                    'app.main:app',
                    '--host', '0.0.0.0',
                    '--port', str(self.config['server']['port'])
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=self.config_dir.parent / 'opt' / 'bridge-server' if sys.platform == 'win32' else Path(__file__).parent.parent
            )
            log_file.close()
            
            print(f"{Colors.GREEN}✅ 服务已启动！{Colors.ENDC}")
            print(f"   PID: {process.pid}")
            print(f"   端口：{self.config['server']['port']}")
            
        except Exception as e:
            print(f"{Colors.YELLOW}⚠️  服务启动失败，可以手动启动：{Colors.ENDC}")
            print(f"   bridge-server start")
    
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
        print(f"\n查看日志：")
        if sys.platform == 'win32':
            print(f"  notepad {self.config_dir / 'server.log'}")
        else:
            print(f"  tail -f {self.config_dir / 'server.log'}")
        print(f"\n管理命令：")
        print(f"  bridge-server start    - 启动服务")
        print(f"  bridge-server stop     - 停止服务")
        print(f"  bridge-server status   - 查看状态")
        print(f"\n{Colors.GREEN}祝您使用愉快！{Colors.ENDC}\n")


def main():
    """主函数"""
    wizard = SetupWizard()
    wizard.run()


if __name__ == "__main__":
    main()
