#!/usr/bin/env python3
"""
Bridge Server v2.0 性能测试
验证异步优化效果
"""

import asyncio
import aiohttp
import json
import time
import logging
from typing import List, Dict, Any
import statistics

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PerformanceTest:
    """性能测试类"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results = []
    
    async def single_request(self, session: aiohttp.ClientSession, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """单个请求测试"""
        start_time = time.perf_counter()
        
        try:
            async with session.post(
                f"{self.base_url}/v1/chat/completions",
                json=request_data,
                headers={"Authorization": "Bearer bridge-admin-token"}
            ) as response:
                end_time = time.perf_counter()
                duration = (end_time - start_time) * 1000  # 转换为毫秒
                
                if response.status == 200:
                    result = await response.json()
                    return {
                        "success": True,
                        "duration_ms": duration,
                        "status_code": response.status,
                        "response": result
                    }
                else:
                    error_text = await response.text()
                    return {
                        "success": False,
                        "duration_ms": duration,
                        "status_code": response.status,
                        "error": error_text
                    }
        
        except Exception as e:
            end_time = time.perf_counter()
            duration = (end_time - start_time) * 1000
            return {
                "success": False,
                "duration_ms": duration,
                "status_code": 0,
                "error": str(e)
            }
    
    async def concurrent_test(self, concurrent_requests: int = 10, total_requests: int = 100) -> Dict[str, Any]:
        """并发测试"""
        logger.info(f"开始并发测试: {concurrent_requests} 并发 x {total_requests} 总请求")
        
        # 准备测试数据
        test_requests = [
            {
                "messages": [
                    {"role": "user", "content": "你好，今天天气怎么样？"}
                ],
                "model": "auto",
                "max_tokens": 100
            },
            {
                "messages": [
                    {"role": "user", "content": "帮我写一个Python快速排序算法"}
                ],
                "model": "auto", 
                "max_tokens": 500
            },
            {
                "messages": [
                    {"role": "user", "content": "分析一下当前AI市场的发展趋势"}
                ],
                "model": "auto",
                "max_tokens": 800
            },
            {
                "messages": [
                    {"role": "user", "content": "写一首关于春天的诗"}
                ],
                "model": "auto",
                "max_tokens": 200
            }
        ]
        
        results = []
        start_time = time.perf_counter()
        
        # 创建信号量控制并发数
        semaphore = asyncio.Semaphore(concurrent_requests)
        
        async def bounded_request(session: aiohttp.ClientSession, request_data: Dict[str, Any]):
            async with semaphore:
                return await self.single_request(session, request_data)
        
        # 创建HTTP会话
        connector = aiohttp.TCPConnector(
            limit=concurrent_requests * 2,  # 连接池大小
            limit_per_host=concurrent_requests * 2,
            keepalive_timeout=60,
            enable_cleanup_closed=True
        )
        
        timeout = aiohttp.ClientTimeout(total=30)
        
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout
        ) as session:
            
            # 创建所有任务
            tasks = []
            for i in range(total_requests):
                request_data = test_requests[i % len(test_requests)]
                task = asyncio.create_task(bounded_request(session, request_data))
                tasks.append(task)
            
            # 执行所有任务
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.perf_counter()
        total_duration = end_time - start_time
        
        # 处理结果
        successful_results = []
        failed_results = []
        
        for result in results:
            if isinstance(result, Exception):
                failed_results.append({
                    "success": False,
                    "error": str(result),
                    "duration_ms": 0
                })
            elif result["success"]:
                successful_results.append(result)
            else:
                failed_results.append(result)
        
        # 计算统计指标
        if successful_results:
            durations = [r["duration_ms"] for r in successful_results]
            
            performance_stats = {
                "total_requests": total_requests,
                "successful_requests": len(successful_results),
                "failed_requests": len(failed_results),
                "success_rate": len(successful_results) / total_requests,
                "total_duration_s": total_duration,
                "requests_per_second": total_requests / total_duration,
                "latency_stats": {
                    "min_ms": min(durations),
                    "max_ms": max(durations),
                    "mean_ms": statistics.mean(durations),
                    "median_ms": statistics.median(durations),
                    "p95_ms": sorted(durations)[int(len(durations) * 0.95)] if len(durations) > 20 else max(durations),
                    "p99_ms": sorted(durations)[int(len(durations) * 0.99)] if len(durations) > 100 else max(durations)
                }
            }
        else:
            performance_stats = {
                "total_requests": total_requests,
                "successful_requests": 0,
                "failed_requests": len(failed_results),
                "success_rate": 0.0,
                "total_duration_s": total_duration,
                "requests_per_second": 0.0,
                "latency_stats": {}
            }
        
        return performance_stats
    
    async def run_health_check(self) -> bool:
        """健康检查"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/health") as response:
                    if response.status == 200:
                        health_data = await response.json()
                        logger.info(f"健康检查通过: {health_data}")
                        return True
                    else:
                        logger.error(f"健康检查失败: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"健康检查异常: {str(e)}")
            return False
    
    async def run_performance_suite(self):
        """运行完整性能测试套件"""
        
        print("=" * 80)
        print("Bridge Server v2.0 - 性能测试套件")
        print("=" * 80)
        
        # 1. 健康检查
        print("\n1. 健康检查...")
        if not await self.run_health_check():
            print("❌ 健康检查失败，测试终止")
            return
        
        print("✅ 健康检查通过")
        
        # 2. 基准测试 (单并发)
        print("\n2. 基准测试 (单并发)...")
        baseline_results = await self.concurrent_test(concurrent_requests=1, total_requests=10)
        self.print_results("基准测试", baseline_results)
        
        # 3. 低并发测试
        print("\n3. 低并发测试 (5并发)...")
        low_concurrency_results = await self.concurrent_test(concurrent_requests=5, total_requests=50)
        self.print_results("低并发测试", low_concurrency_results)
        
        # 4. 中并发测试
        print("\n4. 中并发测试 (10并发)...")
        mid_concurrency_results = await self.concurrent_test(concurrent_requests=10, total_requests=100)
        self.print_results("中并发测试", mid_concurrency_results)
        
        # 5. 高并发测试
        print("\n5. 高并发测试 (20并发)...")
        high_concurrency_results = await self.concurrent_test(concurrent_requests=20, total_requests=200)
        self.print_results("高并发测试", high_concurrency_results)
        
        # 6. 压力测试
        print("\n6. 压力测试 (50并发)...")
        stress_results = await self.concurrent_test(concurrent_requests=50, total_requests=300)
        self.print_results("压力测试", stress_results)
        
        # 7. 总结
        print("\n" + "=" * 80)
        print("性能测试总结")
        print("=" * 80)
        
        all_results = [
            ("基准测试", baseline_results),
            ("低并发测试", low_concurrency_results),
            ("中并发测试", mid_concurrency_results),
            ("高并发测试", high_concurrency_results),
            ("压力测试", stress_results)
        ]
        
        print(f"{'测试场景':<12} {'QPS':<8} {'成功率':<8} {'P50延迟':<10} {'P95延迟':<10} {'P99延迟':<10}")
        print("-" * 70)
        
        for name, result in all_results:
            qps = f"{result['requests_per_second']:.1f}"
            success_rate = f"{result['success_rate']:.3f}"
            latency = result.get('latency_stats', {})
            p50 = f"{latency.get('median_ms', 0):.0f}ms"
            p95 = f"{latency.get('p95_ms', 0):.0f}ms"
            p99 = f"{latency.get('p99_ms', 0):.0f}ms"
            
            print(f"{name:<12} {qps:<8} {success_rate:<8} {p50:<10} {p95:<10} {p99:<10}")
        
        # 性能评估
        print(f"\n📊 性能评估:")
        max_qps = max(r[1]['requests_per_second'] for r in all_results)
        if max_qps >= 200:
            print("🎉 优秀！达到目标性能 (≥200 QPS)")
        elif max_qps >= 100:
            print("✅ 良好！接近目标性能 (≥100 QPS)")
        elif max_qps >= 50:
            print("⚠️  一般，需要进一步优化 (≥50 QPS)")
        else:
            print("❌ 性能不足，需要大幅优化")
        
        print(f"   最大QPS: {max_qps:.1f}")
        print(f"   目标QPS: 200+")
        
    def print_results(self, test_name: str, results: Dict[str, Any]):
        """打印测试结果"""
        print(f"\n📊 {test_name} 结果:")
        print(f"   总请求数: {results['total_requests']}")
        print(f"   成功请求: {results['successful_requests']}")
        print(f"   失败请求: {results['failed_requests']}")
        print(f"   成功率: {results['success_rate']:.3f}")
        print(f"   总耗时: {results['total_duration_s']:.2f}s")
        print(f"   QPS: {results['requests_per_second']:.2f}")
        
        latency = results.get('latency_stats', {})
        if latency:
            print(f"   延迟统计:")
            print(f"     最小: {latency.get('min_ms', 0):.0f}ms")
            print(f"     平均: {latency.get('mean_ms', 0):.0f}ms")
            print(f"     中位数: {latency.get('median_ms', 0):.0f}ms")
            print(f"     P95: {latency.get('p95_ms', 0):.0f}ms")
            print(f"     P99: {latency.get('p99_ms', 0):.0f}ms")
            print(f"     最大: {latency.get('max_ms', 0):.0f}ms")


async def main():
    """主函数"""
    
    # 等待服务启动
    print("等待服务启动...")
    await asyncio.sleep(2)
    
    # 运行性能测试
    test = PerformanceTest()
    await test.run_performance_suite()


if __name__ == "__main__":
    asyncio.run(main())