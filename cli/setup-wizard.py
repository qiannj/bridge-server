#!/usr/bin/env python3
"""
Bridge Server Setup Wizard

交互式配置向导，帮助用户快速选择提供商和模型
支持全球 15 家主流提供商，40+ 模型
"""

import sys
import os
import yaml
import logging
from pathlib import Path
from typing import Optional, Dict, Any

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from providers.loader import ProviderLoader, Provider, Model

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Windows 兼容性：确保 input() 正常工作
if sys.platform == 'win32':
    # 在 Windows 上强制使用控制台输入
    try:
        import msvcrt
    except ImportError:
        pass


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
    """配置向导"""
    
    def __init__(self):
        """初始化向导"""
        self.loader = ProviderLoader()
        self.providers = self.loader.load()
        
        self.selected_region: Optional[str] = None
        self.selected_provider: Optional[Provider] = None
        self.selected_model: Optional[Model] = None
        self.api_key: Optional[str] = None
        self.config_path: Optional[str] = None
        
    def run(self):
        """运行配置向导"""
        self._print_header()
        
        try:
            # 1. 选择区域
            self._select_region()
            
            # 2. 选择提供商
            self._select_provider()
            
            # 3. 选择模型
            self._select_model()
            
            # 4. 输入 API Key
            self._input_api_key()
            
            # 5. 选择保存路径
            self._select_config_path()
            
            # 6. 生成配置
            self._generate_config()
            
            # 7. 完成
            self._finish()
            
        except KeyboardInterrupt:
            print(f"\n\n{Colors.YELLOW}⚠️  配置已取消{Colors.ENDC}")
            sys.exit(0)
        except Exception as e:
            print(f"\n{Colors.RED}❌ 错误：{e}{Colors.ENDC}")
            logger.exception("配置向导异常")
            sys.exit(1)
    
    def run_quick(self):
        """快速配置模式（非交互）"""
        print("\n🚀 快速配置模式\n")
        
        # 默认使用通义千问 qwen-plus
        self.selected_region = 'CN'
        self.selected_provider = self.providers.get('dashscope')
        
        if not self.selected_provider:
            print(f"{Colors.RED}错误：无法加载提供商配置{Colors.ENDC}")
            sys.exit(1)
        
        # 选择默认模型
        if 'qwen-plus' in self.selected_provider.models:
            self.selected_model = self.selected_provider.models['qwen-plus']
        else:
            self.selected_model = list(self.selected_provider.models.values())[0]
        
        # 默认配置路径
        if sys.platform == 'win32':
            config_dir = Path(os.environ.get('USERPROFILE', '')) / '.bridge-server'
        else:
            config_dir = Path.home() / '.bridge-server'
        
        config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = str(config_dir / 'config.yaml')
        
        # 生成配置
        self._generate_config()
        
        print(f"\n{Colors.GREEN}✅ 快速配置完成！{Colors.ENDC}")
        print(f"\n配置文件：{self.config_path}")
        print(f"\n下一步:")
        print(f"  1. 编辑 .env 文件，填入你的 API Key")
        if sys.platform == 'win32':
            print(f"     notepad {config_dir / '.env'}")
        else:
            print(f"     nano {config_dir / '.env'}")
        print(f"\n  2. 启动服务:")
        print(f"     bridge-server start")
        print()
    
    def _print_header(self):
        """打印欢迎头"""
        print(f"\n{Colors.CYAN}{'='*60}{Colors.ENDC}")
        print(f"{Colors.CYAN}  Bridge Server 配置向导 v1.4.0{Colors.ENDC}")
        print(f"{Colors.CYAN}{'='*60}{Colors.ENDC}")
        print(f"\n{Colors.GREEN}👋 欢迎使用 Bridge Server 快速配置工具！{Colors.ENDC}")
        print(f"\n本工具将帮助您：")
        print(f"  1️⃣  选择适合的 LLM 提供商")
        print(f"  2️⃣  选择性价比最高的模型")
        print(f"  3️⃣  配置 API Key")
        print(f"  4️⃣  生成配置文件")
        print(f"\n支持 {len(self.providers)} 家全球主流提供商，40+ 模型")
        print(f"\n{Colors.YELLOW}提示：使用 Ctrl+C 可随时退出{Colors.ENDC}\n")
    
    def _select_region(self):
        """选择区域"""
        print(f"\n{Colors.BOLD}📍 步骤 1/5: 选择区域{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        # 统计各区域提供商数量
        region_stats = {}
        for provider in self.providers.values():
            region = provider.region
            if region not in region_stats:
                region_stats[region] = 0
            region_stats[region] += 1
        
        # 显示选项
        regions = [
            ('CN', '🇨🇳 中国', region_stats.get('CN', 0)),
            ('US', '🇺🇸 美国', region_stats.get('US', 0)),
            ('EU', '🇪🇺 欧洲', region_stats.get('EU', 0)),
            ('SG', '🌏 其他', region_stats.get('SG', 0)),
            ('ALL', '🌍 全部', len(self.providers))
        ]
        
        for i, (code, name, count) in enumerate(regions, 1):
            print(f"  {i}. {name} ({count} 家提供商)")
        
        # 获取用户选择
        while True:
            try:
                choice = input(f"\n请选择 [1-{len(regions)}]: ").strip()
                if not choice.isdigit():
                    print(f"{Colors.RED}请输入数字{Colors.ENDC}")
                    continue
                
                idx = int(choice) - 1
                if 0 <= idx < len(regions):
                    self.selected_region = regions[idx][0]
                    print(f"\n✅ 已选择：{regions[idx][1]}")
                    break
                else:
                    print(f"{Colors.RED}请输入 {1}-{len(regions)} 之间的数字{Colors.ENDC}")
            except EOFError:
                sys.exit(0)
    
    def _select_provider(self):
        """选择提供商"""
        print(f"\n{Colors.BOLD}🏢 步骤 2/5: 选择提供商{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        # 过滤提供商
        if self.selected_region == 'ALL':
            providers = list(self.providers.values())
        else:
            providers = [p for p in self.providers.values() if p.region == self.selected_region]
        
        # 排序（按模型数量）
        providers.sort(key=lambda p: len(p.models), reverse=True)
        
        # 显示选项
        for i, provider in enumerate(providers, 1):
            cheapest = provider.get_cheapest_model()
            price_str = ""
            if cheapest and cheapest.pricing:
                price_str = f" (¥{cheapest.pricing.input_per_1k}/1K 起)"
            
            print(f"  {i:2d}. {provider.name:20s} - {len(provider.models)} 个模型{price_str}")
            print(f"       {provider.name_en}")
        
        # 获取用户选择
        while True:
            try:
                choice = input(f"\n请选择 [1-{len(providers)}]: ").strip()
                if not choice.isdigit():
                    print(f"{Colors.RED}请输入数字{Colors.ENDC}")
                    continue
                
                idx = int(choice) - 1
                if 0 <= idx < len(providers):
                    self.selected_provider = providers[idx]
                    print(f"\n✅ 已选择：{self.selected_provider.name}")
                    print(f"   官网：{self.selected_provider.website}")
                    print(f"   配置文档：{self.selected_provider.api_key_url}")
                    break
                else:
                    print(f"{Colors.RED}请输入 {1}-{len(providers)} 之间的数字{Colors.ENDC}")
            except EOFError:
                sys.exit(0)
    
    def _select_model(self):
        """选择模型"""
        print(f"\n{Colors.BOLD}🤖 步骤 3/5: 选择模型{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        if not self.selected_provider:
            print(f"{Colors.RED}错误：未选择提供商{Colors.ENDC}")
            return
        
        models = self.selected_provider.models
        
        # 分类显示
        print(f"{Colors.BOLD}按推荐度排序:{Colors.ENDC}\n")
        
        # 按价格排序（从便宜到贵）
        models_sorted = sorted(models, key=lambda m: m.pricing.input_per_1k if m.pricing else 999)
        
        for i, model in enumerate(models_sorted, 1):
            price_str = ""
            if model.pricing:
                price_str = f"¥{model.pricing.input_per_1k}/¥{model.pricing.output_per_1k} per 1K"
            
            context_str = f"{model.context_length // 1000}K" if model.context_length >= 1000 else f"{model.context_length}"
            
            caps = ", ".join(model.capabilities[:3]) if model.capabilities else "通用"
            
            print(f"  {i:2d}. {model.name:25s} - {context_str:6s} 上下文")
            print(f"       {model.description}")
            print(f"       能力：{caps}")
            print(f"       价格：{price_str}")
            
            if model.benchmarks:
                benchmark_str = ", ".join(f"{k}:{v}" for k, v in list(model.benchmarks.items())[:2])
                print(f"       基准：{benchmark_str}")
            
            print()
        
        # 获取用户选择
        while True:
            try:
                choice = input(f"请选择 [1-{len(models)}]: ").strip()
                if not choice.isdigit():
                    print(f"{Colors.RED}请输入数字{Colors.ENDC}")
                    continue
                
                idx = int(choice) - 1
                if 0 <= idx < len(models):
                    self.selected_model = models_sorted[idx]
                    print(f"\n✅ 已选择：{self.selected_model.name}")
                    print(f"   描述：{self.selected_model.description}")
                    print(f"   上下文：{self.selected_model.context_length} tokens")
                    if self.selected_model.pricing:
                        print(f"   价格：{self.selected_model.pricing}")
                    break
                else:
                    print(f"{Colors.RED}请输入 {1}-{len(models)} 之间的数字{Colors.ENDC}")
            except EOFError:
                sys.exit(0)
    
    def _input_api_key(self):
        """输入 API Key"""
        print(f"\n{Colors.BOLD}🔑 步骤 4/5: 配置 API Key{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        if not self.selected_provider:
            print(f"{Colors.RED}错误：未选择提供商{Colors.ENDC}")
            return
        
        print(f"提供商：{self.selected_provider.name}")
        print(f"环境变量：{Colors.YELLOW}{self.selected_provider.api_key_env}{Colors.ENDC}")
        print(f"\n获取 API Key: {self.selected_provider.api_key_url}")
        print(f"\n{Colors.YELLOW}⚠️  提示：{Colors.ENDC}")
        print(f"  - API Key 仅保存在本地配置文件中")
        print(f"  - 不会上传到任何服务器")
        print(f"  - 建议使用环境变量或加密存储")
        print(f"\n{Colors.CYAN}提示：直接粘贴 API Key 后按回车即可{Colors.ENDC}")
        print(f"\n{Colors.GREEN}选项：{Colors.ENDC}")
        print(f"  1. 输入 API Key")
        print(f"  2. 使用自定义 API 端点")
        print(f"  3. 跳过（稍后手动配置）")
        
        while True:
            try:
                choice = input(f"\n请选择 [1-3]: ").strip()
                
                if choice == '3':
                    print(f"\n{Colors.YELLOW}⚠️  稍后请手动配置 API Key{Colors.ENDC}")
                    self.api_key = "sk-xxx"  # 占位符
                    break
                elif choice == '2':
                    # 自定义端点
                    custom_endpoint = input("请输入自定义 API 端点 (回车跳过): ").strip()
                    custom_model = input("请输入自定义模型名称 (回车跳过): ").strip()
                    
                    if custom_endpoint:
                        self.selected_provider.api_base = custom_endpoint
                        print(f"✅ 自定义端点：{custom_endpoint}")
                    if custom_model:
                        # 创建临时模型
                        from providers.loader import Model
                        self.selected_model = Model(
                            name=custom_model,
                            description="自定义模型",
                            context_length=32000,
                            pricing=None
                        )
                        print(f"✅ 自定义模型：{custom_model}")
                    
                    # 继续输入 API Key
                    api_key = input("请输入 API Key: ").strip()
                    if not api_key:
                        print(f"{Colors.RED}API Key 不能为空{Colors.ENDC}")
                        continue
                    self.api_key = api_key
                    print(f"\n✅ API Key 已配置")
                    break
                else:
                    # 选项 1: 直接输入 API Key
                    api_key = input("请输入 API Key: ").strip()
                    
                    if not api_key:
                        print(f"{Colors.RED}API Key 不能为空{Colors.ENDC}")
                        continue
                    
                    # 简单验证格式
                    if len(api_key) < 10:
                        print(f"{Colors.YELLOW}⚠️  API Key 看起来太短，确认继续？[y/N]: {Colors.ENDC}", end='')
                        confirm = input().strip().lower()
                        if confirm != 'y':
                            continue
                    
                    self.api_key = api_key
                    print(f"\n✅ API Key 已配置")
                    break
            except EOFError:
                sys.exit(0)
    
    def _select_config_path(self):
        """选择配置文件路径"""
        print(f"\n{Colors.BOLD}📁 步骤 5/5: 选择保存路径{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        default_path = "config.yaml"
        print(f"默认路径：{Colors.YELLOW}{default_path}{Colors.ENDC}")
        
        try:
            path = input(f"\n请输入路径 [回车使用默认]: ").strip()
            if not path:
                path = default_path
            
            self.config_path = path
            print(f"\n✅ 配置文件将保存到：{path}")
        except EOFError:
            sys.exit(0)
    
    def _generate_config(self):
        """生成配置文件"""
        print(f"\n{Colors.BOLD}⚙️  生成配置...{Colors.ENDC}")
        print(f"{'-'*60}\n")
        
        if not all([self.selected_provider, self.selected_model, self.api_key]):
            print(f"{Colors.RED}错误：配置信息不完整{Colors.ENDC}")
            return
        
        # 构建配置
        config = {
            'version': '1.4.0',
            'created_at': __import__('datetime').datetime.now().isoformat(),
            
            'server': {
                'host': '0.0.0.0',
                'port': 19377,
                'auth_tokens': [
                    self.api_key  # 使用用户输入的 API Key 作为初始 token
                ],
                'rate_limiting': {
                    'enabled': True,
                    'requests_per_minute': 60,
                    'tokens_per_minute': 100000
                }
            },
            
            'providers': {
                'template': self.selected_provider.id,
                'selected_model': self.selected_model.id,
                
                'custom': [
                    {
                        'id': self.selected_provider.id,
                        'name': self.selected_provider.name,
                        'base_url': self.selected_provider.base_url,
                        'api_key_env': self.selected_provider.api_key_env,
                        'models': [
                            {
                                'id': self.selected_model.id,
                                'name': self.selected_model.name,
                                'context_length': self.selected_model.context_length,
                                'max_output_tokens': self.selected_model.max_output_tokens
                            }
                        ]
                    }
                ]
            },
            
            'budget': {
                'daily_limit': 100.0,  # CNY
                'monthly_limit': 3000.0,  # CNY
                'alert_threshold': 0.8  # 80% 时告警
            },
            
            'logging': {
                'level': 'INFO',
                'file': str(Path.home() / '.local' / 'var' / 'log' / 'bridge-server' / 'bridge-server.log'),
                'max_size_mb': 100,
                'backup_count': 5
            }
        }
        
        # 设置环境变量提示
        config['environment'] = {
            self.selected_provider.api_key_env: 'sk-xxx (请替换为真实 API Key)'
        }
        
        # 保存到文件
        try:
            config_path = Path(self.config_path)
            
            # 备份已有配置
            if config_path.exists():
                backup_path = config_path.with_suffix('.yaml.bak')
                config_path.rename(backup_path)
                print(f"✅ 已备份旧配置：{backup_path}")
            
            # 写入新配置
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
            
            print(f"✅ 配置文件已保存：{config_path}")
            
            # 生成 .env 文件
            env_path = Path('.env')
            env_content = f"# Bridge Server Environment\n\n"
            env_content += f"# API Key for {self.selected_provider.name}\n"
            env_content += f"{self.selected_provider.api_key_env}=sk-xxx\n"
            env_content += f"# TODO: 将 sk-xxx 替换为您的真实 API Key\n"
            
            if not env_path.exists():
                with open(env_path, 'w', encoding='utf-8') as f:
                    f.write(env_content)
                print(f"✅ 环境变量文件已保存：{env_path}")
            
        except Exception as e:
            print(f"{Colors.RED}❌ 保存配置失败：{e}{Colors.ENDC}")
            raise
    
    def _finish(self):
        """完成配置"""
        print(f"\n{Colors.CYAN}{'='*60}{Colors.ENDC}")
        print(f"{Colors.GREEN}✅ 配置完成！{Colors.ENDC}")
        print(f"{Colors.CYAN}{'='*60}{Colors.ENDC}\n")
        
        print(f"📋 配置摘要:")
        print(f"  提供商：{self.selected_provider.name}")
        print(f"  模型：{self.selected_model.name}")
        print(f"  上下文：{self.selected_model.context_length} tokens")
        if self.selected_model.pricing:
            print(f"  价格：{self.selected_model.pricing}")
        print(f"  配置文件：{self.config_path}")
        
        print(f"\n🚀 下一步:")
        print(f"  1. 编辑配置文件（如需要）:")
        print(f"     nano {self.config_path}")
        print(f"\n  2. 设置环境变量:")
        print(f"     export {self.selected_provider.api_key_env}=your-api-key")
        print(f"\n  3. 启动服务:")
        print(f"     bridge-server start")
        print(f"\n  4. 测试连接:")
        print(f"     curl http://localhost:19377/health")
        
        print(f"\n{Colors.YELLOW}⚠️  重要提示:{Colors.ENDC}")
        print(f"  - 请将 .env 文件中的 sk-xxx 替换为您的真实 API Key")
        print(f"  - 不要将 API Key 提交到版本控制系统")
        print(f"  - 定期检查用量，避免超出预算")
        
        print(f"\n{Colors.GREEN}🎉 祝您使用愉快！{Colors.ENDC}\n")


def main():
    """主函数"""
    # 检查是否使用非交互模式
    if '--no-interactive' in sys.argv or '--quick' in sys.argv:
        # 非交互模式：生成默认配置
        print("使用快速配置模式...")
        wizard = SetupWizard()
        wizard.run_quick()
    else:
        # 交互模式
        wizard = SetupWizard()
        wizard.run()


if __name__ == "__main__":
    main()
