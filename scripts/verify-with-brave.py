#!/usr/bin/env python3
"""
Provider 模型深度核对工具 - Brave Search 版
支持估算缺失的价格数据
"""

import os
import sys
import json
import yaml
import asyncio
import aiohttp
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class BraveVerifier:
    """使用 Brave Search 验证 Provider 模型信息"""
    
    # 估算价格基准（每 1M tokens，美元）
    PRICE_ESTIMATES = {
        # 按模型级别估算
        'flagship': {'input': 5.0, 'output': 15.0},  # 旗舰模型 (GPT-4o, Claude Opus)
        'mid': {'input': 1.0, 'output': 3.0},        # 中端模型 (GPT-4o-mini, Claude Haiku)
        'economy': {'input': 0.1, 'output': 0.3},    # 经济模型 (DeepSeek, 国产)
        
        # 按上下文估算溢价
        'context_128k': 1.5,
        'context_256k': 2.0,
        'context_1m': 3.0,
    }
    
    def __init__(self):
        self.results = {}
    
    async def search_brave(self, query: str, count: int = 5) -> List[Dict]:
        """使用 Brave Search API"""
        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip"
        }
        
        # 从环境变量获取 API Key
        api_key = os.getenv('BRAVE_API_KEY')
        if not api_key:
            print(f"  ⚠️  BRAVE_API_KEY 未设置，使用估算数据")
            return []
        
        headers["X-Subscription-Token"] = api_key
        
        params = {
            "q": query,
            "count": count,
            "text_decorations": False,
            "search_lang": "en"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get('web', {}).get('results', [])
                        return results
                    else:
                        print(f"  ⚠️  Brave API 错误：{resp.status}")
                        return []
        except Exception as e:
            print(f"  ⚠️  搜索异常：{e}")
            return []
    
    def estimate_price(self, provider_id: str, model_id: str, context_size: int = 128000) -> Dict:
        """估算模型价格"""
        # 根据 Provider 和模型类型估算
        if provider_id in ['deepseek', 'yi', 'zhipu', 'baidu', 'tencent']:
            # 国产模型通常更便宜
            base = self.PRICE_ESTIMATES['economy']
        elif provider_id in ['openai', 'anthropic', 'google']:
            # 国际旗舰模型
            if 'opus' in model_id.lower() or 'gpt-5' in model_id.lower() or 'max' in model_id.lower():
                base = self.PRICE_ESTIMATES['flagship']
            else:
                base = self.PRICE_ESTIMATES['mid']
        else:
            # 其他默认中端
            base = self.PRICE_ESTIMATES['mid']
        
        # 上下文溢价
        multiplier = 1.0
        if context_size >= 1000000:
            multiplier = self.PRICE_ESTIMATES['context_1m']
        elif context_size >= 256000:
            multiplier = self.PRICE_ESTIMATES['context_256k']
        elif context_size >= 128000:
            multiplier = self.PRICE_ESTIMATES['context_128k']
        
        return {
            'input_per_1m': round(base['input'] * multiplier, 2),
            'output_per_1m': round(base['output'] * multiplier, 2),
            'estimated': True,
            'basis': f"基于{base['input']}/{base['output']}基准，上下文溢价 x{multiplier}"
        }
    
    async def verify_provider(self, provider_id: str, provider_info: Dict) -> Dict:
        """验证单个 Provider"""
        name = provider_info.get('name', provider_id)
        models = provider_info.get('models', [])
        
        print(f"\n🔍 {name} ({provider_id})")
        
        # 搜索查询
        queries = [
            f"{name} API models pricing 2025 2026 official",
            f"{provider_id} latest model list documentation",
        ]
        
        all_results = []
        for query in queries:
            results = await self.search_brave(query, count=5)
            all_results.extend(results)
        
        # 去重
        seen_urls = set()
        unique_results = []
        for r in all_results:
            url = r.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_results.append({
                    'title': r.get('title', '')[:100],
                    'url': url,
                    'snippet': r.get('description', '')[:200]
                })
        
        print(f"  搜索结果：{len(unique_results)}")
        
        # 分析模型和价格
        verified_models = []
        for model in models:
            model_id = model.get('id', '')
            context = model.get('context_length', 128000)
            
            # 在搜索结果中查找
            found_in_search = False
            price_info = None
            
            for result in unique_results:
                text = (result['title'] + ' ' + result['snippet']).lower()
                if model_id.lower() in text:
                    found_in_search = True
                    # 尝试提取价格
                    import re
                    prices = re.findall(r'\$[\d\.]+|¥[\d\.]+|€[\d\.]+', result['snippet'])
                    if prices:
                        price_info = {'raw': prices[:3], 'source': result['url']}
            
            # 如果没找到，使用估算
            if not found_in_search or not price_info:
                estimated = self.estimate_price(provider_id, model_id, context)
                price_info = {
                    'input_per_1m': estimated['input_per_1m'],
                    'output_per_1m': estimated['output_per_1m'],
                    'estimated': True,
                    'basis': estimated['basis']
                }
            
            verified_models.append({
                'model_id': model_id,
                'context': context,
                'found_in_search': found_in_search,
                'price': price_info,
            })
        
        # 查找是否有新模型
        new_models = []
        for result in unique_results:
            text = result['title'] + ' ' + result['snippet']
            # 简单检查是否有模型 ID 格式的词
            import re
            potential_models = re.findall(r'[a-z]+-[\d\.]+[a-z0-9-]*', text.lower())
            for pm in potential_models:
                if pm not in [m['model_id'] for m in models] and len(pm) > 5:
                    if pm not in new_models:
                        new_models.append(pm)
        
        if new_models:
            print(f"  可能新增模型：{new_models[:5]}")
        
        return {
            'provider': provider_id,
            'name': name,
            'verified_models': verified_models,
            'potential_new_models': new_models[:10],
            'search_results': unique_results[:5],
            'timestamp': datetime.now().isoformat(),
        }
    
    async def verify_all(self, registry_path: str) -> List[Dict]:
        """验证所有 Provider"""
        with open(registry_path, 'r', encoding='utf-8') as f:
            registry = yaml.safe_load(f)
        
        providers = registry.get('providers', [])
        print(f"开始验证 {len(providers)} 家 Provider...")
        
        # 并发验证
        semaphore = asyncio.Semaphore(3)
        
        async def limited_verify(p):
            async with semaphore:
                return await self.verify_provider(p['id'], p)
        
        tasks = [limited_verify(p) for p in providers]
        return await asyncio.gather(*tasks)


async def main():
    """主函数"""
    print("╔════════════════════════════════════════════════════╗")
    print("║   Provider 模型深度核对 (Brave Search)             ║")
    print("╚════════════════════════════════════════════════════╝")
    
    # 路径
    script_dir = Path(__file__).parent
    registry_path = script_dir.parent / 'providers' / 'registry.yaml'
    
    if not registry_path.exists():
        print(f"❌ 找不到 {registry_path}")
        return
    
    # 创建验证器
    verifier = BraveVerifier()
    
    # 执行验证
    results = await verifier.verify_all(str(registry_path))
    
    # 生成报告
    report_path = script_dir.parent / 'providers' / 'DEEP-VERIFICATION-2026-04-BRAVE.md'
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# Provider 模型深度核对报告 (Brave Search)\n\n")
        f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**方法**: Brave Search + 价格估算\n\n")
        
        # 摘要
        f.write("## 📊 总览\n\n")
        f.write(f"- Provider: {len(results)} 家\n")
        f.write(f"- 总模型：{sum(len(r['verified_models']) for r in results)} 个\n")
        f.write(f"- 估算价格：部分模型使用估算（基于市场基准）\n\n")
        
        # 详情
        for r in results:
            f.write(f"## {r['name']} ({r['provider']})\n\n")
            
            # 模型列表
            f.write("### 模型核对\n\n")
            f.write("| 模型 ID | 上下文 | 价格 (输入/输出) | 数据来源 |\n")
            f.write("|---------|--------|-----------------|----------|\n")
            
            for vm in r['verified_models']:
                price = vm['price']
                if price.get('estimated'):
                    price_str = f"¥{price['input_per_1m']}/¥{price['output_per_1m']} (估算)"
                    source = "估算"
                elif 'raw' in price:
                    price_str = ', '.join(price['raw'])
                    source = "搜索"
                else:
                    price_str = f"${price.get('input_per_1m', 'N/A')}/${price.get('output_per_1m', 'N/A')}"
                    source = "搜索"
                
                status = "✅" if vm['found_in_search'] else "⏳"
                f.write(f"| {status} `{vm['model_id']}` | {vm['context']:,} | {price_str} | {source} |\n")
            
            f.write("\n")
            
            # 新模型
            if r['potential_new_models']:
                f.write("### 可能新增的模型\n\n")
                for pm in r['potential_new_models'][:10]:
                    f.write(f"- `{pm}`\n")
                f.write("\n")
            
            # 搜索结果
            if r['search_results']:
                f.write("### 官方文档链接\n\n")
                for i, sr in enumerate(r['search_results'], 1):
                    f.write(f"{i}. [{sr['title']}]({sr['url']})\n")
                f.write("\n")
            
            f.write("---\n\n")
    
    print(f"\n✅ 报告已保存：{report_path}")
    
    # 生成更新建议
    update_path = script_dir.parent / 'providers' / 'REGISTRY-UPDATE-SUGGESTIONS.md'
    
    with open(update_path, 'w', encoding='utf-8') as f:
        f.write("# Registry 更新建议\n\n")
        f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        for r in results:
            needs_update = False
            updates = []
            
            for vm in r['verified_models']:
                if not vm['found_in_search']:
                    needs_update = True
                    updates.append(f"- ⚠️ `{vm['model_id']}` 未在搜索结果中找到，建议手动核对")
            
            if r['potential_new_models']:
                needs_update = True
                updates.append(f"- ℹ️ 可能新增模型：{r['potential_new_models'][:5]}")
            
            if needs_update:
                f.write(f"### {r['name']} ({r['provider']})\n\n")
                for u in updates:
                    f.write(f"{u}\n")
                f.write("\n")
    
    print(f"📄 更新建议已保存：{update_path}")


if __name__ == '__main__':
    asyncio.run(main())
