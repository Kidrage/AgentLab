"""Live external skill smoke test — skipped by default.

Run with:
    AGENTLAB_RUN_EXTERNAL_SKILL_LIVE_TEST=1 \\
    python -m pytest -q tests/test_external_skill_importer_live.py

Validates the full lifecycle: import → approve → stage → validate → promote →
task creation → skill retrieval/injection → usage ledger.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

LIVE_URL = (
    "https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md"
)

pytestmark = pytest.mark.skipif(
    os.getenv("AGENTLAB_RUN_EXTERNAL_SKILL_LIVE_TEST") != "1",
    reason="Set AGENTLAB_RUN_EXTERNAL_SKILL_LIVE_TEST=1 to run live external skill test.",
)


def _write_configs(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "model_pricing.yml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "currency": "USD",
                "models": {"deepseek/deepseek-v4-pro": {"input_per_1m": 1.0, "output_per_1m": 2.0}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / "config" / "skill_injection_policy.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "enabled": True,
                "retrieval": {"max_skills_per_task": 3, "min_confidence": 0.0, "high_risk_requires_approval": True},
                "matching": {"trigger_weight": 3, "applies_to_weight": 2, "summary_weight": 1},
                "usage": {"write_task_usage": True, "append_active_skill_ledger": True},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / "config" / "webhook_policy.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "enabled": False, "endpoints": []}), encoding="utf-8"
    )
    (root / "config" / "external_skill_import_policy.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "enabled": True,
                "allow_network_by_default": False,
                "allowed_hosts": ["raw.githubusercontent.com"],
                "allowed_url_prefixes": [LIVE_URL],
                "max_bytes": 200000,
                "timeout_seconds": 20,
                "store_source_snapshot": True,
                "execute_external_code": False,
                "default_status": "pending_user_approval",
                "default_risk_level": "low",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_live_full_skill_import_and_injection_closure(tmp_path: Path) -> None:
    """Full lifecycle: URL import → approve → stage → validate → promote
    → task → retrieval/injection → usage ledger."""
    import cost_tracker

    cost_tracker._PRICE_CACHE = None
    cost_tracker._PRICE_ROOT = None
    _write_configs(tmp_path)

    from skill_evolution import (
        ensure_skill_registry,
        approve_skill_request,
        stage_skill_request,
        validate_staged_skill,
        promote_skill,
    )
    from external_skill_importer import import_skill_from_url

    project = "AgentLab"

    # Step 1: Import from the actual allowlisted URL.
    ensure_skill_registry(tmp_path)
    result = import_skill_from_url(tmp_path, project=project, url=LIVE_URL, allow_network=True)
    assert result["ok"], f"Import failed: {result.get('error')}"
    assert result["skill_name"] == "skill-creator"
    assert result["status"] == "pending_user_approval"
    snapshot_path = Path(result["snapshot_path"])
    assert snapshot_path.exists()
    assert snapshot_path.name == "SKILL.md"
    assert "skill-creator" in snapshot_path.read_text(encoding="utf-8")
    request_id = result["request_id"]

    # Step 2: Approve
    approved = approve_skill_request(tmp_path, project, request_id)
    assert approved["status"] == "approved"

    # Step 3: Stage
    staged = stage_skill_request(tmp_path, project, request_id)
    skill_id = staged["skill_id"]
    assert skill_id

    # Step 4: Fake validate
    validated = validate_staged_skill(tmp_path, skill_id, fake_sandbox=True)
    assert validated["status"] == "validated"

    # Step 5: Promote to active
    promoted = promote_skill(tmp_path, skill_id)
    assert promoted["status"] == "active"

    # Verify active skill directory was created (NOT manually)
    active_skill_dir = tmp_path / "skills" / "active" / skill_id
    assert active_skill_dir.exists(), f"Active skill dir not created: {active_skill_dir}"
    assert (active_skill_dir / "SKILL.md").exists()
    assert (active_skill_dir / "metadata.yml").exists()
    assert (active_skill_dir / "usage_ledger.yml").exists()

    # Step 6-7: Task retrieval/injection
    run_dir = tmp_path / "projects" / project / "runs" / "task_live"
    run_dir.mkdir(parents=True)
    task_text = "create and validate a new agent skill package"
    (run_dir / "user_request.md").write_text(task_text, encoding="utf-8")
    (run_dir / "workflow_plan.yml").write_text(
        yaml.safe_dump({"route": {"agents": ["Supervisor", "Coder"]}}), encoding="utf-8"
    )

    from skill_retriever import match_active_skills, load_skill_injection_policy
    policy = load_skill_injection_policy(tmp_path)
    matches = match_active_skills(tmp_path, task_text=task_text, policy=policy)
    assert len(matches["selected"]) > 0, "No skill matched task goal"
    assert matches["selected"][0]["name"] == "skill-creator"

    # Step 8-9: skill injection → skill_usage.yml
    from skill_injector import inject_skills_into_workflow_plan
    plan_path = run_dir / "workflow_plan.yml"
    skills = inject_skills_into_workflow_plan(
        tmp_path, plan_path, project=project, task_id="task_live", task_text=task_text, record_usage=True,
    )
    # workflow_plan should record selected skill
    plan_data = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    assert plan_data["skills"]["selected"][0]["skill_id"] == skill_id

    # skill_usage.yml exists
    usage_path = run_dir / "skill_usage.yml"
    assert usage_path.exists(), "skill_usage.yml missing"

    # usage_ledger.yml appended
    ledger_path = active_skill_dir / "usage_ledger.yml"
    ledger = yaml.safe_load(ledger_path.read_text(encoding="utf-8")) or {}
    entries = ledger.get("entries", [])
    assert len(entries) >= 1, "usage_ledger.yml not appended"
    assert entries[0]["task_id"] == "task_live"


def test_promote_missing_if_no_active_skill_fails(tmp_path: Path) -> None:
    """If promote doesn't create active skill directory, test must fail.
    This tests the absence of manual self-patching."""
    import cost_tracker

    cost_tracker._PRICE_CACHE = None
    cost_tracker._PRICE_ROOT = None
    _write_configs(tmp_path)

    from skill_evolution import (
        ensure_skill_registry,
        build_skill_adoption_request,
        write_skill_adoption_request,
        approve_skill_request,
        stage_skill_request,
        validate_staged_skill,
        promote_skill,
    )

    ensure_skill_registry(tmp_path)
    req = build_skill_adoption_request(
        tmp_path, project="AgentLab", skill_name="test-skill",
        source="manual://test", purpose="test", source_type="manual",
    )
    write_skill_adoption_request(tmp_path, req)
    approve_skill_request(tmp_path, "AgentLab", req["id"])
    staged = stage_skill_request(tmp_path, "AgentLab", req["id"])
    validate_staged_skill(tmp_path, staged["skill_id"], fake_sandbox=True)
    promoted = promote_skill(tmp_path, staged["skill_id"])

    active_dir = tmp_path / "skills" / "active" / promoted.get("skill_id", staged["skill_id"])
    assert active_dir.exists(), "promote_skill must create active skill directory"
    assert (active_dir / "SKILL.md").exists()
    assert (active_dir / "metadata.yml").exists()
    assert (active_dir / "usage_ledger.yml").exists()
