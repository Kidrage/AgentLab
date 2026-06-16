"""Tests for P2-I cost ledger integration."""

from __future__ import annotations

import pytest

from agent_runtime.costing.ledger import CostLedger, CostCall


class TestRecoveryCostLedgerIntegration:
    """Tests for cost ledger integration with failure recovery."""

    def test_cost_ledger_records_failure_recovery_event(self) -> None:
        """Test that failure recovery events are logged in cost ledger."""
        ledger = CostLedger(task_id="task_0001")
        ledger.currency = "USD"

        # Simulate a failure recovery event
        recovery_call = CostCall(
            stage="recovery_diagnose",
            agent="recovery_system",
            input_tokens=150,
            output_tokens=200,
            provider="mock",
            model_alias="gpt-4",
            usage_source="failure_recovery",
            price_source="mock pricing",
        )
        ledger.calls.append(recovery_call)

        total = ledger.total()

        assert total["input_tokens"] == 150
        assert total["output_tokens"] == 200
        assert len(ledger.calls) == 1

    def test_cost_ledger_multiple_failure_events(self) -> None:
        """Test cost ledger with multiple failure recovery events."""
        ledger = CostLedger(task_id="task_0002")

        # Multiple recovery events
        event1 = CostCall(
            stage="recovery_diagnose",
            agent="recovery_system",
            input_tokens=100,
            output_tokens=50,
        )
        event2 = CostCall(
            stage="recovery_plan",
            agent="recovery_system",
            input_tokens=50,
            output_tokens=100,
        )
        event3 = CostCall(
            stage="recovery_verdict",
            agent="recovery_system",
            input_tokens=20,
            output_tokens=30,
        )

        ledger.calls.extend([event1, event2, event3])

        total = ledger.total()

        assert total["input_tokens"] == 170
        assert total["output_tokens"] == 180
        assert len(ledger.calls) == 3

    def test_cost_ledger_as_dict(self) -> None:
        """Test cost ledger dictionary serialization."""
        ledger = CostLedger(task_id="task_0003")

        call = CostCall(
            stage="recovery",
            agent="recovery_system",
            input_tokens=100,
            output_tokens=50,
        )
        ledger.calls.append(call)

        ledger_dict = ledger.as_dict()

        assert ledger_dict["task_id"] == "task_0003"
        assert "calls" in ledger_dict
        assert len(ledger_dict["calls"]) == 1

        # Check call serialization
        call_dict = ledger_dict["calls"][0]
        assert call_dict["stage"] == "recovery"
        assert call_dict["agent"] == "recovery_system"
        assert call_dict["input_tokens"] == 100
        assert call_dict["output_tokens"] == 50

    def test_cost_ledger_total_calculation(self) -> None:
        """Test cost ledger total calculation."""
        ledger = CostLedger(task_id="task_0004")

        calls = [
            CostCall(stage="A", agent="test", input_tokens=100, output_tokens=50),
            CostCall(stage="B", agent="test", input_tokens=200, output_tokens=100),
            CostCall(stage="C", agent="test", input_tokens=50, output_tokens=25),
        ]

        ledger.calls.extend(calls)

        total = ledger.total()

        assert total["input_tokens"] == 350
        assert total["output_tokens"] == 175

    def test_cost_ledger_unknown_pricing(self) -> None:
        """Test cost ledger with unknown pricing."""
        ledger = CostLedger(task_id="task_0005")

        call = CostCall(
            stage="recovery",
            agent="test",
            input_tokens=100,
            output_tokens=50,
            estimated_cost_usd=None,
            pricing_confidence="none",
        )
        ledger.calls.append(call)

        total = ledger.total()

        assert total["pricing_confidence"] == "none"
        # With one call having no estimated cost, unknown_priced_calls equals calls
        # so pricing_status remains "unknown"
        assert total["estimated_cost_usd"] is None

    def test_cost_ledger_partial_pricing(self) -> None:
        """Test cost ledger with partial pricing."""
        ledger = CostLedger(task_id="task_0006")

        calls = [
            CostCall(
                stage="A",
                agent="test",
                input_tokens=100,
                output_tokens=50,
                estimated_cost_usd=0.01,
                pricing_confidence="high",
            ),
            CostCall(
                stage="B",
                agent="test",
                input_tokens=50,
                output_tokens=25,
                estimated_cost_usd=None,
                pricing_confidence="none",
            ),
        ]

        ledger.calls.extend(calls)

        total = ledger.total()

        assert total["pricing_status"] == "partial"
        assert total["estimated_cost_usd"] == 0.01
        assert len(total["unknown_priced_calls"]) == 1

    def test_cost_ledger_pricing_status(self) -> None:
        """Test cost ledger pricing status."""
        ledger = CostLedger(task_id="task_0007")

        # No calls - pricing status should be unknown
        total = ledger.total()
        assert total["pricing_status"] == "unknown"

        # All priced - pricing status should be complete
        call = CostCall(
            stage="recovery",
            agent="test",
            input_tokens=100,
            output_tokens=50,
            estimated_cost_usd=0.01,
            pricing_confidence="high",
        )
        ledger.calls.append(call)

        total = ledger.total()
        assert total["pricing_status"] == "complete"

    def test_cost_ledger_empty_calls(self) -> None:
        """Test cost ledger with empty calls."""
        ledger = CostLedger(task_id="task_0008")

        total = ledger.total()

        assert total["input_tokens"] == 0
        assert total["output_tokens"] == 0
        assert total["pricing_status"] == "unknown"

    def test_cost_ledger_all_token_types(self) -> None:
        """Test cost ledger totals all token types."""
        ledger = CostLedger(task_id="task_0009")

        call = CostCall(
            stage="recovery",
            agent="test",
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=25,
            cache_write_tokens=10,
            reasoning_tokens=20,
            image_input_tokens=5,
            audio_input_tokens=3,
        )
        ledger.calls.append(call)

        total = ledger.total()

        assert total["input_tokens"] == 100
        assert total["output_tokens"] == 50
        assert total["cache_read_tokens"] == 25
        assert total["cache_write_tokens"] == 10
        assert total["reasoning_tokens"] == 20
        assert total["image_input_tokens"] == 5
        assert total["audio_input_tokens"] == 3

    def test_cost_ledger_cost_summation(self) -> None:
        """Test cost ledger cost summation."""
        ledger = CostLedger(task_id="task_0010")

        calls = [
            CostCall(
                stage="A", agent="test", input_tokens=100, output_tokens=50,
                estimated_cost_usd=0.01, pricing_confidence="high"
            ),
            CostCall(
                stage="B", agent="test", input_tokens=50, output_tokens=25,
                estimated_cost_usd=0.005, pricing_confidence="high"
            ),
        ]
        ledger.calls.extend(calls)

        total = ledger.total()
        assert total["pricing_status"] == "complete"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
