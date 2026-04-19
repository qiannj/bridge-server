#!/usr/bin/env python3
"""
阶段2性能测试 - 连接池优化验证
目标：验证30-150 QPS性能提升
"""

import asyncio
import aiohttp
import json
import time
import logging
import statistics
from typing import Dict, Any, List
from pathlib import Path
import sys

# 添加src路径
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Stage2PerformanceTest:
    """阶段2性能测试类"""
    
    def __init__(self, base_url: str = "http://localhost:19377"):
        self.base_url = base_url
        self.results = {}
    
    async def single_optimized_request(
        self, 
        session: aiohttp.ClientSession, 
        request_data: Dict[str, Any],
        test_id: str = "default"
    ) -> Dict[str, Any]:
        """单个优化请求测试"""
        
        start_time = time.perf_counter()
        
        try:
            async with session.post(
                f"{self.base_url}/v1/chat/completions",
                json=request_data,
                headers={"Authorization": "Bearer bridge-admin-token"}
            ) as response:
                end_time = time.perf_counter()
                duration = (end_time - start_time) * 1000
                
                if response.status == 200:
                    result = await response.json()
                    
                    # 提取路由信息
                    routing_info = {}
                    if "usage" in result and "routing" in result["usage"]:
                        routing_info = result["usage"]["routing"]
                    
                    return {
                        "success": True,
                        "duration_ms": duration,
                        "status_code": response.status,
                        "model": routing_info.get("selected_model", "unknown"),
                        "provider": routing_info.get("provider", "unknown"),
                        "task_type": routing_info.get("task_type", "unknown"),
                        "from_cache": routing_info.get("from_cache", False),
                        "test_id": test_id
                    }
                else:
                    error_text = await response.text()
                    return {
                        "success": False,
                        "duration_ms": duration,
                        "status_code": response.status,
                        "error": error_text,
                        "test_id": test_id
                    }
        
        except Exception as e:
            end_time = time.perf_counter()
            duration = (end_time - start_time) * 1000
            return {
                "success": False,
                "duration_ms": duration,
                "status_code": 0,
                "error": str(e),
                "test_id": test_id
            }
    
    async def connection_pool_stress_test(
        self, 
        concurrent_requests: int = 20,
        total_requests: int = 200,
        test_name: str = "连接池压力测试"
    ) -> Dict[str, Any]:
        """连接池压力测试"""
        
        logger.info(f"开始{test_name}: {concurrent_requests}并发 x {total_requests}请求")
        
        # 多样化测试数据
        test_scenarios = [
            {
                "id": "simple",
                "data": {
                    "messages": [{"role": "user", "content": "你好"}],
                    "model": "auto",
                    "max_tokens": 50
                }
            },
            {
                "id": "complex",
                "data": {
                    "messages": [{"role": "user", "content": "分析一下人工智能的发展趋势，从技术、商业和社会三个维度深入探讨"}],
                    "model": "auto", 
                    "max_tokens": 800
                }
            },
            {
                "id": "coding",
                "data": {
                    "messages": [{"role": "user", "content": "写一个Python快速排序算法，要求有详细注释"}],
                    "model": "auto",
                    "max_tokens": 500
                }
            },
            {
                "id": "creative",
                "data": {
                    "messages": [{"role": "user", "content": "写一首关于科技改变生活的现代诗"}],
                    "model": "auto",
                    "max_tokens": 300
                }
            }
        ]
        
        start_time = time.perf_counter()
        
        # 创建优化的连接器配置
        connector = aiohttp.TCPConnector(
            limit=concurrent_requests * 3,         # 更大的连接池
            limit_per_host=concurrent_requests * 2, # 单主机连接数
            keepalive_timeout=120,                  # 更长的保持连接时间
            enable_cleanup_closed=True,
            ttl_dns_cache=600,                      # 10分钟DNS缓存
            use_dns_cache=True
        )
        
        timeout = aiohttp.ClientTimeout(total=60)  # 更长的超时时间
        
        # 信号量控制并发
        semaphore = asyncio.Semaphore(concurrent_requests)
        
        async def bounded_request(session: aiohttp.ClientSession, scenario: Dict[str, Any]):
            async with semaphore:
                return await self.single_optimized_request(
                    session, 
                    scenario["data"], 
                    scenario["id"]
                )
        
        results = []
        
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout
        ) as session:
            
            # 创建测试任务
            tasks = []
            for i in range(total_requests):
                scenario = test_scenarios[i % len(test_scenarios)]
                task = asyncio.create_task(bounded_request(session, scenario))
                tasks.append(task)
            
            # 执行所有任务
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.perf_counter()
        total_duration = end_time - start_time
        
        # 分析结果
        return self._analyze_results(results, total_duration, test_name)
    
    def _analyze_results(
        self, 
        results: List[Any], 
        total_duration: float, 
        test_name: str
    ) -> Dict[str, Any]:
        """分析测试结果"""
        
        successful_results = []
        failed_results = []
        routing_stats = {}
        
        for result in results:
            if isinstance(result, Exception):
                failed_results.append({
                    "error": str(result),
                    "duration_ms": 0
                })
            elif result["success"]:
                successful_results.append(result)
                
                # 路由统计
                task_type = result.get("task_type", "unknown")
                provider = result.get("provider", "unknown")
                
                if task_type not in routing_stats:
                    routing_stats[task_type] = {}
                if provider not in routing_stats[task_type]:
                    routing_stats[task_type][provider] = 0
                routing_stats[task_type][provider] += 1
                
            else:
                failed_results.append(result)
        
        # 性能统计
        if successful_results:
            durations = [r["duration_ms"] for r in successful_results]
            cache_hits = sum(1 for r in successful_results if r.get("from_cache", False))
            
            performance_stats = {
                "test_name": test_name,
                "total_requests": len(results),
                "successful_requests": len(successful_results),
                "failed_requests": len(failed_results),
                "success_rate": len(successful_results) / len(results),
                "total_duration_s": total_duration,
                "requests_per_second": len(results) / total_duration,
                "successful_qps": len(successful_results) / total_duration,
                "cache_hit_rate": cache_hits / len(successful_results) if successful_results else 0,
                "latency_stats": {
                    "min_ms": min(durations),
                    "max_ms": max(durations),
                    "mean_ms": statistics.mean(durations),
                    "median_ms": statistics.median(durations),
                    "p90_ms": sorted(durations)[int(len(durations) * 0.9)] if len(durations) > 10 else max(durations),
                    "p95_ms": sorted(durations)[int(len(durations) * 0.95)] if len(durations) > 20 else max(durations),
                    "p99_ms": sorted(durations)[int(len(durations) * 0.99)] if len(durations) > 100 else max(durations),
                    "std_dev": statistics.stdev(durations) if len(durations) > 1 else 0
                },
                "routing_stats": routing_stats
            }
        else:
            performance_stats = {
                "test_name": test_name,
                "total_requests": len(results),
                "successful_requests": 0,
                "failed_requests": len(failed_results),
                "success_rate": 0.0,
                "total_duration_s": total_duration,
                "requests_per_second": 0.0,
                "successful_qps": 0.0,
                "cache_hit_rate": 0.0,
                "latency_stats": {},
                "routing_stats": {}
            }
        
        return performance_stats
    
    async def run_health_check(self) -> Dict[str, Any]:
        """系统健康检查"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/health") as response:
                    if response.status == 200:
                        health_data = await response.json()
                        logger.info("✅ 系统健康检查通过")
                        return health_data
                    else:
                        logger.error(f"❌ 健康检查失败: HTTP {response.status}")
                        return {"status": "unhealthy", "http_status": response.status}
        except Exception as e:
            logger.error(f"❌ 健康检查异常: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    async def get_system_metrics(self) -> Dict[str, Any]:
        """获取系统指标"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/metrics") as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.warning(f"获取指标失败: HTTP {response.status}")
                        return {}
        except Exception as e:
            logger.warning(f"获取指标异常: {str(e)}")
            return {}
    
    async def run_stage2_test_suite(self):
        """运行阶段2完整测试套件"""
        
        print("\n" + "=" * 80)
        print("🚀 Bridge Server v2.0 - 阶段2性能测试套件")
        print("连接池优化 + 异步改造验证")
        print("=" * 80)
        
        # 1. 系统检查
        print("\n1️⃣ 系统健康检查...")
        health_data = await self.run_health_check()
        if health_data.get("status") != "healthy":
            print("❌ 系统不健康，测试终止")
            return
        
        # 2. 基准性能测试
        print("\n2️⃣ 基准性能测试（5并发）...")
        baseline = await self.connection_pool_stress_test(
            concurrent_requests=5,
            total_requests=50,
            test_name="基准测试"
        )
        
        # 3. 阶段2目标1测试（30-50 QPS）
        print("\n3️⃣ 阶段2目标1测试（10并发）...")
        target1 = await self.connection_pool_stress_test(
            concurrent_requests=10,
            total_requests=100,
            test_name="目标1测试"
        )
        
        # 4. 阶段2目标2测试（100+ QPS）
        print("\n4️⃣ 阶段2目标2测试（20并发）...")
        target2 = await self.connection_pool_stress_test(
            concurrent_requests=20,
            total_requests=200,
            test_name="目标2测试"
        )
        
        # 5. 连接池压力测试
        print("\n5️⃣ 连接池压力测试（50并发）...")
        stress = await self.connection_pool_stress_test(
            concurrent_requests=50,
            total_requests=300,
            test_name="连接池压力测试"
        )
        
        # 6. 系统指标检查
        print("\n6️⃣ 系统指标检查...")
        metrics = await self.get_system_metrics()
        
        # 7. 结果汇总分析
        self._print_stage2_summary([
            ("基准测试", baseline),
            ("目标1测试", target1),
            ("目标2测试", target2),
            ("压力测试", stress)
        ], metrics)
    
    def _print_stage2_summary(self, test_results: List, metrics: Dict[str, Any]):
        """打印阶段2测试总结"""
        
        print("\n" + "=" * 80)
        print("📊 阶段2性能测试总结")
        print("=" * 80)
        
        # 性能对比表
        print(f"\n{'测试场景':<15} {'QPS':<8} {'成功QPS':<10} {'成功率':<8} {'P50':<8} {'P95':<8} {'缓存率':<8}")
        print("-" * 80)
        
        best_qps = 0
        best_test = ""
        
        for name, result in test_results:
            qps = f"{result['requests_per_second']:.1f}"
            success_qps = f"{result['successful_qps']:.1f}" 
            success_rate = f"{result['success_rate']:.3f}"
            cache_rate = f"{result['cache_hit_rate']:.3f}"
            
            latency = result.get('latency_stats', {})
            p50 = f"{latency.get('median_ms', 0):.0f}ms"
            p95 = f"{latency.get('p95_ms', 0):.0f}ms"
            
            print(f"{name:<15} {qps:<8} {success_qps:<10} {success_rate:<8} {p50:<8} {p95:<8} {cache_rate:<8}")
            
            # 记录最佳性能
            if result['successful_qps'] > best_qps:
                best_qps = result['successful_qps']
                best_test = name
        
        # 阶段2目标评估
        print(f"\n🎯 阶段2目标评估:")
        if best_qps >= 150:
            print("🎉 优秀！超越阶段2最高目标 (150+ QPS)")
            grade = "A+"
        elif best_qps >= 100:
            print("✅ 优秀！达到阶段2高级目标 (100+ QPS)")
            grade = "A"
        elif best_qps >= 50:
            print("✅ 良好！达到阶段2中级目标 (50+ QPS)")
            grade = "B+"
        elif best_qps >= 30:
            print("✅ 达标！完成阶段2初级目标 (30+ QPS)")
            grade = "B"
        else:
            print("⚠️ 未达标，需要继续优化")
            grade = "C"
        
        print(f"   最佳性能: {best_qps:.1f} QPS ({best_test})")
        print(f"   性能等级: {grade}")
        
        # 连接池效果分析
        if metrics:
            print(f"\n🔗 连接池效果:")
            perf = metrics.get("performance", {})
            if perf:
                print(f"   系统QPS: {perf.get('qps', 0):.1f}")
                print(f"   平均延迟: {perf.get('avg_latency_ms', 0):.1f}ms")
                print(f"   成功率: {perf.get('success_rate', 0):.3f}")
            
            conn_stats = metrics.get("connection_pool", {})
            if conn_stats:
                print(f"   HTTP连接池: {conn_stats.get('http', {})}")
                print(f"   DB连接池: {conn_stats.get('database', {})}")
        
        # 下一步建议
        print(f"\n🚀 下一步优化建议:")
        if best_qps < 100:
            print("• 继续连接池调优")
            print("• 实施智能缓存集成")
            print("• 优化数据库查询")
        elif best_qps < 200:
            print("• 实施批量处理机制")
            print("• 优化内存使用")
            print("• 增强监控体系")
        else:
            print("• 性能已达标，可进入阶段3")
            print("• 完善可观测性建设")
            print("• 生产环境部署准备")


async def main():
    """主函数"""
    
    print("等待服务启动...")
    await asyncio.sleep(3)
    
    # 运行阶段2测试
    test = Stage2PerformanceTest()
    await test.run_stage2_test_suite()


if __name__ == "__main__":
    asyncio.run(main())
