from __future__ import annotations

from types import SimpleNamespace

import pytest

from conftest import REPO_ROOT, load_module


savings = load_module(
    "bridge_savings_service",
    REPO_ROOT / "src" / "bridge_server" / "services" / "savings.py",
)


def test_resolve_baseline_model_prefers_scenario_override():
    config = {
        "baseline": {
            "default_model": "scnet-coding/Qwen3-235B-A22B",
            "scenarios": {
                "coding": "scnet-coding/MiniMax-M2.5",
            },
        }
    }

    model, source = savings.resolve_baseline_model("coding", config)

    assert model == "scnet-coding/MiniMax-M2.5"
    assert source == "scenario_override"


def test_resolve_baseline_model_falls_back_to_default_model():
    config = {
        "baseline": {
            "default_model": "scnet-coding/Qwen3-235B-A22B",
            "scenarios": {
                "coding": "scnet-coding/MiniMax-M2.5",
            },
        }
    }

    model, source = savings.resolve_baseline_model("summary", config)

    assert model == "scnet-coding/Qwen3-235B-A22B"
    assert source == "default"


def test_resolve_baseline_model_returns_none_when_not_configured():
    model, source = savings.resolve_baseline_model("coding", {})

    assert model is None
    assert source == "default"


def test_estimate_baseline_cost_rmb_uses_provider_manager_model_pricing():
    provider_manager = SimpleNamespace(
        providers={
            "scnet-coding": SimpleNamespace(
                get_model_info=lambda model: SimpleNamespace(
                    input_cost_per_1k=0.10,
                    output_cost_per_1k=0.20,
                )
                if model == "Qwen3-235B-A22B"
                else None
            )
        }
    )

    cost = savings.estimate_baseline_cost_rmb(
        baseline_model="scnet-coding/Qwen3-235B-A22B",
        input_tokens=1500,
        output_tokens=500,
        provider_manager=provider_manager,
    )

    assert cost == pytest.approx(1.8, rel=1e-6)


def test_estimate_baseline_cost_rmb_falls_back_to_provider_catalog_pricing():
    provider_catalog = SimpleNamespace(
        get_model=lambda provider_id, model_id: SimpleNamespace(
            pricing=SimpleNamespace(
                currency="USD",
                input_per_1k=0.05,
                output_per_1k=0.15,
            )
        )
        if (provider_id, model_id) == ("scnet-coding", "MiniMax-M2.5")
        else None
    )

    cost = savings.estimate_baseline_cost_rmb(
        baseline_model="scnet-coding/MiniMax-M2.5",
        input_tokens=2000,
        output_tokens=1000,
        provider_catalog=provider_catalog,
    )

    assert cost == pytest.approx(1.8, rel=1e-6)


def test_estimate_baseline_cost_rmb_returns_none_for_unknown_model():
    cost = savings.estimate_baseline_cost_rmb(
        baseline_model="scnet-coding/unknown-model",
        input_tokens=1000,
        output_tokens=1000,
        provider_manager=SimpleNamespace(providers={}),
        provider_catalog=SimpleNamespace(get_model=lambda *_args, **_kwargs: None),
    )

    assert cost is None
