"""Unit tests for ProviderLoader and Provider/Model data classes."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import pytest

from bridge_server.provider_catalog import Model, ModelPricing, Provider, ProviderLoader


class TestProviderLoader:
    def test_loads_successfully(self):
        loader = ProviderLoader()
        providers = loader.load()
        assert len(providers) > 0

    def test_returns_provider_objects(self):
        loader = ProviderLoader()
        providers = loader.load()
        for p in providers.values():
            assert isinstance(p, Provider)

    def test_all_providers_have_non_empty_id_name_base_url(self):
        loader = ProviderLoader()
        providers = loader.load()
        for p in providers.values():
            assert p.id != ""
            assert p.name != ""
            assert p.base_url != ""

    def test_second_load_returns_same_object(self):
        loader = ProviderLoader()
        first = loader.load()
        second = loader.load()
        assert first is second

    def test_force_reload_returns_identical_content(self):
        loader = ProviderLoader()
        first = loader.load()
        second = loader.load(force=True)
        assert set(first.keys()) == set(second.keys())

    def test_missing_file_raises_file_not_found(self, tmp_path):
        loader = ProviderLoader(registry_path=str(tmp_path / "nonexistent.yaml"))
        with pytest.raises(FileNotFoundError):
            loader.load()


class TestModelDataclass:
    def test_supports_true_for_existing_capability(self):
        model = Model(
            id="m1", name="M1", description="", context_length=8192,
            max_output_tokens=2048, capabilities=["chat", "code"],
        )
        assert model.supports("chat") is True
        assert model.supports("code") is True

    def test_supports_false_for_missing_capability(self):
        model = Model(
            id="m1", name="M1", description="", context_length=8192,
            max_output_tokens=2048, capabilities=["chat"],
        )
        assert model.supports("vision") is False

    def test_get_benchmark_existing(self):
        model = Model(
            id="m1", name="M1", description="", context_length=8192,
            max_output_tokens=2048, benchmarks={"MMLU": 85.5},
        )
        assert model.get_benchmark("MMLU") == pytest.approx(85.5)

    def test_get_benchmark_missing_returns_none(self):
        model = Model(
            id="m1", name="M1", description="", context_length=8192,
            max_output_tokens=2048,
        )
        assert model.get_benchmark("nonexistent") is None


class TestProviderDataclass:
    def _make_provider(self, models=None) -> Provider:
        return Provider(
            id="test-p",
            name="Test Provider",
            name_en="Test Provider",
            region="US",
            headquarters="US",
            website="https://test.com",
            base_url="https://api.test.com",
            api_key_env="TEST_API_KEY",
            api_key_url="https://test.com/api-keys",
            status="active",
            models=models or [],
        )

    def _make_model(self, model_id: str, input_price: float) -> Model:
        return Model(
            id=model_id,
            name=model_id,
            description="",
            context_length=8192,
            max_output_tokens=2048,
            pricing=ModelPricing(
                currency="USD",
                input_per_1k=input_price,
                output_per_1k=input_price * 2,
            ),
        )

    def test_get_cheapest_model_selects_min_input_price(self):
        cheap = self._make_model("cheap", 0.001)
        expensive = self._make_model("expensive", 0.01)
        provider = self._make_provider([cheap, expensive])
        assert provider.get_cheapest_model() is cheap

    def test_get_most_powerful_selects_max_input_price(self):
        cheap = self._make_model("cheap", 0.001)
        expensive = self._make_model("expensive", 0.01)
        provider = self._make_provider([cheap, expensive])
        assert provider.get_most_powerful_model() is expensive

    def test_get_model_by_id_found(self):
        model = self._make_model("target-model", 0.005)
        provider = self._make_provider([model])
        assert provider.get_model("target-model") is model

    def test_get_model_by_id_not_found(self):
        provider = self._make_provider()
        assert provider.get_model("missing") is None

    def test_api_base_equals_base_url(self):
        provider = self._make_provider()
        assert provider.api_base == provider.base_url

    def test_no_pricing_get_cheapest_returns_none(self):
        model = Model(
            id="m1", name="M1", description="", context_length=8192,
            max_output_tokens=2048, pricing=None,
        )
        provider = self._make_provider([model])
        assert provider.get_cheapest_model() is None

    def test_no_pricing_get_most_powerful_returns_none(self):
        model = Model(
            id="m1", name="M1", description="", context_length=8192,
            max_output_tokens=2048, pricing=None,
        )
        provider = self._make_provider([model])
        assert provider.get_most_powerful_model() is None
