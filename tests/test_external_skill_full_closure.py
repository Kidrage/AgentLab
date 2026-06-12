"""No-network external skill full lifecycle closure test.

Canonical fixture: openclaw/skills → agentskills-io/SKILL.md

Verifies the complete lifecycle:
  fixture SKILL.md → import_skill_from_fixture → pending → approve → stage
  → fake validate → promote → active skill dir → retrieval → injection
  → skill_usage.yml → usage_ledger.yml
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

CANONICAL_URL = (
    "https://raw.githubusercontent.com/openclaw/skills/main/skills/killerapp/agentskills-io/SKILL.md"
)
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "external_skills" / "agentskills-io" / "SKILL.md"
PROJECT = "AgentLab"
TASK_ID = "task_external_full_closure"
TASK_TEXT = "build an agent skills discovery and import automation system"


def _write_configs(root: Path) -> None:
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "model_pricing.yml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "currency": "USD",
                "models": {
                    "deepseek/deepseek-v4-pro": {
                        "input_per_1m": 1.0,
                        "output_per_1m": 2.0,
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config / "external_skill_import_policy.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "enabled": True,
                "allow_network_by_default": False,
                "allowed_hosts": ["raw.githubusercontent.com"],
                "allowed_url_prefixes": [CANONICAL_URL],
                "max_bytes": 200000,
                "timeout_seconds": 10,
                "store_source_snapshot": True,
                "execute_external_code": False,
                "default_status": "pending_user_approval",
                "default_risk_level": "low",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config / "skill_injection_policy.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "enabled": True,
                "retrieval": {
                    "max_skills_per_task": 3,
                    "min_confidence": 0.0,
                    "high_risk_requires_approval": True,
                },
                "matching": {
                    "trigger_weight": 3,
                    "applies_to_weight": 2,
                    "summary_weight": 1,
                },
                "usage": {
                    "write_task_usage": True,
                    "append_active_skill_ledger": True,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config / "webhook_policy.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "enabled": False, "endpoints": []}),
        encoding="utf-8",
    )


def _promote_fixture_skill(root: Path) -> tuple[str, Path]:
    """Import fixture → approve → stage → validate → promote → return (skill_id, active_dir)."""
    import cost_tracker
    from external_skill_importer import import_skill_from_fixture
    from skill_evolution import (
        approve_skill_request,
        ensure_skill_registry,
        promote_skill,
        stage_skill_request,
        validate_staged_skill,
    )

    cost_tracker._PRICE_CACHE = None
    cost_tracker._PRICE_ROOT = None
    ensure_skill_registry(root)

    result = import_skill_from_fixture(
        root,
        project=PROJECT,
        fixture_path=FIXTURE_PATH,
        source_url=CANONICAL_URL,
    )
    assert result["ok"], result
    assert result["skill_name"] == "agentskills-io"
    assert result["status"] == "pending_user_approval"
    snapshot_path = Path(result["snapshot_path"])
    assert snapshot_path.exists()
    assert snapshot_path.name == "SKILL.md"

    request_id = result["request_id"]
    approved = approve_skill_request(root, PROJECT, request_id)
    assert approved["status"] == "approved"

    staged = stage_skill_request(root, PROJECT, request_id)
    skill_id = staged["skill_id"]

    validated = validate_staged_skill(root, skill_id, fake_sandbox=True)
    assert validated["status"] == "validated"

    promoted = promote_skill(root, skill_id)
    assert promoted["status"] == "active"

    # Verify active skill directory was created by promote (NOT manually)
    active_dir = root / "skills" / "active" / skill_id
    assert active_dir.exists(), (
        "promote_skill must create the active skill directory. "
        "Do NOT manually create it in the test."
    )
    assert (active_dir / "SKILL.md").exists()
    assert (active_dir / "metadata.yml").exists()
    assert (active_dir / "usage_ledger.yml").exists()

    metadata = yaml.safe_load((active_dir / "metadata.yml").read_text(encoding="utf-8")) or {}
    assert metadata["source"]["type"] == "external_url"
    assert metadata["source"]["uri"] == CANONICAL_URL

    return skill_id, active_dir


def test_external_skill_fixture_full_lifecycle_retrieval_injection_and_usage(
    tmp_path: Path,
) -> None:
    """Full closure: fixture → promote → retrieval → injection → usage ledger."""
    _write_configs(tmp_path)
    skill_id, active_dir = _promote_fixture_skill(tmp_path)

    # Create task directory
    run_dir = tmp_path / "projects" / PROJECT / "runs" / TASK_ID
    run_dir.mkdir(parents=True)
    plan_path = run_dir / "workflow_plan.yml"
    (run_dir / "user_request.md").write_text(TASK_TEXT, encoding="utf-8")
    plan_path.write_text(
        yaml.safe_dump({"route": {"agents": ["Supervisor", "Coder"]}}),
        encoding="utf-8",
    )

    from skill_injector import inject_skills_into_workflow_plan
    from skill_retriever import load_skill_injection_policy, match_active_skills

    # Skill retrieval must select the imported skill
    policy = load_skill_injection_policy(tmp_path)
    matches = match_active_skills(tmp_path, task_text=TASK_TEXT, policy=policy)
    assert any(
        item["skill_id"] == skill_id for item in matches["selected"]
    ), f"Skill retrieval failed to match imported skill {skill_id}"

    # Skill injection
    skill_plan = inject_skills_into_workflow_plan(
        tmp_path,
        plan_path,
        project=PROJECT,
        task_id=TASK_ID,
        task_text=TASK_TEXT,
        record_usage=True,
    )
    assert any(
        item["skill_id"] == skill_id for item in skill_plan["selected"]
    ), f"Injection did not include imported skill {skill_id}"

    # Verify workflow_plan.yml records skill
    plan_data = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    assert plan_data["skills"]["selected"][0]["skill_id"] == skill_id

    # Verify skill_usage.yml exists
    usage_path = run_dir / "skill_usage.yml"
    assert usage_path.exists(), "skill_usage.yml must be written by injection"
    usage = yaml.safe_load(usage_path.read_text(encoding="utf-8")) or {}
    assert usage["selected"][0]["skill_id"] == skill_id

    # Verify usage_ledger.yml appended
    ledger = yaml.safe_load(
        (active_dir / "usage_ledger.yml").read_text(encoding="utf-8")
    ) or {}
    assert ledger["entries"], "usage_ledger.yml must have entries after injection"
    assert ledger["entries"][-1]["task_id"] == TASK_ID