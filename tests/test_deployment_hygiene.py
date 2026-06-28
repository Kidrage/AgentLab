from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from deployment_hygiene import assess_checked_out_remote_push


def test_checked_out_250_remote_with_deny_current_branch_ignore_is_unsafe() -> None:
    result = assess_checked_out_remote_push(
        remote_name="250",
        remote_url="ssh://admin@10.147.17.250:/home/admin/AgentLab",
        receive_deny_current_branch="ignore",
    )

    assert result["safe_to_push"] is False
    assert result["hazard"] == "checked_out_runtime_remote"
    assert "fetch/merge --ff-only" in result["recommendation"]


def test_non_runtime_remote_is_not_flagged() -> None:
    result = assess_checked_out_remote_push(
        remote_name="origin",
        remote_url="git@github.com:Kidrage/AgentLab.git",
        receive_deny_current_branch="ignore",
    )

    assert result["safe_to_push"] is True
