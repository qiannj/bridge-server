#!/usr/bin/env python3
"""
沙箱子进程宿主 (Sandbox Runner)
================================
此脚本在独立子进程中运行用户自定义路由器代码。
主进程通过 stdin/stdout 进行 JSON IPC 通信。

协议：
  stdin  ← JSON: {"router_dir": "...", "entrypoint": "...", "class": "...",
                   "config": {...}, "context": {...}}
  stdout → JSON: {"ok": true, "provider": "...", "model": "...",
                   "confidence": 0.9, "reason": "..."}
           or    {"ok": false, "error": "..."}

安全限制（Linux/macOS）：
  - 内存上限 128MB (RLIMIT_AS)
  - 禁止新增文件描述符 (RLIMIT_NOFILE → 10)
  - CPU 时间上限 2 秒 (RLIMIT_CPU)

Windows：上述 resource 限制不可用，依赖主进程的 asyncio 超时控制。
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import os
from pathlib import Path
from typing import Any, Dict, Optional

# ── 平台安全限制 ───────────────────────────────────────────────────────────────

def _apply_resource_limits() -> None:
    """在 Linux/macOS 上施加资源限制；Windows 上静默跳过。"""
    if sys.platform == "win32":
        return

    try:
        import resource

        # 内存上限 128 MB
        _MEM = 128 * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (_MEM, _MEM))
        except (ValueError, resource.error):
            # 某些系统不支持 RLIMIT_AS（如某些 macOS 版本），忽略
            pass

        # CPU 时间上限 2 秒（防止 CPU 密集型死循环）
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
        except (ValueError, resource.error):
            pass

        # 文件描述符上限 10（stdin/stdout/stderr + 少量余量，阻止 open()）
        # 注意：不能设为 0，否则无法读 stdin
        try:
            _cur_nofile, _max_nofile = resource.getrlimit(resource.RLIMIT_NOFILE)
            _safe_nofile = min(10, _cur_nofile)
            resource.setrlimit(resource.RLIMIT_NOFILE, (_safe_nofile, _safe_nofile))
        except (ValueError, resource.error):
            pass

    except ImportError:
        pass  # resource 模块不可用


def _sanitize_environment() -> None:
    """清除可能泄漏敏感信息的环境变量。"""
    sensitive_prefixes = (
        "DASHSCOPE_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY",
        "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "BRIDGE_",
        "AWS_", "AZURE_", "GCP_", "DATABASE_URL",
    )
    for key in list(os.environ.keys()):
        if any(key.upper().startswith(p) for p in sensitive_prefixes):
            del os.environ[key]


# ── 用户代码加载 ───────────────────────────────────────────────────────────────

def _load_router_class(router_dir: str, entrypoint: str, class_name: str) -> type:
    """从沙箱目录加载路由器类。"""
    ep_path = Path(router_dir) / entrypoint
    if not ep_path.exists():
        raise FileNotFoundError(f"入口文件不存在: {ep_path}")

    spec = importlib.util.spec_from_file_location(
        f"_sandbox_router_{ep_path.stem}", ep_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 '{ep_path}'")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    cls = getattr(mod, class_name, None)
    if cls is None:
        raise AttributeError(f"'{ep_path}' 中找不到类 '{class_name}'")
    return cls


# ── 路由执行 ───────────────────────────────────────────────────────────────────

async def _run_router(
    router_dir: str,
    entrypoint: str,
    class_name: str,
    config: Dict[str, Any],
    context_data: Dict[str, Any],
) -> Dict[str, Any]:
    """加载并执行路由器，返回决策结果字典。"""
    # 添加 router_dir 的父目录到 sys.path 以支持 from bridge_server.router_sdk import ...
    src_dir = str(Path(router_dir).parent.parent.parent)
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    # 也添加 router_dir 本身（支持路由器内部的相对 import）
    if router_dir not in sys.path:
        sys.path.insert(0, router_dir)

    # 重建 RoutingContext（仅允许安全字段）
    from bridge_server.router_sdk import (
        BaseRouter, RoutingContext, RoutingDecision,
        ModelInfo, ModelCapabilities, ModelMetrics,
    )

    models = []
    for m in context_data.get("models", []):
        caps_raw = m.get("capabilities", {})
        met_raw = m.get("metrics", {})
        models.append(ModelInfo(
            provider=str(m.get("provider", "")),
            model_id=str(m.get("model_id", "")),
            display_name=str(m.get("display_name", "")),
            health=str(m.get("health", "unknown")),
            input_cost_per_1k=float(m.get("input_cost_per_1k", 0.0)),
            output_cost_per_1k=float(m.get("output_cost_per_1k", 0.0)),
            capabilities=ModelCapabilities(
                coding=float(caps_raw.get("coding", 0.0)),
                reasoning=float(caps_raw.get("reasoning", 0.0)),
                creative=float(caps_raw.get("creative", 0.0)),
                tool_use=float(caps_raw.get("tool_use", 0.0)),
                context_length=int(caps_raw.get("context_length", 4096)),
            ),
            metrics=ModelMetrics(
                latency_p50_ms=float(met_raw.get("latency_p50_ms", 0.0)),
                latency_p99_ms=float(met_raw.get("latency_p99_ms", 0.0)),
                error_rate=float(met_raw.get("error_rate", 0.0)),
                is_rate_limited=bool(met_raw.get("is_rate_limited", False)),
            ),
            tags=list(m.get("tags", [])),
        ))

    ctx = RoutingContext(
        last_user_message=str(context_data.get("last_user_message", "")),
        messages_count=int(context_data.get("messages_count", 1)),
        models=models,
        session_metadata=dict(context_data.get("session_metadata", {})),
    )

    router_cls = _load_router_class(router_dir, entrypoint, class_name)
    if not (isinstance(router_cls, type) and issubclass(router_cls, BaseRouter)):
        raise TypeError(f"'{class_name}' 必须继承 BaseRouter")

    inst: BaseRouter = router_cls(config)
    if not inst.on_load():
        raise RuntimeError("on_load() 返回 False")

    decision: RoutingDecision = await inst.route(ctx)
    if not isinstance(decision, RoutingDecision):
        raise TypeError(f"route() 必须返回 RoutingDecision，实际返回: {type(decision)}")

    err = decision.validate(ctx)
    if err:
        raise ValueError(f"RoutingDecision 校验失败: {err}")

    return {
        "ok": True,
        "provider": decision.provider,
        "model": decision.model,
        "confidence": float(decision.confidence),
        "reason": str(decision.reason),
    }


# ── 主入口 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    # 先施加资源限制（在加载任何用户代码之前）
    _apply_resource_limits()
    _sanitize_environment()

    try:
        raw = sys.stdin.read()
        request = json.loads(raw)
    except Exception as e:
        sys.stdout.write(json.dumps({"ok": False, "error": f"无法解析请求: {e}"}))
        sys.stdout.flush()
        return

    try:
        result = asyncio.run(_run_router(
            router_dir=request["router_dir"],
            entrypoint=request["entrypoint"],
            class_name=request["class"],
            config=request.get("config", {}),
            context_data=request.get("context", {}),
        ))
    except Exception as e:
        result = {"ok": False, "error": str(e)}

    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
