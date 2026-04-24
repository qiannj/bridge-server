"""Unit tests for bridge_server.auth module."""

import hashlib
import json
import time
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from bridge_server.auth import (
    AsyncAuthManager,
    _hash_token,
    _tokens_are_hashed,
    _default_config_dir,
    _HASHED_FORMAT_MARKER,
    _HASHED_FORMAT_VALUE,
)


class TestHashToken:
    def test_returns_64_char_hex(self):
        result = _hash_token("some_token")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self):
        assert _hash_token("same_token") == _hash_token("same_token")

    def test_different_inputs_differ(self):
        assert _hash_token("token_a") != _hash_token("token_b")

    def test_sha256_correctness(self):
        token = "test_token_value"
        expected = hashlib.sha256(token.encode("utf-8")).hexdigest()
        assert _hash_token(token) == expected


class TestTokensAreHashed:
    def test_detects_hashed_format(self):
        data = {_HASHED_FORMAT_MARKER: _HASHED_FORMAT_VALUE}
        assert _tokens_are_hashed(data) is True

    def test_detects_plaintext_format(self):
        data = {"my_plain_token": {"user_id": "admin"}}
        assert _tokens_are_hashed(data) is False

    def test_empty_dict(self):
        assert _tokens_are_hashed({}) is False


class TestDefaultConfigDir:
    def test_default_is_home_bridge_server(self, monkeypatch):
        monkeypatch.delenv("BRIDGE_CONFIG_DIR", raising=False)
        assert _default_config_dir() == Path.home() / ".bridge-server"

    def test_env_var_overrides(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BRIDGE_CONFIG_DIR", str(tmp_path))
        assert _default_config_dir() == tmp_path


class TestEnsureConfigFiles:
    @pytest.mark.asyncio
    async def test_creates_users_file(self, tmp_path):
        mgr = AsyncAuthManager(config_dir=tmp_path)
        await mgr.initialize()
        assert mgr.users_file.exists()

    @pytest.mark.asyncio
    async def test_creates_tokens_file(self, tmp_path):
        mgr = AsyncAuthManager(config_dir=tmp_path)
        await mgr.initialize()
        assert mgr.tokens_file.exists()

    @pytest.mark.asyncio
    async def test_tokens_file_uses_hashed_format(self, tmp_path):
        mgr = AsyncAuthManager(config_dir=tmp_path)
        await mgr.initialize()
        data = json.loads(mgr.tokens_file.read_text(encoding="utf-8"))
        assert data.get(_HASHED_FORMAT_MARKER) == _HASHED_FORMAT_VALUE

    @pytest.mark.asyncio
    async def test_tokens_file_no_plaintext_keys(self, tmp_path):
        mgr = AsyncAuthManager(config_dir=tmp_path)
        await mgr.initialize()
        data = json.loads(mgr.tokens_file.read_text(encoding="utf-8"))
        for key in data:
            if not key.startswith("_"):
                assert len(key) == 64
                assert all(c in "0123456789abcdef" for c in key)

    @pytest.mark.asyncio
    async def test_admin_user_in_users(self, tmp_path):
        mgr = AsyncAuthManager(config_dir=tmp_path)
        await mgr.initialize()
        data = json.loads(mgr.users_file.read_text(encoding="utf-8"))
        assert "admin" in data
        assert data["admin"]["domain"] == "admin"

    @pytest.mark.asyncio
    async def test_no_guest_user(self, tmp_path):
        mgr = AsyncAuthManager(config_dir=tmp_path)
        await mgr.initialize()
        data = json.loads(mgr.users_file.read_text(encoding="utf-8"))
        assert "guest" not in data

    @pytest.mark.asyncio
    async def test_existing_users_file_not_overwritten(self, tmp_path):
        custom_users = {"custom_user": {"user_id": "custom_user", "domain": "custom", "active": True}}
        users_file = tmp_path / "users.json"
        users_file.write_text(json.dumps(custom_users), encoding="utf-8")

        mgr = AsyncAuthManager(config_dir=tmp_path)
        await mgr.initialize()

        data = json.loads(users_file.read_text(encoding="utf-8"))
        assert "custom_user" in data
        assert "admin" not in data


class TestMigrateTokens:
    @pytest.mark.asyncio
    async def test_migrates_plaintext_to_hashed(self, tmp_path):
        plaintext_token = "my_plain_token_value"
        tokens_data = {plaintext_token: {"user_id": "admin", "active": True}}
        (tmp_path / "tokens.json").write_text(json.dumps(tokens_data), encoding="utf-8")

        mgr = AsyncAuthManager(config_dir=tmp_path)
        await mgr.initialize()

        result = json.loads((tmp_path / "tokens.json").read_text(encoding="utf-8"))
        expected_hash = _hash_token(plaintext_token)
        assert plaintext_token not in result
        assert expected_hash in result

    @pytest.mark.asyncio
    async def test_already_hashed_not_remigrated(self, tmp_path):
        token = "my_original_token"
        token_hash = _hash_token(token)
        tokens_data = {
            _HASHED_FORMAT_MARKER: _HASHED_FORMAT_VALUE,
            token_hash: {"user_id": "admin", "active": True},
        }
        (tmp_path / "tokens.json").write_text(json.dumps(tokens_data), encoding="utf-8")

        mgr = AsyncAuthManager(config_dir=tmp_path)
        await mgr.initialize()

        result = json.loads((tmp_path / "tokens.json").read_text(encoding="utf-8"))
        double_hash = _hash_token(token_hash)
        assert double_hash not in result
        assert token_hash in result


def _write_hashed_tokens(tmp_path: Path, token: str, token_info: dict) -> None:
    """Write tokens.json containing a single hashed token entry."""
    data = {
        _HASHED_FORMAT_MARKER: _HASHED_FORMAT_VALUE,
        _hash_token(token): token_info,
    }
    (tmp_path / "tokens.json").write_text(json.dumps(data), encoding="utf-8")


class TestVerifyToken:
    # These tests create the manager without calling initialize() so that the
    # token cache is always empty and all look-ups go through the disk path,
    # which is where the active/expiry checks live.

    @pytest.mark.asyncio
    async def test_valid_token_returns_info(self, tmp_path):
        token = "valid_test_token"
        token_info = {"user_id": "admin", "active": True, "expires_at": None}
        _write_hashed_tokens(tmp_path, token, token_info)

        mgr = AsyncAuthManager(config_dir=tmp_path)
        result = await mgr.verify_token(token)

        assert result is not None
        assert result["user_id"] == "admin"

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none(self, tmp_path):
        token = "valid_test_token"
        token_info = {"user_id": "admin", "active": True, "expires_at": None}
        _write_hashed_tokens(tmp_path, token, token_info)

        mgr = AsyncAuthManager(config_dir=tmp_path)
        result = await mgr.verify_token("completely_different_token")

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_token_returns_none(self, tmp_path):
        mgr = AsyncAuthManager(config_dir=tmp_path)
        assert await mgr.verify_token("") is None

    @pytest.mark.asyncio
    async def test_none_token_returns_none(self, tmp_path):
        mgr = AsyncAuthManager(config_dir=tmp_path)
        assert await mgr.verify_token(None) is None

    @pytest.mark.asyncio
    async def test_bearer_prefix_stripped(self, tmp_path):
        token = "mytoken"
        token_info = {"user_id": "admin", "active": True, "expires_at": None}
        _write_hashed_tokens(tmp_path, token, token_info)

        mgr = AsyncAuthManager(config_dir=tmp_path)
        result = await mgr.verify_token(f"Bearer {token}")

        assert result is not None
        assert result["user_id"] == "admin"

    @pytest.mark.asyncio
    async def test_expired_token_returns_none(self, tmp_path):
        token = "expired_token"
        token_info = {
            "user_id": "admin",
            "active": True,
            "expires_at": time.time() - 3600,
        }
        _write_hashed_tokens(tmp_path, token, token_info)

        mgr = AsyncAuthManager(config_dir=tmp_path)
        result = await mgr.verify_token(token)

        assert result is None

    @pytest.mark.asyncio
    async def test_future_expiry_valid(self, tmp_path):
        token = "future_token"
        token_info = {
            "user_id": "admin",
            "active": True,
            "expires_at": time.time() + 3600,
        }
        _write_hashed_tokens(tmp_path, token, token_info)

        mgr = AsyncAuthManager(config_dir=tmp_path)
        result = await mgr.verify_token(token)

        assert result is not None

    @pytest.mark.asyncio
    async def test_inactive_token_returns_none(self, tmp_path):
        token = "inactive_token"
        token_info = {"user_id": "admin", "active": False, "expires_at": None}
        _write_hashed_tokens(tmp_path, token, token_info)

        mgr = AsyncAuthManager(config_dir=tmp_path)
        result = await mgr.verify_token(token)

        assert result is None


class TestGetUserById:
    # These tests create the manager without calling initialize() so the user
    # cache is always empty and look-ups go straight to the disk path, which
    # is where the active check lives.

    @pytest.mark.asyncio
    async def test_existing_active_user_returned(self, tmp_path):
        users = {"alice": {"user_id": "alice", "domain": "general", "active": True}}
        (tmp_path / "users.json").write_text(json.dumps(users), encoding="utf-8")

        mgr = AsyncAuthManager(config_dir=tmp_path)
        result = await mgr.get_user_by_id("alice")

        assert result is not None
        assert result["user_id"] == "alice"

    @pytest.mark.asyncio
    async def test_missing_user_returns_none(self, tmp_path):
        users = {"alice": {"user_id": "alice", "domain": "general", "active": True}}
        (tmp_path / "users.json").write_text(json.dumps(users), encoding="utf-8")

        mgr = AsyncAuthManager(config_dir=tmp_path)
        result = await mgr.get_user_by_id("nobody")

        assert result is None

    @pytest.mark.asyncio
    async def test_inactive_user_returns_none(self, tmp_path):
        users = {"bob": {"user_id": "bob", "domain": "general", "active": False}}
        (tmp_path / "users.json").write_text(json.dumps(users), encoding="utf-8")

        mgr = AsyncAuthManager(config_dir=tmp_path)
        result = await mgr.get_user_by_id("bob")

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_id_returns_none(self, tmp_path):
        mgr = AsyncAuthManager(config_dir=tmp_path)
        assert await mgr.get_user_by_id("") is None


class TestTokenCache:
    @pytest.mark.asyncio
    async def test_cache_hit_avoids_disk(self, tmp_path):
        """Seed the token cache manually; after tokens.json is removed, verify_token still returns data."""
        token = "cached_only_token"
        token_hash = _hash_token(token)
        token_info = {"user_id": "admin", "active": True, "expires_at": None}

        # Write minimal files so initialize() succeeds.
        (tmp_path / "users.json").write_text(
            json.dumps({"admin": {"user_id": "admin", "domain": "admin", "active": True}}),
            encoding="utf-8",
        )
        (tmp_path / "tokens.json").write_text(
            json.dumps({_HASHED_FORMAT_MARKER: _HASHED_FORMAT_VALUE}),
            encoding="utf-8",
        )

        mgr = AsyncAuthManager(config_dir=tmp_path)
        await mgr.initialize()

        # Manually seed the in-memory cache with our token.
        mgr._token_cache[f"token:{token_hash}"] = {
            "data": token_info,
            "timestamp": time.time(),
        }

        # Remove tokens.json — any disk read would now raise FileNotFoundError.
        mgr.tokens_file.unlink()

        result = await mgr.verify_token(token)

        assert result is not None
        assert result["user_id"] == "admin"

    @pytest.mark.asyncio
    async def test_clear_cache(self, tmp_path):
        (tmp_path / "users.json").write_text(
            json.dumps({"admin": {"user_id": "admin", "domain": "admin", "active": True}}),
            encoding="utf-8",
        )
        (tmp_path / "tokens.json").write_text(
            json.dumps({_HASHED_FORMAT_MARKER: _HASHED_FORMAT_VALUE}),
            encoding="utf-8",
        )

        mgr = AsyncAuthManager(config_dir=tmp_path)
        await mgr.initialize()

        # Ensure both caches have at least one entry.
        mgr._user_cache["user:extra"] = {"data": {}, "timestamp": time.time()}
        mgr._token_cache["token:extra"] = {"data": {}, "timestamp": time.time()}

        mgr.clear_cache()

        assert len(mgr._user_cache) == 0
        assert len(mgr._token_cache) == 0
