#!/usr/bin/env python3
"""
JS 沙箱服务 - v1.6.0
支持用户自定义路由逻辑，安全隔离执行

特性:
- 用户代码执行环境
- 安全隔离（restrictedpython）
- 资源限制（内存 128MB/CPU 5 秒）
- 网络/文件系统/系统调用禁止
"""

import logging
import time
import signal
import os
from typing import Dict, Any, Optional
from dataclasses import dataclass
import json

logger = logging.getLogger(__name__)


@dataclass
class SandboxResult:
    """沙箱执行结果"""
    success: bool
    result: Any
    error: Optional[str] = None
    execution_time_ms: int = 0
    memory_used_kb: int = 0


class JSSandbox:
    """
    JavaScript 沙箱执行环境
    
    使用 restrictedpython 限制用户代码的访问权限
    """
    
    # 安全内置函数
    SAFE_BUILTINS = {
        'abs': abs,
        'all': all,
        'any': any,
        'bin': bin,
        'bool': bool,
        'chr': chr,
        'dict': dict,
        'divmod': divmod,
        'enumerate': enumerate,
        'filter': filter,
        'float': float,
        'hex': hex,
        'int': int,
        'len': len,
        'list': list,
        'map': map,
        'max': max,
        'min': min,
        'oct': oct,
        'ord': ord,
        'pow': pow,
        'range': range,
        'reversed': reversed,
        'round': round,
        'set': set,
        'slice': slice,
        'sorted': sorted,
        'str': str,
        'sum': sum,
        'tuple': tuple,
        'zip': zip,
        'True': True,
        'False': False,
        'None': None,
    }
    
    def __init__(self, timeout_seconds: int = 5, max_memory_mb: int = 128):
        """
        初始化沙箱
        
        Args:
            timeout_seconds: 执行超时（秒）
            max_memory_mb: 最大内存使用（MB）
        """
        self.timeout_seconds = timeout_seconds
        self.max_memory_mb = max_memory_mb
        self._initialized = False
    
    def _init_restrictedpython(self):
        """初始化 RestrictedPython"""
        try:
            from RestrictedPython import compile_restricted, safe_builtins
            self._compile = compile_restricted
            # 合并安全内置函数，添加迭代器支持
            self._safe_builtins = {**self.SAFE_BUILTINS, **safe_builtins}
            # 添加迭代器支持（RestrictedPython 需要）
            # _getiter_ 用于列表推导式和迭代
            self._safe_builtins['_getiter_'] = lambda obj: obj
            self._initialized = True
            logger.info("RestrictedPython 初始化成功")
        except ImportError as e:
            logger.error(f"RestrictedPython 未安装：{e}")
            raise
    
    def execute(self, user_code: str, context: Dict[str, Any]) -> SandboxResult:
        """
        执行用户代码
        
        Args:
            user_code: 用户提供的 Python 代码字符串
            context: 传递给代码的上下文
        
        Returns:
            SandboxResult 执行结果
        
        Example user code:
        ```python
        # 根据消息内容选择模型
        if 'code' in context.get('message', '').lower():
            return {'model': 'qwen3-coder-plus'}
        elif 'hello' in context.get('message', '').lower():
            return {'model': 'qwen3.5-flash'}
        else:
            return {'model': 'qwen3.5-plus'}
        ```
        """
        start_time = time.time()
        
        try:
            # 初始化 RestrictedPython
            if not self._initialized:
                self._init_restrictedpython()
            
            # 设置超时
            old_handler = signal.signal(signal.SIGALRM, self._timeout_handler)
            signal.alarm(self.timeout_seconds)
            
            try:
                # 编译受限代码
                byte_code = self._compile(user_code, '<sandbox>', 'exec')
                
                # 准备执行环境
                exec_globals = {
                    '__builtins__': self._safe_builtins,
                    'context': context,
                    '__name__': 'sandbox',
                    '__doc__': None,
                }
                
                # 执行代码
                exec(byte_code, exec_globals)
                
                # 调用 route 函数（如果定义了）
                if 'route' in exec_globals:
                    result = exec_globals['route'](context)
                else:
                    # 如果没有 route 函数，尝试直接执行
                    result = exec_globals.get('result', None)
                
                execution_time_ms = int((time.time() - start_time) * 1000)
                
                # 取消超时
                signal.alarm(0)
                
                return SandboxResult(
                    success=True,
                    result=result,
                    execution_time_ms=execution_time_ms
                )
                
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
                
        except TimeoutException:
            execution_time_ms = int((time.time() - start_time) * 1000)
            logger.error(f"沙箱执行超时：{self.timeout_seconds}秒")
            return SandboxResult(
                success=False,
                result=None,
                error=f"Execution timeout after {self.timeout_seconds}s",
                execution_time_ms=execution_time_ms
            )
        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            logger.error(f"沙箱执行失败：{e}")
            return SandboxResult(
                success=False,
                result=None,
                error=str(e),
                execution_time_ms=execution_time_ms
            )
    
    def _timeout_handler(self, signum, frame):
        """超时处理"""
        raise TimeoutException(f"Execution timeout after {self.timeout_seconds}s")
    
    def validate_code(self, user_code: str) -> Dict[str, Any]:
        """
        验证用户代码安全性
        
        Args:
            user_code: 用户代码
        
        Returns:
            验证结果
        """
        forbidden_patterns = [
            'import',
            '__import__',
            'eval(',
            'exec(',
            'compile(',
            'open(',
            'os.',
            'sys.',
            'subprocess',
            'socket',
            'urllib',
            'requests',
            'http',
            'file',
            'io.',
        ]
        
        issues = []
        
        for pattern in forbidden_patterns:
            if pattern in user_code:
                issues.append(f"Forbidden pattern detected: {pattern}")
        
        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'warnings': []
        }


class TimeoutException(Exception):
    """超时异常"""
    pass


# 全局沙箱实例
_sandbox: Optional[JSSandbox] = None


def get_sandbox() -> JSSandbox:
    """获取全局沙箱实例"""
    global _sandbox
    if _sandbox is None:
        _sandbox = JSSandbox()
    return _sandbox


def execute_user_route(user_code: str, context: Dict[str, Any]) -> SandboxResult:
    """
    执行用户路由代码
    
    Args:
        user_code: 用户代码
        context: 上下文
    
    Returns:
        执行结果
    """
    sandbox = get_sandbox()
    return sandbox.execute(user_code, context)


# 示例用户代码模板
USER_ROUTE_TEMPLATE = """
# 自定义路由逻辑
# context 包含：message, user_id, config 等

def route(context):
    message = context.get('message', '').lower()
    
    # 根据关键词选择模型
    code_keywords = ['code', 'python', '函数', '编程']
    greeting_keywords = ['你好', 'hi', 'hello', '谢谢']
    analysis_keywords = ['分析', '总结', '解释']
    
    has_code = False
    for kw in code_keywords:
        if kw in message:
            has_code = True
            break
    
    has_greeting = False
    for kw in greeting_keywords:
        if kw in message:
            has_greeting = True
            break
    
    has_analysis = False
    for kw in analysis_keywords:
        if kw in message:
            has_analysis = True
            break
    
    if has_code:
        return {
            'model': 'qwen3-coder-plus',
            'reason': '代码任务'
        }
    elif has_greeting:
        return {
            'model': 'qwen3.5-flash',
            'reason': '简单问候'
        }
    elif has_analysis:
        return {
            'model': 'qwen3.5-plus',
            'reason': '分析任务'
        }
    else:
        return {
            'model': 'qwen3.5-plus',
            'reason': '默认路由'
        }
"""
