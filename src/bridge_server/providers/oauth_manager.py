#!/usr/bin/env python3
"""
OAuth 2.0 Client Credentials Token Manager
为需要 OAuth 鉴权的 Provider 提供自动获取、缓存、刷新 access_token 的能力。

支持标准 RFC 6749 Client Credentials 流程：
  POST token_url  →  { access_token, expires_in, token_type }

配置示例 (config.yaml):
  providers:
    - name: enterprise-ai
      base_url: https://api.enterprise.com/v1
      auth_type: oauth
      oauth:
        token_url: https://oauth.enterprise.com/token
        client_id: my-client-id
        client_secret: my-secret
        scope: api.read        # 可选
        grant_type: client_credentials  # 默认
      models:
        - id: gpt-4
"""

import asyncio
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class OAuthTokenManager:
    """OAuth 2.0 Client Credentials Token Manager.

    线程/协程安全：使用 asyncio.Lock 保证并发下只有一个 coroutine 刷新 token。
    token 会在过期前 30 秒自动续期（留出 buffer，避免请求时 token 恰好过期）。
    """

    EXPIRY_BUFFER_SECONDS = 30  # 提前多少秒视为已过期，触发续期

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: Optional[str] = None,
        grant_type: str = "client_credentials",
        extra_params: Optional[dict] = None,
    ):
        if not token_url:
            raise ValueError("OAuth: token_url 不能为空")
        if not client_id:
            raise ValueError("OAuth: client_id 不能为空")
        if not client_secret:
            raise ValueError("OAuth: client_secret 不能为空")

        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self.grant_type = grant_type
        self.extra_params = extra_params or {}

        self._token: Optional[str] = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    def _is_valid(self) -> bool:
        return bool(self._token) and time.monotonic() < self._expires_at - self.EXPIRY_BUFFER_SECONDS

    async def get_token(self) -> str:
        """获取有效的 access_token（自动续期）。"""
        if self._is_valid():
            return self._token  # type: ignore[return-value]

        async with self._lock:
            # double-check inside lock
            if self._is_valid():
                return self._token  # type: ignore[return-value]
            return await self._fetch_token()

    async def _fetch_token(self) -> str:
        """向 token_url 请求新 token（标准 form-encoded body）。"""
        data: dict = {
            "grant_type": self.grant_type,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        if self.scope:
            data["scope"] = self.scope
        data.update(self.extra_params)

        logger.debug(f"OAuth: 获取 token | url={self.token_url} client_id={self.client_id}")

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(self.token_url, data=data)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                body = e.response.text[:300]
                raise RuntimeError(
                    f"OAuth token 获取失败: HTTP {e.response.status_code} | {body}"
                ) from e
            except Exception as e:
                raise RuntimeError(f"OAuth token 请求失败: {e}") from e

        token_data = resp.json()

        access_token = token_data.get("access_token")
        if not access_token:
            raise RuntimeError(f"OAuth 响应中无 access_token: {list(token_data.keys())}")

        expires_in = int(token_data.get("expires_in", 3600))
        self._token = access_token
        self._expires_at = time.monotonic() + expires_in

        logger.info(
            f"OAuth: token 获取成功 | client_id={self.client_id} "
            f"expires_in={expires_in}s token_type={token_data.get('token_type', 'Bearer')}"
        )
        return self._token  # type: ignore[return-value]

    def invalidate(self):
        """手动使缓存的 token 失效，下次调用 get_token() 时强制刷新。"""
        self._token = None
        self._expires_at = 0.0
