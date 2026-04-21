#!/usr/bin/env python3
"""
Provider 抽象基类 - Bridge Server v2.0
统一各AI平台的接口规范和性能优化
"""

import asyncio
import httpx
import json
import logging
import re
import time
import uuid
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

_OPENAI_EXTRA_PAYLOAD_KEYS = (
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "stop",
    "response_format",
    "presence_penalty",
    "frequency_penalty",
    "seed",
    "n",
)

_TAGGED_TOOL_CALL_RE = re.compile(
    r"<(?:[\w.-]+:)?tool_call>\s*(.*?)\s*</(?:[\w.-]+:)?tool_call>",
    re.IGNORECASE | re.DOTALL,
)
_INVOKE_RE = re.compile(
    r"<invoke\s+name=\"([^\"]+)\"\s*>(.*?)</invoke>",
    re.IGNORECASE | re.DOTALL,
)
_PARAM_RE = re.compile(
    r"<parameter\s+name=\"([^\"]+)\"\s*>(.*?)</parameter>",
    re.IGNORECASE | re.DOTALL,
)
_TOOL_TAG_RE = re.compile(
    r"<tool\s+name=\"([^\"]+)\"\s*>(.*?)</tool>",
    re.IGNORECASE | re.DOTALL,
)
_TOOL_TAG_PARAM_RE = re.compile(
    r"<param\s+name=\"([^\"]+)\"\s*>(.*?)</param>",
    re.IGNORECASE | re.DOTALL,
)
_TOOL_CODE_RE = re.compile(
    r"<tool_code>\s*(.*?)\s*</tool_code>",
    re.IGNORECASE | re.DOTALL,
)
_TOOL_CODE_NAME_RE = re.compile(
    r"tool\s*=>\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_TOOL_CODE_ARGS_RE = re.compile(
    r"args\s*=>\s*['\"](.*?)['\"]",
    re.IGNORECASE | re.DOTALL,
)
_SIMPLE_XML_ARG_RE = re.compile(
    r"<([a-zA-Z0-9_:-]+)>\s*(.*?)\s*</\1>",
    re.DOTALL,
)


class ProviderStatus(Enum):
    """Provider状态枚举"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"  
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ModelInfo:
    """模型信息"""
    id: str
    name: str
    max_tokens: int
    input_cost_per_1k: float
    output_cost_per_1k: float
    supports_streaming: bool = True
    context_window: int = 4096


@dataclass
class ProviderMetrics:
    """Provider性能指标"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency: float = 0.0
    last_request_time: float = 0.0
    
    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests
    
    @property
    def average_latency(self) -> float:
        if self.successful_requests == 0:
            return 0.0
        return self.total_latency / self.successful_requests


class BaseProvider(ABC):
    """AI平台Provider抽象基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.provider_id = config.get("id", self.__class__.__name__)

        # ── OAuth 2.0 Client Credentials support ────────────────────────────
        # Must be initialised before _create_http_client() so the async event
        # hook (_inject_oauth_header) can reference it.
        self._oauth_manager = None
        if config.get("auth_type") == "oauth":
            from .oauth_manager import OAuthTokenManager
            oauth_cfg = config.get("oauth") or {}
            self._oauth_manager = OAuthTokenManager(
                token_url=oauth_cfg.get("token_url", ""),
                client_id=oauth_cfg.get("client_id", ""),
                client_secret=oauth_cfg.get("client_secret", ""),
                scope=oauth_cfg.get("scope"),
                grant_type=oauth_cfg.get("grant_type", "client_credentials"),
                extra_params=oauth_cfg.get("extra_params"),
            )

        self.models = self._load_models()
        # 若 config 里传入了 models 列表，以其为准（自定义 provider 场景）
        config_models = config.get("models")
        if config_models:
            extra = {
                m: ModelInfo(id=m, name=m, max_tokens=4096,
                             input_cost_per_1k=0.0, output_cost_per_1k=0.0,
                             supports_streaming=True, context_window=128000)
                for m in config_models if m not in self.models
            }
            if extra:
                self.models = {**extra, **self.models}
        self.client = self._create_http_client()
        self.metrics = ProviderMetrics()
        
        logger.info(f"初始化 Provider: {self.provider_id}, 支持 {len(self.models)} 个模型")
    
    def _create_http_client(self) -> httpx.AsyncClient:
        """创建优化的HTTP客户端"""
        self._uses_shared_http_client = True
        from ..utils.connection_pools import get_provider_http_client

        # Build request hooks: observability first, then OAuth token injection
        request_hooks = [self._inject_observability_headers]
        if self._oauth_manager is not None:
            request_hooks.append(self._inject_oauth_header)

        return get_provider_http_client(
            self.provider_id,
            base_url=self.config.get("base_url", ""),
            headers=self._get_headers(),
            timeout=self.config.get("timeout", 30.0),
            http2=self.config.get("http2", True),
            max_connections=self.config.get("max_connections", 50),
            max_keepalive_connections=self.config.get("max_keepalive_connections", 20),
            follow_redirects=True,
            event_hooks={"request": request_hooks},
        )

    async def _inject_observability_headers(self, request: httpx.Request) -> None:
        """Inject request correlation headers into outbound provider calls."""
        from ..observability.tracing import get_trace_headers

        for header, value in get_trace_headers().items():
            request.headers[header] = value

    async def _inject_oauth_header(self, request: httpx.Request) -> None:
        """Inject Bearer token from OAuth manager (replaces static Authorization)."""
        if self._oauth_manager is not None:
            try:
                token = await self._oauth_manager.get_token()
                request.headers["Authorization"] = f"Bearer {token}"
            except Exception as e:
                logger.error(f"OAuth token 获取失败 | Provider: {self.provider_id} | {e}")
                raise

    def _format_openai_compatible_messages(self, messages: list) -> list:
        """Preserve OpenAI-compatible tool metadata instead of flattening to role/content only."""
        formatted = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if not role:
                continue

            entry: Dict[str, Any] = {"role": role}
            if "content" in msg:
                entry["content"] = msg.get("content")
            elif role != "assistant":
                entry["content"] = None

            for key in ("name", "tool_calls", "tool_call_id"):
                if key in msg and msg.get(key) is not None:
                    entry[key] = msg.get(key)

            if role == "assistant" and "content" not in entry and "tool_calls" not in entry:
                continue

            formatted.append(entry)
        return formatted

    def _build_openai_compatible_payload(
        self,
        *,
        model: str,
        messages: list,
        stream: bool,
        default_max_tokens: int,
        default_temperature: float,
        default_top_p: float,
        kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": self._format_openai_compatible_messages(messages),
            "stream": stream,
            "max_tokens": kwargs.get("max_tokens", default_max_tokens),
            "temperature": kwargs.get("temperature", default_temperature),
            "top_p": kwargs.get("top_p", default_top_p),
        }

        for key in _OPENAI_EXTRA_PAYLOAD_KEYS:
            if key in kwargs:
                payload[key] = kwargs.get(key)

        stream_options = kwargs.get("stream_options")
        if stream and stream_options:
            payload["stream_options"] = stream_options

        return {k: v for k, v in payload.items() if v is not None}

    @staticmethod
    def _make_tool_call_id() -> str:
        return f"call_{uuid.uuid4().hex[:24]}"

    @staticmethod
    def _extract_tool_code_arguments(raw_args: str) -> Dict[str, Any]:
        xml_matches = _SIMPLE_XML_ARG_RE.findall(raw_args or "")
        if xml_matches:
            return {name.strip(): value.strip() for name, value in xml_matches if name.strip()}

        stripped = (raw_args or "").strip()
        if not stripped:
            return {}

        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        return {"input": stripped}

    def _extract_tagged_tool_calls(self, content: Any):
        if not isinstance(content, str):
            return content, []

        lowered = content.lower()
        if "tool_call" not in lowered and "tool_code" not in lowered:
            return content, []

        tool_calls = []
        for match in _TAGGED_TOOL_CALL_RE.finditer(content):
            inner = (match.group(1) or "").strip()
            if not inner:
                continue

            parsed = None
            try:
                parsed = json.loads(inner)
            except Exception:
                parsed = None

            if isinstance(parsed, dict) and parsed.get("name"):
                arguments = parsed.get("arguments", {})
                if not isinstance(arguments, dict):
                    arguments = {}
                tool_calls.append({
                    "id": self._make_tool_call_id(),
                    "type": "function",
                    "function": {
                        "name": str(parsed["name"]),
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                })
                continue

            invoke_match = _INVOKE_RE.search(inner)
            if invoke_match:
                name = (invoke_match.group(1) or "").strip()
                if name:
                    params = {
                        param_name.strip(): param_value.strip()
                        for param_name, param_value in _PARAM_RE.findall(invoke_match.group(2) or "")
                        if param_name.strip()
                    }
                    tool_calls.append({
                        "id": self._make_tool_call_id(),
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(params, ensure_ascii=False),
                        },
                    })
                    continue

            tool_tag_match = _TOOL_TAG_RE.search(inner)
            if not tool_tag_match:
                continue

            name = (tool_tag_match.group(1) or "").strip()
            if not name:
                continue

            params = {
                param_name.strip(): param_value.strip()
                for param_name, param_value in _TOOL_TAG_PARAM_RE.findall(tool_tag_match.group(2) or "")
                if param_name.strip()
            }
            tool_calls.append({
                "id": self._make_tool_call_id(),
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(params, ensure_ascii=False),
                },
            })

        for match in _TOOL_CODE_RE.finditer(content):
            inner = (match.group(1) or "").strip()
            if not inner:
                continue

            name_match = _TOOL_CODE_NAME_RE.search(inner)
            if not name_match:
                continue
            name = name_match.group(1).strip()
            if not name:
                continue

            args_match = _TOOL_CODE_ARGS_RE.search(inner)
            arguments = self._extract_tool_code_arguments(args_match.group(1) if args_match else "")
            tool_calls.append({
                "id": self._make_tool_call_id(),
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            })

        if not tool_calls:
            return content, []

        cleaned = _TAGGED_TOOL_CALL_RE.sub("", content)
        cleaned = _TOOL_CODE_RE.sub("", cleaned)
        cleaned = cleaned.strip()
        return cleaned or None, tool_calls

    def _normalize_openai_compatible_response(self, result: Dict[str, Any], provider_name: str) -> Dict[str, Any]:
        normalized = dict(result or {})
        normalized["provider"] = provider_name

        choices = normalized.get("choices")
        if not isinstance(choices, list):
            return normalized

        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict) or message.get("tool_calls"):
                continue

            cleaned_content, tool_calls = self._extract_tagged_tool_calls(message.get("content"))
            if not tool_calls:
                continue

            message["content"] = cleaned_content
            message["tool_calls"] = tool_calls
            if choice.get("finish_reason") in (None, "stop"):
                choice["finish_reason"] = "tool_calls"

        return normalized

    def _normalize_openai_compatible_stream_chunk(self, chunk: Dict[str, Any], provider_name: str) -> Dict[str, Any]:
        normalized = dict(chunk or {})
        normalized["provider"] = provider_name

        choices = normalized.get("choices")
        if not isinstance(choices, list):
            return normalized

        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if not isinstance(delta, dict) or delta.get("tool_calls"):
                continue

            cleaned_content, tool_calls = self._extract_tagged_tool_calls(delta.get("content"))
            if not tool_calls:
                continue

            delta["content"] = cleaned_content
            delta["tool_calls"] = tool_calls
            if choice.get("finish_reason") in (None, "stop"):
                choice["finish_reason"] = "tool_calls"

        return normalized
    
    @abstractmethod
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头（子类实现认证逻辑）"""
        pass
    
    @abstractmethod
    def _load_models(self) -> Dict[str, ModelInfo]:
        """加载模型列表（子类实现）"""
        pass
    
    @abstractmethod
    async def _make_request(self, messages: list, model: str, **kwargs) -> Dict[str, Any]:
        """发起实际请求（子类实现）"""
        pass
    
    @abstractmethod
    async def _make_stream_request(self, messages: list, model: str, **kwargs) -> AsyncGenerator[str, None]:
        """发起流式请求（子类实现）"""
        pass
    
    async def chat_completion(self, messages: list, model: str = None, **kwargs) -> Dict[str, Any]:
        """统一的聊天完成接口"""
        start_time = time.perf_counter()
        
        try:
            # 模型验证
            if model and model not in self.models:
                raise ValueError(f"不支持的模型: {model}")
            
            # 执行请求
            result = await self._make_request(messages, model, **kwargs)
            
            # 记录成功指标
            latency = (time.perf_counter() - start_time) * 1000
            self._record_success(latency)
            
            logger.info(f"请求成功 | Provider: {self.provider_id} | 模型: {model} | 延迟: {latency:.2f}ms")
            
            return result
            
        except Exception as e:
            # 记录失败指标
            self._record_failure()
            logger.error(f"请求失败 | Provider: {self.provider_id} | 错误: {str(e)}")
            raise
    
    async def chat_completion_stream(self, messages: list, model: str = None, **kwargs) -> AsyncGenerator[str, None]:
        """统一的流式聊天完成接口"""
        start_time = time.perf_counter()
        
        try:
            # 模型验证
            if model and model not in self.models:
                raise ValueError(f"不支持的模型: {model}")
            
            # 检查流式支持
            if model and not self.models[model].supports_streaming:
                raise ValueError(f"模型 {model} 不支持流式输出")
            
            # 执行流式请求
            async for chunk in self._make_stream_request(messages, model, **kwargs):
                yield chunk
            
            # 记录成功指标
            latency = (time.perf_counter() - start_time) * 1000
            self._record_success(latency)
            
        except Exception as e:
            # 记录失败指标  
            self._record_failure()
            logger.error(f"流式请求失败 | Provider: {self.provider_id} | 错误: {str(e)}")
            raise
    
    async def health_check(self) -> ProviderStatus:
        """健康检查"""
        try:
            # 发起轻量级测试请求
            test_messages = [{"role": "user", "content": "hello"}]
            await asyncio.wait_for(
                self._make_request(test_messages, list(self.models.keys())[0]),
                timeout=10.0
            )
            
            # 根据成功率判断状态
            if self.metrics.success_rate >= 0.95:
                return ProviderStatus.HEALTHY
            elif self.metrics.success_rate >= 0.8:
                return ProviderStatus.DEGRADED
            else:
                return ProviderStatus.UNHEALTHY
                
        except Exception as e:
            logger.warning(f"健康检查失败 | Provider: {self.provider_id} | 错误: {str(e)}")
            return ProviderStatus.UNHEALTHY
    
    def get_supported_models(self) -> list:
        """获取支持的模型列表"""
        return list(self.models.keys())
    
    def get_model_info(self, model: str) -> Optional[ModelInfo]:
        """获取模型信息"""
        return self.models.get(model)
    
    def get_metrics(self) -> Dict[str, Any]:
        """获取性能指标"""
        return {
            "provider_id": self.provider_id,
            "total_requests": self.metrics.total_requests,
            "success_rate": round(self.metrics.success_rate, 3),
            "average_latency": round(self.metrics.average_latency, 2),
            "last_request_time": self.metrics.last_request_time
        }
    
    def _record_success(self, latency_ms: float):
        """记录成功请求指标"""
        self.metrics.total_requests += 1
        self.metrics.successful_requests += 1
        self.metrics.total_latency += latency_ms
        self.metrics.last_request_time = time.time()
    
    def _record_failure(self):
        """记录失败请求指标"""
        self.metrics.total_requests += 1
        self.metrics.failed_requests += 1
        self.metrics.last_request_time = time.time()
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self.client and not getattr(self, "_uses_shared_http_client", False):
            await self.client.aclose()


class ProviderFactory:
    """Provider工厂类"""
    
    _providers = {}
    
    @classmethod
    def register(cls, provider_type: str, provider_class: type):
        """注册Provider类"""
        cls._providers[provider_type] = provider_class
        logger.info(f"注册 Provider: {provider_type}")
    
    @classmethod
    def create(cls, provider_type: str, config: Dict[str, Any]) -> BaseProvider:
        """创建Provider实例"""
        if provider_type not in cls._providers:
            raise ValueError(f"未知的 Provider 类型: {provider_type}")
        
        provider_class = cls._providers[provider_type]
        return provider_class(config)
    
    @classmethod
    def get_supported_types(cls) -> list:
        """获取支持的Provider类型"""
        return list(cls._providers.keys())
