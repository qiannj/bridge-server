#!/usr/bin/env python3
"""
OAuth token manager for Bridge Server.

Supports:
1. Standard OAuth 2.0 client_credentials flow
2. OpenAI Codex / ChatGPT OAuth refresh-token flow backed by auth.json
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import httpx
import yaml

logger = logging.getLogger(__name__)


class OAuthTokenRevokedException(RuntimeError):
    """Raised when the stored refresh_token is no longer valid (401/403).

    Callers should clear stored credentials and prompt the user to re-login.
    """


class OAuthTokenManager:
    """OAuth token manager with support for multiple grant styles."""

    EXPIRY_BUFFER_SECONDS = 120  # refresh 2 minutes before expiry

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: Optional[str] = None,
        scope: Optional[str] = None,
        grant_type: str = "client_credentials",
        extra_params: Optional[dict] = None,
        provider: Optional[str] = None,
        auth_store_key: Optional[str] = None,
    ):
        if not token_url:
            raise ValueError("OAuth: token_url 不能为空")
        if not client_id:
            raise ValueError("OAuth: client_id 不能为空")

        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret or ""
        self.scope = scope
        self.grant_type = grant_type
        self.extra_params = extra_params or {}
        self.provider = (provider or self.extra_params.get("provider") or "").strip()
        self.auth_store_key = (auth_store_key or self.extra_params.get("auth_store_key") or "").strip()

        if self.provider == "openai_codex" and not self.auth_store_key:
            raise ValueError("OAuth: openai_codex 模式需要 auth_store_key")
        if self.provider != "openai_codex" and not self.client_secret:
            raise ValueError("OAuth: client_secret 不能为空")

        self._token: Optional[str] = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    def _config_dir(self) -> Path:
        for env_name in ("BRIDGE_SERVER_CONFIG_DIR", "BRIDGE_CONFIG_DIR"):
            override = os.environ.get(env_name, "").strip()
            if override:
                return Path(override).expanduser()
        if os.name == "nt":
            return Path(os.environ.get("USERPROFILE", "")).expanduser() / ".bridge-server"
        return Path.home() / ".bridge-server"

    def _auth_store_path(self) -> Path:
        return self._config_dir() / "auth.json"

    def _is_valid(self) -> bool:
        return bool(self._token) and time.monotonic() < self._expires_at - self.EXPIRY_BUFFER_SECONDS

    def _load_auth_store(self) -> dict:
        path = self._auth_store_path()
        if not path.exists():
            return {"providers": {}}
        raw = path.read_text(encoding="utf-8")
        try:
            return json.loads(raw)
        except Exception:
            try:
                payload = yaml.safe_load(raw) or {}
                if isinstance(payload, dict):
                    self._save_auth_store(payload)
                    logger.info("OAuth auth.json 发现旧版 YAML，已自动迁移为 JSON | path=%s", path)
                    return payload
            except Exception:
                pass
            logger.warning("OAuth auth.json 损坏，按空状态处理 | path=%s", path)
            return {"providers": {}}

    def _save_auth_store(self, payload: dict) -> None:
        path = self._auth_store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if os.name != "nt":
            os.chmod(path, 0o600)

    def _load_codex_tokens(self) -> dict:
        payload = self._load_auth_store()
        providers = payload.get("providers") or {}
        provider_state = providers.get(self.auth_store_key) or {}
        tokens = provider_state.get("tokens") or {}
        access_token = str(tokens.get("access_token", "") or "").strip()
        refresh_token = str(tokens.get("refresh_token", "") or "").strip()
        expires_at = float(tokens.get("expires_at", 0) or 0)
        if not refresh_token:
            raise RuntimeError("OpenAI Codex OAuth 缺少 refresh_token，请重新登录")
        return {
            "payload": payload,
            "provider_state": provider_state,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
        }

    async def get_token(self) -> str:
        if self._is_valid():
            return self._token  # type: ignore[return-value]

        async with self._lock:
            if self._is_valid():
                return self._token  # type: ignore[return-value]
            return await self._fetch_token()

    def get_cached_token_sync(self) -> str:
        return asyncio.run(self.get_token())

    async def _fetch_token(self) -> str:
        if self.provider == "openai_codex":
            return await self._fetch_codex_token()
        return await self._fetch_client_credentials_token()

    async def _fetch_client_credentials_token(self) -> str:
        data: dict = {
            "grant_type": self.grant_type,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        if self.scope:
            data["scope"] = self.scope
        data.update(self.extra_params)

        logger.debug("OAuth client_credentials: 获取 token | url=%s client_id=%s", self.token_url, self.client_id)

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(self.token_url, data=data)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                body = e.response.text[:300]
                raise RuntimeError(f"OAuth token 获取失败: HTTP {e.response.status_code} | {body}") from e
            except Exception as e:
                raise RuntimeError(f"OAuth token 请求失败: {e}") from e

        token_data = resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise RuntimeError(f"OAuth 响应中无 access_token: {list(token_data.keys())}")

        expires_in = int(token_data.get("expires_in", 3600))
        self._token = access_token
        self._expires_at = time.monotonic() + expires_in
        return self._token  # type: ignore[return-value]

    async def _fetch_codex_token(self) -> str:
        token_state = self._load_codex_tokens()
        access_token = token_state["access_token"]
        refresh_token = token_state["refresh_token"]
        stored_expires_at = token_state["expires_at"]

        # Use stored access_token if it hasn't expired yet (with buffer)
        if access_token and stored_expires_at > 0:
            remaining = stored_expires_at - time.time()
            if remaining > self.EXPIRY_BUFFER_SECONDS:
                logger.debug(
                    "OAuth Codex: 使用缓存 access_token，剩余 %.0f 秒 | key=%s",
                    remaining,
                    self.auth_store_key,
                )
                self._token = access_token
                self._expires_at = time.monotonic() + remaining - self.EXPIRY_BUFFER_SECONDS
                return self._token

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
        }

        logger.debug("OAuth Codex: 刷新 access_token | key=%s", self.auth_store_key)
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(self.token_url, data=data)
            except Exception as e:
                raise RuntimeError(f"OpenAI Codex token 刷新请求失败: {e}") from e

        if resp.status_code in (401, 403):
            # Refresh token revoked or expired — clear stored credentials
            self._clear_codex_tokens(token_state["payload"])
            raise OAuthTokenRevokedException(
                "OpenAI Codex refresh_token 已失效，请重新运行 setup-wizard 登录"
            )

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = e.response.text[:300]
            raise RuntimeError(f"OpenAI Codex token 刷新失败: HTTP {e.response.status_code} | {body}") from e

        token_data = resp.json()
        next_access_token = str(token_data.get("access_token", "") or "").strip()
        next_refresh_token = str(token_data.get("refresh_token", refresh_token) or "").strip()
        if not next_access_token:
            raise RuntimeError("OpenAI Codex token 响应中无 access_token")

        expires_in = int(token_data.get("expires_in", 3600) or 3600)
        expires_at_unix = time.time() + expires_in

        payload = token_state["payload"]
        providers = payload.setdefault("providers", {})
        provider_state = providers.setdefault(self.auth_store_key, {})
        provider_state["provider"] = "openai_codex"
        provider_state["tokens"] = {
            "access_token": next_access_token,
            "refresh_token": next_refresh_token,
            "expires_at": expires_at_unix,
        }
        provider_state["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._save_auth_store(payload)

        self._token = next_access_token
        self._expires_at = time.monotonic() + expires_in - self.EXPIRY_BUFFER_SECONDS
        return self._token

    def _clear_codex_tokens(self, payload: dict) -> None:
        """Remove stored tokens after refresh_token revocation."""
        providers = payload.get("providers") or {}
        provider_state = providers.get(self.auth_store_key) or {}
        provider_state.pop("tokens", None)
        self._save_auth_store(payload)
        self.invalidate()

    def invalidate(self):
        self._token = None
        self._expires_at = 0.0


class OAuthManager(OAuthTokenManager):
    """Backward-compatible wrapper that also accepts the legacy dict constructor."""

    def __init__(self, token_url: str | dict, client_id: Optional[str] = None, **kwargs):
        if isinstance(token_url, dict):
            cfg = dict(token_url)
            super().__init__(
                token_url=cfg.get("token_url", ""),
                client_id=cfg.get("client_id", ""),
                client_secret=cfg.get("client_secret"),
                scope=cfg.get("scope"),
                grant_type=cfg.get("grant_type", "client_credentials"),
                extra_params=cfg.get("extra_params"),
                provider=cfg.get("provider"),
                auth_store_key=cfg.get("auth_store_key"),
            )
            return
        super().__init__(token_url=token_url, client_id=client_id or "", **kwargs)
