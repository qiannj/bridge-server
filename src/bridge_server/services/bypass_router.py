"""旁路模型路由器 (Bypass Router)
====================================
通过指定的路由模型（LLM）来动态决定请求应路由到哪个执行模型，
并可选地在发送给执行模型之前对上下文进行压缩。

路由决策优先级：
  1. _resolve_requested_model — 客户端明确指定 model
  2. BypassRouter (本模块)     — 用户配置的 LLM 路由器
  3. CustomRouter (RouterRegistry) — 用户自编码插件路由器
  4. SmartRouter               — 关键词正则兜底

配置示例（config.yaml）：
  bypass_router:
    enabled: true
    routing_model: "dashscope/qwen3.5-flash"
    routing_rules: "代码任务用 qwen3-coder，长文本用 moonshot/kimi-chat"
    timeout_ms: 3000
    compress_context_threshold: 20   # 超过 N 条消息时才允许压缩
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .routing.router import RouteResult

logger = logging.getLogger(__name__)

# ── 默认提示词 ────────────────────────────────────────────────────────────────

_DEFAULT_ROUTING_PROMPT = """\
你是一个模型路由助手。根据用户最新消息，从下面的可用模型中选择最合适的一个处理该请求。

可用模型列表（格式：provider/model）：
{available_models}

路由规则（管理员配置）：
{routing_rules}

请仅以 JSON 格式回复，不要有任何其他文字：
{{"model": "provider/model", "compress_context": false, "reason": "简短理由"}}

字段说明：
- model：从可用模型中选择，使用 provider/model 格式
- compress_context：若对话历史较长且与当前问题关联度低，设为 true 进行压缩
- reason：简短说明选择理由（20 字以内）
"""

_DEFAULT_COMPRESS_PROMPT = """\
请将以下对话历史压缩为一段简洁的背景摘要，保留关键结论和重要信息，去除冗余内容。
摘要将作为背景信息注入到后续对话中。

对话历史：
{history}

请直接输出压缩后的摘要（不超过 300 字），不要加任何前缀或后缀。
"""

# 从模型回复中提取 JSON 的正则
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_INLINE_RE = re.compile(r'\{[^{}]*"model"\s*:[^{}]*\}', re.DOTALL)


# ── 主类 ──────────────────────────────────────────────────────────────────────

class BypassRouter:
    """
    旁路模型路由器：
    1. 调用指定路由模型，由 LLM 决定使用哪个执行模型
    2. 可选地对历史上下文进行压缩，降低执行模型的 token 消耗
    """

    def __init__(self, config: Dict[str, Any]):
        self.enabled: bool = bool(config.get("enabled", False))
        self.routing_model: str = str(config.get("routing_model") or "")
        self.routing_rules: str = str(
            config.get("routing_rules") or "根据任务类型选择最合适的模型"
        )
        self.routing_prompt: str = str(
            config.get("routing_prompt") or _DEFAULT_ROUTING_PROMPT
        )
        self.compress_prompt: str = str(
            config.get("compress_prompt") or _DEFAULT_COMPRESS_PROMPT
        )
        self.timeout_ms: int = int(config.get("timeout_ms") or 3000)
        # 仅当消息数超过阈值时，才允许路由模型建议压缩
        self.compress_threshold: int = int(
            config.get("compress_context_threshold") or 10
        )

    def reload(self, config: Dict[str, Any]) -> None:
        self.__init__(config)

    # ── 主入口 ─────────────────────────────────────────────────────────────────

    async def route(
        self,
        messages: List[Dict[str, Any]],
        provider_manager,
    ) -> Tuple[Optional[RouteResult], List[Dict[str, Any]]]:
        """
        调用路由模型做路由决策，并在需要时压缩上下文。

        Returns:
            (RouteResult | None, messages)
            RouteResult 为 None 表示决策失败，调用方应降级到下一级路由。
        """
        if not self.enabled or not self.routing_model:
            return None, messages

        available = _get_available_models_str(provider_manager)
        if not available:
            return None, messages

        start = time.perf_counter()
        try:
            decision = await asyncio.wait_for(
                self._call_routing_model(messages, available, provider_manager),
                timeout=self.timeout_ms / 1000,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "bypass_router_timeout",
                routing_model=self.routing_model,
                timeout_ms=self.timeout_ms,
            )
            return None, messages
        except Exception as exc:
            logger.warning("bypass_router_call_error", error=str(exc))
            return None, messages

        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

        if decision is None:
            logger.warning("bypass_router_no_decision", routing_model=self.routing_model)
            return None, messages

        selected_model: str = str(decision.get("model") or "")
        compress: bool = bool(decision.get("compress_context", False))
        reason: str = str(decision.get("reason") or "bypass router")

        provider_id, model_id = _parse_model(selected_model)
        if not provider_id or not model_id:
            logger.warning("bypass_router_invalid_model", selected=selected_model)
            return None, messages

        all_models = provider_manager.get_provider_models()
        if provider_id not in all_models or model_id not in all_models.get(provider_id, []):
            logger.warning(
                "bypass_router_model_not_found",
                selected=selected_model,
            )
            return None, messages

        # 上下文压缩
        if compress and len(messages) > self.compress_threshold:
            try:
                messages = await asyncio.wait_for(
                    self._compress_context(messages, provider_manager),
                    timeout=self.timeout_ms / 1000,
                )
                logger.info("bypass_router_context_compressed", msg_count=len(messages))
            except Exception as exc:
                logger.warning("bypass_router_compress_error", error=str(exc))

        route_result = RouteResult(
            provider_id=provider_id,
            model=model_id,
            task_type="bypass",
            confidence=0.9,
            reason=f"旁路路由: {reason}",
            from_cache=False,
        )

        logger.info(
            "bypass_router_decision",
            selected=selected_model,
            compress_context=compress,
            reason=reason,
            elapsed_ms=elapsed_ms,
        )
        return route_result, messages

    # ── 内部方法 ───────────────────────────────────────────────────────────────

    async def _call_routing_model(
        self,
        messages: List[Dict[str, Any]],
        available_models: str,
        provider_manager,
    ) -> Optional[Dict[str, Any]]:
        """向路由模型发起单次调用，获取路由决策 JSON。"""
        last_user = _extract_last_user_message(messages)

        system_prompt = self.routing_prompt.format(
            available_models=available_models,
            routing_rules=self.routing_rules,
        )
        routing_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": last_user or "(空消息)"},
        ]

        provider_id, model_id = _parse_model(self.routing_model)
        if not provider_id or not model_id:
            return None

        response = await provider_manager.chat_completion(
            messages=routing_messages,
            model=model_id,
            provider_id=provider_id,
            max_tokens=256,
            temperature=0.1,
        )

        content = ""
        choices = response.get("choices") or []
        if choices:
            content = str((choices[0].get("message") or {}).get("content") or "")

        return _parse_json_decision(content)

    async def _compress_context(
        self,
        messages: List[Dict[str, Any]],
        provider_manager,
    ) -> List[Dict[str, Any]]:
        """
        将历史对话压缩为摘要。

        策略：
        - 保留 system 消息不变
        - 保留最后一条 user 消息不压缩
        - 将中间所有消息拼成文本，让路由模型总结
        - 用"摘要 + 一条占位 assistant 消息"替换中间对话
        """
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        if len(non_system) <= 2:
            return messages

        last_user_idx = max(
            (i for i, m in enumerate(non_system) if m.get("role") == "user"),
            default=None,
        )
        if last_user_idx is None or last_user_idx == 0:
            return messages

        history_msgs = non_system[:last_user_idx]
        last_msg = non_system[last_user_idx]

        history_text = "\n".join(
            f"[{m.get('role', '?')}]: {_msg_text(m)}" for m in history_msgs
        )

        compress_messages = [
            {"role": "user", "content": self.compress_prompt.format(history=history_text)},
        ]

        provider_id, model_id = _parse_model(self.routing_model)
        response = await provider_manager.chat_completion(
            messages=compress_messages,
            model=model_id,
            provider_id=provider_id,
            max_tokens=512,
            temperature=0.3,
        )

        summary = ""
        choices = response.get("choices") or []
        if choices:
            summary = str((choices[0].get("message") or {}).get("content") or "")

        if not summary.strip():
            return messages

        compressed: List[Dict[str, Any]] = list(system_msgs)
        compressed.append({"role": "user", "content": f"[历史对话摘要]\n{summary.strip()}"})
        compressed.append({"role": "assistant", "content": "好的，我已了解之前的对话背景。"})
        compressed.append(last_msg)
        return compressed


# ── 模块级工具函数 ─────────────────────────────────────────────────────────────

def _parse_model(model_str: str) -> Tuple[str, str]:
    """解析 'provider/model' 字符串。"""
    if not model_str:
        return "", ""
    idx = model_str.find("/")
    if idx == -1:
        return model_str, model_str
    return model_str[:idx], model_str[idx + 1:]


def _get_available_models_str(provider_manager) -> str:
    """将 provider_manager 中的模型列表格式化为字符串，供路由提示词使用。"""
    if not provider_manager:
        return ""
    try:
        all_models = provider_manager.get_provider_models()
        lines = [f"- {pid}/{m}" for pid, models in all_models.items() for m in models]
        return "\n".join(lines)
    except Exception:
        return ""


def _extract_last_user_message(messages: List[Dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return _msg_text(m)
    return ""


def _msg_text(msg: Dict[str, Any], max_chars: int = 600) -> str:
    content = msg.get("content") or ""
    if isinstance(content, list):
        text = " ".join(
            p.get("text", "") for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    else:
        text = str(content)
    return text[:max_chars]


def _parse_json_decision(content: str) -> Optional[Dict[str, Any]]:
    """从模型回复中提取路由决策 JSON。"""
    if not content:
        return None

    # 直接解析
    try:
        data = json.loads(content.strip())
        if isinstance(data, dict) and "model" in data:
            return data
    except Exception:
        pass

    # 代码块包裹
    m = _JSON_BLOCK_RE.search(content)
    if m:
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict) and "model" in data:
                return data
        except Exception:
            pass

    # 内联 JSON
    m = _JSON_INLINE_RE.search(content)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict) and "model" in data:
                return data
        except Exception:
            pass

    return None


# ── 全局单例 ───────────────────────────────────────────────────────────────────

_bypass_router: Optional[BypassRouter] = None


def get_bypass_router() -> Optional[BypassRouter]:
    return _bypass_router


def set_bypass_router(instance: Optional[BypassRouter]) -> None:
    global _bypass_router
    _bypass_router = instance
