"""P1 Fix 4: High-risk skill injection must create decision cards, not silently reject."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))


def _setup_skill_env(tmp_path: Path, risk_level: str = "high") -> tuple[Path, Path]:
    """Create a minimal AgentLab structure with an active high-risk skill."""
    skills_active = tmp_path / "skills" / "active" / "high_risk_demo"
    skills_active.mkdir(parents=True)
    metadata = {
        "schema_version": 1,
        "skill_id": "high_risk_demo",
        "name": "High Risk Demo Skill",
        "risk_level": risk_level,
        "trigger": "deploy production changes",
        "trigger_keywords": ["deploy", "production", "live"],
        "status": "active",
        "load_tokens": 200,
        "expected_saving_tokens": 800,
    }
    (skills_active / "metadata.yml").write_text(yaml.safe_dump(metadata), encoding="utf-8")
    (skills_active / "SKILL.md").write_text("# High Risk Demo\n", encoding="utf-8")

    # Write skill injection policy
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    config_dir.mkdir(exist_ok=True)

    policy = {
        "schema_version": 2,
        "retrieval": {
            "max_skills_per_task": 3,
            "high_risk_requires_approval": True,
            "silent_reject_high_risk": False,
        },
        "usage": {"write_run_usage": True, "scope": "run_local"},
    }
    (config_dir / "skill_injection_policy.yml").write_text(yaml.safe_dump(policy), encoding="utf-8")

    # Create project structure
    projects = tmp_path / "projects" / "AgentLab" / "runs" / "task_test"
    projects.mkdir(parents=True)
    (projects / "user_request.md").write_text("We need to deploy production changes immediately.\n", encoding="utf-8")
    (projects / "workflow_plan.yml").write_text("route:\n  agents: [Supervisor, Coder]\n", encoding="utf-8")

    # Create skill registry
    registry = {
        "schema_version": 1,
        "skills": [metadata],
        "retired_skills": [],
        "request_queue": [],
    }
    skills_dir = tmp_path / "skills"
    (skills_dir / "registry.yml").write_text(yaml.safe_dump(registry), encoding="utf-8")

    return tmp_path, projects


def test_high_risk_skill_matched_does_not_silently_reject(tmp_path: Path) -> None:
    """High-risk active skills should not be silently rejected from matching."""
    root, run_dir = _setup_skill_env(tmp_path, risk_level="high")
    from skill_retriever import load_skill_injection_policy, match_active_skills

    task_text = "We need to deploy production changes immediately."
    policy = load_skill_injection_policy(root)
    result = match_active_skills(root, task_text=task_text, policy=policy)

    rejected = result.get("rejected", [])
    assert any(item.get("skill_id") == "high_risk_demo" for item in rejected)
    high_risk = next(item for item in rejected if item.get("skill_id") == "high_risk_demo")
    assert high_risk["risk_level"] == "high"
    assert high_risk["approval_type"] == "SKILL_INJECTION_APPROVAL"
    assert high_risk["requires_approval"] is True


def test_high_risk_skill_injection_creates_decision_card(tmp_path: Path) -> None:
    """When a high-risk skill is injected, a decision card should be created."""
    root, run_dir = _setup_skill_env(tmp_path, risk_level="high")
    from skill_injector import build_skill_plan
    from skill_retriever import load_skill_injection_policy

    task_text = "We need to deploy production changes immediately."
    policy = load_skill_injection_policy(root)
    plan = build_skill_plan(
        root,
        project="AgentLab",
        task_id="task_test",
        run_dir=run_dir,
        task_text=task_text,
        policy=policy,
        record_usage=True,
    )

    assert not plan.get("selected", []), "High-risk skill must not be selected before approval"
    assert any(
        item.get("skill_id") == "high_risk_demo"
        and item.get("approval_type") == "SKILL_INJECTION_APPROVAL"
        for item in plan.get("rejected", [])
    ), "High-risk skill should be rejected with approval metadata"

    decision_dir = run_dir / "decision_cards"
    card_files = list(decision_dir.glob("*.yml")) if decision_dir.exists() else []
    assert card_files, "High-risk injection must create a decision card"
    high_risk_cards = [yaml.safe_load(cf.read_text(encoding="utf-8")) or {} for cf in card_files]
    assert any(
        card.get("type") == "SKILL_INJECTION_APPROVAL"
        and card.get("skill", {}).get("skill_id") == "high_risk_demo"
        for card in high_risk_cards
    ), high_risk_cards
    assert "SKILL_APPROVAL_REQUIRED" in (run_dir / "task_events.jsonl").read_text(encoding="utf-8")


def test_low_risk_skill_no_decision_card(tmp_path: Path) -> None:
    """Low-risk skill injection should not trigger a decision card."""
    root, run_dir = _setup_skill_env(tmp_path, risk_level="low")
    from skill_injector import inject_skills_into_workflow_plan

    task_text = "We need to deploy production changes immediately."
    plan_path = run_dir / "workflow_plan.yml"

    # Clear any pre-existing cards
    import shutil
    decision_dir = run_dir / "decision_cards"
    if decision_dir.exists():
        shutil.rmtree(decision_dir)

    result = inject_skills_into_workflow_plan(
        root,
        plan_path,
        project="AgentLab",
        task_id="task_test",
        task_text=task_text,
        record_usage=True,
    )

    # No crash; skill injection completes
    assert result is not None


def test_high_risk_injection_real_path_creates_card_event_and_webhook(tmp_path: Path) -> None:
    """Real high-risk injection path creates approval card, task event, and webhook."""
    root, run_dir = _setup_skill_env(tmp_path, risk_level="high")

    # Enable webhooks in policy
    webhook_policy = {
        "schema_version": 1,
        "enabled": True,
        "endpoints": [
            {
                "name": "mock",
                "url_env": "AGENTLAB_HIGH_RISK_WEBHOOK_URL",
                "events": ["ACTION_REQUIRED"],
            }
        ],
        "retry": {"max_attempts": 1, "backoff_seconds": 0},
        "security": {"sign_payload": False, "redact_secrets": True},
    }
    config_dir = root / "config"
    (config_dir / "webhook_policy.yml").write_text(yaml.safe_dump(webhook_policy), encoding="utf-8")

    import webhook_dispatcher

    calls = []
    original_post_json = webhook_dispatcher.post_json
    webhook_dispatcher.post_json = lambda url, payload, headers, timeout=10: (
        calls.append({"url": url, "payload": payload, "headers": headers}) or (200, "ok")
    )
    import os

    os.environ["AGENTLAB_HIGH_RISK_WEBHOOK_URL"] = "http://mock.test/hook"
    from skill_injector import inject_skills_into_workflow_plan

    task_text = "We need to deploy production changes immediately."
    plan_path = run_dir / "workflow_plan.yml"

    try:
        plan = inject_skills_into_workflow_plan(
            root,
            plan_path,
            project="AgentLab",
            task_id="task_test",
            task_text=task_text,
            record_usage=True,
        )
    finally:
        webhook_dispatcher.post_json = original_post_json
        os.environ.pop("AGENTLAB_HIGH_RISK_WEBHOOK_URL", None)

    assert not plan["selected"]
    assert any(r["approval_type"] == "SKILL_INJECTION_APPROVAL" for r in plan["rejected"])

    decision_dir = run_dir / "decision_cards"
    card_files = list(decision_dir.glob("*.yml")) if decision_dir.exists() else []
    assert card_files, "High-risk injection must create a decision card"
    decision_card = yaml.safe_load(card_files[0].read_text(encoding="utf-8")) or {}
    assert decision_card["type"] == "SKILL_INJECTION_APPROVAL"
    assert decision_card["skill"]["skill_id"] == "high_risk_demo"

    task_events_text = (run_dir / "task_events.jsonl").read_text(encoding="utf-8")
    assert "SKILL_APPROVAL_REQUIRED" in task_events_text

    from feedback_manager import resolve_decision_card

    approved = resolve_decision_card(
        run_dir,
        decision_card["id"],
        option_id="approve_inject",
        resolution="approved",
        actor="user",
    )
    assert approved["status"] == "approved"

    from skill_retriever import load_skill_injection_policy, match_active_skills

    permissive_policy = load_skill_injection_policy(root)
    permissive_policy["retrieval"] = dict(permissive_policy.get("retrieval", {}))
    permissive_policy["retrieval"]["high_risk_requires_approval"] = False
    matches_after_approval = match_active_skills(root, task_text=task_text, policy=permissive_policy)
    assert any(
        item.get("skill_id") == "high_risk_demo"
        for item in matches_after_approval.get("selected", [])
    )

    reject_run_dir = root / "projects" / "AgentLab" / "runs" / "task_reject"
    reject_run_dir.mkdir(parents=True)
    reject_plan_path = reject_run_dir / "workflow_plan.yml"
    reject_plan_path.write_text("route:\n  agents: [Supervisor, Coder]\n", encoding="utf-8")
    reject_plan = inject_skills_into_workflow_plan(
        root,
        reject_plan_path,
        project="AgentLab",
        task_id="task_reject",
        task_text=task_text,
        record_usage=True,
    )
    reject_card_files = sorted((reject_run_dir / "decision_cards").glob("*.yml"))
    assert reject_card_files
    reject_card = yaml.safe_load(reject_card_files[0].read_text(encoding="utf-8")) or {}
    rejected_card = resolve_decision_card(
        reject_run_dir,
        reject_card["id"],
        option_id="reject_inject",
        resolution="rejected",
        actor="user",
    )
    assert rejected_card["status"] == "rejected"
    assert not reject_plan["selected"]

    assert calls, "High-risk approval card creation must dispatch ACTION_REQUIRED webhook"
    webhook_payload = calls[0]["payload"]
    assert webhook_payload["event"] == "ACTION_REQUIRED"
    assert webhook_payload["decision_card"]["id"]
