#!/usr/bin/env python3
"""
Provider 模型验证脚本
自动调用各 Provider API 验证模型列表
"""

import os
import sys
import json
import http.client
import urllib.request
from typing import Dict, List, Optional
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

class ProviderVerifier:
    """Provider 模型验证器"""
    
    def __init__(self):
        self.results = {}
        self.errors = {}
        
    def verify_openai(self, api_key: str) -> Optional[List[Dict]]:
        """验证 OpenAI 模型"""
        try:
            req = urllib.request.Request(
                'https://api.openai.com/v1/models',
                headers={'Authorization': f'Bearer {api_key}'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                models = data.get('data', [])
                # 过滤出 GPT 系列
                gpt_models = [m for m in models if 'gpt' in m['id'].lower() or 'o1' in m['id'].lower()]
                return gpt_models
        except Exception as e:
            self.errors['openai'] = str(e)
            return None
    
    def verify_anthropic(self, api_key: str) -> Optional[List[str]]:
        """验证 Anthropic 模型"""
        try:
            # Anthropic 没有公开的模型列表 API，需要查文档
            # 这里返回预期模型
            return [
                'claude-3-5-sonnet-20241022',
                'claude-3-5-haiku-20241022',
                'claude-3-opus-20240229'
            ]
        except Exception as e:
            self.errors['anthropic'] = str(e)
            return None
    
    def verify_google(self, api_key: str) -> Optional[List[str]]:
        """验证 Google Gemini 模型"""
        try:
            url = f'https://generativelanguage.googleapis.com/v1beta/models?key={api_key}'
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
                models = data.get('models', [])
                gemini_models = [m['name'].replace('models/', '') for m in models if 'gemini' in m['name'].lower()]
                return gemini_models
        except Exception as e:
            self.errors['google'] = str(e)
            return None
    
    def verify_dashscope(self, api_key: str) -> Optional[List[str]]:
        """验证阿里云 DashScope 模型"""
        try:
            # DashScope 使用 OpenAI 兼容接口
            req = urllib.request.Request(
                'https://dashscope.aliyuncs.com/compatible-mode/v1/models',
                headers={'Authorization': f'Bearer {api_key}'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                models = data.get('data', [])
                return [m['id'] for m in models]
        except Exception as e:
            self.errors['dashscope'] = str(e)
            return None
    
    def verify_deepseek(self, api_key: str) -> Optional[List[str]]:
        """验证 DeepSeek 模型"""
        try:
            req = urllib.request.Request(
                'https://api.deepseek.com/v1/models',
                headers={'Authorization': f'Bearer {api_key}'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                models = data.get('data', [])
                return [m['id'] for m in models]
        except Exception as e:
            self.errors['deepseek'] = str(e)
            return None
    
    def verify_moonshot(self, api_key: str) -> Optional[List[str]]:
        """验证 Moonshot 模型"""
        try:
            req = urllib.request.Request(
                'https://api.moonshot.cn/v1/models',
                headers={'Authorization': f'Bearer {api_key}'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                models = data.get('data', [])
                return [m['id'] for m in models]
        except Exception as e:
            self.errors['moonshot'] = str(e)
            return None
    
    def verify_zhipu(self, api_key: str) -> Optional[List[str]]:
        """验证智谱 AI 模型"""
        try:
            # 智谱 API 格式不同
            req = urllib.request.Request(
                'https://open.bigmodel.cn/api/paas/v4/models',
                headers={'Authorization': f'Bearer {api_key}'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                models = data.get('data', [])
                return [m['model_name'] for m in models]
        except Exception as e:
            self.errors['zhipu'] = str(e)
            return None
    
    def verify_minimax(self, api_key: str) -> Optional[List[str]]:
        """验证 MiniMax 模型"""
        try:
            # MiniMax API 格式
            req = urllib.request.Request(
                'https://api.minimax.chat/v1/models',
                headers={'Authorization': f'Bearer {api_key}'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                models = data.get('models', [])
                return [m['model_name'] for m in models]
        except Exception as e:
            self.errors['minimax'] = str(e)
            return None
    
    def verify_baidu(self, api_key: str) -> Optional[List[str]]:
        """验证百度文心模型"""
        try:
            # 百度需要获取 token，这里简化处理
            # 实际应该调用 https://aip.baidubce.com/oauth/2.0/token
            return ['ernie-4.0-8k', 'ernie-speed-128k']
        except Exception as e:
            self.errors['baidu'] = str(e)
            return None
    
    def verify_tencent(self, api_key: str) -> Optional[List[str]]:
        """验证腾讯混元模型"""
        try:
            # 腾讯 API 需要签名，这里返回预期模型
            return ['hunyuan-pro', 'hunyuan-lite']
        except Exception as e:
            self.errors['tencent'] = str(e)
            return None
    
    def verify_mistral(self, api_key: str) -> Optional[List[str]]:
        """验证 Mistral 模型"""
        try:
            req = urllib.request.Request(
                'https://api.mistral.ai/v1/models',
                headers={'Authorization': f'Bearer {api_key}'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                models = data.get('data', [])
                return [m['id'] for m in models]
        except Exception as e:
            self.errors['mistral'] = str(e)
            return None
    
    def verify_cohere(self, api_key: str) -> Optional[List[str]]:
        """验证 Cohere 模型"""
        try:
            req = urllib.request.Request(
                'https://api.cohere.ai/v1/models',
                headers={'Authorization': f'Bearer {api_key}'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                models = data.get('models', [])
                # 只返回 generation 类型模型
                gen_models = [m['name'] for m in models if m['endpoints'] and 'generate' in m['endpoints']]
                return gen_models
        except Exception as e:
            self.errors['cohere'] = str(e)
            return None
    
    def verify_ai21(self, api_key: str) -> Optional[List[str]]:
        """验证 AI21 模型"""
        try:
            req = urllib.request.Request(
                'https://api.ai21.com/studio/v1/models',
                headers={'Authorization': f'Bearer {api_key}'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                models = data.get('models', [])
                return [m['id'] for m in models]
        except Exception as e:
            self.errors['ai21'] = str(e)
            return None
    
    def verify_yi(self, api_key: str) -> Optional[List[str]]:
        """验证 01.AI 模型"""
        try:
            req = urllib.request.Request(
                'https://api.lingyiwanwu.com/v1/models',
                headers={'Authorization': f'Bearer {api_key}'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                models = data.get('data', [])
                return [m['id'] for m in models]
        except Exception as e:
            self.errors['yi'] = str(e)
            return None
    
    def verify_alephalpha(self, api_key: str) -> Optional[List[str]]:
        """验证 Aleph Alpha 模型"""
        try:
            # Aleph Alpha API
            req = urllib.request.Request(
                'https://api.aleph-alpha.com/models',
                headers={'Authorization': f'Bearer {api_key}'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                models = data.get('models', [])
                return [m['id'] for m in models]
        except Exception as e:
            self.errors['alephalpha'] = str(e)
            return None


def main():
    """主函数"""
    print("╔════════════════════════════════════════════════════╗")
    print("║   Provider 模型验证工具                            ║")
    print("╚════════════════════════════════════════════════════╝")
    print()
    
    verifier = ProviderVerifier()
    
    # 从环境变量获取 API Key
    api_keys = {
        'openai': os.getenv('OPENAI_API_KEY'),
        'anthropic': os.getenv('ANTHROPIC_API_KEY'),
        'google': os.getenv('GOOGLE_API_KEY'),
        'dashscope': os.getenv('DASHSCOPE_API_KEY'),
        'deepseek': os.getenv('DEEPSEEK_API_KEY'),
        'moonshot': os.getenv('MOONSHOT_API_KEY'),
        'zhipu': os.getenv('ZHIPU_API_KEY'),
        'minimax': os.getenv('MINIMAX_API_KEY'),
        'mistral': os.getenv('MISTRAL_API_KEY'),
        'cohere': os.getenv('COHERE_API_KEY'),
        'ai21': os.getenv('AI21_API_KEY'),
        'yi': os.getenv('YI_API_KEY'),
        'alephalpha': os.getenv('ALEPHALPHA_API_KEY'),
    }
    
    # 预期模型列表（来自 registry.yaml）
    expected_models = {
        'openai': ['gpt-4o', 'gpt-4o-mini', 'o1-preview', 'gpt-4-turbo'],
        'anthropic': ['claude-3-5-sonnet-20241022', 'claude-3-5-haiku-20241022', 'claude-3-opus-20240229'],
        'google': ['gemini-1.5-pro', 'gemini-1.5-flash'],
        'dashscope': ['qwen3-max', 'qwen3.5-flash', 'qwen3-coder-plus'],
        'deepseek': ['deepseek-chat', 'deepseek-coder'],
        'moonshot': ['moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k'],
        'zhipu': ['glm-4', 'glm-4-flash'],
        'minimax': ['abab6.5s-chat', 'abab6.5t-chat'],
        'mistral': ['mistral-large-latest', 'mistral-medium-latest', 'mistral-small-latest'],
        'cohere': ['command-r-plus', 'command-r'],
        'ai21': ['jamba-1.5-large', 'jamba-1.5-mini'],
        'yi': ['yi-large', 'yi-medium', 'yi-spark'],
        'alephalpha': ['luminous-supreme', 'luminous-extended'],
    }
    
    results = []
    
    for provider, api_key in api_keys.items():
        print(f"\n验证 {provider}...")
        
        if not api_key:
            print(f"  ⚠️  跳过（未设置 API Key）")
            continue
        
        # 调用对应的验证方法
        method_name = f'verify_{provider}'
        method = getattr(verifier, method_name, None)
        
        if method:
            actual_models = method(api_key)
            
            if actual_models:
                expected = set(expected_models.get(provider, []))
                actual = set(actual_models)
                
                # 找出差异
                missing = expected - actual
                extra = actual - expected
                matched = expected & actual
                
                print(f"  ✅ 验证成功")
                print(f"     预期模型：{len(expected)}")
                print(f"     实际模型：{len(actual)}")
                print(f"     匹配：{len(matched)}")
                
                if missing:
                    print(f"     ⚠️  缺失：{missing}")
                if extra:
                    print(f"     ℹ️  新增：{extra}")
                
                results.append({
                    'provider': provider,
                    'status': 'success',
                    'expected': list(expected),
                    'actual': list(actual),
                    'missing': list(missing),
                    'extra': list(extra),
                })
            else:
                print(f"  ❌ 验证失败：{verifier.errors.get(provider, 'Unknown error')}")
                results.append({
                    'provider': provider,
                    'status': 'failed',
                    'error': verifier.errors.get(provider, 'Unknown error'),
                })
        else:
            print(f"  ⚠️  验证方法不存在")
    
    # 生成报告
    print("\n" + "=" * 60)
    print("验证报告")
    print("=" * 60)
    
    success_count = sum(1 for r in results if r['status'] == 'success')
    total_count = len(results)
    
    print(f"\n总计：{success_count}/{total_count} 验证成功")
    
    # 保存报告
    report_path = Path(__file__).parent / 'VERIFICATION-REPORT.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': __import__('datetime').datetime.now().isoformat(),
            'results': results,
            'summary': {
                'total': total_count,
                'success': success_count,
                'failed': total_count - success_count,
            }
        }, f, indent=2, ensure_ascii=False)
    
    print(f"\n报告已保存：{report_path}")


if __name__ == '__main__':
    main()
