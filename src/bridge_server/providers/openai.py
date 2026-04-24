#!/usr/bin/env python3
"""
OpenAI Provider - OpenAI官方接口
支持 GPT-4, GPT-3.5 等模型
"""

import asyncio
import json
import os
import time
from typing import Dict, Any, AsyncGenerator, List, Tuple
from .base import BaseProvider, ModelInfo, ProviderFactory, ProviderStatus


class OpenAIProvider(BaseProvider):
    """OpenAI Provider"""
    
    def __init__(self, config: Dict[str, Any]):
        # OAuth providers don't use a static API key; token is fetched dynamically.
        if config.get("auth_type") == "oauth":
            self.api_key = None
            config.pop("api_key", None)
        else:
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
        """获取OpenAI请求头。OAuth 模式下不设置静态 Authorization（由事件钩子动态注入）。"""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "BridgeServer/2.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
    
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
        return self._format_openai_compatible_messages(messages)

    def _is_codex_backend(self) -> bool:
        oauth_cfg = self.config.get("oauth") or {}
        base_url = str(self.config.get("base_url") or "").lower()
        return oauth_cfg.get("provider") == "openai_codex" or "chatgpt.com/backend-api/codex" in base_url

    def _build_codex_responses_payload(
        self,
        messages: list,
        model: str,
        stream: bool,
        kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        instructions_parts: List[str] = []
        input_items: List[Dict[str, Any]] = []

        for msg in self._format_openai_compatible_messages(messages):
            role = msg.get("role")
            content = msg.get("content")
            if role == "system":
                if isinstance(content, str) and content.strip():
                    instructions_parts.append(content.strip())
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                            instructions_parts.append(str(part["text"]).strip())
                continue

            codex_content: List[Dict[str, Any]] = []
            if isinstance(content, str):
                codex_content.append({"type": "input_text", "text": content})
            elif isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    part_type = part.get("type")
                    if part_type == "text" and part.get("text") is not None:
                        codex_content.append({"type": "input_text", "text": str(part.get("text", ""))})
                    elif part_type == "input_text" and part.get("text") is not None:
                        codex_content.append({"type": "input_text", "text": str(part.get("text", ""))})
                    elif part_type == "image_url":
                        image_url = part.get("image_url")
                        if isinstance(image_url, dict):
                            image_url = image_url.get("url")
                        if image_url:
                            codex_content.append({"type": "input_image", "image_url": str(image_url)})
            if not codex_content:
                codex_content.append({"type": "input_text", "text": ""})

            input_items.append({
                "type": "message",
                "role": role or "user",
                "content": codex_content,
            })

        payload: Dict[str, Any] = {
            "model": model,
            "instructions": "\n\n".join(part for part in instructions_parts if part) or "You are a helpful assistant.",
            "input": input_items or [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": ""}]}],
            "stream": stream,
            "store": False,
        }
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]
        if "top_p" in kwargs:
            payload["top_p"] = kwargs["top_p"]
        return payload

    async def _collect_codex_response(self, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        response_id = ""
        text_parts: List[str] = []
        async with self.client.stream(
            "POST",
            "/responses",
            json=payload,
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")
                if event_type in {"response.created", "response.in_progress", "response.completed"}:
                    resp = event.get("response") or {}
                    response_id = response_id or str(resp.get("id") or "")
                elif event_type == "response.output_text.delta":
                    text_parts.append(str(event.get("delta") or ""))
                elif event_type == "response.output_text.done" and not text_parts:
                    text_parts.append(str(event.get("text") or ""))
        result = {
            "id": response_id or f"codex-resp-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.get("model"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "".join(text_parts)},
                    "finish_reason": "stop",
                }
            ],
        }
        return result, "".join(text_parts)

    async def _stream_codex_response(self, payload: Dict[str, Any]) -> AsyncGenerator[str, None]:
        chunk_id = f"chatcmpl-codex-{int(time.time() * 1000)}"
        sent_role = False
        async with self.client.stream(
            "POST",
            "/responses",
            json=payload,
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")
                if event_type == "response.created":
                    resp = event.get("response") or {}
                    chunk_id = str(resp.get("id") or chunk_id)
                elif event_type == "response.output_text.delta":
                    delta_text = str(event.get("delta") or "")
                    if not sent_role:
                        yield json.dumps({
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": payload.get("model"),
                            "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
                            "provider": "openai",
                        }, ensure_ascii=False)
                        sent_role = True
                    yield json.dumps({
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": payload.get("model"),
                        "choices": [{"index": 0, "delta": {"content": delta_text}, "finish_reason": None}],
                        "provider": "openai",
                    }, ensure_ascii=False)
                elif event_type == "response.completed":
                    if not sent_role:
                        yield json.dumps({
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": payload.get("model"),
                            "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
                            "provider": "openai",
                        }, ensure_ascii=False)
                    yield json.dumps({
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": payload.get("model"),
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                        "provider": "openai",
                    }, ensure_ascii=False)
                    return
    
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
        if self._is_codex_backend():
            payload = self._build_codex_responses_payload(messages, model, stream=True, kwargs=kwargs)
            result, _ = await self._collect_codex_response(payload)
            return result

        payload = self._build_openai_compatible_payload(
            model=model,
            messages=messages,
            stream=False,
            default_max_tokens=4000,
            default_temperature=0.7,
            default_top_p=1.0,
            kwargs=kwargs,
        )
        
        response = await self.client.post(
            "/chat/completions",
            json=payload
        )
        response.raise_for_status()
        
        result = response.json()
        return self._normalize_openai_compatible_response(result, "openai")
    
    async def _make_stream_request(self, messages: list, model: str = None, **kwargs) -> AsyncGenerator[str, None]:
        """发起OpenAI流式请求，支持 reasoning_content（思维链模型）"""
        model = model or "gpt-3.5-turbo"
        if self._is_codex_backend():
            payload = self._build_codex_responses_payload(messages, model, stream=True, kwargs=kwargs)
            async for chunk in self._stream_codex_response(payload):
                yield chunk
            return

        payload = self._build_openai_compatible_payload(
            model=model,
            messages=messages,
            stream=True,
            default_max_tokens=4000,
            default_temperature=0.7,
            default_top_p=1.0,
            kwargs=kwargs,
        )
        
        async with self.client.stream(
            "POST",
            "/chat/completions", 
            json=payload
        ) as response:
            response.raise_for_status()
            stream_state = {}
            
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
                        chunk = self._normalize_openai_compatible_stream_chunk(chunk, "openai", stream_state)

                        # 规范化 delta：确保 reasoning_content 字段存在（方便客户端处理）
                        for choice in chunk.get("choices", []):
                            delta = choice.get("delta", {})
                            rc = delta.get("reasoning_content")
                            if rc is not None:
                                delta["reasoning_content"] = rc
                        
                        yield json.dumps(chunk, ensure_ascii=False)
                    
                    except json.JSONDecodeError:
                        continue


# 注册Provider
ProviderFactory.register("openai", OpenAIProvider)
