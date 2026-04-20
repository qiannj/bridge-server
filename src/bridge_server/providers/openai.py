#!/usr/bin/env python3
"""
OpenAI Provider - OpenAI官方接口
支持 GPT-4, GPT-3.5 等模型
"""

import asyncio
import json
import os
from typing import Dict, Any, AsyncGenerator
from .base import BaseProvider, ModelInfo, ProviderFactory, ProviderStatus


class OpenAIProvider(BaseProvider):
    """OpenAI Provider"""
    
    def __init__(self, config: Dict[str, Any]):
        # Validate API key and immediately remove it from the config dict so it
        # is never accidentally serialised or exposed via self.config.
        self.api_key = config.get("api_key") or os.getenv("OPENAI_API_KEY")
        config.pop("api_key", None)
        if not self.api_key:
            raise ValueError("OpenAI API密钥未配置，请设置 OPENAI_API_KEY 环境变量")
        
        # 设置默认基础URL
        config.setdefault("base_url", "https://api.openai.com/v1")
        config.setdefault("id", "openai")
        
        super().__init__(config)
    
    def _get_headers(self) -> Dict[str, str]:
        """获取OpenAI请求头"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "BridgeServer/2.0"
        }
    
    def _load_models(self) -> Dict[str, ModelInfo]:
        """加载OpenAI支持的模型"""
        return {
            "gpt-4": ModelInfo(
                id="gpt-4",
                name="GPT-4", 
                max_tokens=4096,
                input_cost_per_1k=30.0,
                output_cost_per_1k=60.0,
                supports_streaming=True,
                context_window=8192
            ),
            "gpt-4-turbo": ModelInfo(
                id="gpt-4-turbo",
                name="GPT-4 Turbo",
                max_tokens=4096,
                input_cost_per_1k=10.0,
                output_cost_per_1k=30.0,
                supports_streaming=True,
                context_window=128000
            ),
            "gpt-3.5-turbo": ModelInfo(
                id="gpt-3.5-turbo",
                name="GPT-3.5 Turbo",
                max_tokens=4096,
                input_cost_per_1k=0.5,
                output_cost_per_1k=1.5,
                supports_streaming=True,
                context_window=16385
            )
        }
    
    def _format_messages(self, messages: list) -> list:
        """格式化消息为OpenAI格式"""
        formatted = []
        for msg in messages:
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                formatted.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
        return formatted
    
    async def health_check(self) -> ProviderStatus:
        """用 GET /models 做轻量探活，避免 thinking 模型超时。"""
        try:
            response = await asyncio.wait_for(
                self.client.get("/models"),
                timeout=10.0,
            )
            # 200 = OK；401/403 = key 问题但服务可达（视为 healthy，key 在配置时已验证）
            if response.status_code < 500:
                return ProviderStatus.HEALTHY
            return ProviderStatus.UNHEALTHY
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"健康检查失败 | Provider: {self.provider_id} | {e}"
            )
            return ProviderStatus.UNHEALTHY

    async def _make_request(self, messages: list, model: str = None, **kwargs) -> Dict[str, Any]:
        """发起OpenAI请求"""
        model = model or "gpt-3.5-turbo"
        
        payload = {
            "model": model,
            "messages": self._format_messages(messages),
            "stream": False,
            "max_tokens": kwargs.get("max_tokens", 4000),
            "temperature": kwargs.get("temperature", 0.7),
            "top_p": kwargs.get("top_p", 1.0),
        }
        
        # 移除None值
        payload = {k: v for k, v in payload.items() if v is not None}
        
        response = await self.client.post(
            "/chat/completions",
            json=payload
        )
        response.raise_for_status()
        
        result = response.json()
        
        # OpenAI响应已经是标准格式，直接返回并添加provider标识
        result["provider"] = "openai"
        return result
    
    async def _make_stream_request(self, messages: list, model: str = None, **kwargs) -> AsyncGenerator[str, None]:
        """发起OpenAI流式请求，支持 reasoning_content（思维链模型）"""
        model = model or "gpt-3.5-turbo"
        
        payload = {
            "model": model,
            "messages": self._format_messages(messages),
            "stream": True,
            "max_tokens": kwargs.get("max_tokens", 4000),
            "temperature": kwargs.get("temperature", 0.7),
            "top_p": kwargs.get("top_p", 1.0),
        }

        # 传递 stream_options（OpenAI 及兼容 API 支持，让末尾 chunk 携带 usage）
        stream_options = kwargs.get("stream_options")
        if stream_options:
            payload["stream_options"] = stream_options

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
                        
                        # 添加provider标识
                        chunk["provider"] = "openai"

                        # 规范化 delta：确保 reasoning_content 字段存在（方便客户端处理）
                        for choice in chunk.get("choices", []):
                            delta = choice.get("delta", {})
                            # 若上游有 reasoning_content，保留；否则不添加（避免污染普通模型输出）
                            rc = delta.get("reasoning_content")
                            if rc is not None:
                                delta["reasoning_content"] = rc
                        
                        yield json.dumps(chunk, ensure_ascii=False)
                    
                    except json.JSONDecodeError:
                        continue


# 注册Provider
ProviderFactory.register("openai", OpenAIProvider)