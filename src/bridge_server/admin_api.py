#!/usr/bin/env python3
"""Admin Panel API - Bridge Server web UI backend."""

import json
import os
import re as _re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import yaml
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bridge_server.auth import _HASHED_FORMAT_MARKER, _HASHED_FORMAT_VALUE, _hash_token

GITHUB_REPO = "qiannj/bridge-server"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
CURRENT_VERSION = "2.0.0"
OPENAI_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"


def _get_config_dir() -> Path:
    for env in ("BRIDGE_SERVER_CONFIG_DIR", "BRIDGE_CONFIG_DIR"):
        v = os.getenv(env)
        if v:
            return Path(v)
    return Path.home() / ".bridge-server"


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_yaml(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)


def _resolve_provider_base_url(provider: dict) -> str:
    base_url = str(provider.get("base_url", "") or "")
    oauth_cfg = provider.get("oauth") or {}
    if oauth_cfg.get("provider") == "openai_codex":
        if not base_url or base_url.rstrip("/") == "https://api.openai.com/v1":
            return str(oauth_cfg.get("base_url") or OPENAI_CODEX_BASE_URL)
    return base_url


def _resolve_oauth_config(provider: dict) -> dict:
    oauth_cfg = dict(provider.get("oauth") or {})
    if oauth_cfg.get("provider") == "openai_codex" and not oauth_cfg.get("auth_store_key"):
        oauth_cfg["auth_store_key"] = provider.get("name") or "openai"
    return oauth_cfg


# ── Panel token management ──────────────────────────────────────────────────

def get_panel_token() -> Optional[str]:
    auth = _load_yaml(_get_config_dir() / "auth.yaml")
    return auth.get("panel_token")


def generate_panel_token() -> str:
    token = "pt-" + secrets.token_hex(24)
    auth_file = _get_config_dir() / "auth.yaml"
    auth = _load_yaml(auth_file)
    auth["panel_token"] = token
    _save_yaml(auth_file, auth)
    return token


def _tokens_file() -> Path:
    return _get_config_dir() / "tokens.json"


def _load_tokens() -> Dict[str, Any]:
    path = _tokens_file()
    if not path.exists():
        return {_HASHED_FORMAT_MARKER: _HASHED_FORMAT_VALUE}
    with open(path, encoding="utf-8") as f:
        data = json.load(f) or {}
    if data.get(_HASHED_FORMAT_MARKER) != _HASHED_FORMAT_VALUE:
        migrated: Dict[str, Any] = {_HASHED_FORMAT_MARKER: _HASHED_FORMAT_VALUE}
        for key, value in data.items():
            if not str(key).startswith("_"):
                migrated[_hash_token(str(key))] = value
        return migrated
    return data


def _save_tokens(data: Dict[str, Any]) -> None:
    data[_HASHED_FORMAT_MARKER] = _HASHED_FORMAT_VALUE
    path = _tokens_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    try:
        import bridge_server.auth as auth_module
        if auth_module.auth_manager is not None:
            auth_module.auth_manager.clear_cache()
    except Exception:
        pass


def _parse_expires_at(value: Optional[float] = None, iso_value: Optional[str] = None) -> Optional[float]:
    if value is not None:
        return float(value)
    if not iso_value:
        return None
    text = iso_value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).timestamp()


def _api_key_response(key_hash: str, info: Dict[str, Any]) -> Dict[str, Any]:
    expires_at = info.get("expires_at")
    return {
        "id": key_hash[:16],
        "name": info.get("name") or info.get("user_id") or "External API Key",
        "key_preview": info.get("key_preview", "sk-****"),
        "model_permissions": info.get("model_permissions") or ["*"],
        "expires_at": expires_at,
        "expires_at_iso": datetime.fromtimestamp(expires_at).isoformat() if expires_at else None,
        "active": bool(info.get("active", True)),
        "created_at": info.get("created_at"),
        "updated_at": info.get("updated_at"),
    }


def list_external_api_keys() -> List[Dict[str, Any]]:
    tokens = _load_tokens()
    keys = []
    for key_hash, info in tokens.items():
        if str(key_hash).startswith("_") or not isinstance(info, dict):
            continue
        if info.get("type") == "external_api_key":
            keys.append(_api_key_response(key_hash, info))
    return sorted(keys, key=lambda item: item.get("created_at") or 0, reverse=True)


def create_external_api_key(
    *,
    name: str,
    model_permissions: Optional[List[str]] = None,
    expires_at: Optional[float] = None,
) -> Dict[str, Any]:
    token = "sk-" + secrets.token_hex(32)
    token_hash = _hash_token(token)
    now = time.time()
    permissions = [p.strip() for p in (model_permissions or ["*"]) if str(p).strip()]
    if not permissions:
        permissions = ["*"]

    tokens = _load_tokens()
    info = {
        "type": "external_api_key",
        "user_id": f"api-key:{name}",
        "name": name,
        "key_preview": token[:8] + "..." + token[-4:],
        "model_permissions": permissions,
        "expires_at": expires_at,
        "active": True,
        "created_at": now,
        "updated_at": now,
    }
    tokens[token_hash] = info
    _save_tokens(tokens)
    return {"token": token, **_api_key_response(token_hash, info)}


def update_external_api_key(
    key_id: str,
    *,
    name: Optional[str] = None,
    model_permissions: Optional[List[str]] = None,
    expires_at: Any = ...,
    active: Optional[bool] = None,
) -> Dict[str, Any]:
    tokens = _load_tokens()
    matches = [
        key_hash for key_hash, info in tokens.items()
        if not str(key_hash).startswith("_")
        and str(key_hash).startswith(key_id)
        and isinstance(info, dict)
        and info.get("type") == "external_api_key"
    ]
    if not matches:
        raise KeyError(key_id)
    if len(matches) > 1:
        raise ValueError("API Key ID 不唯一，请使用更长的 ID")

    key_hash = matches[0]
    info = tokens[key_hash]
    if name is not None:
        info["name"] = name
        info["user_id"] = f"api-key:{name}"
    if model_permissions is not None:
        permissions = [p.strip() for p in model_permissions if str(p).strip()]
        info["model_permissions"] = permissions or ["*"]
    if expires_at is not ...:
        info["expires_at"] = expires_at
    if active is not None:
        info["active"] = active
    info["updated_at"] = time.time()
    tokens[key_hash] = info
    _save_tokens(tokens)
    return _api_key_response(key_hash, info)


def delete_external_api_key(key_id: str) -> None:
    update_external_api_key(key_id, active=False)


async def require_panel_auth(
    x_panel_token: Optional[str] = Header(None),
):
    t = x_panel_token
    stored = get_panel_token()
    if not t or not stored or not secrets.compare_digest(t, stored):
        raise HTTPException(status_code=401, detail="无效的 Panel Token")


# ── Router ──────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/admin", tags=["admin"])
_deps = [Depends(require_panel_auth)]


# ── Auth ─────────────────────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    token: str


class ExternalApiKeyCreateRequest(BaseModel):
    name: str
    model_permissions: List[str] = Field(default_factory=lambda: ["*"])
    expires_at: Optional[float] = None
    expires_at_iso: Optional[str] = None


class ExternalApiKeyUpdateRequest(BaseModel):
    name: Optional[str] = None
    model_permissions: Optional[List[str]] = None
    expires_at: Optional[float] = None
    expires_at_iso: Optional[str] = None
    clear_expires_at: bool = False
    active: Optional[bool] = None


@router.post("/auth/verify", dependencies=[])
async def verify_token(req: TokenRequest):
    """Verify panel token (no auth required - this IS the auth endpoint)."""
    stored = get_panel_token()
    if not stored:
        raise HTTPException(status_code=503, detail="Panel token 未配置，请运行 bridge-server panel-token")
    if secrets.compare_digest(req.token, stored):
        return {"ok": True}
    raise HTTPException(status_code=401, detail="Token 无效")


@router.get("/api-keys", dependencies=_deps)
async def get_api_keys():
    """List external API keys without exposing plaintext secrets."""
    return {"api_keys": list_external_api_keys()}


@router.post("/api-keys", dependencies=_deps)
async def add_api_key(req: ExternalApiKeyCreateRequest):
    """Create an external API key. Plaintext token is returned once."""
    expires_at = _parse_expires_at(req.expires_at, req.expires_at_iso)
    created = create_external_api_key(
        name=req.name,
        model_permissions=req.model_permissions,
        expires_at=expires_at,
    )
    return {"ok": True, "api_key": created}


@router.put("/api-keys/{key_id}", dependencies=_deps)
async def edit_api_key(key_id: str, req: ExternalApiKeyUpdateRequest):
    """Update external API key metadata and permissions."""
    try:
        expires_marker: Any = ...
        if req.clear_expires_at:
            expires_marker = None
        elif req.expires_at is not None or req.expires_at_iso:
            expires_marker = _parse_expires_at(req.expires_at, req.expires_at_iso)

        updated = update_external_api_key(
            key_id,
            name=req.name,
            model_permissions=req.model_permissions,
            expires_at=expires_marker,
            active=req.active,
        )
        return {"ok": True, "api_key": updated}
    except KeyError:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/api-keys/{key_id}", dependencies=_deps)
async def remove_api_key(key_id: str):
    """Deactivate an external API key."""
    try:
        delete_external_api_key(key_id)
        return {"ok": True}
    except KeyError:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status", dependencies=_deps)
async def get_status():
    """Server status + provider health."""
    try:
        import httpx as _httpx
        config = _load_yaml(_get_config_dir() / "config.yaml")
        port = config.get("server", {}).get("port", 19377)
        async with _httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"http://localhost:{port}/health")
            return resp.json()
    except Exception as e:
        return {"status": "unknown", "error": str(e)}


# ── Config ────────────────────────────────────────────────────────────────────

@router.get("/config", dependencies=_deps)
async def get_config():
    """Return full config (with API keys masked)."""
    config = _load_yaml(_get_config_dir() / "config.yaml")
    # Mask sensitive credentials
    for p in config.get("providers", []):
        if "api_key" in p:
            key = p["api_key"]
            p["api_key"] = key[:8] + "****" + key[-4:] if len(key) > 12 else "****"
        # Mask OAuth client_secret
        oauth = p.get("oauth")
        if oauth and "client_secret" in oauth:
            s = oauth["client_secret"]
            oauth["client_secret"] = s[:4] + "****" if len(s) > 4 else "****"
    return config


class ModelConfig(BaseModel):
    id: str
    name: Optional[str] = None
    input_cost: float = 0.0   # ¥ per 1K input tokens
    output_cost: float = 0.0  # ¥ per 1K output tokens


def _model_config_to_dict(m: ModelConfig) -> dict:
    d: dict = {"id": m.id, "name": m.name or m.id}
    if m.input_cost:
        d["input_cost"] = m.input_cost
    if m.output_cost:
        d["output_cost"] = m.output_cost
    return d


class OAuthConfig(BaseModel):
    token_url: str
    client_id: str
    client_secret: str
    scope: Optional[str] = None
    grant_type: str = "client_credentials"


class ProviderAddRequest(BaseModel):
    name: str
    base_url: str
    # api_key auth
    api_key: Optional[str] = None
    # oauth auth
    auth_type: str = "api_key"  # "api_key" | "oauth"
    oauth: Optional[OAuthConfig] = None
    models: List[ModelConfig]


@router.post("/providers", dependencies=_deps)
async def add_provider(req: ProviderAddRequest):
    config_file = _get_config_dir() / "config.yaml"
    config = _load_yaml(config_file)
    providers = config.get("providers", [])
    # Check duplicate
    if any(p.get("name") == req.name for p in providers):
        raise HTTPException(status_code=409, detail=f"Provider '{req.name}' 已存在")

    if req.auth_type == "oauth":
        if not req.oauth:
            raise HTTPException(status_code=422, detail="OAuth 模式需要提供 oauth 配置")
        entry = {
            "name": req.name,
            "base_url": req.base_url,
            "auth_type": "oauth",
            "oauth": req.oauth.model_dump(exclude_none=True),
            "models": [_model_config_to_dict(m) for m in req.models],
        }
    else:
        if not req.api_key:
            raise HTTPException(status_code=422, detail="API Key 模式需要提供 api_key")
        env_var = req.name.upper().replace("-", "_") + "_API_KEY"
        entry = {
            "name": req.name,
            "base_url": req.base_url,
            "api_key_env": env_var,
            "api_key": req.api_key,
            "models": [_model_config_to_dict(m) for m in req.models],
        }
        # Save to .env
        env_file = _get_config_dir() / ".env"
        env_lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
        env_lines = [l for l in env_lines if not l.startswith(f"{env_var}=")]
        env_lines.append(f"{env_var}={req.api_key}")
        env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    providers.append(entry)
    config["providers"] = providers
    _save_yaml(config_file, config)
    return {"ok": True, "name": req.name}


@router.delete("/providers/{name}", dependencies=_deps)
async def delete_provider(name: str):
    config_file = _get_config_dir() / "config.yaml"
    config = _load_yaml(config_file)
    providers = config.get("providers", [])
    new_providers = [p for p in providers if p.get("name") != name]
    if len(new_providers) == len(providers):
        raise HTTPException(status_code=404, detail=f"Provider '{name}' 不存在")
    config["providers"] = new_providers
    _save_yaml(config_file, config)
    return {"ok": True}


class ProviderUpdateRequest(BaseModel):
    api_key: Optional[str] = None
    oauth: Optional[OAuthConfig] = None
    models: Optional[List[ModelConfig]] = None


@router.put("/providers/{name}", dependencies=_deps)
async def update_provider(name: str, req: ProviderUpdateRequest):
    config_file = _get_config_dir() / "config.yaml"
    config = _load_yaml(config_file)
    providers = config.get("providers", [])
    found = False
    for p in providers:
        if p.get("name") == name:
            found = True
            # Update API key (api_key mode)
            if req.api_key:
                p["api_key"] = req.api_key
                env_var = p.get("api_key_env", name.upper().replace("-", "_") + "_API_KEY")
                env_file = _get_config_dir() / ".env"
                env_lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
                env_lines = [l for l in env_lines if not l.startswith(f"{env_var}=")]
                env_lines.append(f"{env_var}={req.api_key}")
                env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
            # Update OAuth config (oauth mode)
            if req.oauth:
                p["auth_type"] = "oauth"
                existing = p.get("oauth") or {}
                updated = req.oauth.model_dump(exclude_none=True)
                # Preserve existing client_secret if placeholder is passed (****) 
                if updated.get("client_secret", "").endswith("****"):
                    updated.pop("client_secret", None)
                existing.update(updated)
                p["oauth"] = existing
            # Update models
            if req.models is not None:
                p["models"] = [_model_config_to_dict(m) for m in req.models]
            break
    if not found:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' 不存在")
    config["providers"] = providers
    _save_yaml(config_file, config)
    return {"ok": True}


# Default patterns (mirrored from router.py for seeding new scenarios)
_SCENARIO_DEFAULT_PATTERNS: Dict[str, List[str]] = {
    'coding': [
        r'代码|编程|函数|debug|bug|算法|程序|脚本|API|接口|实现|报错|错误|exception|syntax',
        r'code|python|javascript|typescript|java|golang|cpp|rust|programming|function|debug|algorithm|script',
    ],
    'writing': [
        r'写|文章|邮件|报告|文档|文案|润色|改写|撰写|起草|文稿|作文|创作',
        r'write|article|email|report|document|essay|draft|rewrite|proofread|compose',
    ],
    'search': [
        r'搜索|查找|查询|检索|找一下|查一下|哪里有|在哪|怎么找|有没有',
        r'search|find|lookup|query|retrieve|where is|how to find|locate',
    ],
    'summary': [
        r'总结|摘要|归纳|概括|提炼|压缩|简化|要点|精华|缩写',
        r'summarize|summary|abstract|condense|brief|key points|tldr|recap',
    ],
    'translation': [
        r'翻译|译成|译为|中译英|英译中|用.*语说|怎么说|转换语言|多语言',
        r'translate|translation|in english|in chinese|in japanese|how do you say|language',
    ],
    'chat': [
        r'你好|hi|hello|谢谢|再见|在吗|聊天|说说|讲讲|介绍一下|是什么|怎么样',
        r'hello|hi|hey|thanks|bye|chat|tell me|what is|who is|explain|how are you',
    ],
}


def _enrich_scenario(name: str, cfg: Any) -> Dict:
    """Ensure a scenario dict has all required fields, filling in defaults."""
    if not isinstance(cfg, dict):
        cfg = {"model": str(cfg)}
    patterns = cfg.get("patterns") or _SCENARIO_DEFAULT_PATTERNS.get(name, [])
    return {
        "enabled": cfg.get("enabled", True),
        "model": cfg.get("model", ""),
        "patterns": patterns,
        "exclude_patterns": cfg.get("exclude_patterns", []),
        "priority": cfg.get("priority", 0),
    }


@router.get("/routing", dependencies=_deps)
async def get_routing():
    config = _load_yaml(_get_config_dir() / "config.yaml")
    strategy = config.get("routing", {}).get("strategy", "fallback")
    raw = config.get("scenarios", {})
    scenarios = {k: _enrich_scenario(k, v) for k, v in raw.items()}
    return {"strategy": strategy, "scenarios": scenarios}


class ScenarioConfig(BaseModel):
    enabled: bool = True
    model: str = ""
    patterns: List[str] = []
    exclude_patterns: List[str] = []  # Skip this scenario if any of these match
    priority: int = 0                 # Higher priority wins when multiple scenarios match


class RoutingUpdateRequest(BaseModel):
    strategy: Optional[str] = None
    scenarios: Optional[Dict[str, ScenarioConfig]] = None


@router.put("/routing", dependencies=_deps)
async def update_routing(req: RoutingUpdateRequest):
    config_file = _get_config_dir() / "config.yaml"
    config = _load_yaml(config_file)
    if req.strategy:
        if "routing" not in config:
            config["routing"] = {}
        config["routing"]["strategy"] = req.strategy
    if req.scenarios is not None:
        config["scenarios"] = {
            k: {
                "enabled": v.enabled,
                "model": v.model,
                "patterns": v.patterns,
                "exclude_patterns": v.exclude_patterns,
                "priority": v.priority,
            }
            for k, v in req.scenarios.items()
        }
    _save_yaml(config_file, config)
    # Hot-reload the running router
    try:
        from bridge_server import runtime as _rt
        if _rt.smart_router is not None:
            _rt.smart_router.reload(config.get("scenarios", {}))
    except Exception:
        pass
    return {"ok": True}


@router.patch("/routing/scenarios/{name}", dependencies=_deps)
async def patch_scenario(name: str, req: ScenarioConfig):
    """Update a single scenario's model/enabled state without touching others."""
    config_file = _get_config_dir() / "config.yaml"
    config = _load_yaml(config_file)
    scenarios = config.setdefault("scenarios", {})
    existing = scenarios.get(name, {})
    if not isinstance(existing, dict):
        existing = {"model": str(existing)}
    if req.model:
        existing["model"] = req.model
    existing["enabled"] = req.enabled
    if req.patterns:  # Only overwrite patterns when explicitly provided
        existing["patterns"] = req.patterns
    if req.exclude_patterns is not None:
        existing["exclude_patterns"] = req.exclude_patterns
    existing["priority"] = req.priority
    scenarios[name] = existing
    config["scenarios"] = scenarios
    _save_yaml(config_file, config)
    try:
        from bridge_server import runtime as _rt
        if _rt.smart_router is not None:
            _rt.smart_router.reload(config.get("scenarios", {}))
    except Exception:
        pass
    return {"ok": True, "name": name}


@router.post("/reload", dependencies=_deps)
async def reload_config():
    """Hot-reload config.yaml into the running server without restarting."""
    config = _load_yaml(_get_config_dir() / "config.yaml")
    reloaded = []
    try:
        from bridge_server import runtime as _rt
        if _rt.smart_router is not None:
            _rt.smart_router.reload(config.get("scenarios", {}))
            reloaded.append("router")
    except Exception:
        pass
    return {"ok": True, "reloaded": reloaded}


# ── 旁路模型路由器配置 ─────────────────────────────────────────────────────────

class BypassRouterConfig(BaseModel):
    enabled: bool = False
    routing_model: str = ""
    routing_rules: str = "根据任务类型选择最合适的模型"
    routing_prompt: Optional[str] = None
    compress_prompt: Optional[str] = None
    timeout_ms: int = 3000
    compress_context_threshold: int = 10


@router.get("/bypass-router", dependencies=_deps)
async def get_bypass_router_config():
    """获取旁路模型路由器配置。"""
    config = _load_yaml(_get_config_dir() / "config.yaml")
    defaults: Dict[str, Any] = {
        "enabled": False,
        "routing_model": "",
        "routing_rules": "根据任务类型选择最合适的模型",
        "timeout_ms": 3000,
        "compress_context_threshold": 10,
    }
    return {**defaults, **config.get("bypass_router", {})}


@router.put("/bypass-router", dependencies=_deps)
async def update_bypass_router_config(req: BypassRouterConfig):
    """更新旁路模型路由器配置并热重载。"""
    config_file = _get_config_dir() / "config.yaml"
    config = _load_yaml(config_file)
    new_cfg: Dict[str, Any] = {
        "enabled": req.enabled,
        "routing_model": req.routing_model,
        "routing_rules": req.routing_rules,
        "timeout_ms": req.timeout_ms,
        "compress_context_threshold": req.compress_context_threshold,
    }
    if req.routing_prompt:
        new_cfg["routing_prompt"] = req.routing_prompt
    if req.compress_prompt:
        new_cfg["compress_prompt"] = req.compress_prompt
    config["bypass_router"] = new_cfg
    _save_yaml(config_file, config)
    # 热重载
    try:
        from bridge_server.services.bypass_router import BypassRouter as _BR
        from bridge_server.services.bypass_router import get_bypass_router as _get_br
        from bridge_server.services.bypass_router import set_bypass_router as _set_br
        existing = _get_br()
        if existing is not None:
            existing.reload(new_cfg)
        else:
            _set_br(_BR(new_cfg))
    except Exception:
        pass
    return {"ok": True}


class BypassRouterTestRequest(BaseModel):
    messages: List[Dict[str, Any]] = Field(
        default=[{"role": "user", "content": "帮我写一个 Python 快速排序算法"}]
    )


@router.post("/bypass-router/test", dependencies=_deps)
async def test_bypass_router(req: BypassRouterTestRequest):
    """使用当前配置对给定消息执行一次旁路路由测试。"""
    try:
        from bridge_server import runtime as _rt
        from bridge_server.services.bypass_router import get_bypass_router as _get_br
        br = _get_br()
        if br is None:
            return {"ok": False, "error": "旁路路由器未初始化"}
        if not br.enabled:
            return {"ok": False, "error": "旁路路由器未启用，请先在配置中开启"}
        if _rt.provider_manager is None:
            return {"ok": False, "error": "ProviderManager 未初始化"}
        result, compressed_msgs = await br.route(req.messages, _rt.provider_manager)
        if result is None:
            return {"ok": False, "error": "路由决策失败（模型未响应或响应格式无效）"}
        return {
            "ok": True,
            "selected_model": f"{result.provider_id}/{result.model}",
            "reason": result.reason,
            "context_compressed": len(compressed_msgs) < len(req.messages),
            "original_message_count": len(req.messages),
            "compressed_message_count": len(compressed_msgs),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Usage ─────────────────────────────────────────────────────────────────────

def _query_usage(period: str = "today") -> Dict[str, Any]:
    db_path = _get_config_dir() / "usage.db"
    if not db_path.exists():
        return {"records": [], "summary": {}}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        now = datetime.now()
        if period == "today":
            # Start from midnight of today — not rolling 24h window
            since = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        elif period == "week":
            since = time.time() - 7 * 86400
        elif period == "month":
            since = time.time() - 30 * 86400
        else:
            since = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        rows = conn.execute(
            "SELECT * FROM usage_records WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT 500",
            (since,)
        ).fetchall()
        records = [dict(r) for r in rows]
        # Summary
        summary = {"total_requests": len(records), "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        by_model: Dict[str, Dict] = {}
        daily: Dict[str, Dict] = {}
        for r in records:
            summary["prompt_tokens"] += r.get("prompt_tokens") or 0
            summary["completion_tokens"] += r.get("completion_tokens") or 0
            summary["total_tokens"] += r.get("total_tokens") or 0
            model = r.get("model", "unknown")
            by_model.setdefault(model, {"requests": 0, "tokens": 0})
            by_model[model]["requests"] += 1
            by_model[model]["tokens"] += r.get("total_tokens") or 0
            day = datetime.fromtimestamp(r["timestamp"]).strftime("%Y-%m-%d")
            daily.setdefault(day, {"requests": 0, "tokens": 0})
            daily[day]["requests"] += 1
            daily[day]["tokens"] += r.get("total_tokens") or 0
        return {"records": records[:50], "summary": summary, "by_model": by_model, "daily": daily}
    finally:
        conn.close()


@router.get("/usage", dependencies=_deps)
async def get_usage(period: str = Query("today")):
    return _query_usage(period)


# ── Savings ───────────────────────────────────────────────────────────────────

def _empty_savings_payload(days: int) -> Dict[str, Any]:
    return {
        "period_days": days,
        "summary": {
            "total_requests": 0,
            "covered_requests": 0,
            "uncovered_requests": 0,
            "actual_cost_rmb": 0.0,
            "baseline_cost_rmb": 0.0,
            "savings_rmb": 0.0,
            "savings_rate": 0.0,
        },
        "by_model": {},
        "by_task_type": {},
        "daily": {},
        "records": [],
    }


def _normalize_savings_config(raw: Optional[dict]) -> Dict[str, Any]:
    savings = raw or {}
    baseline = savings.get("baseline") or {}
    scenarios = baseline.get("scenarios") or {}

    normalized_scenarios = {}
    if isinstance(scenarios, dict):
        for task_type, model_ref in scenarios.items():
            task_key = str(task_type or "").strip()
            model_value = str(model_ref or "").strip()
            if task_key and model_value:
                normalized_scenarios[task_key] = model_value

    return {
        "enabled": bool(savings.get("enabled", False)),
        "baseline": {
            "default_model": str(baseline.get("default_model") or "").strip(),
            "scenarios": normalized_scenarios,
        },
    }


def _query_savings(days: int = 1) -> Dict[str, Any]:
    db_path = _get_config_dir() / "usage.db"
    if not db_path.exists():
        return _empty_savings_payload(days)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        since = time.time() - days * 86400
        rows = conn.execute(
            "SELECT * FROM usage_records WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT 500",
            (since,),
        ).fetchall()
        if not rows:
            return _empty_savings_payload(days)

        records = [dict(r) for r in rows]
        summary = {
            "total_requests": len(records),
            "covered_requests": 0,
            "uncovered_requests": 0,
            "actual_cost_rmb": 0.0,
            "baseline_cost_rmb": 0.0,
            "savings_rmb": 0.0,
            "savings_rate": 0.0,
        }
        by_model: Dict[str, Dict[str, Any]] = {}
        by_task_type: Dict[str, Dict[str, Any]] = {}
        daily: Dict[str, Dict[str, Any]] = {}

        def _bucket(target: Dict[str, Dict[str, Any]], key: str) -> Dict[str, Any]:
            target.setdefault(
                key,
                {
                    "requests": 0,
                    "covered_requests": 0,
                    "actual_cost_rmb": 0.0,
                    "baseline_cost_rmb": 0.0,
                    "savings_rmb": 0.0,
                },
            )
            return target[key]

        for record in records:
            actual_cost_rmb = float(record.get("cost_rmb") or ((record.get("cost_usd") or 0.0) * 7.2))
            baseline_cost_rmb = float(record.get("baseline_cost_rmb") or 0.0)
            savings_rmb = float(record.get("savings_rmb") or 0.0)
            is_covered = bool(record.get("baseline_model")) and baseline_cost_rmb > 0

            summary["actual_cost_rmb"] += actual_cost_rmb
            summary["baseline_cost_rmb"] += baseline_cost_rmb
            summary["savings_rmb"] += savings_rmb
            if is_covered:
                summary["covered_requests"] += 1
            else:
                summary["uncovered_requests"] += 1

            model_bucket = _bucket(by_model, record.get("model") or "unknown")
            task_bucket = _bucket(by_task_type, record.get("task_type") or "general")
            day_bucket = _bucket(
                daily,
                datetime.fromtimestamp(record["timestamp"]).strftime("%Y-%m-%d"),
            )

            for bucket in (model_bucket, task_bucket, day_bucket):
                bucket["requests"] += 1
                bucket["actual_cost_rmb"] += actual_cost_rmb
                bucket["baseline_cost_rmb"] += baseline_cost_rmb
                bucket["savings_rmb"] += savings_rmb
                if is_covered:
                    bucket["covered_requests"] += 1

        if summary["baseline_cost_rmb"] > 0:
            summary["savings_rate"] = summary["savings_rmb"] / summary["baseline_cost_rmb"]

        sorted_daily = {key: daily[key] for key in sorted(daily)}
        return {
            "period_days": days,
            "summary": summary,
            "by_model": by_model,
            "by_task_type": by_task_type,
            "daily": sorted_daily,
            "records": records[:50],
        }
    finally:
        conn.close()


class SavingsBaselineConfig(BaseModel):
    default_model: str = ""
    scenarios: Dict[str, str] = Field(default_factory=dict)


class SavingsConfigUpdateRequest(BaseModel):
    enabled: bool = False
    baseline: SavingsBaselineConfig = Field(default_factory=SavingsBaselineConfig)


@router.get("/savings", dependencies=_deps)
async def get_savings(period: str = Query("today")):
    days = {"today": 1, "week": 7, "month": 30}.get(period, 1)
    return _query_savings(days)


@router.get("/savings/config", dependencies=_deps)
async def get_savings_config():
    config = _load_yaml(_get_config_dir() / "config.yaml")
    return _normalize_savings_config(config.get("savings"))


@router.put("/savings/config", dependencies=_deps)
async def update_savings_config(req: SavingsConfigUpdateRequest):
    config_file = _get_config_dir() / "config.yaml"
    config = _load_yaml(config_file)
    normalized = _normalize_savings_config(req.model_dump())
    config["savings"] = normalized
    _save_yaml(config_file, config)

    try:
        import importlib
        import sys

        _rt = sys.modules.get("bridge_server.runtime")
        if _rt is None:
            _rt = importlib.import_module("bridge_server.runtime")

        if not isinstance(getattr(_rt, "runtime_config", None), dict):
            _rt.runtime_config = {}
        _rt.runtime_config["savings"] = normalized
    except Exception:
        pass

    return {"ok": True, "config": normalized}


@router.get("/savings/overview", dependencies=_deps)
async def get_savings_overview():
    """老板视角：核心 KPI + 30 天趋势图数据。"""
    data_30d = _query_savings(30)
    data_7d  = _query_savings(7)
    data_1d  = _query_savings(1)

    config = _load_yaml(_get_config_dir() / "config.yaml")
    savings_cfg = _normalize_savings_config(config.get("savings"))

    # 30-day trend array for chart
    trend: List[Dict[str, Any]] = []
    for date_str in sorted(data_30d["daily"].keys()):
        b = data_30d["daily"][date_str]
        trend.append({
            "date": date_str,
            "savings_rmb":      round(float(b.get("savings_rmb", 0)), 4),
            "actual_cost_rmb":  round(float(b.get("actual_cost_rmb", 0)), 4),
            "baseline_cost_rmb": round(float(b.get("baseline_cost_rmb", 0)), 4),
            "requests":         int(b.get("requests", 0)),
        })

    # Top model by savings
    by_model = data_30d.get("by_model") or {}
    top_model = max(by_model, key=lambda k: by_model[k].get("savings_rmb", 0), default=None) if by_model else None

    def _kpis(s: Dict) -> Dict:
        return {
            "savings_rmb":      round(float(s.get("savings_rmb", 0)), 4),
            "actual_cost_rmb":  round(float(s.get("actual_cost_rmb", 0)), 4),
            "baseline_cost_rmb": round(float(s.get("baseline_cost_rmb", 0)), 4),
            "savings_rate":     round(float(s.get("savings_rate", 0)), 4),
            "total_requests":   int(s.get("total_requests", 0)),
            "covered_requests": int(s.get("covered_requests", 0)),
        }

    return {
        "savings_enabled": savings_cfg["enabled"],
        "baseline_model":  savings_cfg["baseline"]["default_model"],
        "kpis": {
            "today": _kpis(data_1d["summary"]),
            "week":  _kpis(data_7d["summary"]),
            "month": _kpis(data_30d["summary"]),
        },
        "trend_30d":       trend,
        "top_saving_model": top_model,
        "by_task_type_30d": data_30d.get("by_task_type") or {},
        "by_model_30d":     by_model,
    }


# ── Updates ───────────────────────────────────────────────────────────────────

@router.get("/updates", dependencies=_deps)
async def check_updates():
    try:
        ssl_verify = os.getenv("BRIDGE_DISABLE_SSL_VERIFY") != "1"
        async with httpx.AsyncClient(timeout=8.0, verify=ssl_verify) as client:
            try:
                resp = await client.get(GITHUB_API)
            except Exception:
                resp = await httpx.AsyncClient(timeout=8.0, verify=False).get(GITHUB_API)
        if resp.status_code == 200:
            data = resp.json()
            latest = data.get("tag_name", "").lstrip("v")
            return {
                "current": CURRENT_VERSION,
                "latest": latest,
                "has_update": latest != CURRENT_VERSION and bool(latest),
                "release_url": data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases"),
                "release_notes": data.get("body", "")[:500],
                "published_at": data.get("published_at", ""),
            }
    except Exception as e:
        pass
    return {
        "current": CURRENT_VERSION,
        "latest": None,
        "has_update": False,
        "release_url": f"https://github.com/{GITHUB_REPO}/releases",
        "error": "无法连接 GitHub",
    }


# ── Logs ──────────────────────────────────────────────────────────────────────

@router.get("/logs", dependencies=_deps)
async def get_logs(n: int = Query(100, le=500)):
    log_file = _get_config_dir() / "server.log"
    if not log_file.exists():
        return {"lines": []}
    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    return {"lines": lines[-n:]}


# ── Custom Router Management ──────────────────────────────────────────────────

class RouterImportRequest(BaseModel):
    path: str  # 本地目录路径或 .bspkg 文件路径


class RouterActivateRequest(BaseModel):
    name: str


class RouterTestRequest(BaseModel):
    name: str
    message: str = "帮我写一个快速排序算法"


def _get_registry():
    """获取 RouterRegistry 单例（runtime 启动后可用）。"""
    try:
        from bridge_server.services.router_registry import get_router_registry
        reg = get_router_registry()
        if reg is None:
            raise HTTPException(status_code=503, detail="RouterRegistry 未初始化")
        return reg
    except ImportError:
        raise HTTPException(status_code=503, detail="RouterRegistry 模块不可用")


@router.get("/router/list", dependencies=_deps)
async def list_routers():
    """列出所有已安装的自定义路由器。"""
    reg = _get_registry()
    return {"routers": reg.list_routers(), "active": reg.get_active()}


@router.get("/router/active", dependencies=_deps)
async def get_active_router():
    """获取当前激活的路由器名称（null 表示使用内置路由）。"""
    reg = _get_registry()
    return {"active": reg.get_active()}


@router.post("/router/import", dependencies=_deps)
async def import_router(req: RouterImportRequest):
    """从本地路径安装路由器（目录或 .bspkg 文件）。"""
    reg = _get_registry()
    src = Path(req.path)
    if not src.exists():
        raise HTTPException(status_code=400, detail=f"路径不存在: {req.path}")
    try:
        manifest = reg.install(src)
        return {
            "ok": True,
            "name": manifest.name,
            "version": manifest.version,
            "description": manifest.description,
        }
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/router/activate", dependencies=_deps)
async def activate_router(req: RouterActivateRequest):
    """激活指定路由器（替换当前激活的路由器）。"""
    reg = _get_registry()
    try:
        reg.activate(req.name)
        return {"ok": True, "active": req.name}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/router/deactivate", dependencies=_deps)
async def deactivate_router():
    """停用自定义路由器，回退到内置 SmartRouter。"""
    reg = _get_registry()
    reg.deactivate()
    return {"ok": True, "active": None}


@router.post("/router/rollback/{name}", dependencies=_deps)
async def rollback_router(name: str):
    """将指定路由器回滚到上一个版本（需要之前有备份）。"""
    reg = _get_registry()
    try:
        reg.rollback(name)
        return {"ok": True, "message": f"路由器 '{name}' 已回滚到上一个版本"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/router/{name}", dependencies=_deps)
async def remove_router(name: str):
    """卸载指定路由器（不可撤销）。"""
    reg = _get_registry()
    try:
        reg.remove(name)
        return {"ok": True, "message": f"路由器 '{name}' 已卸载"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/router/test", dependencies=_deps)
async def test_router(req: RouterTestRequest):
    """测试路由器：使用指定消息运行路由，返回决策结果和耗时。"""
    reg = _get_registry()
    try:
        from bridge_server.services.model_info import get_model_info_aggregator
        from bridge_server.router_sdk import RoutingContext

        agg = get_model_info_aggregator()
        model_list = agg.get_snapshot() if agg else []
        ctx = RoutingContext(
            last_user_message=req.message,
            messages_count=1,
            models=model_list,
        )
        result = await reg.test_router(req.name, ctx)
        return result
    except KeyError:
        raise HTTPException(status_code=404, detail=f"路由器 '{req.name}' 未安装")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Benchmark ─────────────────────────────────────────────────────────────────

_BENCHMARK_QUESTIONS: Dict[str, List[Dict]] = {
    "coding": [
        {
            "id": "code_1",
            "prompt": "用Python实现一个二分查找函数，要求：函数签名为 binary_search(arr, target)，包含详细注释，并给出时间复杂度。",
            "check": lambda r: bool(_re.search(r"def binary_search", r) and ("O(" in r or "时间复杂度" in r)),
        },
        {
            "id": "code_2",
            "prompt": "写一段JavaScript代码，使用Promise实现一个带超时控制的fetch请求（超时3秒自动拒绝），并加注释。",
            "check": lambda r: bool(_re.search(r"Promise|fetch|timeout|setTimeout", r, _re.I)),
        },
        {
            "id": "code_3",
            "prompt": "请找出以下Python代码中的bug并修复：\n```python\ndef find_max(lst):\n    max_val = lst[0]\n    for i in range(len(lst)):\n        if lst[i] > max_val:\n            max_val = lst[i+1]\n    return max_val\n```",
            "check": lambda r: bool(_re.search(r"lst\[i\]|索引越界|index|bug|修复|错误", r, _re.I)),
        },
    ],
    "math": [
        {
            "id": "math_1",
            "prompt": "一列火车从A城出发，速度60km/h，同时另一列火车从B城出发，速度90km/h，两城相距600km，两车相向而行，请问几小时后相遇？给出完整解题过程。",
            "check": lambda r: bool(_re.search(r"4\s*小时|4h|4\s*hour", r, _re.I) or "4" in r),
        },
        {
            "id": "math_2",
            "prompt": "已知等差数列首项a₁=2，公差d=3，求第15项和前15项之和，请给出推导步骤。",
            "check": lambda r: bool(_re.search(r"44", r) and _re.search(r"345", r)),
        },
        {
            "id": "math_3",
            "prompt": "用数学归纳法证明：对所有正整数n，1+2+3+...+n = n(n+1)/2",
            "check": lambda r: bool(_re.search(r"归纳|induction|k\+1|假设|成立", r, _re.I)),
        },
    ],
    "writing": [
        {
            "id": "write_1",
            "prompt": "以「第一场雪」为题，写一段200字左右的散文，要求意境优美，有具体的场景描写。",
            "check": lambda r: len(r) >= 100,
        },
        {
            "id": "write_2",
            "prompt": "帮我写一封给领导申请居家办公的邮件，原因是家中有老人生病需要照料，语气正式但不失人情味，不超过150字。",
            "check": lambda r: bool(_re.search(r"申请|敬请|居家|审批|办公|领导|尊敬", r)),
        },
        {
            "id": "write_3",
            "prompt": "为一款主打「极简主义」风格的蓝牙耳机写一段产品介绍文案（80字以内），突出设计感和音质。",
            "check": lambda r: 20 <= len(r) <= 300,
        },
    ],
    "translation": [
        {
            "id": "trans_1",
            "prompt": '将以下古文翻译成现代英文：\n"知之者不如好之者，好之者不如乐之者。"（出自《论语》）\n请同时给出字面意思和引申义。',
            "check": lambda r: bool(_re.search(r"know|learn|enjoy|love|delight|pleasure", r, _re.I)),
        },
        {
            "id": "trans_2",
            "prompt": '将以下英文段落翻译成流畅的中文：\n"Artificial intelligence is transforming every industry, from healthcare to finance, creating both unprecedented opportunities and significant challenges for society."',
            "check": lambda r: bool(_re.search(r"人工智能|医疗|金融|机遇|挑战", r)),
        },
        {
            "id": "trans_3",
            "prompt": "请将以下句子分别翻译成日语和法语：\n「春天来了，万物复苏。」",
            "check": lambda r: bool(_re.search(r"春|printemps|春が|haru", r, _re.I)),
        },
    ],
    "chat": [
        {
            "id": "chat_1",
            "prompt": "我最近工作压力很大，经常失眠，有什么实用的放松建议？",
            "check": lambda r: len(r) >= 80 and bool(_re.search(r"放松|呼吸|运动|睡眠|休息|建议", r)),
        },
        {
            "id": "chat_2",
            "prompt": "如果你是一种天气，你会是什么天气？为什么？（请给出有趣且有深度的回答）",
            "check": lambda r: len(r) >= 50,
        },
        {
            "id": "chat_3",
            "prompt": "我朋友说「人生苦短，及时行乐」，我觉得这句话有点问题，你怎么看？",
            "check": lambda r: bool(_re.search(r"但|然而|不过|另一方面|平衡|责任|意义|价值", r)),
        },
    ],
}

_BENCHMARK_DIMENSION_NAMES: Dict[str, str] = {
    "coding":      "💻 代码编程",
    "math":        "🔢 数学推理",
    "writing":     "✍️ 文学创作",
    "translation": "🌐 语言翻译",
    "chat":        "💬 日常对话",
}

_BENCHMARK_QUESTIONS_PER_DIM = 3
_BENCHMARK_TOKENS_PER_CALL = 750
_BENCHMARK_SECS_PER_CALL = 6  # conservative estimate

# In-memory task store: task_id -> task_state_dict
_benchmark_tasks: Dict[str, Dict[str, Any]] = {}


def _benchmark_stars(score: int) -> str:
    s = round(score / 20)
    return "★" * s + "☆" * (5 - s)


def _score_benchmark_response(content: str, latency: float, check_fn, error: str) -> Dict[str, Any]:
    if error:
        return {"score": 0, "quality": False, "latency": latency, "error": error}
    quality = bool(check_fn(content))
    q_score = 40 if quality else 0
    length = len(content)
    l_score = min(30, int(length / 500 * 30)) if length >= 20 else 0
    speed = max(0, 30 - int((latency - 5) / 85 * 30)) if latency > 5 else 30
    return {
        "score": q_score + l_score + speed,
        "quality": quality,
        "latency": round(latency, 1),
        "length": length,
        "error": "",
    }


async def _call_benchmark_model(
    base_url: str, api_key: str, model_id: str, prompt: str, timeout: int = 60
) -> Tuple[str, float, str]:
    """Async model call for benchmark. Returns (content, latency_sec, error)."""
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1000,
        "temperature": 0.7,
    }
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            resp = await client.post(url, json=payload, headers=headers)
        latency = time.perf_counter() - t0
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or msg.get("reasoning_content") or ""
        return content.strip(), latency, ""
    except httpx.TimeoutException:
        return "", time.perf_counter() - t0, f"超时（>{timeout}s）"
    except Exception as e:
        return "", time.perf_counter() - t0, str(e)[:120]


async def _run_benchmark_task(
    task_id: str,
    models: List[Tuple[str, str, str, str]],  # (provider_name, model_id, base_url, api_key)
    dimensions: List[str],
) -> None:
    """Background task: run benchmark and update _benchmark_tasks[task_id] in-place."""
    task = _benchmark_tasks[task_id]
    task["status"] = "running"
    total_calls = len(models) * len(dimensions) * _BENCHMARK_QUESTIONS_PER_DIM
    done = 0
    results: Dict[str, Any] = {}

    try:
        for provider_name, model_id, base_url, api_key in models:
            model_key = f"{provider_name}/{model_id}"
            results[model_key] = {}

            for dim in dimensions:
                questions = _BENCHMARK_QUESTIONS[dim][:_BENCHMARK_QUESTIONS_PER_DIM]
                dim_scores = []

                for q in questions:
                    task["current_step"] = (
                        f"{model_key}  ·  {_BENCHMARK_DIMENSION_NAMES.get(dim, dim)}  ·  {q['id']}"
                    )
                    content, latency, error = await _call_benchmark_model(
                        base_url, api_key, model_id, q["prompt"]
                    )
                    score_info = _score_benchmark_response(content, latency, q["check"], error)
                    dim_scores.append(score_info)
                    done += 1
                    task["progress"] = int(done / total_calls * 100)

                avg_score = (
                    int(sum(r["score"] for r in dim_scores) / len(dim_scores))
                    if dim_scores else 0
                )
                avg_latency = (
                    round(sum(r["latency"] for r in dim_scores) / len(dim_scores), 1)
                    if dim_scores else 0.0
                )
                quality_rate = (
                    round(sum(1 for r in dim_scores if r["quality"]) / len(dim_scores), 2)
                    if dim_scores else 0.0
                )
                results[model_key][dim] = {
                    "score": avg_score,
                    "stars": _benchmark_stars(avg_score),
                    "quality_rate": quality_rate,
                    "avg_latency": avg_latency,
                }

        # Persist results (merge with existing file so previous models are kept)
        out_file = _get_config_dir() / "benchmark_results.yaml"
        existing: dict = {}
        if out_file.exists():
            with open(out_file, encoding="utf-8") as f:
                existing = yaml.safe_load(f) or {}
        existing.setdefault("results", {}).update(results)
        existing["generated_at"] = datetime.now().isoformat()
        existing["dimensions"] = dimensions
        with open(out_file, "w", encoding="utf-8") as f:
            yaml.dump(existing, f, allow_unicode=True, default_flow_style=False)

        task["status"] = "done"
        task["results"] = results
        task["progress"] = 100
        task["current_step"] = "测试完成"

    except Exception as e:
        task["status"] = "error"
        task["error"] = str(e)
        task["current_step"] = ""


class BenchmarkStartRequest(BaseModel):
    provider_name: str
    model_ids: Optional[List[str]] = None   # None = all models in provider
    dimensions: Optional[List[str]] = None  # None = all dimensions


@router.get("/benchmark/info", dependencies=_deps)
async def get_benchmark_info():
    """Return benchmark dimension descriptions and estimation constants."""
    return {
        "dimensions": _BENCHMARK_DIMENSION_NAMES,
        "questions_per_dim": _BENCHMARK_QUESTIONS_PER_DIM,
        "tokens_per_call": _BENCHMARK_TOKENS_PER_CALL,
        "secs_per_call": _BENCHMARK_SECS_PER_CALL,
    }


@router.post("/benchmark/start", dependencies=_deps)
async def start_benchmark(req: BenchmarkStartRequest, background_tasks: BackgroundTasks):
    """Start an async benchmark task for one provider's models."""
    config = _load_yaml(_get_config_dir() / "config.yaml")
    provider = next(
        (p for p in config.get("providers", []) if p.get("name") == req.provider_name),
        None,
    )
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{req.provider_name}' 不存在")

    base_url = _resolve_provider_base_url(provider)
    auth_type = provider.get("auth_type", "api_key")

    # Resolve API key / bearer token
    if auth_type == "oauth":
        api_key = ""
        try:
            from bridge_server.providers.oauth_manager import OAuthManager
            mgr = OAuthManager(_resolve_oauth_config(provider))
            api_key = await mgr.get_token()
        except Exception:
            pass
    else:
        env_var = provider.get("api_key_env", "")
        env_file = _get_config_dir() / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
        api_key = os.environ.get(env_var, "") or provider.get("api_key", "")

    if not api_key:
        raise HTTPException(status_code=422, detail="无法获取 API Key，请检查配置")

    # Resolve model list
    all_model_ids = [
        (m.get("id") if isinstance(m, dict) else str(m))
        for m in provider.get("models", [])
    ]
    model_ids = req.model_ids if req.model_ids else all_model_ids
    model_ids = [m for m in model_ids if m in all_model_ids]
    if not model_ids:
        raise HTTPException(status_code=422, detail="没有有效的模型 ID")

    dimensions = req.dimensions if req.dimensions else list(_BENCHMARK_QUESTIONS.keys())
    dimensions = [d for d in dimensions if d in _BENCHMARK_QUESTIONS]
    if not dimensions:
        raise HTTPException(status_code=422, detail="没有有效的测试维度")

    total_calls = len(model_ids) * len(dimensions) * _BENCHMARK_QUESTIONS_PER_DIM
    est_tokens = total_calls * _BENCHMARK_TOKENS_PER_CALL
    est_minutes = round(total_calls * _BENCHMARK_SECS_PER_CALL / 60, 1)

    task_id = secrets.token_hex(8)
    _benchmark_tasks[task_id] = {
        "status": "pending",
        "progress": 0,
        "current_step": "等待启动…",
        "results": None,
        "error": None,
        "provider_name": req.provider_name,
        "model_ids": model_ids,
        "dimensions": dimensions,
        "total_calls": total_calls,
    }

    models_tuples = [
        (req.provider_name, mid, base_url, api_key) for mid in model_ids
    ]
    background_tasks.add_task(_run_benchmark_task, task_id, models_tuples, dimensions)

    return {
        "task_id": task_id,
        "estimated_calls": total_calls,
        "estimated_tokens": est_tokens,
        "estimated_minutes": est_minutes,
        "model_ids": model_ids,
        "dimensions": dimensions,
    }


@router.get("/benchmark/status/{task_id}", dependencies=_deps)
async def get_benchmark_status(task_id: str):
    """Poll the status of a running benchmark task."""
    task = _benchmark_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task 不存在或已过期")
    return task


@router.get("/benchmark/results", dependencies=_deps)
async def get_benchmark_results():
    """Return the last saved benchmark results file."""
    out_file = _get_config_dir() / "benchmark_results.yaml"
    if not out_file.exists():
        return {"results": {}, "generated_at": None, "dimensions": []}
    with open(out_file, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data
