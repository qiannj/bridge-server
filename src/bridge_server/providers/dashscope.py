#!/usr/bin/env python3
"""
DashScope Provider - 阿里云通义千问
支持 Qwen3 系列模型的统一接口
"""

import json
import os
from typing import Dict, Any, AsyncGenerator
from .base import BaseProvider, ModelInfo, ProviderFactory


class DashScopeProvider(BaseProvider):
    """阿里云 DashScope Provider"""
    
    def __init__(self, config: Dict[str, Any]):
        # Validate API key and immediately remove it from the config dict so it
        # is never accidentally serialised or exposed via self.config.
        self.api_key = config.get("api_key") or os.getenv("DASHSCOPE_API_KEY")
        config.pop("api_key", None)
        if not self.api_key:
            raise ValueError("DashScope API密钥未配置，请设置 DASHSCOPE_API_KEY 环境变量")
        
        # 设置默认基础URL
        config.setdefault("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        config.setdefault("id", "dashscope")
        
        super().__init__(config)
    
    def _get_headers(self) -> Dict[str, str]:
        """获取DashScope请求头"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "BridgeServer/2.0"
        }
    
    def _load_models(self) -> Dict[str, ModelInfo]:
        """加载DashScope支持的模型"""
        return {
            "qwen3-max": ModelInfo(
                id="qwen3-max",
                name="Qwen3 Max",
                max_tokens=8192,
                input_cost_per_1k=2.5,
                output_cost_per_1k=10.0,
                supports_streaming=True,
                context_window=256000
            ),
            "qwen3.5-flash": ModelInfo(
                id="qwen3.5-flash", 
                name="Qwen3.5 Flash",
                max_tokens=8192,
                input_cost_per_1k=0.5,
                output_cost_per_1k=1.5,
                supports_streaming=True,
                context_window=256000
            ),
            "qwen3.6-plus": ModelInfo(
                id="qwen3.6-plus",
                name="Qwen3.6 Plus", 
                max_tokens=8192,
                input_cost_per_1k=1.0,
                output_cost_per_1k=3.0,
                supports_streaming=True,
                context_window=256000
            )
        }
    
    def _format_messages(self, messages: list) -> list:
        """格式化消息为DashScope格式"""
        formatted = []
        for msg in messages:
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                formatted.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
        return formatted
    
    async def _make_request(self, messages: list, model: str = None, **kwargs) -> Dict[str, Any]:
        """发起DashScope请求"""
        model = model or "qwen3.5-flash"  # 默认使用性价比高的模型
        
        payload = {
            "model": model,
            "messages": self._format_messages(messages),
            "stream": False,
            "max_tokens": kwargs.get("max_tokens", 4000),
            "temperature": kwargs.get("temperature", 0.7),
            "top_p": kwargs.get("top_p", 0.8),
        }
        
        # 移除None值
        payload = {k: v for k, v in payload.items() if v is not None}
        
        response = await self.client.post(
            "/chat/completions",
            json=payload
        )
        response.raise_for_status()
        
        result = response.json()
        
        # 标准化响应格式
        return {
            "id": result.get("id"),
            "model": result.get("model"),
            "choices": result.get("choices", []),
            "usage": result.get("usage", {}),
            "provider": "dashscope"
        }
    
    async def _make_stream_request(self, messages: list, model: str = None, **kwargs) -> AsyncGenerator[str, None]:
        """发起DashScope流式请求"""
        model = model or "qwen3.5-flash"
        
        payload = {
            "model": model,
            "messages": self._format_messages(messages),
            "stream": True,
            "max_tokens": kwargs.get("max_tokens", 4000),
            "temperature": kwargs.get("temperature", 0.7),
            "top_p": kwargs.get("top_p", 0.8),
        }
        
        # 移除None值
        payload = {k: v for k, v in payload.items() if v is not None}
        
        async with self.client.stream(
            "POST", 
            "/chat/completions",
            json=payload
        ) as response:
            response.raise_for_status()
            
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                
                # 解析SSE格式
                if line.startswith("data: "):
                    data = line[6:].strip()
                    
                    if data == "[DONE]":
                        break
                    
                    try:
                        chunk = json.loads(data)
                        
                        # 提取内容
                        choices = chunk.get("choices", [])
                        if choices and len(choices) > 0:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            
                            if content:
                                # 返回标准格式
                                yield json.dumps({
                                    "id": chunk.get("id"),
                                    "model": chunk.get("model"),
                                    "choices": [{
                                        "delta": {"content": content},
                                        "index": 0
                                    }],
                                    "provider": "dashscope"
                                })
                    
                    except json.JSONDecodeError:
                        continue


# 注册Provider
ProviderFactory.register("dashscope", DashScopeProvider)