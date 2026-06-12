from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from ingestion.clone_guard import evaluate_command
from ingestion.resource_ledger import ResourceLedger


def test_repo_profile_denies_git_clone() -> None:
    decision = evaluate_command("git clone https://github.com/Kidrage/AgentLab", mode="repo_profile")

    assert decision.action == "deny"
    assert "repo_profile" in decision.reason


def test_repo_patch_allows_sparse_clone_only() -> None:
    sparse = evaluate_command("git clone --depth=1 --filter=blob:none --sparse https://github.com/Kidrage/AgentLab", mode="repo_patch")
    full = evaluate_command("git clone https://github.com/Kidrage/AgentLab", mode="repo_patch")

    assert sparse.action == "allow"
    assert full.action == "pending_approval"


def test_repo_build_test_full_clone_requires_approval() -> None:
    decision = evaluate_command("git clone https://github.com/Kidrage/AgentLab", mode="repo_build_test")

    assert decision.action == "pending_approval"
    assert decision.approval_required is True


def test_clone_guard_records_resource_ledger_block() -> None:
    decision = evaluate_command("git clone https://github.com/Kidrage/AgentLab", mode="repo_profile")
    ledger = ResourceLedger(task_id="task_guard")

    ledger.record_clone_guard(decision)

    assert ledger.commands["clone_commands_blocked"] == 1
    assert ledger.commands["high_cost_commands_seen"]
