#!/usr/bin/env python3
"""
测试 JS 沙箱服务 - v1.6.0
"""

import pytest
from services.sandbox import JSSandbox, execute_user_route, USER_ROUTE_TEMPLATE


class TestJSSandboxBasic:
    """测试沙箱基本功能"""
    
    def test_sandbox_init(self):
        """测试沙箱初始化"""
        sandbox = JSSandbox(timeout_seconds=5, max_memory_mb=128)
        assert sandbox.timeout_seconds == 5
        assert sandbox.max_memory_mb == 128
    
    def test_sandbox_simple_code(self):
        """测试简单代码执行"""
        sandbox = JSSandbox()
        
        code = """
def route(context):
    return {'result': 'hello', 'value': 42}
"""
        result = sandbox.execute(code, {})
        
        assert result.success is True
        assert result.result['result'] == 'hello'
        assert result.result['value'] == 42
        assert result.execution_time_ms >= 0
    
    def test_sandbox_context_access(self):
        """测试上下文访问"""
        sandbox = JSSandbox()
        
        code = """
def route(context):
    message = context.get('message', '')
    return {'length': len(message), 'upper': message.upper()}
"""
        result = sandbox.execute(code, {'message': 'Hello World'})
        
        assert result.success is True
        assert result.result['length'] == 11
        assert result.result['upper'] == 'HELLO WORLD'


class TestJSSandboxRouting:
    """测试沙箱路由功能"""
    
    def test_route_by_keyword(self):
        """测试关键词路由"""
        code = """
def route(context):
    message = context.get('message', '').lower()
    if 'code' in message or 'python' in message:
        return {'model': 'qwen3-coder-plus', 'reason': '代码任务'}
    elif 'hello' in message or 'hi' in message:
        return {'model': 'qwen3.5-flash', 'reason': '简单问候'}
    else:
        return {'model': 'qwen3.5-plus', 'reason': '默认路由'}
"""
        # 测试代码任务
        result = execute_user_route(code, {'message': '用 Python 写个快速排序'})
        assert result.success is True
        assert result.result['model'] == 'qwen3-coder-plus'
        
        # 测试简单问候
        result = execute_user_route(code, {'message': 'Hello, how are you?'})
        assert result.success is True
        assert result.result['model'] == 'qwen3.5-flash'
        
        # 测试默认路由
        result = execute_user_route(code, {'message': '分析一下这个数据'})
        assert result.success is True
        assert result.result['model'] == 'qwen3.5-plus'
    
    def test_route_with_config(self):
        """测试带配置的路由"""
        code = """
def route(context):
    config = context.get('config', {})
    strategy = config.get('strategy', 'balanced')
    
    if strategy == 'cost-first':
        return {'model': 'qwen3.5-flash', 'reason': '成本优先'}
    elif strategy == 'quality-first':
        return {'model': 'qwen3-max', 'reason': '质量优先'}
    else:
        return {'model': 'qwen3.5-plus', 'reason': '平衡模式'}
"""
        result = execute_user_route(code, {
            'message': 'test',
            'config': {'strategy': 'cost-first'}
        })
        
        assert result.success is True
        assert result.result['model'] == 'qwen3.5-flash'


class TestJSSandboxSecurity:
    """测试沙箱安全性"""
    
    def test_forbidden_import(self):
        """测试禁止 import"""
        sandbox = JSSandbox()
        
        code = """
import os
def route(context):
    return os.getcwd()
"""
        result = sandbox.execute(code, {})
        
        # 应该失败或无法访问 os
        assert result.success is False or 'ImportError' in str(result.error) or result.result is None
    
    def test_forbidden_exec(self):
        """测试禁止 exec/eval"""
        sandbox = JSSandbox()
        
        code = """
def route(context):
    return eval("1+1")
"""
        result = sandbox.execute(code, {})
        
        # 应该失败
        assert result.success is False or 'eval' in str(result.error).lower() or result.result is None
    
    def test_forbidden_file_access(self):
        """测试禁止文件访问"""
        sandbox = JSSandbox()
        
        code = """
def route(context):
    with open('/etc/passwd', 'r') as f:
        return f.read()
"""
        result = sandbox.execute(code, {})
        
        # 应该失败
        assert result.success is False
    
    def test_code_validation(self):
        """测试代码验证"""
        sandbox = JSSandbox()
        
        # 危险代码
        dangerous_code = """
import os
os.system('rm -rf /')
"""
        validation = sandbox.validate_code(dangerous_code)
        assert validation['valid'] is False
        assert len(validation['issues']) > 0
        
        # 安全代码
        safe_code = """
def route(context):
    return {'model': 'qwen3.5-plus'}
"""
        validation = sandbox.validate_code(safe_code)
        assert validation['valid'] is True
        assert len(validation['issues']) == 0


class TestJSSandboxTimeout:
    """测试沙箱超时"""
    
    def test_timeout_handling(self):
        """测试超时处理"""
        sandbox = JSSandbox(timeout_seconds=1)
        
        # 无限循环代码
        code = """
def route(context):
    while True:
        pass
    return {'model': 'test'}
"""
        result = sandbox.execute(code, {})
        
        # 应该超时
        assert result.success is False
        assert 'timeout' in result.error.lower() or result.execution_time_ms >= 1000


class TestUserRouteTemplate:
    """测试用户路由模板"""
    
    def test_template_execution(self):
        """测试模板执行"""
        from services.sandbox import USER_ROUTE_TEMPLATE
        
        result = execute_user_route(USER_ROUTE_TEMPLATE, {
            'message': '用 Python 写个函数'
        })
        
        assert result.success is True
        assert result.result['model'] == 'qwen3-coder-plus'
        
        # 测试问候
        result = execute_user_route(USER_ROUTE_TEMPLATE, {
            'message': '你好，早上好'
        })
        
        assert result.success is True
        assert result.result['model'] == 'qwen3.5-flash'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
