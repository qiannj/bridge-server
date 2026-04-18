"""Unit tests for provider implementations — API key security and metrics."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

# The inline import inside BaseProvider._create_http_client resolves this name
# from the module object at call time, so patching the module attribute is
# sufficient to intercept every provider instantiation.
_PATCH_TARGET = "bridge_server.utils.connection_pools.get_provider_http_client"


@pytest.fixture
def mock_http_client():
    """Patch get_provider_http_client so no real HTTP client is created."""
    mock_client = MagicMock()
    with patch(_PATCH_TARGET, return_value=mock_client):
        yield mock_client


class TestOpenAIApiKeySecurity:
    def test_api_key_popped_from_config(self, mock_http_client):
        from bridge_server.providers.openai import OpenAIProvider

        config = {"api_key": "sk-test123"}
        provider = OpenAIProvider(config)
        assert "api_key" not in provider.config

    def test_api_key_stored_on_self(self, mock_http_client):
        from bridge_server.providers.openai import OpenAIProvider

        config = {"api_key": "sk-test123"}
        provider = OpenAIProvider(config)
        assert provider.api_key == "sk-test123"

    def test_header_has_bearer_token(self, mock_http_client):
        from bridge_server.providers.openai import OpenAIProvider

        provider = OpenAIProvider({"api_key": "sk-mykey"})
        assert provider._get_headers()["Authorization"] == "Bearer sk-mykey"

    def test_missing_api_key_raises_value_error(self, mock_http_client, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from bridge_server.providers.openai import OpenAIProvider

        with pytest.raises(ValueError):
            OpenAIProvider({})


class TestDashScopeApiKeySecurity:
    def test_api_key_popped_from_config(self, mock_http_client):
        from bridge_server.providers.dashscope import DashScopeProvider

        config = {"api_key": "ds-test123"}
        provider = DashScopeProvider(config)
        assert "api_key" not in provider.config

    def test_api_key_stored_on_self(self, mock_http_client):
        from bridge_server.providers.dashscope import DashScopeProvider

        config = {"api_key": "ds-test123"}
        provider = DashScopeProvider(config)
        assert provider.api_key == "ds-test123"

    def test_header_has_bearer_token(self, mock_http_client):
        from bridge_server.providers.dashscope import DashScopeProvider

        provider = DashScopeProvider({"api_key": "ds-mykey"})
        assert provider._get_headers()["Authorization"] == "Bearer ds-mykey"

    def test_missing_api_key_raises_value_error(self, mock_http_client, monkeypatch):
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        from bridge_server.providers.dashscope import DashScopeProvider

        with pytest.raises(ValueError):
            DashScopeProvider({})


class TestMoonshotApiKeySecurity:
    def test_api_key_popped_from_config(self, mock_http_client):
        from bridge_server.providers.moonshot import MoonshotProvider

        config = {"api_key": "ms-test123"}
        provider = MoonshotProvider(config)
        assert "api_key" not in provider.config

    def test_api_key_stored_on_self(self, mock_http_client):
        from bridge_server.providers.moonshot import MoonshotProvider

        config = {"api_key": "ms-test123"}
        provider = MoonshotProvider(config)
        assert provider.api_key == "ms-test123"

    def test_header_has_bearer_token(self, mock_http_client):
        from bridge_server.providers.moonshot import MoonshotProvider

        provider = MoonshotProvider({"api_key": "ms-mykey"})
        assert provider._get_headers()["Authorization"] == "Bearer ms-mykey"

    def test_missing_api_key_raises_value_error(self, mock_http_client, monkeypatch):
        monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
        from bridge_server.providers.moonshot import MoonshotProvider

        with pytest.raises(ValueError):
            MoonshotProvider({})


class TestBaseProviderMetrics:
    @pytest.fixture(autouse=True)
    def setup_provider(self, mock_http_client):
        from bridge_server.providers.dashscope import DashScopeProvider

        self._provider = DashScopeProvider({"api_key": "test-key"})

    def test_success_rate_at_zero_requests(self):
        assert self._provider.metrics.success_rate == 1.0

    def test_success_rate_with_mixed_calls(self):
        self._provider._record_success(100.0)
        self._provider._record_failure()
        # 1 success out of 2 total
        assert self._provider.metrics.success_rate == pytest.approx(0.5)

    def test_average_latency_at_zero_requests(self):
        assert self._provider.metrics.average_latency == 0.0

    def test_average_latency_calculation(self):
        self._provider._record_success(100.0)
        self._provider._record_success(200.0)
        assert self._provider.metrics.average_latency == pytest.approx(150.0)

    def test_get_supported_models_non_empty(self):
        models = self._provider.get_supported_models()
        assert len(models) > 0

    def test_get_model_info_existing(self):
        models = self._provider.get_supported_models()
        model_id = models[0]
        info = self._provider.get_model_info(model_id)
        assert info is not None
        assert info.id == model_id

    def test_get_model_info_missing(self):
        assert self._provider.get_model_info("nonexistent-model-xyz") is None
