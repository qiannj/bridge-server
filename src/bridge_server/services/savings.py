from __future__ import annotations

from typing import Any, Optional, Tuple

RMB_PER_USD = 7.2


def resolve_baseline_model(task_type: str, savings_config: Optional[dict]) -> Tuple[Optional[str], str]:
    """Resolve the configured baseline model for a request task type.

    Precedence: scenario override > default model.
    Returns (baseline_model, baseline_source).
    """
    baseline = (savings_config or {}).get("baseline") or {}
    scenarios = baseline.get("scenarios") or {}

    if task_type and scenarios.get(task_type):
        return scenarios[task_type], "scenario_override"

    default_model = baseline.get("default_model")
    return default_model, "default"


def estimate_baseline_cost_rmb(
    baseline_model: str,
    input_tokens: int,
    output_tokens: int,
    provider_manager: Any = None,
    provider_catalog: Any = None,
) -> Optional[float]:
    """Estimate RMB cost for the configured baseline model.

    Looks up pricing from the runtime provider manager first, then falls back to
    the static provider catalog. Returns None when pricing is unavailable.
    """
    provider_id, model_id = _parse_model_ref(baseline_model)
    if not provider_id or not model_id:
        return None

    pricing = _lookup_pricing(
        provider_id=provider_id,
        model_id=model_id,
        provider_manager=provider_manager,
        provider_catalog=provider_catalog,
    )
    if pricing is None:
        return None

    input_cost_per_1k, output_cost_per_1k, currency = pricing
    baseline_cost = (
        (max(input_tokens, 0) / 1000.0) * input_cost_per_1k
        + (max(output_tokens, 0) / 1000.0) * output_cost_per_1k
    )
    return _convert_to_rmb(baseline_cost, currency)


def estimate_model_cost_usd(
    model_ref: str,
    input_tokens: int,
    output_tokens: int,
    provider_manager: Any = None,
    provider_catalog: Any = None,
) -> Optional[float]:
    """Estimate USD cost for any provider/model reference."""
    provider_id, model_id = _parse_model_ref(model_ref)
    if not provider_id or not model_id:
        return None

    pricing = _lookup_pricing(
        provider_id=provider_id,
        model_id=model_id,
        provider_manager=provider_manager,
        provider_catalog=provider_catalog,
    )
    if pricing is None:
        return None

    input_cost_per_1k, output_cost_per_1k, currency = pricing
    raw_cost = (
        (max(input_tokens, 0) / 1000.0) * input_cost_per_1k
        + (max(output_tokens, 0) / 1000.0) * output_cost_per_1k
    )
    return _convert_to_usd(raw_cost, currency)


def _parse_model_ref(model_ref: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not model_ref or "/" not in model_ref:
        return None, None
    provider_id, model_id = model_ref.split("/", 1)
    provider_id = provider_id.strip() or None
    model_id = model_id.strip() or None
    return provider_id, model_id


def _lookup_pricing(
    *,
    provider_id: str,
    model_id: str,
    provider_manager: Any = None,
    provider_catalog: Any = None,
) -> Optional[Tuple[float, float, str]]:
    provider = getattr(provider_manager, "providers", {}).get(provider_id) if provider_manager else None
    if provider is not None:
        model_info = provider.get_model_info(model_id)
        if model_info is not None:
            return (
                float(getattr(model_info, "input_cost_per_1k", 0.0)),
                float(getattr(model_info, "output_cost_per_1k", 0.0)),
                "USD",
            )

    if provider_catalog is not None and hasattr(provider_catalog, "get_model"):
        model = provider_catalog.get_model(provider_id, model_id)
        pricing = getattr(model, "pricing", None) if model is not None else None
        if pricing is not None:
            return (
                float(getattr(pricing, "input_per_1k", 0.0)),
                float(getattr(pricing, "output_per_1k", 0.0)),
                getattr(pricing, "currency", "USD"),
            )

    return None


def _convert_to_rmb(amount: float, currency: str) -> float:
    normalized = (currency or "USD").upper()
    if normalized in {"RMB", "CNY"}:
        return amount
    if normalized == "USD":
        return amount * RMB_PER_USD
    return amount


def _convert_to_usd(amount: float, currency: str) -> float:
    normalized = (currency or "USD").upper()
    if normalized == "USD":
        return amount
    if normalized in {"RMB", "CNY"}:
        return amount / RMB_PER_USD
    return amount
