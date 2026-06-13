from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


def _run(tmp_path: Path, mode: str, max_attempts: int = 3):
    out = tmp_path / mode
    return subprocess.run(
        [
            sys.executable,
            "scripts/p2_retry_loop_check.py",
            "--task-type",
            "repo_patch",
            "--summary",
            "Patch",
            "--output",
            str(out),
            "--mode",
            mode,
            "--max-attempts",
            str(max_attempts),
        ],
        text=True,
        capture_output=True,
        timeout=30,
    ), out


def test_retry_report_written(tmp_path: Path):
    proc, out = _run(tmp_path, "mock-pass-first")
    assert proc.returncode == 0, proc.stderr
    assert (out / "retry_loop_report.md").is_file()


def test_final_acceptance_receipt_only_when_accepted(tmp_path: Path):
    proc, out = _run(tmp_path, "mock-pass-first")
    assert proc.returncode == 0, proc.stderr
    assert (out / "final_acceptance_receipt.yml").is_file()
    assert not (out / "final_rejection_receipt.yml").exists()


def test_final_rejection_receipt_when_not_accepted(tmp_path: Path):
    proc, out = _run(tmp_path, "mock-fail-until-max", max_attempts=2)
    assert proc.returncode == 1
    assert (out / "final_rejection_receipt.yml").is_file()
    assert not (out / "final_acceptance_receipt.yml").exists()


def test_retry_loop_cli_mock_pass_first(tmp_path: Path):
    proc, out = _run(tmp_path, "mock-pass-first")
    assert proc.returncode == 0, proc.stderr
    receipt = yaml.safe_load((out / "final_acceptance_receipt.yml").read_text(encoding="utf-8"))
    assert receipt["accepted_attempt_id"] == "attempt_001"


def test_retry_loop_cli_mock_fail_then_pass(tmp_path: Path):
    proc, out = _run(tmp_path, "mock-fail-then-pass")
    assert proc.returncode == 0, proc.stderr
    ledger = yaml.safe_load((out / "retry_attempt_ledger.yml").read_text(encoding="utf-8"))
    assert len(ledger["attempts"]) == 2
    assert ledger["attempts"][0]["retry_handoff"]


def test_retry_loop_cli_mock_fail_until_max_exits_nonzero(tmp_path: Path):
    proc, out = _run(tmp_path, "mock-fail-until-max", max_attempts=2)
    assert proc.returncode == 1
    state = yaml.safe_load((out / "retry_loop_state.yml").read_text(encoding="utf-8"))
    assert state["status"] == "STOP_MAX_ATTEMPTS"


def test_retry_loop_cli_manual_handoff_requires_approval(tmp_path: Path):
    proc, out = _run(tmp_path, "manual-handoff")
    assert proc.returncode == 0, proc.stderr
    state = yaml.safe_load((out / "retry_loop_state.yml").read_text(encoding="utf-8"))
    assert state["status"] == "NEEDS_MANUAL_APPROVAL"
    assert (out / "attempt_001" / "external_execution_handoff.md").is_file()
