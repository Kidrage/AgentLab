from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from costing.ledger import CostCall, CostLedger, write_cost_artifacts
from costing.pricing import PriceResolver
from costing.usage import normalize_usage


def _write_pricing(root: Path, models: dict) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "model_pricing.yml").write_text(
        yaml.safe_dump({"version": 1, "currency": "USD", "models": models}, sort_keys=False),
        encoding="utf-8",
    )


def test_usage_record_preserves_api_usage() -> None:
    usage = normalize_usage({"prompt_tokens": 123, "completion_tokens": 45})

    assert usage.input_tokens == 123
    assert usage.output_tokens == 45
    assert usage.usage_source == "api_usage"


def test_price_resolver_known_model(tmp_path: Path) -> None:
    _write_pricing(tmp_path, {
        "qwen3-coder-next": {
            "provider": "qwen",
            "input_per_1m_usd": 0.144,
            "output_per_1m_usd": 0.574,
            "pricing_confidence": "medium",
        }
    })

    price = PriceResolver(tmp_path).resolve(model_alias="qwen3-coder-next", provider="qwen")
    cost = price.estimate_cost_usd(input_tokens=1_000_000, output_tokens=1_000_000)

    assert cost == 0.718
    assert price.price_source == "config/model_pricing.yml"
    assert price.pricing_confidence == "medium"


def test_price_resolver_unknown_model_does_not_fake_zero(tmp_path: Path) -> None:
    _write_pricing(tmp_path, {})

    price = PriceResolver(tmp_path).resolve(model_alias="missing-model")
    cost = price.estimate_cost_usd(input_tokens=1000, output_tokens=1000)

    assert cost is None
    assert price.pricing_confidence == "none"


def test_zero_price_without_free_flag_does_not_fake_free(tmp_path: Path) -> None:
    _write_pricing(tmp_path, {
        "tbd-model": {
            "input_per_1m_usd": 0,
            "output_per_1m_usd": 0,
            "pricing_confidence": "none",
        }
    })

    price = PriceResolver(tmp_path).resolve(model_alias="tbd-model")

    assert price.estimate_cost_usd(input_tokens=1000, output_tokens=1000) is None


def test_cost_ledger_writes_yaml_and_summary(tmp_path: Path) -> None:
    call = CostCall(
        stage="Supervisor",
        agent="Supervisor",
        provider="qwen",
        model_alias="qwen3-coder-next",
        provider_model_id="qwen-coder",
        input_tokens=1000,
        output_tokens=500,
        usage_source="api_usage",
        price_source="config/model_pricing.yml",
        estimated_cost_usd=0.000431,
        pricing_confidence="medium",
    )
    ledger = CostLedger(task_id="task_xxx", calls=[call])

    ledger_path, summary_path = write_cost_artifacts(tmp_path, ledger)

    assert ledger_path.exists()
    assert summary_path.exists()
    data = yaml.safe_load(ledger_path.read_text(encoding="utf-8"))
    assert data["task_id"] == "task_xxx"
    assert data["calls"][0]["stage"] == "Supervisor"
    assert data["calls"][0]["model_alias"] == "qwen3-coder-next"
    assert data["total"]["input_tokens"] == 1000
    summary = summary_path.read_text(encoding="utf-8")
    assert "Cost Summary" in summary
    assert "qwen3-coder-next" in summary
    assert "api_usage" in summary
