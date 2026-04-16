#!/usr/bin/env python3
"""
阶段2简化性能测试 - 无外部依赖版本
使用urllib.request进行HTTP测试
"""

import asyncio
import json
import time
import statistics
import concurrent.futures
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import threading
from typing import Dict, Any, List


class SimplePerformanceTest:
    """简化性能测试类"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results = []
    
    def single_request(self, request_data: Dict[str, Any], test_id: str = "default") -> Dict[str, Any]:
        """单个HTTP请求"""
        
        start_time = time.perf_counter()
        
        try:
            # 准备请求
            url = f"{self.base_url}/v1/chat/completions"
            data = json.dumps(request_data).encode('utf-8')
            
            req = Request(
                url, 
                data=data,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer bridge-admin-token'
                }
            )
            
            # 发送请求
            with urlopen(req, timeout=30) as response:
                end_time = time.perf_counter()
                duration = (end_time - start_time) * 1000
                
                if response.getcode() == 200:
                    result = json.loads(response.read().decode('utf-8'))
                    
                    # 提取路由信息
                    routing_info = {}
                    if "usage" in result and "routing" in result["usage"]:
                        routing_info = result["usage"]["routing"]
                    
                    return {
                        "success": True,
                        "duration_ms": duration,
                        "status_code": response.getcode(),
                        "model": routing_info.get("selected_model", "unknown"),
                        "provider": routing_info.get("provider", "unknown"),
                        "task_type": routing_info.get("task_type", "unknown"),
                        "from_cache": routing_info.get("from_cache", False),
                        "test_id": test_id
                    }
                else:
                    return {
                        "success": False,
                        "duration_ms": duration,
                        "status_code": response.getcode(),
                        "error": f"HTTP {response.getcode()}",
                        "test_id": test_id
                    }
        
        except (URLError, HTTPError) as e:
            end_time = time.perf_counter()
            duration = (end_time - start_time) * 1000
            return {
                "success": False,
                "duration_ms": duration,
                "status_code": getattr(e, 'code', 0),
                "error": str(e),
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
    
    def concurrent_test(
        self, 
        concurrent_requests: int = 10,
        total_requests: int = 100,
        test_name: str = "并发测试"
    ) -> Dict[str, Any]:
        """并发请求测试"""
        
        print(f"开始{test_name}: {concurrent_requests}并发 x {total_requests}请求")
        
        # 测试场景
        scenarios = [
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
                    "messages": [{"role": "user", "content": "分析AI技术发展趋势"}],
                    "model": "auto",
                    "max_tokens": 200
                }
            },
            {
                "id": "coding",
                "data": {
                    "messages": [{"role": "user", "content": "写Python排序算法"}],
                    "model": "auto",
                    "max_tokens": 300
                }
            }
        ]
        
        start_time = time.perf_counter()
        
        # 使用线程池模拟并发
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_requests) as executor:
            
            # 创建任务
            futures = []
            for i in range(total_requests):
                scenario = scenarios[i % len(scenarios)]
                future = executor.submit(self.single_request, scenario["data"], scenario["id"])
                futures.append(future)
            
            # 等待所有任务完成
            results = []
            for future in concurrent.futures.as_completed(futures, timeout=120):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    results.append({
                        "success": False,
                        "duration_ms": 0,
                        "status_code": 0,
                        "error": str(e),
                        "test_id": "exception"
                    })
        
        end_time = time.perf_counter()
        total_duration = end_time - start_time
        
        return self._analyze_results(results, total_duration, test_name)
    
    def _analyze_results(self, results: List[Dict], total_duration: float, test_name: str) -> Dict[str, Any]:
        """分析结果"""
        
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]
        
        # 路由统计
        routing_stats = {}
        for r in successful:
            task_type = r.get("task_type", "unknown")
            provider = r.get("provider", "unknown")
            
            if task_type not in routing_stats:
                routing_stats[task_type] = {}
            if provider not in routing_stats[task_type]:
                routing_stats[task_type][provider] = 0
            routing_stats[task_type][provider] += 1
        
        # 性能统计
        if successful:
            durations = [r["duration_ms"] for r in successful]
            cache_hits = sum(1 for r in successful if r.get("from_cache", False))
            
            stats = {
                "test_name": test_name,
                "total_requests": len(results),
                "successful_requests": len(successful),
                "failed_requests": len(failed),
                "success_rate": len(successful) / len(results),
                "total_duration_s": total_duration,
                "requests_per_second": len(results) / total_duration,
                "successful_qps": len(successful) / total_duration,
                "cache_hit_rate": cache_hits / len(successful) if successful else 0,
                "latency_stats": {
                    "min_ms": min(durations),
                    "max_ms": max(durations),
                    "mean_ms": statistics.mean(durations),
                    "median_ms": statistics.median(durations),
                    "p90_ms": sorted(durations)[int(len(durations) * 0.9)] if len(durations) > 10 else max(durations),
                    "p95_ms": sorted(durations)[int(len(durations) * 0.95)] if len(durations) > 20 else max(durations),
                    "std_dev": statistics.stdev(durations) if len(durations) > 1 else 0
                },
                "routing_stats": routing_stats
            }
        else:
            stats = {
                "test_name": test_name,
                "total_requests": len(results),
                "successful_requests": 0,
                "failed_requests": len(failed),
                "success_rate": 0.0,
                "total_duration_s": total_duration,
                "requests_per_second": 0.0,
                "successful_qps": 0.0,
                "cache_hit_rate": 0.0,
                "latency_stats": {},
                "routing_stats": {}
            }
        
        return stats
    
    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        try:
            req = Request(f"{self.base_url}/health")
            with urlopen(req, timeout=5) as response:
                if response.getcode() == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    print("✅ 系统健康检查通过")
                    return data
                else:
                    print(f"❌ 健康检查失败: HTTP {response.getcode()}")
                    return {"status": "unhealthy", "http_status": response.getcode()}
        except Exception as e:
            print(f"❌ 健康检查异常: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    def get_metrics(self) -> Dict[str, Any]:
        """获取系统指标"""
        try:
            req = Request(f"{self.base_url}/metrics")
            with urlopen(req, timeout=5) as response:
                if response.getcode() == 200:
                    return json.loads(response.read().decode('utf-8'))
                else:
                    print(f"获取指标失败: HTTP {response.getcode()}")
                    return {}
        except Exception as e:
            print(f"获取指标异常: {str(e)}")
            return {}
    
    def run_stage2_test_suite(self):
        """运行阶段2测试套件"""
        
        print("\n" + "=" * 80)
        print("🚀 Bridge Server v2.0 - 阶段2性能测试套件")
        print("连接池优化 + 异步改造验证 (简化版)")
        print("=" * 80)
        
        # 1. 系统检查
        print("\n1️⃣ 系统健康检查...")
        health_data = self.health_check()
        if health_data.get("status") != "healthy":
            print("❌ 系统不健康，测试终止")
            return
        
        # 2. 基准测试
        print("\n2️⃣ 基准性能测试（5并发）...")
        baseline = self.concurrent_test(5, 25, "基准测试")
        
        # 3. 阶段2目标1
        print("\n3️⃣ 阶段2目标1测试（10并发）...")
        target1 = self.concurrent_test(10, 50, "目标1测试")
        
        # 4. 阶段2目标2
        print("\n4️⃣ 阶段2目标2测试（20并发）...")
        target2 = self.concurrent_test(20, 80, "目标2测试")
        
        # 5. 压力测试
        print("\n5️⃣ 连接池压力测试（30并发）...")
        stress = self.concurrent_test(30, 100, "压力测试")
        
        # 6. 系统指标
        print("\n6️⃣ 系统指标检查...")
        metrics = self.get_metrics()
        
        # 7. 结果汇总
        self._print_summary([
            ("基准测试", baseline),
            ("目标1测试", target1),
            ("目标2测试", target2),
            ("压力测试", stress)
        ], metrics)
    
    def _print_summary(self, test_results: List, metrics: Dict[str, Any]):
        """打印测试总结"""
        
        print("\n" + "=" * 80)
        print("📊 阶段2性能测试总结 (简化版)")
        print("=" * 80)
        
        # 性能表格
        print(f"\n{'测试场景':<12} {'QPS':<8} {'成功QPS':<10} {'成功率':<8} {'P50':<8} {'P95':<8} {'缓存率':<8}")
        print("-" * 72)
        
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
            
            print(f"{name:<12} {qps:<8} {success_qps:<10} {success_rate:<8} {p50:<8} {p95:<8} {cache_rate:<8}")
            
            if result['successful_qps'] > best_qps:
                best_qps = result['successful_qps']
                best_test = name
        
        # 目标评估
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
        
        # 系统指标
        if metrics:
            print(f"\n📊 系统指标:")
            perf = metrics.get("performance", {})
            if perf:
                print(f"   系统QPS: {perf.get('qps', 0):.1f}")
                print(f"   平均延迟: {perf.get('avg_latency_ms', 0):.1f}ms")
                print(f"   成功率: {perf.get('success_rate', 0):.3f}")
        
        # 建议
        print(f"\n🚀 优化建议:")
        if best_qps < 50:
            print("• 检查连接池配置")
            print("• 验证异步改造效果")
            print("• 优化数据库操作")
        elif best_qps < 100:
            print("• 实施智能缓存")
            print("• 优化批量处理")
            print("• 增强监控")
        else:
            print("• 性能达标，准备进入阶段3")
            print("• 完善可观测性")
            print("• 生产环境部署")


def main():
    """主函数"""
    
    # 等待服务器启动
    print("等待服务启动...")
    time.sleep(2)
    
    # 运行测试
    test = SimplePerformanceTest()
    test.run_stage2_test_suite()


if __name__ == "__main__":
    main()