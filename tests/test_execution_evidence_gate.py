"""P1-1: Verify execution evidence gate — reports claiming commands must reference execution_log."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from execution_log import append_command_record, load_execution_log
from artifact_contract import _check_execution_evidence, artifact_content_issues
from command_runner import run_logged_command, run_validation_commands_if_present


class ExecutionEvidenceGateTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_report(self, fname: str, content: str) -> None:
        (self.run_dir / fname).parent.mkdir(parents=True, exist_ok=True)
        (self.run_dir / fname).write_text(content, encoding="utf-8")

    def test_validation_report_with_pytest_claim_no_command_id_fails(self) -> None:
        """Report claims pytest passed but does not reference command_id."""
        content = (
            "# Validation Report\n\n"
            "Tests passed.\n"
            "Commands run: pytest tests -q\n"
            "All 22 tests passed.\n"
        )
        issue = _check_execution_evidence("07_validation_report.md", content, self.run_dir)
        self.assertIsNotNone(issue)
        self.assertIn("command_id", issue)

    def test_report_with_command_id_but_missing_execution_log_fails(self) -> None:
        """Report references command_id but execution_log.yml doesn't exist."""
        content = (
            "# Audit Report\n\n"
            "Tests passed.\n"
            "command_id: cmd_0001\n"
            "Evidence: execution_log.yml\n"
        )
        issue = _check_execution_evidence("08_audit_report.md", content, self.run_dir)
        self.assertIsNotNone(issue)

    def test_report_with_valid_command_id_passes(self) -> None:
        """Report references a real command_id that exists in execution_log.yml with exit_code=0."""
        append_command_record(self.run_dir, {
            "command_id": "cmd_0001",
            "command": "pytest tests -q",
            "exit_code": 0,
            "stdout": "22 passed",
            "stderr": "",
            "cwd": str(self.run_dir),
        })
        content = (
            "# Verification Report\n\n"
            "All tests passed.\n"
            "command_id: cmd_0001\n"
            "Evidence: execution_log.yml\n"
        )
        issue = _check_execution_evidence("verification_report.md", content, self.run_dir)
        self.assertIsNone(issue)

    def test_native_report_accepts_matching_cli_companion_evidence(self) -> None:
        append_command_record(self.run_dir, {
            "command_id": "cmd_0007",
            "command": "codex exec --json",
            "exit_code": 0,
            "stdout": "completed",
        })
        (self.run_dir / "verifier_cli_result_capture.md").write_text(
            "Evidence: execution_log.yml\ncommand_id: cmd_0007\n",
            encoding="utf-8",
        )

        issue = _check_execution_evidence(
            "verification_report.md",
            "# Verification\n\nValidation passed.\n",
            self.run_dir,
        )

        self.assertIsNone(issue)

    def test_native_report_rejects_unknown_cli_companion_command(self) -> None:
        append_command_record(self.run_dir, {
            "command_id": "cmd_0007",
            "command": "codex exec --json",
            "exit_code": 0,
            "stdout": "completed",
        })
        (self.run_dir / "testerauditor_cli_result_capture.md").write_text(
            "Evidence: execution_log.yml\ncommand_id: cmd_9999\n",
            encoding="utf-8",
        )

        issue = _check_execution_evidence(
            "07_validation_report.md",
            "# Validation\n\nTests passed.\n",
            self.run_dir,
        )

        self.assertIsNotNone(issue)
        self.assertIn("no matching command_id", issue)

    def test_report_with_matching_command_id_in_log_passes(self) -> None:
        """Report has 'cmd_' reference that matches an actual command in the log."""
        append_command_record(self.run_dir, {
            "command_id": "cmd_0002",
            "command": "npm test",
            "exit_code": 0,
            "stdout": "All tests passed",
        })
        content = (
            "# Validation Report\n\n"
            "npm test passed.\n"
            "Evidence: command_id cmd_0002\n"
        )
        issue = _check_execution_evidence("07_validation_report.md", content, self.run_dir)
        self.assertIsNone(issue)

    def test_report_with_commands_run_no_claim_skipped(self) -> None:
        """Report without any command execution claims should not trigger gate."""
        content = (
            "# Validation Report\n\n"
            "This is a planning phase report.\n"
            "No commands were run.\n"
        )
        issue = _check_execution_evidence("07_validation_report.md", content, self.run_dir)
        self.assertIsNone(issue)

    def test_non_evidence_report_skipped(self) -> None:
        """Non-validation/audit/verification reports are not checked."""
        content = (
            "# Supervisor Plan\n\n"
            "pytest tests -q\n"
            "Tests passed.\n"
        )
        issue = _check_execution_evidence("01_supervisor_plan.md", content, self.run_dir)
        self.assertIsNone(issue)

    def test_artifact_content_issues_integrates_evidence_gate(self) -> None:
        """Verify the gate integrates into artifact_content_issues."""
        self._write_report("07_validation_report.md",
            "# Validation\n\nTests passed.\nCommands run: pytest\n")
        issues = artifact_content_issues(
            "07_validation_report.md",
            (self.run_dir / "07_validation_report.md").read_text(encoding="utf-8"),
            self.run_dir,
        )
        self.assertTrue(any("command_id" in iss for iss in issues))

    def test_unknown_command_id_with_existing_log_fails(self) -> None:
        """Report references command_id that does not exist in execution_log.yml."""
        append_command_record(self.run_dir, {
            "command_id": "cmd_0001",
            "command": "pytest tests -q",
            "exit_code": 0,
            "stdout": "22 passed",
        })
        content = (
            "# Validation Report\n\n"
            "Tests passed.\n"
            "command_id: cmd_9999\n"
            "Evidence: execution_log.yml\n"
        )
        issue = _check_execution_evidence("07_validation_report.md", content, self.run_dir)
        self.assertIsNotNone(issue)
        self.assertIn("no matching command_id", issue)

    def test_report_claims_success_but_exit_code_nonzero_fails(self) -> None:
        """Report claims success but the referenced command has exit_code != 0."""
        append_command_record(self.run_dir, {
            "command_id": "cmd_0001",
            "command": "pytest tests -q",
            "exit_code": 1,
            "stdout": "1 failed",
        })
        content = (
            "# Validation Report\n\n"
            "All tests passed.\n"
            "command_id: cmd_0001\n"
        )
        issue = _check_execution_evidence("07_validation_report.md", content, self.run_dir)
        self.assertIsNotNone(issue)
        self.assertIn("non-zero exit_code", issue)

    def test_artifact_gate_accepts_real_command_runner_success(self) -> None:
        """A validation summary containing a real successful command_id passes."""
        (self.run_dir / "ok.py").write_text("x = 1\n", encoding="utf-8")
        (self.run_dir / "validation_commands.yml").write_text(
            "version: 1\n"
            "workspace_root: .\n"
            "commands:\n"
            "  - name: py_compile\n"
            "    command: python -m py_compile ok.py\n"
            "    cwd: .\n"
            "    required: true\n",
            encoding="utf-8",
        )
        summary = run_validation_commands_if_present(
            agentlab_root=ROOT,
            run_dir=self.run_dir,
            workspace_root=self.run_dir,
        )
        content = "# Validation Report\n\nAll tests passed.\n" + summary["summary_markdown"]
        issue = _check_execution_evidence("07_validation_report.md", content, self.run_dir)
        self.assertIsNone(issue)

    def test_artifact_gate_rejects_failed_command_claimed_as_passed(self) -> None:
        """A success claim with a real nonzero command_id is rejected."""
        (self.run_dir / "broken.py").write_text("def broken(:\n", encoding="utf-8")
        result = run_logged_command(
            agentlab_root=ROOT,
            run_dir=self.run_dir,
            command="python -m py_compile broken.py",
            workspace_root=self.run_dir,
        )
        content = (
            "# Validation Report\n\n"
            "All tests passed.\n"
            f"command_id: {result['command_id']}\n"
        )
        issue = _check_execution_evidence("07_validation_report.md", content, self.run_dir)
        self.assertIsNotNone(issue)
        self.assertIn("non-zero exit_code", issue)


if __name__ == "__main__":
    main()
