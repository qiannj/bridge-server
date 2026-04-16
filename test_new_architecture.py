#!/usr/bin/env python3
"""
Provider系统测试示例 - 验证新架构的功能
"""

import asyncio
import logging
import os
import sys
import json
from pathlib import Path

# 添加src目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.providers import (
    ProviderManager, 
    ProviderConfig, 
    RoutingStrategy,
    DashScopeProvider,
    OpenAIProvider,
    MoonshotProvider
)
from src.services.routing.router import SmartRouter, RouterConfig
from src.utils.cache import HybridCache

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_provider_system():
    """测试Provider系统"""
    
    print("=" * 60)
    print("Bridge Server v2.0 - Provider系统测试")
    print("=" * 60)
    
    # 1. 创建缓存系统
    print("\n1. 初始化缓存系统...")
    cache = HybridCache(
        redis_url=os.getenv("REDIS_URL"),  # 可选，没有Redis也能工作
        l1_maxsize=1000,
        l1_ttl=300
    )
    
    # 2. 创建Provider管理器
    print("\n2. 初始化Provider管理器...")
    provider_manager = ProviderManager(routing_strategy=RoutingStrategy.COST_OPTIMIZED)
    
    # 3. 添加Provider配置
    providers_config = [
        ProviderConfig(
            provider_type="dashscope",
            config={
                "id": "dashscope",
                "api_key": os.getenv("DASHSCOPE_API_KEY"),
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
            },
            weight=3,
            priority=1
        ),
        ProviderConfig(
            provider_type="openai", 
            config={
                "id": "openai",
                "api_key": os.getenv("OPENAI_API_KEY"),
                "base_url": "https://api.openai.com/v1"
            },
            weight=2,
            priority=2
        ),
        ProviderConfig(
            provider_type="moonshot",
            config={
                "id": "moonshot", 
                "api_key": os.getenv("MOONSHOT_API_KEY"),
                "base_url": "https://api.moonshot.cn/v1"
            },
            weight=1,
            priority=3
        )
    ]
    
    # 4. 添加可用的Provider
    print("\n3. 添加Provider...")
    added_providers = []
    for config in providers_config:
        if config.config.get("api_key"):  # 只添加有API密钥的Provider
            success = await provider_manager.add_provider(config)
            if success:
                added_providers.append(config.config["id"])
                print(f"   ✓ {config.config['id']} 添加成功")
            else:
                print(f"   ✗ {config.config['id']} 添加失败")
        else:
            print(f"   - {config.config['id']} 跳过（无API密钥）")
    
    if not added_providers:
        print("\n❌ 没有可用的Provider，请设置至少一个API密钥:")
        print("   - DASHSCOPE_API_KEY（推荐）")
        print("   - OPENAI_API_KEY") 
        print("   - MOONSHOT_API_KEY")
        return
    
    # 5. 创建智能路由器
    print("\n4. 初始化智能路由器...")
    router_config = RouterConfig()
    smart_router = SmartRouter(router_config, cache)
    
    # 6. 测试路由决策
    print("\n5. 测试智能路由...")
    test_messages = [
        {"role": "user", "content": "你好，今天天气怎么样？"},
        {"role": "user", "content": "帮我写一个Python快速排序算法"},
        {"role": "user", "content": "分析一下当前AI市场的发展趋势"},
        {"role": "user", "content": "写一篇关于春天的诗歌"},
    ]
    
    for i, messages in enumerate(test_messages, 1):
        print(f"\n   测试 {i}: {messages['content']}")
        
        # 路由决策
        route_result = await smart_router.route([messages], provider_manager=provider_manager)
        print(f"   → 路由结果: {route_result.provider_id}/{route_result.model}")
        print(f"   → 任务类型: {route_result.task_type.value} (置信度: {route_result.confidence:.2f})")
        print(f"   → 决策原因: {route_result.reason}")
    
    # 7. 测试实际请求（仅第一个可用Provider）
    if added_providers:
        print(f"\n6. 测试实际请求 (使用 {added_providers[0]})...")
        test_message = [{"role": "user", "content": "请简单介绍一下人工智能"}]
        
        try:
            # 发起请求
            response = await provider_manager.chat_completion(
                messages=test_message,
                provider_id=added_providers[0],
                model=None,  # 使用默认模型
                max_tokens=100
            )
            
            print("   ✓ 请求成功!")
            if "choices" in response and len(response["choices"]) > 0:
                content = response["choices"][0].get("message", {}).get("content", "")
                print(f"   → 响应内容: {content[:100]}...")
            
        except Exception as e:
            print(f"   ✗ 请求失败: {str(e)}")
    
    # 8. 显示统计信息
    print("\n7. 系统统计信息...")
    
    # Provider统计
    provider_stats = provider_manager.get_stats()
    print(f"   Provider总数: {provider_stats['total_providers']}")
    print(f"   可用Provider: {provider_stats['available_providers']}")
    print(f"   路由策略: {provider_stats['routing_strategy']}")
    
    # 缓存统计
    cache_metrics = cache.get_metrics()
    print(f"   缓存命中率: {cache_metrics['metrics']['hit_rate']:.3f}")
    print(f"   缓存总请求: {cache_metrics['metrics']['total_requests']}")
    
    # 路由统计
    router_stats = smart_router.get_stats()
    print(f"   支持任务类型: {len(router_stats['task_types'])}")
    
    # 9. 健康检查
    print("\n8. 健康检查...")
    health_results = await provider_manager.health_check_all()
    for provider_id, status in health_results.items():
        print(f"   {provider_id}: {status.value}")
    
    # 10. 清理资源
    print("\n9. 清理资源...")
    await provider_manager.cleanup()
    await cache.close()
    
    print("\n✓ 测试完成！")
    print("=" * 60)


async def main():
    """主函数"""
    try:
        await test_provider_system()
    except KeyboardInterrupt:
        print("\n\n中断测试...")
    except Exception as e:
        logger.error(f"测试异常: {str(e)}", exc_info=True)


if __name__ == "__main__":
    # 运行测试
    asyncio.run(main())