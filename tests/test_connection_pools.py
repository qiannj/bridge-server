"""Unit tests for ConnectionPoolManager — config defaults and HTTP client caching."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import pytest
import httpx

import bridge_server.utils.connection_pools as cpm
from bridge_server.utils.connection_pools import ConnectionPoolManager, get_provider_http_client


class TestConnectionPoolManagerDefaults:
    def setup_method(self):
        cpm.connection_pool_manager = None

    def test_config_has_required_keys(self):
        manager = ConnectionPoolManager()
        assert "http" in manager.config
        assert "database" in manager.config
        assert "redis" in manager.config

    def test_db_pool_size_default(self):
        manager = ConnectionPoolManager()
        assert manager.db_pool_size == 10


class TestGetProviderHttpClient:
    def setup_method(self):
        cpm.connection_pool_manager = None

    def test_returns_httpx_async_client(self):
        client = get_provider_http_client(
            "test-p1",
            base_url="https://a.com",
            headers={},
        )
        assert isinstance(client, httpx.AsyncClient)

    def test_same_provider_id_returns_cached_client(self):
        client1 = get_provider_http_client(
            "test-p1",
            base_url="https://a.com",
            headers={},
        )
        client2 = get_provider_http_client(
            "test-p1",
            base_url="https://a.com",
            headers={},
        )
        assert client1 is client2
