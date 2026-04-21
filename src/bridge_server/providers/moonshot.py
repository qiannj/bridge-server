#!/usr/bin/env python3
"""
Moonshot Provider - 月之暗面 Kimi
支持长上下文对话模型
"""

import json
import os
from typing import Dict, Any, AsyncGenerator
from .base import BaseProvider, ModelInfo, ProviderFactory


class MoonshotProvider(BaseProvider):
    """月之暗面 Moonshot Provider"""
    
    def __init__(self, config: Dict[str, Any]):
        # Validate API key and immediately remove it from the config dict so it
        # is never accidentally serialised or exposed via self.config.
        self.api_key = config.get("api_key") or os.getenv("MOONSHOT_API_KEY")
        config.pop("api_key", None)
        if not self.api_key:
            raise ValueError("Moonshot API密钥未配置，请设置 MOONSHOT_API_KEY 环境变量")
        
        # 设置默认基础URL
        config.setdefault("base_url", "https://api.moonshot.cn/v1")
        config.setdefault("id", "moonshot")
        
        super().__init__(config)
    
    def _get_headers(self) -> Dict[str, str]:
        """获取Moonshot请求头"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "BridgeServer/2.0"
        }
    
    def _load_models(self) -> Dict[str, ModelInfo]:
        """加载Moonshot支持的模型"""
        return {
            "moonshot-v1-8k": ModelInfo(
                id="moonshot-v1-8k",
                name="Moonshot v1 8K",
                max_tokens=4000,
                input_cost_per_1k=12.0,
                output_cost_per_1k=12.0,
                supports_streaming=True,
                context_window=8000
            ),
            "moonshot-v1-32k": ModelInfo(
                id="moonshot-v1-32k", 
                name="Moonshot v1 32K",
                max_tokens=4000,
                input_cost_per_1k=24.0,
                output_cost_per_1k=24.0,
                supports_streaming=True,
                context_window=32000
            ),
            "moonshot-v1-128k": ModelInfo(
                id="moonshot-v1-128k",
                name="Moonshot v1 128K",
                max_tokens=4000, 
                input_cost_per_1k=60.0,
                output_cost_per_1k=60.0,
                supports_streaming=True,
                context_window=128000
            )
        }
    
    def _format_messages(self, messages: list) -> list:
        """格式化消息为Moonshot格式"""
        return self._format_openai_compatible_messages(messages)
    
    async def _make_request(self, messages: list, model: str = None, **kwargs) -> Dict[str, Any]:
        """发起Moonshot请求"""
        model = model or "moonshot-v1-8k"  # 默认使用8K模型
        
        payload = self._build_openai_compatible_payload(
            model=model,
            messages=messages,
            stream=False,
            default_max_tokens=4000,
            default_temperature=0.3,
            default_top_p=1.0,
            kwargs=kwargs,
        )
        
        response = await self.client.post(
            "/chat/completions",
            json=payload
        )
        response.raise_for_status()
        
        result = response.json()
        return self._normalize_openai_compatible_response(result, "moonshot")
    
    async def _make_stream_request(self, messages: list, model: str = None, **kwargs) -> AsyncGenerator[str, None]:
        """发起Moonshot流式请求"""
        model = model or "moonshot-v1-8k"
        
        payload = self._build_openai_compatible_payload(
            model=model,
            messages=messages,
            stream=True,
            default_max_tokens=4000,
            default_temperature=0.3,
            default_top_p=1.0,
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
                        chunk = self._normalize_openai_compatible_stream_chunk(chunk, "moonshot")
                        yield json.dumps(chunk, ensure_ascii=False)
                    
                    except json.JSONDecodeError:
                        continue


# 注册Provider
ProviderFactory.register("moonshot", MoonshotProvider)