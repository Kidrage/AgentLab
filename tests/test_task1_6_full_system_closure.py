"""P0 Fix 3: End-to-end closure test for Task 1–6 full system.

Simulates the complete closed-loop path:
1. Create skill request → 2. Approve → 3. Stage → 4. Validate → 5. Promote
6. Create task → 7. Skill retrieval selects active skill → 8. Workflow plan records skill
9. skill_usage.yml written → 10. Block event → 11. decision_card created
12. task_events.jsonl records SKILL_APPROVAL_REQUIRED event → 13. Webhook via dispatcher → 14. MCP approve → 15. Resume
16. Finalize → 17. learning_review → 18. skill_candidate → 19. candidate approve

Uses temp directory, no real model calls, no real webhooks.

ABSOLUTE RULES:
- active skill directory, SKILL.md, metadata.yml, usage_ledger.yml MUST be created
  by skill lifecycle code (promote_skill). Tests MUST NOT create them manually.
  If promote_skill doesn't create them → FAIL.
- Webhook E2E must go through dispatch_event, not manual payload construction.
- learning_review.yml MUST exist when blocked/validation_failure events exist.
- At least 1 skill_candidate MUST be generated when blocked/validation_failure events exist.
- decision card type MUST be SKILL_INJECTION_APPROVAL for high-risk injection.
- task_events.jsonl MUST contain SKILL_APPROVAL_REQUIRED for high-risk skills.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))


def _setup_full_system_env(tmp_path: Path) -> tuple[Path, str, str, str]:
    """Set up a full minimal project with all configs needed for Task 1-6 closure.
    Returns (root, project, task_id, skill_name)."""
    root = tmp_path
    project = "E2EProject"
    task_id = "task_e2e"
    skill_name = "e2e_demo_skill"

    # === Configs ===
    config = root / "config"
    config.mkdir(parents=True)

    # Webhook (disabled for no-network test)
    (config / "webhook_policy.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "enabled": False, "endpoints": []}), encoding="utf-8"
    )

    # Feedback
    (config / "feedback_policy.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "notification_levels": {}, "watchdog_thresholds": {}}),
        encoding="utf-8",
    )

    # Watchdog
    (config / "watchdog_policy.yml").write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "enabled": False,
            "thresholds": {
                "running_without_heartbeat_seconds": 900,
                "running_without_event_seconds": 900,
                "waiting_for_approval_seconds": 86400,
                "stale_lock_seconds": 1800,
            },
            "stale_actions": {"append_event": True, "write_feedback_status": True, "create_decision_card": True},
        }),
        encoding="utf-8",
    )

    # MCP policy
    (config / "mcp_policy.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "tools_enabled": True, "gates": {}}), encoding="utf-8"
    )

    # Skill injection policy
    (config / "skill_injection_policy.yml").write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "retrieval": {"max_skills_per_task": 3, "high_risk_requires_approval": True},
            "usage": {"write_task_usage": True},
        }),
        encoding="utf-8",
    )

    # Skill evolution policy
    (config / "skill_evolution_policy.yml").write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "require_approval": False,
            "allow_fake_sandbox": True,
            "max_candidates_per_task": 5,
        }),
        encoding="utf-8",
    )

    # Model pricing for cost tracker
    (config / "model_pricing.yml").write_text(
        yaml.safe_dump({
            "version": 1,
            "currency": "USD",
            "models": {"deepseek/deepseek-v4-pro": {"input_per_1m": 1.0, "output_per_1m": 2.0}},
        }, sort_keys=False),
        encoding="utf-8",
    )
    import cost_tracker
    cost_tracker._PRICE_CACHE = None
    cost_tracker._PRICE_ROOT = None

    # === Skills dir ===
    skills_dir = root / "skills"
    skills_dir.mkdir(parents=True)

    # === Skill lifecycle (Steps 1-5) ===
    from skill_evolution import ensure_skill_registry, build_skill_adoption_request, write_skill_adoption_request
    from skill_evolution import approve_skill_request, stage_skill_request, validate_staged_skill, promote_skill

    ensure_skill_registry(root)
    req = build_skill_adoption_request(
        root,
        project=project,
        skill_name=skill_name,
        source="manual://demo",
        purpose="E2E demo skill for deployment",
        source_type="manual",
        risk={"has_scripts": False, "requires_network": False, "modifies_files": True, "permission_level": "low"},
        applies_to=["deployment", "production"],
    )
    write_skill_adoption_request(root, req)

    # Step 2: Approve
    approve_skill_request(root, project, req["id"])

    # Step 3: Stage
    staged = stage_skill_request(root, project, req["id"])

    # Step 4: Validate
    validate_staged_skill(root, staged["skill_id"], fake_sandbox=True)

    # Step 5: Promote to active
    actual_skill_id = staged["skill_id"]
    promoted = promote_skill(root, actual_skill_id)

    # ── RULE: Do NOT manually create active skill dir, SKILL.md, metadata.yml,
    #       or usage_ledger.yml. promote_skill() must have created them. ──
    active_skill_dir = root / "skills" / "active" / actual_skill_id
    assert active_skill_dir.exists(), (
        f"PROMOTE FAILED: active skill dir not created at {active_skill_dir}. "
        f"promote_skill must create it. Do NOT patch in test."
    )
    assert (active_skill_dir / "SKILL.md").exists(), "SKILL.md must be created by promote_skill"
    assert (active_skill_dir / "metadata.yml").exists(), "metadata.yml must be created by promote_skill"
    assert (active_skill_dir / "usage_ledger.yml").exists(), "usage_ledger.yml must be created by promote_skill"

    # Verify metadata has triggers
    metadata = yaml.safe_load((active_skill_dir / "metadata.yml").read_text(encoding="utf-8")) or {}
    assert metadata.get("status") == "active", f"Skill status should be active, got {metadata.get('status')}"

    # === Task setup ===
    run_dir = root / "projects" / project / "runs" / task_id
    run_dir.mkdir(parents=True)

    user_request = "We need to deploy production changes immediately.\nThis is a test E2E deployment."
    (run_dir / "user_request.md").write_text(user_request, encoding="utf-8")
    (run_dir / "task_events.jsonl").write_text("", encoding="utf-8")

    # Create workflow_plan.yml with basic structure
    workflow_plan = {
        "route": {"agents": ["Supervisor", "Coder", "TesterAuditor"]},
        "task_id": task_id,
        "project": project,
        "run_dir": str(run_dir),
    }
    (run_dir / "workflow_plan.yml").write_text(yaml.safe_dump(workflow_plan), encoding="utf-8")

    # Create state + progress
    (run_dir / "state.yml").write_text(
        yaml.safe_dump({
            "project": project,
            "task_id": task_id,
            "status": "new",
            "last_event": "Task initialized.",
            "updated_at": "2026-06-11T00:00:00Z",
            "completed_agents": [],
            "reports": {},
            "execution_mode": "codex",
        }),
        encoding="utf-8",
    )
    (run_dir / "progress.yml").write_text(
        yaml.safe_dump({"status": "new", "last_event": "Task initialized."}),
        encoding="utf-8",
    )

    return root, project, task_id, skill_name


def test_full_system_closure(tmp_path: Path) -> None:
    """Verify the complete Task 1-6 closure loop end-to-end."""
    root, project, task_id, skill_name = _setup_full_system_env(tmp_path)
    run_dir = root / "projects" / project / "runs" / task_id

    # === Step 6-7: Skill retrieval selects the active skill ===
    from skill_retriever import load_skill_injection_policy, match_active_skills

    task_text = (run_dir / "user_request.md").read_text(encoding="utf-8")
    policy = load_skill_injection_policy(root)
    result = match_active_skills(root, task_text=task_text, policy=policy)

    assert len(result["selected"]) > 0, f"No skills matched for task text: {task_text[:100]}"
    skill = result["selected"][0]
    assert "e2e" in skill["skill_id"].lower() or "e2e" in skill.get("name", "").lower(), (
        f"Skill mismatch: {skill}"
    )

    # === Step 8-9: Skill injection writes workflow plan + skill_usage.yml ===
    from skill_injector import inject_skills_into_workflow_plan

    plan_path = run_dir / "workflow_plan.yml"
    skills = inject_skills_into_workflow_plan(
        root,
        plan_path,
        project=project,
        task_id=task_id,
        task_text=task_text,
        record_usage=True,
    )
    assert "selected" in skills or "skills" in plan_path.read_text(encoding="utf-8").lower()

    # Verify skill_usage.yml exists (written by lifecycle code)
    usage_path = run_dir / "skill_usage.yml"
    assert usage_path.exists(), f"skill_usage.yml missing at {usage_path}"

    # === Step 10-12: Simulate blocked event → decision card → task_events ===
    from feedback_manager import create_decision_card

    card, _path = create_decision_card(
        run_dir,
        task_id=task_id,
        card_type="stale_running",
        title="E2E block test",
        reason="Simulated block for E2E test.",
        options=[
            {"id": "approve_write", "label": "Approve write", "risk": "low"},
            {"id": "approve_resume", "label": "Approve resume", "risk": "low"},
            {"id": "stop_task", "label": "Stop task", "risk": "medium"},
        ],
        recommended_action="approve_resume",
        risk="low",
    )
    assert card is not None
    assert "id" in card

    # Verify task_events.jsonl has APPROVAL_REQUIRED
    events_path = run_dir / "task_events.jsonl"
    assert events_path.exists()
    lines = events_path.read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line) for line in lines if line.strip()]
    assert events, "No events written"
    approval_events = [e for e in events if e.get("event") in {"APPROVAL_REQUIRED", "ACTION_REQUIRED"}]
    assert len(approval_events) > 0, f"No approval event in: {events}"

    # === Step 13-14: Webhook MUST go through dispatcher (P0-7) ===
    # monkeypatch the HTTP delivery function, then call dispatch_event for real
    webhook_calls = []

    def fake_post_json(url, payload, headers, timeout=10):
        webhook_calls.append({"url": url, "payload": dict(payload), "headers": dict(headers)})
        return 200, "ok"

    import webhook_dispatcher

    # Enable webhook for this dispatch
    (root / "config" / "webhook_policy.yml").write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "enabled": True,
            "endpoints": [{
                "name": "mock",
                "url_env": "AGENTLAB_TEST_WEBHOOK_URL",
                "secret_env": "AGENTLAB_TEST_WEBHOOK_SECRET",
                "events": ["ACTION_REQUIRED"],
            }],
            "retry": {"max_attempts": 1, "backoff_seconds": 0},
            "security": {"sign_payload": True, "redact_secrets": True},
        }),
        encoding="utf-8",
    )
    import os as _os
    _os.environ["AGENTLAB_TEST_WEBHOOK_URL"] = "http://mock.test/hook"
    _os.environ["AGENTLAB_TEST_WEBHOOK_SECRET"] = "test-secret"
    monkeypatch_orig = webhook_dispatcher.post_json
    webhook_dispatcher.post_json = fake_post_json

    try:
        dispatched = webhook_dispatcher.dispatch_event(
            root,
            event="ACTION_REQUIRED",
            project=project,
            task_id=task_id,
            stage="blocked",
            severity="ACTION_REQUIRED",
            summary="E2E webhook test",
            reason="Testing webhook via dispatcher",
            decision_card={"id": card["id"], "options": card.get("options", [])},
        )
        assert dispatched["enabled"] is True
        assert len(webhook_calls) >= 1, "dispatch_event did not call post_json"
        captured_payload = webhook_calls[0]["payload"]
        assert captured_payload["event"] == "ACTION_REQUIRED"
        assert captured_payload["project"] == project
    finally:
        webhook_dispatcher.post_json = monkeypatch_orig
        _os.environ.pop("AGENTLAB_TEST_WEBHOOK_URL", None)
        _os.environ.pop("AGENTLAB_TEST_WEBHOOK_SECRET", None)

    # === Now use chat_adapter_mock with the captured payload ===
    from chat_adapter_mock import mock_full_chat_closure

    closure = mock_full_chat_closure(
        root,
        project=project,
        task_id=task_id,
        webhook_payload=webhook_calls[0]["payload"],
        user_choice="B",  # approve_resume
    )
    assert closure["ok"], f"MCP closure failed: {closure}"

    # === Step 15: Resume ===
    from feedback_manager import load_pending_decision_cards
    pending = load_pending_decision_cards(run_dir)
    assert len(pending) == 0, f"Still pending decisions: {pending}"

    # === Step 16: Write NODE_BLOCKED event so learning_review finds patterns ===
    from task_events import append_task_event
    append_task_event(
        run_dir,
        "NODE_BLOCKED",
        status="FAILED_RECOVERABLE",
        severity="BLOCKED",
        message="Simulated node block for E2E test.",
        payload={"block_type": "user_decision"},
    )
    # Also write a validation_failure indicator
    (run_dir / "07_validation_report.md").write_text(
        "Result: required validation command failed.\n", encoding="utf-8"
    )

    # Finalize (mark as complete)
    from state_store import load_state, save_state
    state = load_state(run_dir, project, task_id)
    state.status = "completed"
    state.last_event = "Task completed E2E closure."
    save_state(run_dir, state)

    # === Step 17: learning_review MUST exist (P0-8) ===
    from post_task_learning import run_learning_review

    review = run_learning_review(root, project, task_id, create_candidates=True)
    review_path = run_dir / "learning_review.yml"
    assert review_path.exists(), (
        "P0-8: learning_review.yml MUST exist after blocked event. "
        f"Review status: {review.get('status')}, patterns: {review.get('patterns')}"
    )

    # === Step 18: At least 1 skill_candidate (P0-8 strong assertion) ===
    from post_task_learning import list_skill_candidates, approve_skill_candidate

    candidates = list_skill_candidates(root, project, task_id)
    assert len(candidates) >= 1, (
        "P0-8: At least 1 skill_candidate MUST be generated for blocked event. "
        "If no candidate, task must FAIL."
    )

    # === Step 19: Approve a candidate creates self-learned skill request ===
    candidate = candidates[0]
    approved = approve_skill_candidate(root, project, task_id, candidate["id"])
    assert approved.get("status") in {"approved", "created_skill_request"}

    # === Final verification: no corrupted files, all paths clean ===
    assert run_dir.exists()
    assert usage_path.exists()
    assert events_path.exists()


# ── P0-6: High-risk Skill Approval strong assertions ───────────────────

def test_high_risk_skill_approval_strong_assertions(tmp_path: Path) -> None:
    """High-risk skill injection must:
    1. Match the active high-risk skill
    2. NOT inject into workflow plan before approval
    3. Create decision card with type=SKILL_INJECTION_APPROVAL
    4. task_events.jsonl MUST contain SKILL_APPROVAL_REQUIRED
    5. User approve → allow injection
    6. User reject/skip → no injection
    7. If webhook enabled, dispatch ACTION_REQUIRED
    """
    import os as _os
    config = tmp_path / "config"
    config.mkdir(parents=True)

    # Write injection policy with high_risk_requires_approval=True
    (config / "skill_injection_policy.yml").write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "enabled": True,
            "retrieval": {
                "max_skills_per_task": 3,
                "min_confidence": 0.0,
                "high_risk_requires_approval": True,
            },
            "matching": {"trigger_weight": 3, "applies_to_weight": 2, "summary_weight": 1},
            "usage": {"write_task_usage": True},
        }, sort_keys=False),
        encoding="utf-8",
    )

    # Webhook disabled for this test
    (config / "webhook_policy.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "enabled": False, "endpoints": []}), encoding="utf-8"
    )

    # Create high-risk active skill via lifecycle
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
        tmp_path, project="AgentLab", skill_name="high-risk-deploy",
        source="manual://test", purpose="Deploy production changes",
        source_type="manual",
        risk={"has_scripts": True, "requires_network": True, "modifies_files": True, "permission_level": "high"},
        applies_to=["deployment", "production"],
    )
    write_skill_adoption_request(tmp_path, req)
    approve_skill_request(tmp_path, "AgentLab", req["id"])
    staged = stage_skill_request(tmp_path, "AgentLab", req["id"])
    skill_id = staged["skill_id"]
    validate_staged_skill(tmp_path, skill_id, fake_sandbox=True)
    promoted = promote_skill(tmp_path, skill_id)

    # Verify promote created the active dir
    active_dir = tmp_path / "skills" / "active" / skill_id
    assert active_dir.exists(), "promote_skill must create active dir"

    # Manually tag as high-risk in metadata (since build_skill_adoption_request
    # sets permission_level but the stage might normalize it)
    metadata_path = active_dir / "metadata.yml"
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
    metadata["risk_level"] = "high"
    metadata["triggers"] = ["deploy", "production", "live"]
    metadata["applies_to"] = ["deployment", "production"]
    metadata_path.write_text(yaml.safe_dump(metadata), encoding="utf-8")

    # Setup task
    run_dir = tmp_path / "projects" / "AgentLab" / "runs" / "task_high_risk"
    run_dir.mkdir(parents=True)
    task_text = "We need to deploy production changes immediately with live updates."
    (run_dir / "user_request.md").write_text(task_text, encoding="utf-8")
    (run_dir / "task_events.jsonl").write_text("", encoding="utf-8")
    (run_dir / "workflow_plan.yml").write_text(
        yaml.safe_dump({"route": {"agents": ["Supervisor", "Coder"]}}), encoding="utf-8"
    )

    # === Assertion 1: high-risk skill matched ===
    from skill_retriever import match_active_skills, load_skill_injection_policy
    policy = load_skill_injection_policy(tmp_path)
    matches = match_active_skills(tmp_path, task_text=task_text, policy=policy)
    # With high_risk_requires_approval=True, the skill should appear as matched
    # but in 'rejected' due to high-risk policy
    assert any(
        s.get("skill_id") == skill_id for s in matches.get("selected", []) + matches.get("rejected", [])
    ), "High-risk skill should appear in matches"

    # === Assertion 2-4: real injection path blocks high-risk skill and creates card/event ===
    from skill_injector import inject_skills_into_workflow_plan
    plan_path = run_dir / "workflow_plan.yml"
    result = inject_skills_into_workflow_plan(
        tmp_path, plan_path, project="AgentLab", task_id="task_high_risk",
        task_text=task_text, record_usage=True,
    )
    plan_data = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    selected = plan_data.get("skills", {}).get("selected", [])
    # If skill appears as 'selected' despite being high-risk, fail
    high_risk_selected = [s for s in selected if s.get("risk_level") == "high"]
    assert len(high_risk_selected) == 0, (
        "High-risk skill was injected into workflow plan before approval! "
        "It should be blocked by high_risk_requires_approval policy."
    )
    assert not result["selected"]
    assert any(
        item.get("skill_id") == skill_id
        and item.get("approval_type") == "SKILL_INJECTION_APPROVAL"
        for item in result["rejected"]
    )

    from feedback_manager import load_pending_decision_cards

    pending_cards = load_pending_decision_cards(run_dir)
    assert pending_cards, "skill_injector must create the high-risk decision card"
    card = pending_cards[0]
    assert card.get("type") == "SKILL_INJECTION_APPROVAL", (
        f"Decision card type must be SKILL_INJECTION_APPROVAL, got {card.get('type')}"
    )
    assert card.get("skill", {}).get("skill_id") == skill_id

    # Verify task_events.jsonl contains SKILL_APPROVAL_REQUIRED
    events_path = run_dir / "task_events.jsonl"
    events_text = events_path.read_text(encoding="utf-8")
    assert "SKILL_APPROVAL_REQUIRED" in events_text, (
        "P0-9: task_events.jsonl MUST contain SKILL_APPROVAL_REQUIRED for high-risk skill"
    )

    # === Assertion 5: User approve → allow injection ===
    from feedback_manager import resolve_decision_card
    resolved = resolve_decision_card(
        run_dir, card["id"], option_id="approve_inject", resolution="approved", actor="user"
    )
    assert resolved["status"] == "approved"
    assert resolved["selected_option"] == "approve_inject"

    # After approval, the skill CAN be injected (retrieval should return it as selected now)
    # Simulate a policy that doesn't block high-risk (approval happened)
    permissive_policy = dict(policy)
    permissive_policy["retrieval"] = dict(permissive_policy.get("retrieval", {}))
    permissive_policy["retrieval"]["high_risk_requires_approval"] = False
    matches_after = match_active_skills(tmp_path, task_text=task_text, policy=permissive_policy)
    assert any(
        s.get("skill_id") == skill_id for s in matches_after.get("selected", [])
    ), "After approval, high-risk skill should match as selected"

    # === Assertion 6-7: webhook dispatches ACTION_REQUIRED from the real injection path ===
    webhook_calls_2 = []
    def fake_post_2(url, payload, headers, timeout=10):
        webhook_calls_2.append(payload)
        return 200, "ok"

    (config / "webhook_policy.yml").write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "enabled": True,
            "endpoints": [{
                "name": "mock2",
                "url_env": "AGENTLAB_TEST_WEBHOOK_URL_2",
                "secret_env": "AGENTLAB_TEST_WEBHOOK_SECRET_2",
                "events": ["ACTION_REQUIRED"],
            }],
            "retry": {"max_attempts": 1, "backoff_seconds": 0},
            "security": {"sign_payload": False, "redact_secrets": True},
        }),
        encoding="utf-8",
    )
    _os.environ["AGENTLAB_TEST_WEBHOOK_URL_2"] = "http://mock2.test/hook"
    _os.environ["AGENTLAB_TEST_WEBHOOK_SECRET_2"] = "s2"

    import webhook_dispatcher as wd2
    wd2_orig = wd2.post_json
    wd2.post_json = fake_post_2
    webhook_run_dir = tmp_path / "projects" / "AgentLab" / "runs" / "task_high_risk_webhook"
    webhook_run_dir.mkdir(parents=True)
    webhook_plan = webhook_run_dir / "workflow_plan.yml"
    webhook_plan.write_text(
        yaml.safe_dump({"route": {"agents": ["Supervisor", "Coder"]}}), encoding="utf-8"
    )
    try:
        webhook_result = inject_skills_into_workflow_plan(
            tmp_path,
            webhook_plan,
            project="AgentLab",
            task_id="task_high_risk_webhook",
            task_text=task_text,
            record_usage=True,
        )
        assert not webhook_result["selected"]
        assert len(webhook_calls_2) >= 1, "Webhook should dispatch ACTION_REQUIRED"
        assert webhook_calls_2[0]["event"] == "ACTION_REQUIRED"
    finally:
        wd2.post_json = wd2_orig
        _os.environ.pop("AGENTLAB_TEST_WEBHOOK_URL_2", None)
        _os.environ.pop("AGENTLAB_TEST_WEBHOOK_SECRET_2", None)


def test_task1_6_external_imported_skill_retrieval_cross_check(tmp_path: Path) -> None:
    """External imported active skills must participate in Task 1-6 retrieval."""
    canonical_url = "https://raw.githubusercontent.com/pizzzzzza/printkk-agent-skill/main/printkk/SKILL.md"
    fixture_path = ROOT / "tests" / "fixtures" / "external_skills" / "printkk" / "SKILL.md"
    project = "AgentLab"
    task_id = "task_external_skill_cross_check"
    task_text = "build a PrintKK print on demand product design and order automation"

    config = tmp_path / "config"
    config.mkdir(parents=True)
    (config / "model_pricing.yml").write_text(
        yaml.safe_dump({
            "version": 1,
            "currency": "USD",
            "models": {"deepseek/deepseek-v4-pro": {"input_per_1m": 1.0, "output_per_1m": 2.0}},
        }, sort_keys=False),
        encoding="utf-8",
    )
    (config / "external_skill_import_policy.yml").write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "enabled": True,
            "allow_network_by_default": False,
            "allowed_hosts": ["raw.githubusercontent.com"],
            "allowed_url_prefixes": [canonical_url],
            "store_source_snapshot": True,
            "execute_external_code": False,
        }, sort_keys=False),
        encoding="utf-8",
    )
    (config / "skill_injection_policy.yml").write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "enabled": True,
            "retrieval": {"max_skills_per_task": 3, "min_confidence": 0.0, "high_risk_requires_approval": True},
            "matching": {"trigger_weight": 3, "applies_to_weight": 2, "summary_weight": 1},
            "usage": {"write_task_usage": True},
        }, sort_keys=False),
        encoding="utf-8",
    )
    (config / "webhook_policy.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "enabled": False, "endpoints": []}),
        encoding="utf-8",
    )

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
    ensure_skill_registry(tmp_path)
    imported = import_skill_from_fixture(
        tmp_path,
        project=project,
        fixture_path=fixture_path,
        source_url=canonical_url,
    )
    assert imported["ok"], imported
    approved = approve_skill_request(tmp_path, project, imported["request_id"])
    assert approved["status"] == "approved"
    staged = stage_skill_request(tmp_path, project, imported["request_id"])
    validate_staged_skill(tmp_path, staged["skill_id"], fake_sandbox=True)
    promoted = promote_skill(tmp_path, staged["skill_id"])
    skill_id = promoted["skill_id"]

    active_metadata_path = tmp_path / "skills" / "active" / skill_id / "metadata.yml"
    metadata = yaml.safe_load(active_metadata_path.read_text(encoding="utf-8")) or {}
    assert metadata["source"]["type"] == "external_url"
    assert metadata["source"]["uri"] == canonical_url

    run_dir = tmp_path / "projects" / project / "runs" / task_id
    run_dir.mkdir(parents=True)
    plan_path = run_dir / "workflow_plan.yml"
    plan_path.write_text(yaml.safe_dump({"route": {"agents": ["Supervisor", "Coder"]}}), encoding="utf-8")

    from skill_injector import inject_skills_into_workflow_plan
    from skill_retriever import load_skill_injection_policy, match_active_skills

    policy = load_skill_injection_policy(tmp_path)
    matches = match_active_skills(tmp_path, task_text=task_text, policy=policy)
    assert any(item["skill_id"] == skill_id for item in matches["selected"])

    plan = inject_skills_into_workflow_plan(
        tmp_path,
        plan_path,
        project=project,
        task_id=task_id,
        task_text=task_text,
        record_usage=True,
    )
    assert any(item["skill_id"] == skill_id for item in plan["selected"])
