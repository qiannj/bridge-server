"""Unit tests for HybridCache (L1 + optional L2 Redis)."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import pytest
from unittest.mock import patch

from bridge_server.utils.cache import CacheMetrics, HybridCache


class TestCacheMetrics:
    def test_total_requests_sum(self):
        m = CacheMetrics(l1_hits=3, l2_hits=2, misses=1)
        assert m.total_requests == 6

    def test_hit_rate_calculation(self):
        m = CacheMetrics(l1_hits=4, l2_hits=1, misses=5)
        assert m.hit_rate == pytest.approx(0.5)

    def test_hit_rate_zero_requests(self):
        m = CacheMetrics()
        assert m.hit_rate == 0.0

    def test_l1_hit_rate(self):
        m = CacheMetrics(l1_hits=3, l2_hits=2, misses=5)
        assert m.l1_hit_rate == pytest.approx(0.3)


class TestL1CacheOnly:
    def setup_method(self):
        with patch("asyncio.create_task"):
            self.cache = HybridCache(redis_url=None, l1_maxsize=100, l1_ttl=300)

    @pytest.mark.asyncio
    async def test_set_get_round_trip(self):
        await self.cache.set("mykey", "myvalue")
        result = await self.cache.get("mykey")
        assert result == "myvalue"

    @pytest.mark.asyncio
    async def test_miss_returns_none(self):
        result = await self.cache.get("nonexistent_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_l1_hits_counter(self):
        await self.cache.set("k", "v")
        await self.cache.get("k")
        assert self.cache.metrics.l1_hits == 1

    @pytest.mark.asyncio
    async def test_misses_counter(self):
        await self.cache.get("missing_key")
        assert self.cache.metrics.misses == 1

    @pytest.mark.asyncio
    async def test_overwrite_key(self):
        await self.cache.set("k", "original")
        await self.cache.set("k", "updated")
        result = await self.cache.get("k")
        assert result == "updated"

    @pytest.mark.asyncio
    async def test_key_prefix_used_in_make_key(self):
        full_key = self.cache._make_key("test")
        assert full_key == "bridge:cache:test"


class TestL1CacheEviction:
    @pytest.mark.asyncio
    async def test_last_item_accessible_after_eviction(self):
        with patch("asyncio.create_task"):
            cache = HybridCache(redis_url=None, l1_maxsize=2, l1_ttl=300)
        await cache.set("item1", "value1")
        await cache.set("item2", "value2")
        await cache.set("item3", "value3")
        # item3 is the most recently written — must survive eviction
        result = await cache.get("item3")
        assert result == "value3"


class TestRedisUnavailableFallback:
    @pytest.mark.asyncio
    async def test_set_get_works_without_l2(self):
        with patch("asyncio.create_task"):
            cache = HybridCache(redis_url=None, l1_maxsize=100, l1_ttl=300)
        assert cache.l2_cache is None
        await cache.set("key", {"data": 42})
        result = await cache.get("key")
        assert result == {"data": 42}
