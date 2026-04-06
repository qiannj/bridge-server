"""路由模块测试"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
import sys
import asyncio

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.router import detect_task_type, route_model, get_default_mapping, find_full_model_id


class TestDetectTaskType:
    """测试任务类型检测"""
    
    def test_simple_greeting(self):
        """测试简单问候"""
        assert detect_task_type("你好") == "simple"
        assert detect_task_type("hi") == "simple"
        assert detect_task_type("hello") == "simple"
        assert detect_task_type("谢谢") == "simple"
        assert detect_task_type("早上好") == "simple"
    
    def test_coding_task(self):
        """测试编程任务"""
        assert detect_task_type("写一个 python 函数") == "coding"
        assert detect_task_type("帮我 debug 这段代码") == "coding"
        assert detect_task_type("javascript 算法实现") == "coding"
    
    def test_writing_task(self):
        """测试写作任务"""
        assert detect_task_type("写一篇文章") == "writing"
        assert detect_task_type("帮我润色这段文案") == "writing"
        assert detect_task_type("写一封邮件") == "writing"
    
    def test_analysis_task(self):
        """测试分析任务"""
        assert detect_task_type("分析这个数据") == "analysis"
        assert detect_task_type("为什么是这样") == "analysis"
        assert detect_task_type("对比两个方案") == "analysis"
    
    def test_creative_task(self):
        """测试创意任务"""
        assert detect_task_type("想一个创意") == "creative"
        # "写一个故事" 包含"写"关键词，优先级上 writing 在 creative 之前
        assert detect_task_type("头脑风暴") == "creative"
        assert detect_task_type("设计一个创意方案") == "creative"
    
    def test_complex_task(self):
        """测试复杂推理任务"""
        assert detect_task_type("深入分析这个问题") == "complex"
        assert detect_task_type("数学证明") == "complex"
        assert detect_task_type("逻辑推理") == "complex"
    
    def test_general_task(self):
        """测试通用任务"""
        assert detect_task_type("今天天气怎么样") == "general"
        assert detect_task_type("随便聊聊") == "general"
    
    def test_empty_message(self):
        """测试空消息"""
        assert detect_task_type("") == "general"
        assert detect_task_type(None) == "general"
    
    def test_mixed_keywords(self):
        """测试混合关键词（优先级测试）"""
        # complex 优先级高于 coding
        assert detect_task_type("复杂的代码问题") == "complex"
        # coding 优先级高于 writing
        assert detect_task_type("写代码实现文章生成") == "coding"


class TestGetDefaultMapping:
    """测试默认路由映射"""
    
    def test_cost_first_strategy(self):
        """测试成本优先策略"""
        mapping = get_default_mapping("cost-first")
        assert mapping['simple'] == 'qwen3.5-flash'
        assert mapping['coding'] == 'qwen3.5-plus'
        assert mapping['general'] == 'qwen3.5-flash'
    
    def test_quality_first_strategy(self):
        """测试质量优先策略"""
        mapping = get_default_mapping("quality-first")
        assert mapping['simple'] == 'qwen3.5-plus'
        assert mapping['coding'] == 'qwen3-coder-plus'
        assert mapping['complex'] == 'qwen3-max'
    
    def test_balanced_strategy(self):
        """测试平衡策略"""
        mapping = get_default_mapping("balanced")
        assert mapping['simple'] == 'qwen3.5-flash'
        assert mapping['coding'] == 'qwen3-coder-plus'
        assert mapping['complex'] == 'qwen3-max'
    
    def test_unknown_strategy(self):
        """测试未知策略（默认 balanced）"""
        mapping = get_default_mapping("unknown")
        assert mapping == get_default_mapping("balanced")


class TestFindFullModelId:
    """测试模型 ID 查找"""
    
    def test_find_existing_model(self):
        """测试找到已存在的模型"""
        config = {
            'providers': {
                'dashscope': {
                    'enabled': True,
                    'models': {
                        'qwen3.5-plus': {},
                        'qwen3.5-flash': {}
                    }
                }
            }
        }
        
        assert find_full_model_id('qwen3.5-plus', config) == 'dashscope/qwen3.5-plus'
        assert find_full_model_id('qwen3.5-flash', config) == 'dashscope/qwen3.5-flash'
    
    def test_disabled_provider(self):
        """测试禁用的 provider"""
        config = {
            'providers': {
                'dashscope': {
                    'enabled': False,
                    'models': {'qwen3.5-plus': {}}
                }
            }
        }
        
        assert find_full_model_id('qwen3.5-plus', config) == 'qwen3.5-plus'
    
    def test_model_not_found(self):
        """测试模型未找到"""
        config = {
            'providers': {
                'dashscope': {
                    'enabled': True,
                    'models': {'other-model': {}}
                }
            }
        }
        
        assert find_full_model_id('nonexistent', config) == 'nonexistent'
    
    def test_empty_config(self):
        """测试空配置"""
        assert find_full_model_id('any-model', {}) == 'any-model'


class TestRouteModel:
    """测试模型路由"""
    
    def test_route_simple_task(self):
        """测试简单任务路由"""
        config = {
            'routing': {'strategy': 'balanced'},
            'providers': {
                'dashscope': {'enabled': True, 'models': {'qwen3.5-flash': {}}}
            }
        }
        
        model, task_type, reason = route_model("你好", config)
        assert task_type == "simple"
        assert "qwen3.5-flash" in model
    
    def test_route_coding_task(self):
        """测试编程任务路由"""
        config = {
            'routing': {'strategy': 'balanced'},
            'providers': {
                'dashscope': {'enabled': True, 'models': {'qwen3-coder-plus': {}}}
            }
        }
        
        model, task_type, reason = route_model("写一个 python 函数", config)
        assert task_type == "coding"
        assert "qwen3-coder-plus" in model
    
    def test_custom_routing(self):
        """测试自定义路由"""
        config = {
            'routing': {
                'strategy': 'custom',
                'model_mapping': {
                    'simple': 'custom-model',
                    'coding': 'coder-model'
                }
            },
            'providers': {
                'custom': {'enabled': True, 'models': {'custom-model': {}, 'coder-model': {}}}
            }
        }
        
        model, task_type, reason = route_model("你好", config)
        assert task_type == "simple"
        assert "custom-model" in model
        assert "自定义路由" in reason
