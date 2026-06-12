"""Tests for external result evidence validation and artifact gate rules."""

import unittest
from pathlib import Path
from agent_runtime.external_agents.result import (
    normalize_external_result,
    validate_external_result_evidence,
)


class TestExternalResultArtifactGate(unittest.TestCase):
    """Test that external result submission does NOT auto-pass artifact gates."""

    def _make_valid_result(self, overrides=None):
        """Helper: build a minimal valid result dict."""
        data = {
            "handoff_id": "handoff_001",
            "task_id": "task_001",
            "executor": {
                "agent_id": "cline_codex",
                "reported_by": "user",
                "billing_mode": "subscription_quota",
                "token_visibility": "unknown",
            },
            "summary": "Completed implementation",
            "status": "completed",
        }
        if overrides:
            data.update(overrides)
        return data

    def test_external_cost_unknown_not_zero(self):
        """External cost must default to None, not 0."""
        result = normalize_external_result(self._make_valid_result())
        self.assertIsNone(result.cost_notes.get("api_cost_usd"))
        self.assertEqual(
            result.cost_notes.get("subscription_quota_used"), "unknown"
        )
        self.assertEqual(
            result.cost_notes.get("pricing_status"), "external_unknown"
        )

    def test_external_cost_zero_is_warned(self):
        """api_cost_usd=0 without free=true should trigger an issue."""
        data = self._make_valid_result({
            "cost_notes": {
                "api_cost_usd": 0,
                "free": False,
            }
        })
        result = normalize_external_result(data)
        issues = validate_external_result_evidence(result)
        self.assertTrue(any("api_cost_usd is 0" in i for i in issues))

    def test_missing_command_evidence_warns(self):
        """commands_run with no evidence or external_unverified must warn."""
        data = self._make_valid_result({
            "commands_run": [
                {"command": "pytest", "evidence": None},
            ],
        })
        result = normalize_external_result(data)
        # normalize will auto-add external_unverified
        # so explicitly remove it to test missing-evidence case
        for cmd in result.commands_run:
            cmd.pop("external_unverified", None)
            cmd.pop("evidence", None)

        issues = validate_external_result_evidence(result)
        self.assertTrue(
            any("no evidence" in i.lower() or "has no evidence" in i for i in issues),
            f"Expected missing-evidence warning, got issues: {issues}"
        )

    def test_external_unverified_is_warning_not_pass(self):
        """external_unverified: true should not count as evidence pass."""
        data = self._make_valid_result({
            "commands_run": [
                {"command": "make build", "external_unverified": True},
            ],
        })
        result = normalize_external_result(data)
        issues = validate_external_result_evidence(result)
        # external_unverified suppresses the "no evidence" error,
        # but it's still noted
        # Ensure no false-positive missing-evidence error
        evidence_missing = [
            i for i in issues
            if "has no evidence" in i and "no external_unverified flag" in i
        ]
        self.assertEqual(
            len(evidence_missing), 0,
            f"external_unverified should prevent missing-evidence error: {issues}"
        )

    def test_submit_result_does_not_auto_pass(self):
        """Submit result does NOT auto-accept or auto-pass artifact gate."""
        # This is validated by the ExternalResult.submit_result behavior:
        # evidence_status is "complete" but artifact_gate_status is NEVER set.
        # We verify this through the ledger integration.
        from agent_runtime.external_agents.ledger import (
            ExternalAgentLedger,
        )

        task_id = "gate_test_001"
        output_dir = f"projects/AgentLab/runs/{task_id}"
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Clean up any previous ledger
        ledger_path = Path(output_dir) / "external_agent_ledger.yml"
        if ledger_path.exists():
            ledger_path.unlink()

        # Create a handoff entry
        from agent_runtime.external_agents.ledger import (
            record_handoff_created,
        )

        record_handoff_created(
            ledger_path=ledger_path,
            task_id=task_id,
            handoff_id="handoff_gate_001",
            agent_id="cline_codex",
            billing_mode="subscription_quota",
        )

        # Submit result
        from agent_runtime.external_agents.ledger import (
            record_result_submitted,
        )

        record_result_submitted(
            ledger_path=ledger_path,
            task_id=task_id,
            handoff_id="handoff_gate_001",
            evidence_status="complete",
        )

        # Verify ledger state
        from agent_runtime.external_agents.ledger import (
            load_external_agent_ledger,
        )

        ledger = load_external_agent_ledger(ledger_path, task_id)
        self.assertEqual(len(ledger.handoffs), 1)
        entry = ledger.handoffs[0]

        # Status must be "submitted", NOT "accepted"
        self.assertEqual(entry.status, "submitted")
        # artifact_gate_status must still be "pending"
        self.assertEqual(entry.artifact_gate_status, "pending")
        # evidence_status was recorded but does NOT pass the gate
        self.assertEqual(entry.evidence_status, "complete")


if __name__ == "__main__":
    unittest.main()