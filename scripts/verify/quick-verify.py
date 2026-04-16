#!/usr/bin/env python3
"""
Provider 模型快速核对工具
使用 Tavily 搜索生成核对报告，供人工验证
"""

import os
import sys
import json
import yaml
import asyncio
import aiohttp
from datetime import datetime
from pathlib import Path


async def search_with_tavily(query: str, max_results: int = 3) -> list:
    """使用 Tavily 搜索"""
    api_key = os.getenv('TAVILY_API_KEY')
    if not api_key:
        return []
    
    url = "https://api.tavily.com/search"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "query": query,
        "search_depth": "basic",
        "include_answer": False,
        "max_results": max_results
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('results', [])
                else:
                    return []
    except Exception as e:
        print(f"  搜索异常：{e}")
        return []


async def verify_provider(provider_id: str, provider_info: dict) -> dict:
    """验证单个 Provider"""
    name = provider_info.get('name', provider_id)
    docs_url = provider_info.get('docs_url', '')
    models = provider_info.get('models', [])
    
    print(f"\n🔍 {name} ({provider_id})")
    
    # 构建搜索查询
    if provider_id == 'dashscope':
        query = "阿里云 dashscope 通义千问 qwen 模型列表 官方文档 2025"
    elif provider_id == 'openai':
        query = "OpenAI GPT-4o models API pricing official 2025"
    elif provider_id == 'anthropic':
        query = "Anthropic Claude 3.5 sonnet haiku models API 2025"
    elif provider_id == 'google':
        query = "Google Gemini 1.5 pro flash models API pricing 2025"
    elif provider_id == 'moonshot':
        query = "月之暗面 Kimi moonshot 模型 API 官方 2025"
    elif provider_id == 'deepseek':
        query = "DeepSeek chat coder 模型 API 官方 2025"
    elif provider_id == 'mistral':
        query = "Mistral AI large medium small models API 2025"
    else:
        query = f"{name} models API pricing official 2025"
    
    # 执行搜索
    results = await search_with_tavily(query, max_results=5)
    
    # 提取有用信息
    search_results = []
    for r in results:
        search_results.append({
            'title': r.get('title', ''),
            'url': r.get('url', ''),
            'snippet': r.get('content', '')[:200]  # 只保留前 200 字符
        })
    
    # 预期模型列表
    expected_models = [m['id'] for m in models]
    
    print(f"  预期模型：{len(expected_models)}")
    print(f"  搜索结果：{len(search_results)}")
    
    # 检查搜索结果中是否提到预期模型
    matched_in_search = []
    for exp_id in expected_models:
        for sr in search_results:
            if exp_id.lower() in sr['title'].lower() or exp_id.lower() in sr['snippet'].lower():
                matched_in_search.append(exp_id)
                break
    
    print(f"  搜索中提到：{len(matched_in_search)}")
    
    return {
        'provider': provider_id,
        'name': name,
        'docs_url': docs_url,
        'search_query': query,
        'expected_models': expected_models,
        'matched_in_search': matched_in_search,
        'search_results': search_results,
        'timestamp': datetime.now().isoformat(),
    }


async def main():
    """主函数"""
    print("╔════════════════════════════════════════════════════╗")
    print("║   Provider 模型快速核对工具                        ║")
    print("╚════════════════════════════════════════════════════╝")
    
    # 检查 API Key
    if not os.getenv('TAVILY_API_KEY'):
        print("\n❌ TAVILY_API_KEY 未设置")
        return
    
    # 加载 registry
    repo_root = Path(__file__).resolve().parents[2]
    registry_path = repo_root / 'src' / 'bridge_server' / 'registry.yaml'
    
    with open(registry_path, 'r', encoding='utf-8') as f:
        registry = yaml.safe_load(f)
    
    providers = registry.get('providers', [])
    
    print(f"\n开始核对 {len(providers)} 家 Provider...\n")
    
    # 并发验证
    semaphore = asyncio.Semaphore(3)
    
    async def limited_verify(p):
        async with semaphore:
            return await verify_provider(p['id'], p)
    
    tasks = [limited_verify(p) for p in providers]
    results = await asyncio.gather(*tasks)
    
    # 生成 Markdown 报告
    report_path = repo_root / 'reports' / 'provider-catalog' / 'QUICK-VERIFICATION.md'
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# Provider 模型快速核对报告\n\n")
        f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**方法**: Tavily 搜索辅助 + 人工核对\n\n")
        
        f.write("## 📊 总览\n\n")
        f.write(f"- Provider 数量：{len(results)}\n")
        f.write(f"- 总模型数：{sum(len(r['expected_models']) for r in results)}\n\n")
        
        f.write("## 🔍 核对详情\n\n")
        
        for r in results:
            f.write(f"### {r['name']} ({r['provider']})\n\n")
            f.write(f"**官方文档**: [{r['docs_url']}]({r['docs_url']})\n\n")
            f.write(f"**搜索查询**: `{r['search_query']}`\n\n")
            
            # 预期模型
            f.write("**预期模型**:\n")
            for model_id in r['expected_models']:
                matched = "✅" if model_id in r['matched_in_search'] else "⏳"
                f.write(f"- {matched} `{model_id}`\n")
            f.write("\n")
            
            # 搜索结果
            if r['search_results']:
                f.write("**相关搜索结果**:\n\n")
                for i, sr in enumerate(r['search_results'], 1):
                    f.write(f"{i}. **[{sr['title'][:80]}]({sr['url']})**\n")
                    f.write(f"   > {sr['snippet']}...\n\n")
            
            # 核对建议
            f.write(f"**核对建议**:\n")
            f.write(f"1. 访问 [官方文档]({r['docs_url']})\n")
            f.write(f"2. 确认上述 {len(r['expected_models'])} 个模型是否仍然存在\n")
            f.write(f"3. 检查是否有新增模型\n")
            f.write(f"4. 核对价格和上下文长度\n\n")
            
            f.write("---\n\n")
    
    print(f"\n✅ 报告已保存：{report_path}")
    print(f"\n💡 下一步:")
    print(f"   1. 打开报告文件")
    print(f"   2. 点击官方文档链接")
    print(f"   3. 人工核对模型列表")
    print(f"   4. 更新 VERIFICATION-CHECKLIST.md")


if __name__ == '__main__':
    asyncio.run(main())
