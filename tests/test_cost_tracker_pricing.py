"""P1.5: Verify cost_tracker pricing ledger field consistency and combo-key support."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

import yaml
from cost_tracker import (
    estimate_cost,
    usage_entry,
    load_pricing,
    append_cost_ledgers,
    _resolve_model_entry,
    _PRICE_CACHE,
    _PRICE_ROOT,
)


def _clear_price_cache() -> None:
    import cost_tracker
    cost_tracker._PRICE_CACHE = None
    cost_tracker._PRICE_ROOT = None


class CostTrackerPricingTests(TestCase):
    """P1-2 original tests – kept for regression."""

    def setUp(self) -> None:
        _clear_price_cache()
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
        _clear_price_cache()

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
        _clear_price_cache()
        with tempfile.TemporaryDirectory() as tmp2:
            root2 = Path(tmp2)
            pricing = load_pricing(root2)
            self.assertEqual(pricing, {})

    def test_append_cost_ledgers_writes_to_run_and_project(self) -> None:
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


class P15PricingLedgerTests(TestCase):
    """P1.5: pricing_source field consistency and append_cost_ledgers field preservation."""

    def setUp(self) -> None:
        _clear_price_cache()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        _clear_price_cache()

    def _write_pricing(self, models: dict) -> None:
        (self.root / "config" / "model_pricing.yml").write_text(
            yaml.safe_dump({
                "version": 1,
                "currency": "USD",
                "models": models,
            }, sort_keys=False),
            encoding="utf-8",
        )

    # ── Test 1: usage_entry writes pricing_source for known model ──

    def test_usage_entry_includes_pricing_source_for_known_model(self) -> None:
        self._write_pricing({
            "test-model": {
                "input_per_1m": 1.0,
                "output_per_1m": 2.0,
            },
        })
        entry = usage_entry(
            "Tester", "task_x", "Auditor",
            "test-provider", "test-model", "completed",
            input_tokens=1_000_000, output_tokens=500_000,
            agentlab_root=self.root,
        )
        self.assertEqual(entry["estimated_cost"], 2.0)
        self.assertEqual(entry["cost_currency"], "USD")
        self.assertTrue(entry["exact_cost_available"])
        self.assertEqual(entry["pricing_source"], "config/model_pricing.yml")

    # ── Test 2: missing model still has pricing_source field ──

    def test_usage_entry_missing_model_has_pricing_source_field(self) -> None:
        self._write_pricing({
            "test-model": {
                "input_per_1m": 1.0,
                "output_per_1m": 2.0,
            },
        })
        entry = usage_entry(
            "Tester", "task_x", "Auditor",
            "test-provider", "missing-model", "completed",
            input_tokens=1_000, output_tokens=1_000,
            agentlab_root=self.root,
        )
        self.assertIn("pricing_source", entry)
        self.assertFalse(entry["exact_cost_available"])
        # missing model: pricing_source may be None (file existed but model not found)
        self.assertIsNone(entry["pricing_source"])

    # ── Test 3: null-price model retains pricing_source ──

    def test_usage_entry_null_price_model_has_pricing_source(self) -> None:
        self._write_pricing({
            "codex_plus_manual": {
                "input_per_1m": None,
                "output_per_1m": None,
            },
        })
        entry = usage_entry(
            "Tester", "task_x", "Auditor",
            "test-provider", "codex_plus_manual", "completed",
            input_tokens=1_000, output_tokens=1_000,
            agentlab_root=self.root,
        )
        self.assertIsNone(entry["estimated_cost"])
        self.assertFalse(entry["exact_cost_available"])
        self.assertIn("pricing_source", entry)
        self.assertEqual(entry["pricing_source"], "config/model_pricing.yml")

    # ── Test 4: legacy path (no agentlab_root) includes pricing_source = None ──

    def test_usage_entry_legacy_path_includes_pricing_source_none(self) -> None:
        entry = usage_entry(
            "Tester", "task_x", "Auditor",
            "openai", "gpt-4", "completed",
            input_tokens=100, output_tokens=100,
            total_tokens=200,
        )
        self.assertIsNone(entry["estimated_cost"])
        self.assertIsNone(entry["cost_currency"])
        self.assertIn("pricing_source", entry)
        self.assertIsNone(entry["pricing_source"])

    # ── Test 5: append_cost_ledgers preserves all pricing fields ──

    def test_append_cost_ledgers_preserves_pricing_fields(self) -> None:
        self._write_pricing({
            "test-model": {
                "input_per_1m": 1.0,
                "output_per_1m": 2.0,
            },
        })
        project_root = self.root / "projects" / "Demo"
        run_dir = project_root / "runs" / "task_pricing_001"
        run_dir.mkdir(parents=True)

        entry = usage_entry(
            "Tester", "task_pricing_001", "Coder",
            "test-provider", "test-model", "completed",
            input_tokens=1_000_000, output_tokens=500_000,
            agentlab_root=self.root,
        )
        append_cost_ledgers(project_root, run_dir, entry)

        # Check run ledger
        run_ledger = run_dir / "cost_ledger.yml"
        data = yaml.safe_load(run_ledger.read_text(encoding="utf-8"))
        record = data["entries"][0]
        self.assertEqual(record["pricing_source"], "config/model_pricing.yml")
        self.assertEqual(record["estimated_cost"], 2.0)
        self.assertEqual(record["cost_currency"], "USD")
        self.assertTrue(record["exact_cost_available"])

        # Check project ledger
        proj_ledger = project_root / "agent_docs" / "09_COST_LEDGER.yml"
        pdata = yaml.safe_load(proj_ledger.read_text(encoding="utf-8"))
        precord = pdata["entries"][0]
        self.assertEqual(precord["pricing_source"], "config/model_pricing.yml")
        self.assertEqual(precord["estimated_cost"], 2.0)
        self.assertEqual(precord["cost_currency"], "USD")
        self.assertTrue(precord["exact_cost_available"])

    # ── Test 6: append_cost_ledgers with explicit pricing fields ──

    def test_append_cost_ledgers_preserves_explicit_pricing_entry(self) -> None:
        project_root = self.root / "projects" / "ExplicitDemo"
        run_dir = project_root / "runs" / "task_explicit_001"
        run_dir.mkdir(parents=True)

        entry = {
            "agent": "Tester",
            "provider": "test-provider",
            "model": "test-model",
            "input_tokens": 1,
            "output_tokens": 2,
            "total_tokens": 3,
            "estimated_cost": 0.01,
            "cost_currency": "USD",
            "exact_cost_available": True,
            "pricing_source": "config/model_pricing.yml",
        }
        append_cost_ledgers(project_root, run_dir, entry)

        # Run ledger
        run_ledger = run_dir / "cost_ledger.yml"
        data = yaml.safe_load(run_ledger.read_text(encoding="utf-8"))
        record = data["entries"][0]
        self.assertEqual(record["pricing_source"], "config/model_pricing.yml")
        self.assertEqual(record["estimated_cost"], 0.01)
        self.assertEqual(record["cost_currency"], "USD")
        self.assertTrue(record["exact_cost_available"])

        # Project ledger
        proj_ledger = project_root / "agent_docs" / "09_COST_LEDGER.yml"
        pdata = yaml.safe_load(proj_ledger.read_text(encoding="utf-8"))
        precord = pdata["entries"][0]
        self.assertEqual(precord["pricing_source"], "config/model_pricing.yml")
        self.assertEqual(precord["estimated_cost"], 0.01)
        self.assertEqual(precord["cost_currency"], "USD")
        self.assertTrue(precord["exact_cost_available"])


class P15ComboKeyTests(TestCase):
    """P1.5-4: provider/model combo key support in estimate_cost."""

    def setUp(self) -> None:
        _clear_price_cache()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        _clear_price_cache()

    def _write_pricing(self, models: dict) -> None:
        (self.root / "config" / "model_pricing.yml").write_text(
            yaml.safe_dump({
                "version": 1,
                "currency": "USD",
                "models": models,
            }, sort_keys=False),
            encoding="utf-8",
        )

    def test_combo_key_fallback_to_plain_model(self) -> None:
        self._write_pricing({
            "test-model": {
                "input_per_1m": 1.0,
                "output_per_1m": 2.0,
            },
        })
        # No combo key, provider should be ignored and fallback to plain model
        info = estimate_cost(self.root, "test-model", 1_000_000, 500_000, provider="my-provider")
        self.assertEqual(info["estimated_cost"], 2.0)
        self.assertTrue(info["exact_cost_available"])

    def test_combo_key_takes_priority(self) -> None:
        self._write_pricing({
            "test-model": {
                "input_per_1m": 1.0,
                "output_per_1m": 2.0,
            },
            "my-provider/test-model": {
                "input_per_1m": 1.2,
                "output_per_1m": 2.4,
            },
        })
        info = estimate_cost(self.root, "test-model", 1_000_000, 500_000, provider="my-provider")
        # combo: 1M * 1.2 + 0.5M * 2.4 = 1.2 + 1.2 = 2.4
        self.assertEqual(info["estimated_cost"], 2.4)
        self.assertTrue(info["exact_cost_available"])
        self.assertEqual(info["pricing_source"], "config/model_pricing.yml")

    def test_combo_key_not_matched_without_provider(self) -> None:
        self._write_pricing({
            "test-model": {
                "input_per_1m": 1.0,
                "output_per_1m": 2.0,
            },
            "my-provider/test-model": {
                "input_per_1m": 1.2,
                "output_per_1m": 2.4,
            },
        })
        # No provider arg => fallback to plain model
        info = estimate_cost(self.root, "test-model", 1_000_000, 500_000)
        self.assertEqual(info["estimated_cost"], 2.0)  # plain, not combo
        self.assertTrue(info["exact_cost_available"])

    def test_combo_key_unknown_model_returns_none(self) -> None:
        self._write_pricing({
            "test-model": {
                "input_per_1m": 1.0,
                "output_per_1m": 2.0,
            },
        })
        info = estimate_cost(
            self.root, "no-such-model", 1000, 1000, provider="my-provider",
        )
        self.assertIsNone(info["estimated_cost"])
        self.assertFalse(info["exact_cost_available"])
        self.assertIsNone(info["pricing_source"])

    def test_usage_entry_passes_provider_for_combo_key(self) -> None:
        self._write_pricing({
            "test-model": {
                "input_per_1m": 1.0,
                "output_per_1m": 2.0,
            },
            "openai/test-model": {
                "input_per_1m": 1.5,
                "output_per_1m": 3.0,
            },
        })
        entry = usage_entry(
            "Demo", "task_001", "Coder",
            "openai", "test-model", "completed",
            input_tokens=1_000_000, output_tokens=500_000,
            agentlab_root=self.root,
        )
        # combo: 1M * 1.5 + 0.5M * 3.0 = 1.5 + 1.5 = 3.0
        self.assertEqual(entry["estimated_cost"], 3.0)
        self.assertTrue(entry["exact_cost_available"])
        self.assertEqual(entry["pricing_source"], "config/model_pricing.yml")


if __name__ == "__main__":
    main()