#!/usr/bin/env python3
"""Admin Panel API - Bridge Server web UI backend."""

import json
import os
import secrets
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

GITHUB_REPO = "qiannj/bridge-server"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
CURRENT_VERSION = "2.0.0"


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
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)


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


@router.post("/auth/verify", dependencies=[])
async def verify_token(req: TokenRequest):
    """Verify panel token (no auth required - this IS the auth endpoint)."""
    stored = get_panel_token()
    if not stored:
        raise HTTPException(status_code=503, detail="Panel token 未配置，请运行 bridge-server panel-token")
    if secrets.compare_digest(req.token, stored):
        return {"ok": True}
    raise HTTPException(status_code=401, detail="Token 无效")


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
    # Mask API keys
    for p in config.get("providers", []):
        if "api_key" in p:
            key = p["api_key"]
            p["api_key"] = key[:8] + "****" + key[-4:] if len(key) > 12 else "****"
    return config


class ProviderAddRequest(BaseModel):
    name: str
    base_url: str
    api_key: str
    models: List[str]


@router.post("/providers", dependencies=_deps)
async def add_provider(req: ProviderAddRequest):
    config_file = _get_config_dir() / "config.yaml"
    config = _load_yaml(config_file)
    providers = config.get("providers", [])
    # Check duplicate
    if any(p.get("name") == req.name for p in providers):
        raise HTTPException(status_code=409, detail=f"Provider '{req.name}' 已存在")
    env_var = req.name.upper().replace("-", "_") + "_API_KEY"
    providers.append({
        "name": req.name,
        "base_url": req.base_url,
        "api_key_env": env_var,
        "api_key": req.api_key,
        "models": [{"id": m, "name": m} for m in req.models],
    })
    config["providers"] = providers
    # Also save to .env
    env_file = _get_config_dir() / ".env"
    env_lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    env_lines = [l for l in env_lines if not l.startswith(f"{env_var}=")]
    env_lines.append(f"{env_var}={req.api_key}")
    env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
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
    models: Optional[List[str]] = None


@router.put("/providers/{name}", dependencies=_deps)
async def update_provider(name: str, req: ProviderUpdateRequest):
    config_file = _get_config_dir() / "config.yaml"
    config = _load_yaml(config_file)
    providers = config.get("providers", [])
    found = False
    for p in providers:
        if p.get("name") == name:
            found = True
            if req.api_key:
                p["api_key"] = req.api_key
                env_var = p.get("api_key_env", name.upper().replace("-", "_") + "_API_KEY")
                env_file = _get_config_dir() / ".env"
                env_lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
                env_lines = [l for l in env_lines if not l.startswith(f"{env_var}=")]
                env_lines.append(f"{env_var}={req.api_key}")
                env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
            if req.models is not None:
                p["models"] = [{"id": m, "name": m} for m in req.models if m.strip()]
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


# ── Usage ─────────────────────────────────────────────────────────────────────

def _query_usage(days: int = 1) -> Dict[str, Any]:
    db_path = _get_config_dir() / "usage.db"
    if not db_path.exists():
        return {"records": [], "summary": {}}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        since = time.time() - days * 86400
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
    days = {"today": 1, "week": 7, "month": 30}.get(period, 1)
    return _query_usage(days)


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
