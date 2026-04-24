"""Unit tests for ProviderManager."""
import sys
import time
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from bridge_server.providers.manager import (
    ProviderManager,
    RoutingStrategy,
    ProviderConfig,
)
from bridge_server.providers.base import ProviderStatus, ProviderFactory


def _make_mock_provider(provider_id, models=None, latency=100.0, status=ProviderStatus.HEALTHY):
    p = MagicMock()
    p.provider_id = provider_id
    p.get_supported_models = MagicMock(return_value=models or ["model-a"])
    p.get_metrics = MagicMock(return_value={"average_latency": latency})
    p.get_model_info = MagicMock(
        return_value=SimpleNamespace(input_cost_per_1k=1.0, output_cost_per_1k=2.0)
    )
    p.health_check = AsyncMock(return_value=status)
    p.chat_completion = AsyncMock(return_value={"choices": [{"message": {"content": "ok"}}]})
    p.__aexit__ = AsyncMock(return_value=None)
    return p


def _make_manager(strategy=RoutingStrategy.ROUND_ROBIN):
    with patch.object(ProviderManager, "_import_providers"):
        return ProviderManager(routing_strategy=strategy)


class TestGetAvailableProviders:
    def test_enabled_provider_included(self):
        manager = _make_manager()
        manager.providers["p1"] = _make_mock_provider("p1")
        manager.provider_configs["p1"] = ProviderConfig("type1", {"id": "p1"}, enabled=True)

        assert "p1" in manager.get_available_providers()

    def test_disabled_provider_excluded(self):
        manager = _make_manager()
        manager.providers["p1"] = _make_mock_provider("p1")
        manager.provider_configs["p1"] = ProviderConfig("type1", {"id": "p1"}, enabled=False)

        assert "p1" not in manager.get_available_providers()

    def test_empty_manager_returns_empty_list(self):
        manager = _make_manager()
        assert manager.get_available_providers() == []


class TestAddProvider:
    @pytest.mark.asyncio
    async def test_healthy_provider_added_successfully(self):
        manager = _make_manager()
        mock_provider = _make_mock_provider("test-provider", status=ProviderStatus.HEALTHY)

        with patch.object(ProviderFactory, "create", return_value=mock_provider):
            cfg = ProviderConfig("test_type", {"id": "test-provider"})
            result = await manager.add_provider(cfg)

        assert result is True
        assert "test-provider" in manager.providers

    @pytest.mark.asyncio
    async def test_unhealthy_provider_rejected(self):
        manager = _make_manager()
        mock_provider = _make_mock_provider("bad-provider", status=ProviderStatus.UNHEALTHY)

        with patch.object(ProviderFactory, "create", return_value=mock_provider):
            cfg = ProviderConfig("test_type", {"id": "bad-provider"})
            result = await manager.add_provider(cfg)

        assert result is False
        assert "bad-provider" not in manager.providers


class TestRemoveProvider:
    @pytest.mark.asyncio
    async def test_existing_provider_removed(self):
        manager = _make_manager()
        manager.providers["to-remove"] = _make_mock_provider("to-remove")
        manager.provider_configs["to-remove"] = ProviderConfig("t", {"id": "to-remove"})

        result = await manager.remove_provider("to-remove")

        assert result is True
        assert "to-remove" not in manager.providers

    @pytest.mark.asyncio
    async def test_nonexistent_provider_returns_false(self):
        manager = _make_manager()
        result = await manager.remove_provider("does-not-exist")
        assert result is False


class TestRoundRobinSelect:
    def test_cycles_through_all_providers(self):
        manager = _make_manager()
        providers = ["p1", "p2", "p3"]
        selected = [manager._round_robin_select(providers) for _ in range(6)]
        assert selected == ["p1", "p2", "p3", "p1", "p2", "p3"]

    def test_single_provider_always_selected(self):
        manager = _make_manager()
        for _ in range(3):
            assert manager._round_robin_select(["only"]) == "only"

    def test_empty_list_returns_none(self):
        manager = _make_manager()
        assert manager._round_robin_select([]) is None


class TestLowestLatencySelect:
    @pytest.mark.asyncio
    async def test_selects_provider_with_lowest_latency(self):
        manager = _make_manager(RoutingStrategy.LOWEST_LATENCY)
        manager.providers["fast"] = _make_mock_provider("fast", latency=50.0)
        manager.providers["slow"] = _make_mock_provider("slow", latency=200.0)

        result = await manager._lowest_latency_select(["fast", "slow"])
        assert result == "fast"

    @pytest.mark.asyncio
    async def test_fallback_to_first_if_no_latency_in_metrics(self):
        manager = _make_manager(RoutingStrategy.LOWEST_LATENCY)
        p1 = _make_mock_provider("p1")
        p1.get_metrics = MagicMock(return_value={})  # No average_latency key
        p2 = _make_mock_provider("p2")
        p2.get_metrics = MagicMock(return_value={})
        manager.providers["p1"] = p1
        manager.providers["p2"] = p2

        # All latencies default to inf → best_provider stays None → falls back to providers[0]
        result = await manager._lowest_latency_select(["p1", "p2"])
        assert result == "p1"


class TestCostOptimizedSelect:
    def test_selects_cheapest_provider(self):
        manager = _make_manager(RoutingStrategy.COST_OPTIMIZED)
        p_cheap = _make_mock_provider("cheap")
        p_cheap.get_model_info = MagicMock(
            return_value=SimpleNamespace(input_cost_per_1k=0.5, output_cost_per_1k=0.5)
        )
        p_expensive = _make_mock_provider("expensive")
        p_expensive.get_model_info = MagicMock(
            return_value=SimpleNamespace(input_cost_per_1k=5.0, output_cost_per_1k=5.0)
        )
        manager.providers["cheap"] = p_cheap
        manager.providers["expensive"] = p_expensive

        result = manager._cost_optimized_select(["cheap", "expensive"], model="model-a")
        assert result == "cheap"

    def test_no_model_fallback_to_first_provider(self):
        manager = _make_manager(RoutingStrategy.COST_OPTIMIZED)
        manager.providers["p1"] = _make_mock_provider("p1")
        manager.providers["p2"] = _make_mock_provider("p2")

        result = manager._cost_optimized_select(["p1", "p2"], model=None)
        assert result == "p1"


class TestSelectProviderByModel:
    @pytest.mark.asyncio
    async def test_selects_provider_that_supports_model(self):
        manager = _make_manager()
        manager.providers["p1"] = _make_mock_provider("p1", models=["model-x"])
        manager.providers["p2"] = _make_mock_provider("p2", models=["model-y"])
        manager.provider_configs["p1"] = ProviderConfig("t", {"id": "p1"}, enabled=True)
        manager.provider_configs["p2"] = ProviderConfig("t", {"id": "p2"}, enabled=True)

        result = await manager.select_provider(model="model-y")
        assert result == "p2"

    @pytest.mark.asyncio
    async def test_no_provider_supports_model_returns_none(self):
        manager = _make_manager()
        manager.providers["p1"] = _make_mock_provider("p1", models=["model-a"])
        manager.provider_configs["p1"] = ProviderConfig("t", {"id": "p1"}, enabled=True)

        result = await manager.select_provider(model="model-unknown")
        assert result is None


class TestChatCompletionFailover:
    @pytest.mark.asyncio
    async def test_primary_failure_falls_over_to_backup(self):
        manager = _make_manager()
        manager.round_robin_index = 0

        primary = _make_mock_provider("primary")
        primary.chat_completion = AsyncMock(side_effect=RuntimeError("primary failed"))

        backup_response = {"choices": [{"message": {"content": "backup ok"}}]}
        backup = _make_mock_provider("backup")
        backup.chat_completion = AsyncMock(return_value=backup_response)

        manager.providers["primary"] = primary
        manager.providers["backup"] = backup
        manager.provider_configs["primary"] = ProviderConfig("t", {"id": "primary"}, enabled=True)
        manager.provider_configs["backup"] = ProviderConfig("t", {"id": "backup"}, enabled=True)

        result = await manager.chat_completion([{"role": "user", "content": "hi"}])
        assert result == backup_response

    @pytest.mark.asyncio
    async def test_all_providers_fail_raises_original_exception(self):
        manager = _make_manager()
        manager.round_robin_index = 0

        only_provider = _make_mock_provider("only")
        only_provider.chat_completion = AsyncMock(side_effect=RuntimeError("all failed"))
        manager.providers["only"] = only_provider
        manager.provider_configs["only"] = ProviderConfig("t", {"id": "only"}, enabled=True)

        with pytest.raises(RuntimeError, match="all failed"):
            await manager.chat_completion([{"role": "user", "content": "hi"}])


class TestHealthCheckThrottling:
    @pytest.mark.asyncio
    async def test_recent_health_check_returns_cached_results(self):
        manager = _make_manager()
        cached = {"p1": ProviderStatus.HEALTHY}
        manager.last_health_results = cached.copy()
        manager.last_health_check = time.time()  # Just ran — within throttle window

        result = await manager.health_check_all()
        assert result == cached

    @pytest.mark.asyncio
    async def test_stale_health_check_reruns_checks(self):
        manager = _make_manager()
        p1 = _make_mock_provider("p1", status=ProviderStatus.HEALTHY)
        manager.providers["p1"] = p1
        manager.provider_configs["p1"] = ProviderConfig("t", {"id": "p1"}, enabled=True)
        manager.last_health_check = 0  # Force re-check

        result = await manager.health_check_all()
        assert "p1" in result
        p1.health_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_unhealthy_provider_gets_disabled(self):
        manager = _make_manager()
        p1 = _make_mock_provider("p1", status=ProviderStatus.UNHEALTHY)
        manager.providers["p1"] = p1
        manager.provider_configs["p1"] = ProviderConfig("t", {"id": "p1"}, enabled=True)
        manager.last_health_check = 0  # Force re-check

        await manager.health_check_all()

        assert manager.provider_configs["p1"].enabled is False
