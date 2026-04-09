#!/usr/bin/env python3
"""
Bridge Server v2.1.0 功能测试脚本

测试场景：
1. 路由函数支持 requested_model 参数
2. smart 模式正确触发智能路由
3. 指定模型 ID 直接使用
4. 不传 model 使用默认策略
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from app.router import route_model

# 测试配置
TEST_CONFIG = {
    "providers": [
        {
            "name": "dashscope",
            "models": [
                {"id": "qwen3.5-flash", "name": "Flash"},
                {"id": "qwen3.5-plus", "name": "Plus"},
                {"id": "qwen3-coder-plus", "name": "Coder"},
                {"id": "qwen3-max", "name": "Max"},
            ]
        },
        {
            "name": "moonshot",
            "models": [
                {"id": "kimi-chat", "name": "Kimi Chat"},
                {"id": "kimi-k2.5", "name": "Kimi K2.5"},
            ]
        }
    ],
    "routing": {
        "strategy": "balanced",
        "model_mapping": {
            "coding": "qwen3-coder-plus",
            "writing": "qwen3.5-plus",
            "simple": "qwen3.5-flash",
            "general": "qwen3.5-plus",
        }
    }
}

def test_smart_routing():
    """测试 1: smart 模式 - 代码任务"""
    print("\n🧪 测试 1: smart 模式 - 代码任务")
    message = "用 Python 写个快速排序"
    model, task_type, reason = route_model(message, TEST_CONFIG, requested_model="smart")
    
    print(f"  消息：{message}")
    print(f"  任务类型：{task_type}")
    print(f"  选择模型：{model}")
    print(f"  路由原因：{reason}")
    
    assert task_type == "coding", f"期望 coding，得到 {task_type}"
    assert "qwen3-coder-plus" in model, f"期望 coder 模型，得到 {model}"
    print("  ✅ 通过")

def test_smart_routing_simple():
    """测试 2: smart 模式 - 简单问候"""
    print("\n🧪 测试 2: smart 模式 - 简单问候")
    message = "你好啊"
    model, task_type, reason = route_model(message, TEST_CONFIG, requested_model="smart")
    
    print(f"  消息：{message}")
    print(f"  任务类型：{task_type}")
    print(f"  选择模型：{model}")
    print(f"  路由原因：{reason}")
    
    assert task_type == "simple", f"期望 simple，得到 {task_type}"
    assert "qwen3.5-flash" in model, f"期望 flash 模型，得到 {model}"
    print("  ✅ 通过")

def test_user_specified_model():
    """测试 3: 其他 model 值会被忽略，使用默认路由"""
    print("\n🧪 测试 3: 其他 model 值会被忽略，使用默认路由")
    message = "写首诗"
    model, task_type, reason = route_model(message, TEST_CONFIG, requested_model="dashscope/qwen3.5-plus")
    
    print(f"  消息：{message}")
    print(f"  任务类型：{task_type}")
    print(f"  选择模型：{model}")
    print(f"  路由原因：{reason}")
    
    # 非 smart 值会被忽略，使用默认路由
    assert task_type in ["creative", "writing", "general"], f"期望创意/写作类任务，得到 {task_type}"
    assert "智能路由" in reason or "策略" in reason, f"期望智能路由原因，得到 {reason}"
    print("  ✅ 通过")

def test_user_specified_short_name():
    """测试 4: 空字符串 model 使用默认路由"""
    print("\n🧪 测试 4: 空字符串 model 使用默认路由")
    message = "分析这个数据"
    model, task_type, reason = route_model(message, TEST_CONFIG, requested_model="")
    
    print(f"  消息：{message}")
    print(f"  任务类型：{task_type}")
    print(f"  选择模型：{model}")
    print(f"  路由原因：{reason}")
    
    # 空字符串使用默认路由
    assert task_type == "analysis", f"期望 analysis，得到 {task_type}"
    assert "智能路由" in reason, f"期望智能路由原因，得到 {reason}"
    print("  ✅ 通过")

def test_default_strategy():
    """测试 5: 默认策略（不传 model）"""
    print("\n🧪 测试 5: 默认策略（不传 model）")
    message = "解释一下量子力学"
    model, task_type, reason = route_model(message, TEST_CONFIG, requested_model=None)
    
    print(f"  消息：{message}")
    print(f"  任务类型：{task_type}")
    print(f"  选择模型：{model}")
    print(f"  路由原因：{reason}")
    
    assert task_type in ["analysis", "general", "creative"], f"期望分析类任务，得到 {task_type}"
    assert "智能路由" in reason or "策略" in reason, f"期望路由相关原因，得到 {reason}"
    print("  ✅ 通过")


def main():
    """运行所有测试"""
    print("="*60)
    print("Bridge Server v2.1.0 路由功能测试")
    print("="*60)
    
    tests = [
        test_smart_routing,
        test_smart_routing_simple,
        test_user_specified_model,
        test_user_specified_short_name,
        test_default_strategy,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ 失败：{e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ 异常：{e}")
            failed += 1
    
    print("\n" + "="*60)
    print(f"测试结果：{passed} 通过，{failed} 失败")
    print("="*60)
    
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
