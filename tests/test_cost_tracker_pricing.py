"""P1-2: Verify cost_tracker pricing integration with config/model_pricing.yml."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

import yaml
from cost_tracker import estimate_cost, usage_entry, load_pricing


class CostTrackerPricingTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir(parents=True)
        (self.root / "config" / "model_pricing.yml").write_text(
            yaml.safe_dump({
                "version": 1,
                "currency": "USD",
                "models": {
                    "test-model": {
                        "input_per_1m": 2.0,
                        "output_per_1m": 6.0,
                        "notes": "Test model.",
                    },
                    "null-price-model": {
                        "input_per_1m": None,
                        "output_per_1m": None,
                        "notes": "Subscription quota.",
                    },
                },
            }, sort_keys=False),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_pricing_loaded_and_cached(self) -> None:
        pricing = load_pricing(self.root)
        self.assertIn("models", pricing)
        self.assertIn("test-model", pricing["models"])
        pricing2 = load_pricing(self.root)
        self.assertIs(pricing, pricing2)

    def test_known_model_with_tokens_has_cost(self) -> None:
        info = estimate_cost(self.root, "test-model", 1_000_000, 1_000_000)
        self.assertEqual(info["estimated_cost"], 8.0)
        self.assertEqual(info["cost_currency"], "USD")
        self.assertTrue(info["exact_cost_available"])
        self.assertIsNotNone(info["pricing_source"])

    def test_unknown_model_cost_none(self) -> None:
        info = estimate_cost(self.root, "no-such-model", 1000, 1000)
        self.assertIsNone(info["estimated_cost"])
        self.assertFalse(info["exact_cost_available"])

    def test_null_price_model_cost_unavailable(self) -> None:
        info = estimate_cost(self.root, "null-price-model", 1000, 1000)
        self.assertIsNone(info["estimated_cost"])
        self.assertFalse(info["exact_cost_available"])

    def test_missing_tokens_cost_unavailable(self) -> None:
        info = estimate_cost(self.root, "test-model", None, 1000)
        self.assertIsNone(info["estimated_cost"])
        self.assertFalse(info["exact_cost_available"])

    def test_usage_entry_with_agentlab_root_includes_cost(self) -> None:
        entry = usage_entry(
            "Demo", "task_001", "TesterAuditor",
            "openai", "test-model", "completed",
            input_tokens=100_000, output_tokens=50_000,
            agentlab_root=self.root,
        )
        self.assertEqual(entry["estimated_cost"], 0.5)
        self.assertEqual(entry["cost_currency"], "USD")
        self.assertTrue(entry["exact_cost_available"])

    def test_usage_entry_without_agentlab_root_is_legacy(self) -> None:
        entry = usage_entry(
            "Demo", "task_001", "TesterAuditor",
            "openai", "test-model", "completed",
            input_tokens=100_000, output_tokens=50_000,
        )
        self.assertIsNone(entry["estimated_cost"])
        self.assertIsNone(entry["cost_currency"])

    def test_pricing_config_missing_returns_empty_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp2:
            root2 = Path(tmp2)
            pricing = load_pricing(root2)
            self.assertEqual(pricing, {})

    def test_append_cost_ledgers_writes_to_run_and_project(self) -> None:
        from cost_tracker import append_cost_ledgers
        project_root = self.root / "projects" / "Demo"
        run_dir = project_root / "runs" / "task_cost_001"
        run_dir.mkdir(parents=True)
        entry = usage_entry(
            "Demo", "task_cost_001", "Coder",
            "openai", "test-model", "completed",
            input_tokens=1000, output_tokens=500,
            agentlab_root=self.root,
        )
        append_cost_ledgers(project_root, run_dir, entry)
        run_ledger = run_dir / "cost_ledger.yml"
        self.assertTrue(run_ledger.exists())
        data = yaml.safe_load(run_ledger.read_text(encoding="utf-8"))
        self.assertEqual(len(data["entries"]), 1)
        self.assertIsNotNone(data["entries"][0]["estimated_cost"])


if __name__ == "__main__":
    main()