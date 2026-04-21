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
        return self._format_openai_compatible_messages(messages)
    
    async def _make_request(self, messages: list, model: str = None, **kwargs) -> Dict[str, Any]:
        """发起DashScope请求"""
        model = model or "qwen3.5-flash"  # 默认使用性价比高的模型
        
        payload = self._build_openai_compatible_payload(
            model=model,
            messages=messages,
            stream=False,
            default_max_tokens=4000,
            default_temperature=0.7,
            default_top_p=0.8,
            kwargs=kwargs,
        )
        
        response = await self.client.post(
            "/chat/completions",
            json=payload
        )
        response.raise_for_status()
        
        result = response.json()
        return self._normalize_openai_compatible_response(result, "dashscope")
    
    async def _make_stream_request(self, messages: list, model: str = None, **kwargs) -> AsyncGenerator[str, None]:
        """发起DashScope流式请求"""
        model = model or "qwen3.5-flash"
        
        payload = self._build_openai_compatible_payload(
            model=model,
            messages=messages,
            stream=True,
            default_max_tokens=4000,
            default_temperature=0.7,
            default_top_p=0.8,
            kwargs=kwargs,
        )
        
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
                        chunk = self._normalize_openai_compatible_stream_chunk(chunk, "dashscope")
                        yield json.dumps(chunk, ensure_ascii=False)
                    
                    except json.JSONDecodeError:
                        continue


# 注册Provider
ProviderFactory.register("dashscope", DashScopeProvider)