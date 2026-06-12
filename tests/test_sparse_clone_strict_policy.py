from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from ingestion.clone_guard import evaluate_command


def test_depth_only_clone_is_not_sparse() -> None:
    decision = evaluate_command("git clone --depth=1 https://github.com/x/y", mode="repo_patch")
    assert decision.action == "pending_approval"


def test_filter_only_clone_is_not_sparse() -> None:
    decision = evaluate_command("git clone --filter=blob:none https://github.com/x/y", mode="repo_patch")
    assert decision.action == "pending_approval"


def test_strict_sparse_clone_allowed_in_repo_patch() -> None:
    decision = evaluate_command(
        "git clone --depth=1 --filter=blob:none --sparse --single-branch https://github.com/x/y dst",
        mode="repo_patch",
    )
    assert decision.action == "allow"


def test_repo_profile_blocks_even_strict_sparse_clone_unless_explicitly_allowed() -> None:
    decision = evaluate_command(
        "git clone --depth=1 --filter=blob:none --sparse --single-branch https://github.com/x/y dst",
        mode="repo_profile",
    )
    assert decision.action == "deny"