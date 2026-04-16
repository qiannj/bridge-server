#!/usr/bin/env python3
"""
使用 Tavily 搜索 + 网页抓取自动验证 Provider 模型信息
改进版：直接抓取官方文档页面
"""

import os
import sys
import json
import yaml
import asyncio
import aiohttp
import re
from typing import Dict, List, Optional
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class ProviderVerifier:
    """Provider 模型验证器（改进版）"""
    
    def __init__(self):
        self.tavily_api_key = os.getenv('TAVILY_API_KEY')
        self.results = {}
        
    async def fetch_url(self, url: str) -> Optional[str]:
        """抓取网页内容（使用简单的 HTTP GET）"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=15) as resp:
                    if resp.status == 200:
                        return await resp.text('utf-8')
                    else:
                        print(f"  ⚠️  抓取失败：{resp.status}")
                        return None
        except Exception as e:
            print(f"  ⚠️  抓取异常：{e}")
            return None
    
    def extract_models_from_html(self, html: str, provider_id: str) -> List[str]:
        """从 HTML 中提取模型 ID"""
        models = []
        
        # 清理 HTML，保留文本
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text)
        
        # 根据不同 Provider 使用不同的提取策略
        if provider_id == 'openai':
            # 提取 GPT 模型
            patterns = [
                r'gpt-4o(?:-mini)?',
                r'gpt-4-turbo',
                r'o1-preview',
                r'o1-mini',
                r'gpt-3\.5-turbo'
            ]
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                models.extend(matches)
        
        elif provider_id == 'anthropic':
            # 提取 Claude 模型
            patterns = [
                r'claude-3-5-sonnet-\d{8}',
                r'claude-3-5-haiku-\d{8}',
                r'claude-3-opus-\d{8}',
                r'claude-3-sonnet',
                r'claude-3-haiku'
            ]
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                models.extend(matches)
        
        elif provider_id == 'google':
            # 提取 Gemini 模型
            patterns = [
                r'gemini-1\.5-pro',
                r'gemini-1\.5-flash',
                r'gemini-1\.0-pro',
                r'gemini-pro'
            ]
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                models.extend(matches)
        
        elif provider_id == 'dashscope':
            # 提取 Qwen 模型
            patterns = [
                r'qwen3-max',
                r'qwen3\.5-flash',
                r'qwen3-coder-plus',
                r'qwen-2\.5',
                r'qwen-max',
                r'qwen-plus'
            ]
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                models.extend(matches)
        
        elif provider_id == 'moonshot':
            # 提取 Kimi 模型
            patterns = [
                r'moonshot-v1-8k',
                r'moonshot-v1-32k',
                r'moonshot-v1-128k',
                r'kimi'
            ]
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                models.extend(matches)
        
        elif provider_id == 'deepseek':
            patterns = [
                r'deepseek-chat',
                r'deepseek-coder',
                r'deepseek-v3'
            ]
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                models.extend(matches)
        
        elif provider_id == 'mistral':
            patterns = [
                r'mistral-large',
                r'mistral-medium',
                r'mistral-small',
                r'mistral-nemo'
            ]
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                models.extend(matches)
        
        else:
            # 通用提取：查找包含 provider 名称的模型 ID
            pass
        
        return list(set(models))  # 去重
    
    async def verify_provider(self, provider_id: str, provider_info: Dict) -> Dict:
        """验证单个 Provider"""
        name = provider_info.get('name', provider_id)
        docs_url = provider_info.get('docs_url', '')
        
        print(f"\n🔍 验证 {name} ({provider_id})...")
        
        # 优先抓取官方文档
        if docs_url:
            print(f"  📄 抓取官方文档：{docs_url}")
            html = await self.fetch_url(docs_url)
            
            if html:
                found_models = self.extract_models_from_html(html, provider_id)
                print(f"  ✅ 抓取成功，找到 {len(found_models)} 个模型")
                
                if found_models:
                    print(f"     模型：{found_models[:10]}")  # 只显示前 10 个
            else:
                found_models = []
        else:
            found_models = []
        
        # 对比预期模型
        expected_models = provider_info.get('models', [])
        expected_ids = [m['id'] for m in expected_models]
        
        # 找出匹配和差异
        matched = []
        missing = []
        
        for exp_id in expected_ids:
            # 检查是否在找到的模型中
            found = any(exp_id.lower() in fm.lower() for fm in found_models)
            if found:
                matched.append(exp_id)
            else:
                missing.append(exp_id)
        
        print(f"  匹配：{len(matched)}/{len(expected_ids)}")
        
        if missing:
            print(f"  ⚠️  未找到：{missing[:5]}")
        
        return {
            'provider': provider_id,
            'status': 'success',
            'docs_url': docs_url,
            'found_models': found_models,
            'expected_models': expected_ids,
            'matched': matched,
            'missing': missing,
            'timestamp': datetime.now().isoformat(),
        }
    
    async def verify_all_providers(self, registry_path: str) -> List[Dict]:
        """验证所有 Provider"""
        # 加载 registry
        with open(registry_path, 'r', encoding='utf-8') as f:
            registry = yaml.safe_load(f)
        
        providers = registry.get('providers', [])
        results = []
        
        print(f"开始验证 {len(providers)} 家 Provider...")
        
        # 并发验证（限制并发数）
        semaphore = asyncio.Semaphore(5)  # 最多 5 个并发
        
        async def limited_verify(provider):
            async with semaphore:
                return await self.verify_provider(provider['id'], provider)
        
        tasks = [limited_verify(p) for p in providers]
        results = await asyncio.gather(*tasks)
        
        return results


async def main():
    """主函数"""
    print("╔════════════════════════════════════════════════════╗")
    print("║   Tavily 自动验证 Provider 模型信息                ║")
    print("╚════════════════════════════════════════════════════╝")
    print()
    
    # 检查 API Key
    if not os.getenv('TAVILY_API_KEY'):
        print("❌ 错误：TAVILY_API_KEY 环境变量未设置")
        print()
        print("请设置 API Key:")
        print("  export TAVILY_API_KEY='tvly-xxx'")
        print()
        print("或者从 https://tavily.com 获取 API Key")
        return
    
    # 路径
    repo_root = Path(__file__).resolve().parents[2]
    registry_path = repo_root / 'src' / 'bridge_server' / 'registry.yaml'
    
    if not registry_path.exists():
        print(f"❌ 错误：找不到 {registry_path}")
        return
    
    # 创建验证器
    verifier = TavilyVerifier()
    
    # 执行验证
    results = await verifier.verify_all_providers(str(registry_path))
    
    # 生成报告
    print("\n" + "=" * 60)
    print("验证报告")
    print("=" * 60)
    
    success_count = sum(1 for r in results if r['status'] == 'success')
    total_count = len(results)
    
    print(f"\n总计：{success_count}/{total_count} 验证成功")
    print(f"匹配率：{sum(len(r.get('matched', [])) for r in results)}/{sum(len(r.get('expected_models', [])) for r in results)}")
    
    # 保存报告
    report_path = repo_root / 'reports' / 'provider-catalog' / 'TAVILY-VERIFICATION-REPORT.json'
    report_data = {
        'timestamp': datetime.now().isoformat(),
        'method': 'tavily_search',
        'total_providers': total_count,
        'success_count': success_count,
        'results': results,
        'summary': {
            'total_models_expected': sum(len(r.get('expected_models', [])) for r in results),
            'total_models_matched': sum(len(r.get('matched', [])) for r in results),
            'providers_with_missing': [r['provider'] for r in results if r.get('missing')],
        }
    }
    
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n📁 报告已保存：{report_path}")
    
    # 生成 Markdown 摘要
    md_path = script_dir.parent / 'providers' / 'TAVILY-VERIFICATION-SUMMARY.md'
    
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write("# Tavily 自动验证报告\n\n")
        f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**方法**: Tavily 网络搜索\n\n")
        
        f.write("## 📊 总览\n\n")
        f.write(f"- 验证 Provider: {total_count} 家\n")
        f.write(f"- 验证成功：{success_count} 家\n")
        f.write(f"- 模型匹配：{report_data['summary']['total_models_matched']}/{report_data['summary']['total_models_expected']}\n\n")
        
        f.write("## ✅ 验证详情\n\n")
        
        for result in results:
            if result['status'] == 'success':
                f.write(f"### {result['provider']}\n\n")
                f.write(f"- 匹配：{len(result.get('matched', []))}/{len(result.get('expected_models', []))}\n")
                f.write(f"- 搜索查询：{result.get('search_query', 'N/A')}\n")
                
                if result.get('missing'):
                    f.write(f"- ⚠️ 未找到：{result['missing'][:5]}\n")
                if result.get('extra'):
                    f.write(f"- ℹ️ 可能新增：{result['extra'][:5]}\n")
                if result.get('official_urls'):
                    f.write(f"- 📄 官方文档：{result['official_urls'][0]}\n")
                
                f.write("\n")
    
    print(f"📄 摘要已保存：{md_path}")


if __name__ == '__main__':
    asyncio.run(main())
