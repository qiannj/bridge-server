#!/usr/bin/env python3
"""
模型路由核心 - v1.6.0 升级
支持 JS 沙箱自定义路由逻辑
"""

import re
import httpx
import logging
from typing import Tuple, Dict, List, Optional
import os

logger = logging.getLogger(__name__)

# 任务类型识别关键词
TASK_KEYWORDS = {
    "complex": ["推理", "证明", "推导", "复杂", "深入分析", "数学", "逻辑"],
    "coding": [
        "code",
        "python",
        "javascript",
        "函数",
        "编程",
        "写代码",
        "debug",
        "bug",
        "算法",
    ],
    "writing": ["写", "文章", "邮件", "报告", "文档", "文案", "润色", "改写"],
    "analysis": ["分析", "总结", "数据", "解释", "为什么", "如何", "对比", "评估"],
    "creative": ["创意", "故事", "头脑风暴", "想象", "设计", "诗歌", "小说"],
    "simple": ["你好", "hi", "hello", "谢谢", "再见", "在吗", "早上好", "晚上好"],
}


def detect_task_type(message: str) -> str:
    """
    根据消息内容识别任务类型
    """
    if not message:
        return "general"

    clean_message = re.sub(r"[^\w\s\u4e00-\u9fff]", "", message.lower())
    priority_order = ["complex", "coding", "writing", "analysis", "creative", "simple"]

    for task_type in priority_order:
        keywords = TASK_KEYWORDS.get(task_type, [])
        if any(kw in clean_message for kw in keywords):
            return task_type

    return "general"


def route_model(message: str, config: dict) -> Tuple[str, str, str]:
    """
    根据任务类型路由到合适的模型
    
    v1.6.0 升级：支持 JS 沙箱自定义路由
    
    Args:
        message: 用户消息
        config: 配置字典
    
    Returns:
        (selected_model, task_type, reason)
    """
    # 检查是否启用了自定义路由
    routing_config = config.get("routing", {})
    
    # 1. 优先使用 JS 沙箱自定义路由
    if routing_config.get("custom_routing_enabled", False):
        custom_route = execute_js_route(message, routing_config)
        if custom_route:
            logger.info(f"使用自定义路由 | model={custom_route['model']} | reason={custom_route['reason']}")
            return custom_route['model'], "custom", custom_route['reason']
    
    # 2. 使用默认路由策略
    task_type = detect_task_type(message)
    strategy = routing_config.get("strategy", "balanced")
    model_mapping = routing_config.get("model_mapping", {})
    
    if strategy == "custom" and model_mapping:
        model_id = model_mapping.get(task_type, model_mapping.get("general", "qwen3.5-plus"))
        reason = f"自定义路由：{task_type}"
    else:
        default_mapping = get_default_mapping(strategy)
        model_id = default_mapping.get(task_type, "qwen3.5-plus")
        reason = f"策略：{strategy}, 任务类型：{task_type}"
    
    full_model_id = find_full_model_id(model_id, config)
    
    logger.info(f"路由决策 | 任务类型={task_type} | 模型={full_model_id} | 策略={strategy}")
    
    return full_model_id, task_type, reason


def execute_js_route(message: str, routing_config: dict) -> Optional[Dict]:
    """
    执行 JS 沙箱路由代码
    
    Args:
        message: 用户消息
        routing_config: 路由配置
    
    Returns:
        路由结果字典或 None
    """
    user_code = routing_config.get("custom_route_code")
    if not user_code:
        return None
    
    try:
        from services.sandbox import execute_user_route
        
        context = {
            'message': message,
            'config': routing_config,
            'task_type': detect_task_type(message)
        }
        
        result = execute_user_route(user_code, context)
        
        if result.success and result.result:
            route_result = result.result
            if isinstance(route_result, dict) and 'model' in route_result:
                return {
                    'model': route_result.get('model', 'qwen3.5-plus'),
                    'reason': route_result.get('reason', '自定义路由')
                }
        else:
            logger.warning(f"沙箱执行失败：{result.error}")
        
        return None
        
    except Exception as e:
        logger.error(f"执行自定义路由失败：{e}")
        return None


def get_default_mapping(strategy: str) -> Dict[str, str]:
    """获取默认路由映射"""

    if strategy == "cost-first":
        return {
            "simple": "qwen3.5-flash",
            "coding": "qwen3.5-plus",
            "writing": "qwen3.5-flash",
            "analysis": "qwen3.5-flash",
            "creative": "qwen3.5-plus",
            "complex": "qwen3.5-plus",
            "general": "qwen3.5-flash",
        }
    elif strategy == "quality-first":
        return {
            "simple": "qwen3.5-plus",
            "coding": "qwen3-coder-plus",
            "writing": "qwen3.5-plus",
            "analysis": "qwen3-max",
            "creative": "kimi-k2.5",
            "complex": "qwen3-max",
            "general": "qwen3.5-plus",
        }
    else:  # balanced
        return {
            "simple": "qwen3.5-flash",
            "coding": "qwen3-coder-plus",
            "writing": "qwen3.5-plus",
            "analysis": "qwen3.5-plus",
            "creative": "kimi-k2.5",
            "complex": "qwen3-max",
            "general": "qwen3.5-plus",
        }


def find_full_model_id(model_name: str, config: dict) -> str:
    """
    查找模型的完整 ID（包含 provider 前缀）
    """
    providers = config.get("providers", [])
    
    # 兼容新格式（list）
    if isinstance(providers, list):
        for provider_config in providers:
            if not provider_config.get("enabled", True):  # 默认启用
                continue
            
            models = provider_config.get("models", [])
            if isinstance(models, list):
                for model in models:
                    model_id = model.get("id", "") if isinstance(model, dict) else str(model)
                    if model_id == model_name:
                        provider_name = provider_config.get("name", "unknown")
                        return f"{provider_name}/{model_id}"
            elif isinstance(models, dict):
                if model_name in models:
                    provider_name = provider_config.get("name", "unknown")
                    return f"{provider_name}/{model_name}"
    
    # 兼容旧格式（dict）
    elif isinstance(providers, dict):
        for provider_name, provider_config in providers.items():
            if not provider_config.get("enabled", False):
                continue
            
            models = provider_config.get("models", {})
            if model_name in models:
                return f"{provider_name}/{model_name}"
    
    return model_name


async def call_llm(
    model: str, messages: list, config: dict, timeout: int = 120
) -> dict:
    """
    调用 LLM API
    """
    import time
    from services.usage import get_tracker

    start_time = time.time()

    # 解析模型 ID
    if "/" in model:
        provider, model_name = model.split("/", 1)
    else:
        provider = None
        model_name = model
    
    # 查找 provider 配置（支持 list 和 dict）
    providers = config.get("providers", [])
    provider_config = None
    
    if isinstance(providers, list):
        # 新格式：list
        for p in providers:
            p_name = p.get("name", "")
            if provider:
                if p_name == provider:
                    provider_config = p
                    break
            else:
                # 没有指定 provider，查找模型
                models = p.get("models", [])
                if isinstance(models, list):
                    for m in models:
                        m_id = m.get("id", "") if isinstance(m, dict) else str(m)
                        if m_id == model_name:
                            provider_config = p
                            provider = p_name
                            break
                if provider_config:
                    break
    elif isinstance(providers, dict):
        # 旧格式：dict
        provider_config = providers.get(provider, {})
    
    if not provider_config:
        raise ValueError(f"Provider '{provider}' 或模型 '{model_name}' 未找到")

    # 获取 API Key
    api_key = provider_config.get("api_key", "")
    if "api_key_env" in provider_config:
        env_var = provider_config["api_key_env"]
        api_key = os.getenv(env_var)
        if not api_key:
            raise ValueError(f"环境变量 {env_var} 未设置")

    if not api_key:
        raise ValueError(f"Provider '{provider}' 缺少 API Key")

    base_url = provider_config.get("base_url", "")

    masked_key = api_key[:8] + "***" if len(api_key) > 8 else "***"
    logger.info(f"调用 LLM | provider={provider} | model={model_name} | key={masked_key}")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model_name, "messages": messages}

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url}/chat/completions", json=payload, headers=headers
        )

        duration_ms = int((time.time() - start_time) * 1000)

        try:
            response_data = response.json()
            usage_info = response_data.get("usage", {})
            tokens_in = usage_info.get("prompt_tokens", 0)
            tokens_out = usage_info.get("completion_tokens", 0)
            total_tokens = tokens_in + tokens_out

            cost = get_tracker().get_cost_estimate(model_name, total_tokens)

            from services.usage import record_usage
            record_usage(model_name, provider, tokens_in, tokens_out, cost, duration_ms)

            logger.info(f"API 调用完成 | tokens={total_tokens} | cost=¥{cost:.4f} | duration={duration_ms}ms")

            return response_data
        except Exception as e:
            logger.warning(f"记录用量失败：{e}")
            return response.json()
