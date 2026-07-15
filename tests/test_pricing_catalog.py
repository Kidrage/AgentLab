from pathlib import Path

from agent_runtime.costing.catalog import PricingCatalog


ROOT = Path(__file__).resolve().parents[1]


def test_supplier_native_price_is_preserved_and_converted_with_versioned_fx():
    catalog = PricingCatalog.load(ROOT)

    quote = catalog.quote(
        "deepseek_v4_pro",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    assert quote.native_currency == "USD"
    assert quote.native_amount == 1.305
    assert quote.cny_amount == 9.396
    assert quote.fx_version == "2026-07-15-operational"
    assert quote.pricing_source == "config/model_pricing.yml#deepseek-v4-pro"


def test_qwen_supplier_usd_price_is_converted_once_with_versioned_fx():
    catalog = PricingCatalog.load(ROOT)
    quote = catalog.quote(
        "qwen3_6_plus_dashscope",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    assert quote.native_currency == "USD"
    assert quote.native_amount == 1.927
    assert quote.cny_amount == 13.8744


def test_runtime_projection_does_not_duplicate_numeric_authority():
    catalog = PricingCatalog.load(ROOT)
    entry = catalog.models["qwen3_6_plus_dashscope"]

    assert entry["source_ref"] == "config/model_pricing.yml#qwen3.6-plus"
    assert entry["input_per_1m"] == 0.276
    assert entry["output_per_1m"] == 1.651
    raw = (ROOT / "config" / "pricing_catalog.yml").read_text(encoding="utf-8")
    assert "input_per_1m:" not in raw
    assert "output_per_1m:" not in raw


def test_subscription_shell_has_zero_marginal_cash_but_keeps_billing_mode():
    quote = PricingCatalog.load(ROOT).quote(
        "codex_gpt_5_5_high_hermes_oauth",
        input_tokens=10_000_000,
        output_tokens=1_000_000,
    )

    assert quote.billing_mode == "oauth_subscription"
    assert quote.native_amount == 0.0
    assert quote.cash_basis == "marginal_task_cash"
