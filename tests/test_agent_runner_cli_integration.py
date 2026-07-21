"""Tests for agent_runner CLI executor dispatch integration.

These tests prove that ``run_agent_model`` in ``agent_runner.py`` actually
dispatches through the CLI executor before falling back to the direct API path.

No real subprocess is spawned — ``run_cli_agent`` and ``generate_text`` are
mocked so the dispatch logic is tested in isolation.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml


# Make agent_runtime/ importable
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "agent_runtime"))
SYNTHESIS_AGENTS = yaml.safe_load(
    (ROOT / "config" / "production_packs.yml").read_text(encoding="utf-8")
)["pack_synthesis_policy"]["agents"]

from schemas import AgentRoute, LLMCallResult, WorkflowPlan  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────────────


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _make_plan(tmp_path: Path, budget_mode: str = "balanced") -> WorkflowPlan:
    """Build a minimal WorkflowPlan for testing."""
    _write_role_binding_policy(tmp_path)
    route = AgentRoute(task_size="small", agents=["Supervisor", "Coder"])
    return WorkflowPlan(
        project="TestProject",
        task_id="task_test_001",
        agentlab_root=str(tmp_path),
        project_root=str(tmp_path / "projects" / "TestProject"),
        repo_path=str(tmp_path / "projects" / "TestProject"),
        run_dir=str(tmp_path / "projects" / "TestProject" / "runs" / "task_test_001"),
        user_request_path=str(
            tmp_path / "projects" / "TestProject" / "runs" / "task_test_001" / "user_request.md"
        ),
        budget_mode=budget_mode,
        route=route,
    )


def test_media_artifact_producer_generic_dispatch_is_blocked_before_provider(
    tmp_path: Path, monkeypatch
) -> None:
    from agent_runner import run_agent_model

    plan = _make_plan(tmp_path)
    plan.route.route_key = "media_generation_task"
    plan.route.agents = ["Supervisor", "ArtifactProducer"]
    provider_called = False

    def forbidden_provider(*args, **kwargs):
        nonlocal provider_called
        provider_called = True
        raise AssertionError("generic provider must not run for media ArtifactProducer")

    monkeypatch.setattr("agent_runner.run_cli_agent", forbidden_provider)
    monkeypatch.setattr("agent_runner.generate_text", forbidden_provider)

    result = run_agent_model(
        tmp_path,
        plan,
        "ArtifactProducer",
        Path(plan.run_dir) / "artifact_producer_report.md",
    )

    assert result.status == "blocked_user_decision"
    assert result.error == "media_artifact_producer_requires_adapter_execution"
    assert result.raw_usage["provider_process_started"] is False
    assert provider_called is False


def test_writer_explicit_ultracode_opt_in_selects_dedicated_capacity_contract(
    tmp_path: Path,
) -> None:
    from agent_runner import _resolve_cli_profile_for_agent

    plan = _make_plan(tmp_path)
    plan.route.agents = ["Writer"]
    plan.included_agents["Writer"] = {
        "ultracode_opt_in": True,
        "writer_mode": "developmental_ultracode",
        "work_type": "revision_plan",
    }

    _configs, _mode, _role, profile = _resolve_cli_profile_for_agent(
        ROOT,
        plan,
        "Writer",
    )

    assert profile["writer_workflow_activation_status"] == "requested"
    assert profile["invocation_contract"] == "claude_writer_ultracode"
    assert profile["capacity_route"] == "WriterUltracode"
    assert profile["default"] == "deepseek_v4_pro"


def test_writer_without_explicit_opt_in_keeps_the_pure_writer_contract(
    tmp_path: Path,
) -> None:
    from agent_runner import _resolve_cli_profile_for_agent

    plan = _make_plan(tmp_path)
    plan.route.agents = ["Writer"]

    _configs, _mode, _role, profile = _resolve_cli_profile_for_agent(
        ROOT,
        plan,
        "Writer",
    )

    assert profile.get("writer_workflow_activation_status") is None
    assert profile["invocation_contract"] == "claude_writer"
    assert profile["capacity_route"] == "Writer"


def test_narrative_planner_resolves_fixed_claude_deepseek_route(
    tmp_path: Path,
) -> None:
    from agent_runner import _resolve_cli_profile_for_agent

    plan = _make_plan(tmp_path)
    plan.route.route_key = "narrative_rewrite_plan"
    plan.route.agents = ["Supervisor", "NarrativePlanner"]

    _configs, _mode, role, profile = _resolve_cli_profile_for_agent(
        ROOT,
        plan,
        "NarrativePlanner",
    )

    assert role == "narrative_planner"
    assert profile["cli_agent"] == "claude_code"
    assert profile["invocation_contract"] == "claude_narrative_planner"
    assert profile["default"] == "deepseek_v4_pro"
    assert profile["capacity_route"] == "NarrativePlannerRewrite"


def test_narrative_planner_missing_contract_blocks_before_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent_runner import run_agent_model

    plan = _make_plan(tmp_path)
    plan.route.route_key = "narrative_rewrite_plan"
    plan.route.agents = ["Supervisor", "NarrativePlanner"]
    provider_called = False

    def forbidden_provider(*args, **kwargs):
        nonlocal provider_called
        provider_called = True
        raise AssertionError("provider must not run without rewrite contract")

    monkeypatch.setattr("agent_runner.run_cli_agent", forbidden_provider)
    monkeypatch.setattr("agent_runner.generate_text", forbidden_provider)

    result = run_agent_model(
        tmp_path,
        plan,
        "NarrativePlanner",
        Path(plan.run_dir) / "chapter_state_plan.yml",
    )

    assert result.status == "blocked_user_decision"
    assert result.error == "narrative_rewrite_contract_missing_or_symlinked"
    assert result.raw_usage["provider_process_started"] is False
    assert provider_called is False


def test_narrative_planner_context_accepts_only_hash_bound_inputs(
    tmp_path: Path,
) -> None:
    from agent_runner import narrative_planner_context_source_files

    plan = _make_plan(tmp_path)
    plan.route.route_key = "narrative_rewrite_plan"
    plan.route.agents = ["Supervisor", "NarrativePlanner"]
    run_dir = Path(plan.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in ("user_request.md", "workflow_plan.yml", "mission_contract.yml"):
        (run_dir / name).write_text(f"source: {name}\n", encoding="utf-8")
    evidence = tmp_path / "audit" / "heavy_audit_summary.yml"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("status: rewrite_required\n", encoding="utf-8")
    payload = evidence.read_bytes()
    _write_yaml(
        run_dir / "narrative_rewrite_contract.yml",
        {
            "schema_version": 1,
            "project": "TestProject",
            "status": "candidate_contract",
            "candidate_only": True,
            "production_modified": False,
            "blocking_evidence_confirmed": True,
            "chapter_range": [1, 2],
            "assigned_inputs": [
                {
                    "source_path": "audit/heavy_audit_summary.yml",
                    "staged_path": "artifact_inputs/01_heavy_audit_summary.yml",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "byte_count": len(payload),
                    "read_only": True,
                }
            ],
        },
    )

    sources = narrative_planner_context_source_files(
        tmp_path,
        plan,
        run_dir / "chapter_state_plan.yml",
    )

    assert evidence in sources
    assert run_dir / "narrative_rewrite_contract.yml" in sources


def test_writer_ultracode_opt_in_reaches_cli_only_through_dedicated_route(
    tmp_path: Path,
) -> None:
    from agent_runner import run_agent_model

    plan = _make_plan(tmp_path)
    plan.route.agents = ["Writer"]
    plan.included_agents["Writer"] = {
        "ultracode_opt_in": True,
        "writer_mode": "developmental_ultracode",
        "work_type": "revision_plan",
    }
    observed: dict[str, object] = {}

    def fake_cli(_plan, _agent, profile, **kwargs):
        observed["profile"] = dict(profile)
        observed["sealed_messages"] = kwargs.get("sealed_messages")
        return LLMCallResult(
            provider="agentlab-cli-executor",
            model="deepseek-v4-pro",
            content="# Revision plan\n",
            status="completed",
        )

    with patch(
        "operational_uploader.maybe_run_operational_agent", return_value=None
    ), patch(
        "agent_runner.compose_agent_messages",
        return_value=[{"role": "user", "content": "Plan a revision."}],
    ), patch("agent_runner.run_cli_agent", side_effect=fake_cli):
        result = run_agent_model(
            ROOT,
            plan,
            "Writer",
            Path(plan.run_dir) / "revision_plan.md",
        )

    assert result.status == "completed"
    profile = observed["profile"]
    assert profile["invocation_contract"] == "claude_writer_ultracode"
    assert profile["capacity_selected_route"] == "WriterUltracode"
    assert profile["capacity_selection_kind"] == "primary"
    assert observed["sealed_messages"]


def test_artifact_producer_profile_is_selected_by_artifact_capability(tmp_path: Path) -> None:
    from agent_runner import _check_cli_role_binding, _resolve_cli_profile_for_agent

    plan = _make_plan(tmp_path)
    plan.route.route_key = "article_light_draft"
    plan.route.agents = ["Supervisor", "ArtifactProducer"]
    request_path = Path(plan.user_request_path)
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text("Write a concise product article.", encoding="utf-8")

    _configs, _mode, _role, profile = _resolve_cli_profile_for_agent(
        ROOT, plan, "ArtifactProducer"
    )

    assert profile["artifact_type"] == "text"
    assert profile["artifact_provider"] == "qwen_cli"
    assert profile["cli_agent"] == "qwen"
    assert profile["invocation_contract"] == "qwen_artifact"
    assert profile["capacity_route"] == "ArtifactProducerQwen"
    assert _check_cli_role_binding(ROOT, "ArtifactProducer", profile)[0] is True

    request_path.write_text("Generate an audio narration.wav", encoding="utf-8")
    _configs, _mode, _role, blocked = _resolve_cli_profile_for_agent(
        ROOT, plan, "ArtifactProducer"
    )
    allowed, reason = _check_cli_role_binding(ROOT, "ArtifactProducer", blocked)
    assert allowed is False
    assert blocked["artifact_type"] == "audio"
    assert blocked["artifact_routing_status"] == "capability_mismatch"
    assert "no approved cli provider satisfies audio" in reason


def test_artifact_producer_honors_prebound_native_codex_yaml_route(
    tmp_path: Path,
) -> None:
    from agent_runner import _check_cli_role_binding, _resolve_cli_profile_for_agent
    from protocols.artifact_task import build_artifact_task_contract

    plan = _make_plan(tmp_path)
    plan.route.route_key = "artifact_production_task"
    plan.route.agents = ["Supervisor", "ArtifactProducer"]
    request_path = Path(plan.user_request_path)
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text("Create fact_distillation.yml as YAML.", encoding="utf-8")
    contract = build_artifact_task_contract(
        ROOT,
        request_path.read_text(encoding="utf-8"),
        artifact_type="text",
        output_path="runs/task_test_001/artifacts/fact_distillation.yml",
        project="TestProject",
        task_id="task_test_001",
        preferred_provider="codex_cli",
    )
    _write_yaml(Path(plan.run_dir) / "artifact_task.yml", contract)

    _configs, _mode, _role, profile = _resolve_cli_profile_for_agent(
        ROOT, plan, "ArtifactProducer"
    )

    assert profile["artifact_provider"] == "codex_cli"
    assert profile["cli_agent"] == "codex"
    assert profile["invocation_contract"] == "codex"
    assert profile["capacity_route"] == "ArtifactProducerCodex"
    assert _check_cli_role_binding(ROOT, "ArtifactProducer", profile)[0] is True


def test_artifact_producer_full_api_uses_explicit_text_api_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent_runner import _resolve_cli_profile_for_agent

    plan = _make_plan(tmp_path)
    plan.route.route_key = "article_light_draft"
    plan.route.agents = ["Supervisor", "ArtifactProducer"]
    request_path = Path(plan.user_request_path)
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text("Write a concise markdown article.", encoding="utf-8")
    monkeypatch.setenv("AGENTLAB_MODE", "full_api")

    _configs, mode, _role, profile = _resolve_cli_profile_for_agent(
        ROOT, plan, "ArtifactProducer"
    )

    assert mode == "full_api"
    assert profile["executor_type"] == "direct_api"
    assert profile["artifact_provider"] == "qwen_37max_api"
    assert profile["artifact_routing_status"] == "routed"

    request_path.write_text("Create a spreadsheet.xlsx", encoding="utf-8")
    _configs, _mode, _role, blocked = _resolve_cli_profile_for_agent(
        ROOT, plan, "ArtifactProducer"
    )
    assert blocked["artifact_routing_status"] == "capability_mismatch"
    assert blocked["executor_type"] == "blocked"


def test_artifact_producer_does_not_cross_execution_mode_billing_surface(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent_runner import _resolve_cli_profile_for_agent

    plan = _make_plan(tmp_path)
    plan.route.route_key = "article_light_draft"
    request_path = Path(plan.user_request_path)
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text("Write a markdown article.", encoding="utf-8")
    monkeypatch.setenv("AGENTLAB_MODE", "qwen_token_plan_cli")

    _configs, mode, _role, profile = _resolve_cli_profile_for_agent(
        ROOT, plan, "ArtifactProducer"
    )

    assert mode == "qwen_token_plan_cli"
    assert profile["artifact_routing_status"] == "capability_mismatch"
    assert profile["_artifact_task_contract"]["routing"]["mode_blocker"] == (
        "unsupported_artifact_execution_mode:qwen_token_plan_cli"
    )


def test_artifact_producer_materializes_contract_before_cli_execution(
    tmp_path: Path,
) -> None:
    from agent_runner import run_agent_model

    plan = _make_plan(tmp_path)
    plan.route.route_key = "article_light_draft"
    plan.route.agents = ["Supervisor", "ArtifactProducer"]
    request_path = Path(plan.user_request_path)
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text("Write a concise product article.", encoding="utf-8")
    run_dir = Path(plan.run_dir)

    def fake_cli(_plan, _agent, profile, **_kwargs):
        contract_path = run_dir / "artifact_task.yml"
        assert contract_path.exists()
        contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        assert contract["artifact_type"] == "text"
        assert contract["routing"]["selected"]["provider_id"] == "qwen_cli"
        assert profile["cli_agent"] == "qwen"
        for raw_path in contract["validation"]["required_paths"]:
            target = Path(plan.project_root) / raw_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# Article candidate\n", encoding="utf-8")
        return LLMCallResult(
            provider="agentlab-cli-executor",
            model="deepseek-v4-pro",
            content="# Article candidate\n",
        )

    with patch(
        "operational_uploader.maybe_run_operational_agent", return_value=None
    ), patch(
        "agent_runner.compose_agent_messages",
        return_value=[{"role": "user", "content": "Write article"}],
    ), patch("agent_runner.run_cli_agent", side_effect=fake_cli):
        result = run_agent_model(
            ROOT,
            plan,
            "ArtifactProducer",
            run_dir / "artifact_producer_report.md",
        )

    assert result.status == "completed"
    assert result.raw_usage["capacity_route_id"] == "ArtifactProducerQwen"


def test_artifact_producer_context_resolves_internal_project_config_symlink(
    tmp_path: Path,
) -> None:
    from agent_runner import artifact_producer_context_source_files

    plan = _make_plan(tmp_path)
    project_root = Path(plan.project_root)
    agent_docs = project_root / "agent_docs"
    agent_docs.mkdir(parents=True, exist_ok=True)
    config_target = agent_docs / "project_config.yml"
    config_target.write_text("project: TestProject\n", encoding="utf-8")
    (project_root / "project_config.yml").symlink_to(
        Path("agent_docs") / "project_config.yml"
    )

    sources = artifact_producer_context_source_files(
        tmp_path,
        plan,
        Path(plan.run_dir) / "artifact_producer_report.md",
    )

    assert config_target.resolve() in sources
    assert all(not source.is_symlink() for source in sources)


def test_unsupported_audio_artifact_fails_with_capability_mismatch_before_provider(
    tmp_path: Path,
) -> None:
    from agent_runner import run_agent_model

    plan = _make_plan(tmp_path)
    plan.route.route_key = "artifact_production_task"
    plan.route.agents = ["Supervisor", "ArtifactProducer"]
    request_path = Path(plan.user_request_path)
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text("Generate an audio narration.wav", encoding="utf-8")

    with patch(
        "operational_uploader.maybe_run_operational_agent", return_value=None
    ), patch("agent_runner.run_cli_agent") as cli, patch(
        "agent_runner.generate_text"
    ) as direct_api:
        result = run_agent_model(
            ROOT,
            plan,
            "ArtifactProducer",
            Path(plan.run_dir) / "artifact_producer_report.md",
        )

    assert result.status == "blocked_user_decision"
    assert result.error == "capability_mismatch"
    assert result.raw_usage["reason"] == "capability_mismatch"
    assert result.raw_usage["artifact_type"] == "audio"
    assert result.raw_usage["provider_process_started"] is False
    cli.assert_not_called()
    direct_api.assert_not_called()


def _write_role_binding_policy(root: Path) -> None:
    """Write the minimal role binding policy needed by CLI dispatch tests."""
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "agent_role_bindings.yml").write_text(
        """
schema_version: 1
roles:
  Supervisor:
    allowed_workers: [hermes, qwen, claude_code]
  Coder:
    allowed_workers: [claude_code, codex, aider]
  Writer:
    allowed_workers: [claude_code]
  Observer:
    allowed_workers: [agy]
  ArtifactProducer:
    allowed_workers: [grok, codex, qwen]
  NarrativePlanner:
    allowed_workers: [claude_code]
workers:
  hermes:
    worker_capable: true
    worker_capabilities: [role_worker]
    allowed_roles: [Supervisor]
    forbidden_roles: []
  claude_code:
    worker_capable: true
    worker_capabilities: [role_worker]
    allowed_roles: [Supervisor, Coder, NarrativePlanner, Writer]
    forbidden_roles: []
  codex:
    worker_capable: true
    worker_capabilities: [role_worker]
    allowed_roles: [Coder, ArtifactProducer]
    forbidden_roles: [Supervisor, Writer, Observer]
  agy:
    worker_capable: true
    worker_capabilities: [multimodal_observer]
    allowed_roles: [Observer]
    forbidden_roles: [Supervisor, Coder, Writer, ArtifactProducer]
  grok:
    worker_capable: true
    worker_capabilities: [artifact_producer]
    allowed_roles: [ArtifactProducer]
    forbidden_roles: [Supervisor, Coder, Writer, Observer]
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _cli_role_profile() -> dict:
    """Return a minimal CLI-backed supervisor profile."""
    return {
        "executor_type": "cli_agent",
        "cli_agent": "hermes",
        "cli_command": 'hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}, perform the requested AgentLab role work, and return a concise markdown report with findings, actions taken, verification, and blockers."',
        "default": "deepseek_v4_pro",
    }


def _cli_success_result() -> LLMCallResult:
    """Return a simulated successful CLI LLMCallResult."""
    return LLMCallResult(
        provider="agentlab-cli-executor",
        model="hermes",
        content="# Supervisor Report (CLI)\n\nAll good.",
        status="completed",
    )


def _cli_not_available() -> object:
    """Return a CliAgentNotAvailable sentinel."""
    from cli_executor import CliAgentNotAvailable

    return CliAgentNotAvailable(
        cli_agent="hermes",
        reason="binary_not_found",
        detail="hermes not in PATH",
    )


def _api_fallback_result() -> LLMCallResult:
    """Return a simulated API fallback LLMCallResult."""
    return LLMCallResult(
        provider="deepseek",
        model="deepseek_v4_flash",
        content="# Supervisor Report (API fallback)\n\nAll good via API.",
        status="completed",
    )


def test_writer_prompt_requires_delivery_edit_blocks(tmp_path: Path) -> None:
    from agent_runner import compose_agent_messages

    config_dir = tmp_path / "config"
    template_dir = tmp_path / "agent_templates"
    project_root = tmp_path / "projects" / "TestProject"
    run_dir = tmp_path / "projects" / "TestProject" / "runs" / "task_test_001"
    config_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)
    (project_root / "project_brain").mkdir(parents=True)
    run_dir.mkdir(parents=True)
    (config_dir / "agent_registry.yml").write_text(
        """
agents:
  Writer:
    template_path: agent_templates/writer.md
    role: Writer
""".lstrip(),
        encoding="utf-8",
    )
    (template_dir / "writer.md").write_text("# Writer\n\nEmit candidate files.\n", encoding="utf-8")
    (run_dir / "user_request.md").write_text("写 Crown 第 1 章候选正文。", encoding="utf-8")
    (run_dir / "workflow_plan.yml").write_text(
        "route:\n  route_key: narrative_light_chapter\nworkflow_marker: do_not_inject_full_workflow\n",
        encoding="utf-8",
    )
    (run_dir / "fiction_draft.md").write_text("old_current_run_draft_should_not_be_injected\n", encoding="utf-8")
    (run_dir / "writer_contract_retry_feedback.yml").write_text(
        "status: correction_required\nretry_feedback_marker: exact_schema_required\n",
        encoding="utf-8",
    )
    (run_dir / "mission_contract.yml").write_text(
        """
allowed_output_files:
  - runs/task_test_001/fiction_draft.md
  - runs/task_test_001/continuity_ledger.yml
  - runs/task_test_001/state_transition_proposal.yml
  - runs/task_test_001/narrative_delivery_receipt.yml
""".lstrip(),
        encoding="utf-8",
    )
    (run_dir / "chapter_packet.yml").write_text(
        """
chapter_intent:
  target_character_range: [4500, 5500]
  hard_character_range: [3000, 8000]
must_read:
  - project_brain/project_fact_snapshot.yml
  - ../outside_project_story.yml
""".lstrip(),
        encoding="utf-8",
    )
    (project_root / "project_brain" / "project_fact_snapshot.yml").write_text(
        "project: TestProject\ncanon_marker: loaded_from_chapter_packet\n",
        encoding="utf-8",
    )
    (project_root.parent / "outside_project_story.yml").write_text(
        "outside_project_marker: must_not_be_injected\n",
        encoding="utf-8",
    )
    skill_path = tmp_path / "skills" / "narrative-lite" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("writer_skill_marker: injected_without_local_path\n", encoding="utf-8")
    plan = _make_plan(tmp_path)
    plan.route.agents = ["Supervisor", "Writer"]
    plan.skills = {
        "selected": [
            {
                "name": "narrative-chapter-writer-lite",
                "skill_path": str(skill_path),
                "injected_into": ["Writer"],
            }
        ]
    }

    messages = compose_agent_messages(tmp_path, plan, "Writer", run_dir / "writer_report.md")
    user_message = messages[-1]["content"]
    all_message_text = "\n".join(message["content"] for message in messages)

    assert "Produce the AgentLab narrative candidate files" in user_message
    assert "Do not write a prose report." in user_message
    assert "Do not copy substantive prose from the previous candidate chapter" in all_message_text
    assert "AGENTLAB_EDIT block" in user_message
    assert "fiction_draft.md" in user_message
    assert "loaded_from_chapter_packet" in user_message
    assert "must_not_be_injected" not in user_message
    assert "writer_skill_marker" in user_message
    assert "retry_feedback_marker: exact_schema_required" in user_message
    assert "target_character_range: [4500, 5500]" in user_message
    assert "hard_character_range: [3000, 8000]" in user_message
    assert str(tmp_path) not in all_message_text
    assert "do_not_inject_full_workflow" not in user_message
    assert "old_current_run_draft_should_not_be_injected" not in user_message
    assert "Prepare the AgentLab report" not in user_message

    for malformed_packet in (
        "- not-a-mapping\n",
        "chapter_intent: not-a-mapping\n",
        "must_read: project_brain/project_fact_snapshot.yml\n",
    ):
        (run_dir / "chapter_packet.yml").write_text(
            malformed_packet,
            encoding="utf-8",
        )
        malformed_messages = compose_agent_messages(
            tmp_path,
            plan,
            "Writer",
            run_dir / "writer_report.md",
        )
        malformed_user_message = malformed_messages[-1]["content"]
        assert "Produce the AgentLab narrative candidate files" in malformed_user_message
        assert "Draft length contract" not in malformed_user_message
        assert "loaded_from_chapter_packet" not in malformed_user_message


def test_narrative_heavy_audit_prompts_require_exact_candidate_blocks(tmp_path: Path) -> None:
    from agent_runner import compose_agent_messages

    config_dir = tmp_path / "config"
    template_dir = tmp_path / "agent_templates"
    project_root = tmp_path / "projects" / "TestProject"
    run_dir = project_root / "runs" / "task_test_001"
    config_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    (config_dir / "agent_registry.yml").write_text(
        """
agents:
  Reviewer:
    template_path: agent_templates/reviewer.md
    role: Reviewer
  Scribe:
    template_path: agent_templates/scribe.md
    role: Scribe
  Verifier:
    template_path: agent_templates/verifier.md
    role: Verifier
""".lstrip(),
        encoding="utf-8",
    )
    for name in ["reviewer", "scribe", "verifier"]:
        (template_dir / f"{name}.md").write_text(f"# {name.title()}\n", encoding="utf-8")
    (run_dir / "user_request.md").write_text("审计 Crown 第 1-10 章。", encoding="utf-8")
    (run_dir / "mission_contract.yml").write_text("task_domain: creative_writing\n", encoding="utf-8")
    (run_dir / "narrative_audit_manifest.yml").write_text("chapter_range: [1, 10]\n", encoding="utf-8")
    (run_dir / "narrative_audit_context.md").write_text("# Audit context\n", encoding="utf-8")
    (run_dir / "narrative_heavy_audit_scribe_output_contract.yml").write_text(
        "status: blocked\nissues:\n  - retry_feedback_marker\n",
        encoding="utf-8",
    )
    plan = _make_plan(tmp_path)
    plan.route.route_key = "narrative_heavy_audit"
    plan.route.agents = ["Supervisor", "Reviewer", "Scribe", "Verifier"]

    expected = {
        "Reviewer": ["fiction_review.yml", "continuity_failure_report.yml"],
        "Scribe": ["state_transition_proposal.yml"],
        "Verifier": ["revision_or_rewrite_proposal.yml"],
    }
    for agent, outputs in expected.items():
        messages = compose_agent_messages(
            tmp_path,
            plan,
            agent,
            run_dir / f"{agent.lower()}_role_session_capture.md",
        )
        text = "\n".join(message["content"] for message in messages)
        assert "Narrative heavy audit" in text
        assert "AGENTLAB_EDIT" in text
        assert "production_modified: false" in text
        for output in outputs:
            assert output in text
        if agent == "Reviewer":
            assert "# Audit context" in text
        else:
            assert "# Audit context" not in text
        if agent == "Scribe":
            assert "retry_feedback_marker" in text
            assert "top level" in text


def test_narrative_heavy_audit_cli_roles_receive_sealed_context(
    tmp_path: Path,
) -> None:
    from agent_runner import run_agent_model

    plan = _make_plan(tmp_path)
    plan.route.route_key = "narrative_heavy_audit"
    plan.route.agents = ["Supervisor", "Reviewer", "Scribe", "Verifier"]
    run_dir = Path(plan.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    for name, value in {
        "user_request.md": "Audit Crown chapters 1-20.\n",
        "workflow_plan.yml": "route: narrative_heavy_audit\n",
        "mission_contract.yml": "task_domain: creative_writing\n",
        "01_supervisor_plan.md": "# Governed plan\n",
        "narrative_audit_manifest.yml": "chapter_range: [1, 20]\n",
        "narrative_audit_context.md": "# Complete bounded audit context\n",
    }.items():
        (run_dir / name).write_text(value, encoding="utf-8")
    project_root = Path(plan.project_root)
    (project_root / "project_brain").mkdir(parents=True, exist_ok=True)
    (project_root / "project_brain" / "project_fact_snapshot.yml").write_text(
        "facts: []\n",
        encoding="utf-8",
    )
    (project_root / "project_artifact_index.yml").write_text(
        "artifacts: []\n",
        encoding="utf-8",
    )

    messages = [
        {"role": "system", "content": "Use only the sealed audit context."},
        {"role": "user", "content": "Return the exact required audit blocks."},
    ]
    observed: dict[str, object] = {}

    def fake_cli(_plan, _agent, profile, **kwargs):
        observed["profile"] = dict(profile)
        observed["sealed_messages"] = kwargs.get("sealed_messages")
        observed["outbound_source_paths"] = kwargs.get("outbound_source_paths")
        return LLMCallResult(
            provider="agentlab-cli-executor",
            model="qwen3.6-flash",
            content="review complete",
            status="completed",
        )

    with patch(
        "operational_uploader.maybe_run_operational_agent", return_value=None
    ), patch(
        "agent_runner.compose_agent_messages", return_value=messages
    ), patch("agent_runner.run_cli_agent", side_effect=fake_cli):
        result = run_agent_model(
            ROOT,
            plan,
            "Reviewer",
            run_dir / "reviewer_role_session_capture.md",
        )

    assert result.status == "completed"
    assert observed["sealed_messages"] == messages
    profile = observed["profile"]
    assert profile["invocation_contract"] == "qwen"
    source_names = {
        Path(path).name for path in observed["outbound_source_paths"]
    }
    assert "narrative_audit_context.md" in source_names
    assert "project_fact_snapshot.yml" in source_names
    assert "project_artifact_index.yml" in source_names


def test_coder_prompt_excludes_current_output_and_placeholder_reports(tmp_path: Path) -> None:
    from agent_runner import compose_agent_messages

    config_dir = tmp_path / "config"
    template_dir = tmp_path / "agent_templates"
    project_root = tmp_path / "projects" / "TestProject"
    run_dir = project_root / "runs" / "task_test_001"
    config_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    (config_dir / "agent_registry.yml").write_text(
        """
agents:
  Coder:
    template_path: agent_templates/coder.md
    role: Coder
""".lstrip(),
        encoding="utf-8",
    )
    (template_dir / "coder.md").write_text("# Coder\n\nImplement scoped code changes.\n", encoding="utf-8")
    (tmp_path / ".agentlab").mkdir(parents=True)
    (tmp_path / "PROJECT_HANDOFF.md").write_text(
        "# HandOff\n\nduplicate_handoff_marker\n",
        encoding="utf-8",
    )
    (tmp_path / ".agentlab" / "HandOff.md").write_text(
        "# HandOff\n\nduplicate_handoff_marker\n",
        encoding="utf-8",
    )
    (run_dir / "user_request.md").write_text("Build the production pack UI concept.", encoding="utf-8")
    (run_dir / "workflow_plan.yml").write_text(
        "route:\n  route_key: interface_sensitive_task\nproduction_pack: full_workflow_plan_marker\n",
        encoding="utf-8",
    )
    (run_dir / "task_packet.yml").write_text(
        "task_packet:\n  project_type: codebase_build_project\n  roles: [Coder]\n  marker: structured_phase_contract_marker\n",
        encoding="utf-8",
    )
    (run_dir / "01_supervisor_plan.md").write_text(
        "# Supervisor\n\nTBD upstream_placeholder_marker\n",
        encoding="utf-8",
    )
    (run_dir / "02_reposcout_report.md").write_text(
        "# RepoScout\n\nreposcout_real_context_marker\n",
        encoding="utf-8",
    )
    (run_dir / "04_interface_map.md").write_text(
        "# InterfaceMapper\n\nPlaceholder interface_placeholder_marker\n",
        encoding="utf-8",
    )
    output_path = run_dir / "06_implementation_report.md"
    output_path.write_text(
        "# Coder\n\nplan-only stale_current_output_marker\n",
        encoding="utf-8",
    )
    plan = _make_plan(tmp_path)

    messages = compose_agent_messages(tmp_path, plan, "Coder", output_path)
    system_message = messages[0]["content"]
    user_message = messages[-1]["content"]

    assert "direct API text-generation path" in system_message
    assert "You cannot run shell commands" in system_message
    assert "execution-mode Coder call" in user_message
    assert "coder_model_call_mode: direct_api_text_generation" in user_message
    assert "Report Coder backend and execution mode as direct_api_text_generation" in user_message
    assert "HTML-style full-file block" in user_message
    assert "execution_backend:" not in user_message
    assert "Commands run by this model call: none" in user_message
    assert "reposcout_real_context_marker" in user_message
    assert "structured_phase_contract_marker" in user_message
    assert "duplicate_handoff_marker" not in user_message
    assert "stale_current_output_marker" not in user_message
    assert "upstream_placeholder_marker" not in user_message
    assert "interface_placeholder_marker" not in user_message
    assert "full_workflow_plan_marker" not in user_message
    assert "Prepare the AgentLab report" not in user_message


def test_artifact_producer_prompt_uses_production_pack_contract_not_code_context(tmp_path: Path) -> None:
    from agent_runner import compose_agent_messages

    config_dir = tmp_path / "config"
    template_dir = tmp_path / "agent_templates"
    project_root = tmp_path / "projects" / "TestProject"
    run_dir = project_root / "runs" / "task_test_001"
    config_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    (config_dir / "agent_registry.yml").write_text(
        """
agents:
  ArtifactProducer:
    template_path: agent_templates/artifact_producer.md
    role: ArtifactProducer
""".lstrip(),
        encoding="utf-8",
    )
    (template_dir / "artifact_producer.md").write_text(
        "# ArtifactProducer\n\nUse production_pack.required_outputs when no artifact_task.yml exists.\n",
        encoding="utf-8",
    )
    (run_dir / "user_request.md").write_text("生成一份产品说明文章。", encoding="utf-8")
    (run_dir / "workflow_plan.yml").write_text(
        "route:\n  route_key: article_light_draft\nworkflow_marker: injected_for_artifact_context\n",
        encoding="utf-8",
    )
    (run_dir / "01_supervisor_plan.md").write_text("# Supervisor\n\narticle audience: operators\n", encoding="utf-8")
    (project_root / "agent_docs").mkdir(parents=True)
    (project_root / "agent_docs" / "01_REPO_MAP.md").write_text("repo_map_should_not_be_injected\n", encoding="utf-8")
    (run_dir / "06_implementation_report.md").write_text("implementation_should_not_be_injected\n", encoding="utf-8")
    plan = _make_plan(tmp_path)
    plan.route.agents = ["Supervisor", "ArtifactProducer"]
    plan.route.route_key = "article_light_draft"
    plan.included_agents = {
        "ArtifactProducer": {
            "required_inputs": [
                "runs/task_xxxx/mission_contract.yml",
                "runs/task_xxxx/user_request.md",
                "runs/task_xxxx/workflow_plan.yml",
            ],
            "required_outputs": [
                "runs/task_xxxx/article_draft.md",
                "runs/task_xxxx/article_structure_check.yml",
            ],
        }
    }
    plan.production_pack = {
        "pack_id": "article_light",
        "required_outputs": ["article_draft.md", "article_structure_check.yml"],
    }
    candidate_dir = run_dir / "artifacts"
    plan.artifact_intent = {
        "candidate_dir": str(candidate_dir),
        "allowed_write_roots": [str(candidate_dir)],
        "declared_production_paths": [],
    }

    messages = compose_agent_messages(tmp_path, plan, "ArtifactProducer", run_dir / "artifact_producer_report.md")
    system_message = messages[0]["content"]
    user_message = messages[-1]["content"]

    assert "Use production_pack.required_outputs when no artifact_task.yml exists" in system_message
    assert "Direct API ArtifactProducer rules" in system_message
    assert "Produce the AgentLab non-code candidate artifacts" in user_message
    assert "article_draft.md" in user_message
    assert "article_structure_check.yml" in user_message
    assert "AGENTLAB_EDIT block" in user_message
    assert "Commands run by this model call: none" in user_message
    assert "repo_map_should_not_be_injected" not in user_message
    assert "implementation_should_not_be_injected" not in user_message
    assert "workflow_marker: injected_for_artifact_context" not in user_message
    assert "Prepare the AgentLab report" not in user_message


def test_pack_synthesis_researcher_prompt_uses_domain_brief_not_code_context(tmp_path: Path) -> None:
    from agent_runner import compose_agent_messages

    config_dir = tmp_path / "config"
    template_dir = tmp_path / "agent_templates"
    project_root = tmp_path / "projects" / "TestProject"
    run_dir = project_root / "runs" / "task_test_001"
    config_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    (config_dir / "agent_registry.yml").write_text(
        """
agents:
  Researcher:
    template_path: agent_templates/researcher.md
    role: Researcher
""".lstrip(),
        encoding="utf-8",
    )
    (config_dir / "production_packs.yml").write_text("packs: []\n", encoding="utf-8")
    (template_dir / "researcher.md").write_text("# Researcher\n\nResearch domain requirements.\n", encoding="utf-8")
    (run_dir / "user_request.md").write_text("设计沉浸式展览生产包。", encoding="utf-8")
    (run_dir / "workflow_plan.yml").write_text(
        "route:\n  route_key: artifact_production_task\nworkflow_marker_should_not_be_injected\n",
        encoding="utf-8",
    )
    (project_root / "agent_docs").mkdir(parents=True)
    (project_root / "agent_docs" / "01_REPO_MAP.md").write_text("repo_map_should_not_be_injected\n", encoding="utf-8")
    (run_dir / "06_implementation_report.md").write_text("implementation_should_not_be_injected\n", encoding="utf-8")
    plan = _make_plan(tmp_path)
    plan.route.agents = ["Supervisor", "Researcher", "ArtifactProducer", "Verifier"]
    plan.route.route_key = "artifact_production_task"
    plan.included_agents = {
        "Researcher": {
            "required_outputs": ["runs/task_xxxx/domain_research_brief.md"],
        }
    }
    plan.production_pack = {
        "status": "synthesis_candidate",
        "pack_id": "pack_synthesis_candidate",
        "agents": SYNTHESIS_AGENTS,
        "task_domain": "multimodal_asset_generation",
        "required_outputs": [
            "production_pack_proposal.yml",
            "domain_memory_contract.yml",
            "lifecycle_profile.yml",
        ],
    }

    messages = compose_agent_messages(tmp_path, plan, "Researcher", run_dir / "03_research_notes.md")
    system_message = messages[0]["content"]
    user_message = messages[-1]["content"]

    assert "Production-pack synthesis Researcher rules" in system_message
    assert "Produce the AgentLab production-pack domain research brief" in user_message
    assert "external resources/providers/tools" in user_message
    assert "code-factory nodes should remain excluded" in user_message
    assert "repo_map_should_not_be_injected" not in user_message
    assert "implementation_should_not_be_injected" not in user_message
    assert "workflow_marker_should_not_be_injected" not in user_message
    assert "Prepare the AgentLab report" not in user_message


def test_pack_synthesis_supervisor_uses_bounded_non_code_packet(
    tmp_path: Path,
) -> None:
    from agent_runner import (
        compose_agent_messages,
        production_pack_context_source_files,
    )

    config_dir = tmp_path / "config"
    template_dir = tmp_path / "agent_templates"
    project_root = tmp_path / "projects" / "TestProject"
    run_dir = project_root / "runs" / "task_test_001"
    config_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    (config_dir / "agent_registry.yml").write_text(
        """
agents:
  Supervisor:
    template_path: agent_templates/supervisor.md
    role: Supervisor
""".lstrip(),
        encoding="utf-8",
    )
    (config_dir / "production_packs.yml").write_text(
        "packs: []\n", encoding="utf-8"
    )
    (template_dir / "supervisor.md").write_text(
        "# Supervisor\n\nCompile the execution contract.\n", encoding="utf-8"
    )
    (run_dir / "user_request.md").write_text(
        "设计沉浸式展览生产包。", encoding="utf-8"
    )
    (run_dir / "mission_contract.yml").write_text(
        "schema_version: 2\ntask_domain: installation_art\n",
        encoding="utf-8",
    )
    (run_dir / "workflow_plan.yml").write_text(
        "route:\n  route_key: artifact_production_task\n", encoding="utf-8"
    )
    plan = _make_plan(tmp_path)
    plan.route.agents = [
        "Supervisor",
        "Researcher",
        "ArtifactProducer",
        "Verifier",
    ]
    plan.route.route_key = "artifact_production_task"
    plan.production_pack = {
        "status": "synthesis_candidate",
        "pack_id": "pack_synthesis_candidate",
        "agents": SYNTHESIS_AGENTS,
        "required_outputs": [
            "production_pack_proposal.yml",
            "domain_memory_contract.yml",
            "lifecycle_profile.yml",
        ],
    }
    plan.included_agents = {
        "Supervisor": {
            "required_outputs": ["runs/task_test_001/01_supervisor_plan.md"]
        }
    }

    output_path = run_dir / "01_supervisor_plan.md"
    messages = compose_agent_messages(
        tmp_path,
        plan,
        "Supervisor",
        output_path,
    )
    sources = production_pack_context_source_files(
        tmp_path,
        plan,
        "Supervisor",
        output_path,
    )
    rendered = "\n".join(item["content"] for item in messages)

    assert "production-pack synthesis Supervisor plan" in rendered
    assert "Researcher, ArtifactProducer, and Verifier" in rendered
    assert "Use only the exact messages and files embedded" in rendered
    assert "Before reading repository/project content" not in rendered
    assert str(tmp_path) not in rendered
    assert {path.name for path in sources} >= {
        "agent_registry.yml",
        "supervisor.md",
        "user_request.md",
        "mission_contract.yml",
        "workflow_plan.yml",
        "production_packs.yml",
    }


def test_artifact_supervisor_receives_governance_metadata_not_source_content(
    tmp_path: Path,
) -> None:
    from agent_runner import compose_agent_messages, supervisor_context_source_files

    project_root = tmp_path / "projects" / "TestProject"
    run_dir = project_root / "runs" / "task_test_001"
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "agent_templates").mkdir()
    (project_root / "agent_docs").mkdir(parents=True)
    (project_root / "project_brain").mkdir()
    (project_root / "production" / "bible").mkdir(parents=True)
    run_dir.mkdir(parents=True)
    (tmp_path / "config" / "agent_registry.yml").write_text(
        "agents:\n  Supervisor:\n    template_path: agent_templates/supervisor.md\n",
        encoding="utf-8",
    )
    (tmp_path / "agent_templates" / "supervisor.md").write_text(
        "# Supervisor\n\nApprove the bounded contract.\n", encoding="utf-8"
    )
    for path, marker in (
        (run_dir / "user_request.md", "request_marker"),
        (run_dir / "workflow_plan.yml", "workflow_marker"),
        (run_dir / "mission_contract.yml", "mission_marker"),
        (run_dir / "artifact_task.yml", "artifact_task_marker"),
        (project_root / "project_artifact_index.yml", "artifact_index_marker"),
        (
            project_root / "project_brain" / "artifact_version_policy.yml",
            "version_policy_marker",
        ),
        (
            project_root / "project_brain" / "local_asset_cleanup_receipt.yml",
            "cleanup_receipt_marker",
        ),
        (project_root / "agent_docs" / "02_TASK_LEDGER.yml", "task_ledger_marker"),
        (
            project_root / "production" / "bible" / "world.md",
            "source_content_must_not_reach_supervisor",
        ),
    ):
        path.write_text(f"marker: {marker}\n", encoding="utf-8")

    plan = _make_plan(tmp_path)
    plan.route.route_key = "artifact_production_task"
    plan.route.agents = ["Supervisor", "ArtifactProducer"]
    output_path = run_dir / "01_supervisor_plan.md"

    sources = supervisor_context_source_files(tmp_path, plan, output_path)
    messages = compose_agent_messages(tmp_path, plan, "Supervisor", output_path)
    rendered = "\n".join(item["content"] for item in messages)

    assert {path.name for path in sources} >= {
        "artifact_task.yml",
        "project_artifact_index.yml",
        "artifact_version_policy.yml",
        "local_asset_cleanup_receipt.yml",
        "02_TASK_LEDGER.yml",
    }
    assert "artifact_task_marker" in rendered
    assert "artifact_index_marker" in rendered
    assert "version_policy_marker" in rendered
    assert "cleanup_receipt_marker" in rendered
    assert "task_ledger_marker" in rendered
    assert "Artifact governance Supervisor rules" in rendered
    assert "Do not request tools, shell commands, file reads" in rendered
    assert "source_content_must_not_reach_supervisor" not in rendered


def test_pack_synthesis_artifact_and_verifier_prompts_bind_returned_contracts(
    tmp_path: Path,
) -> None:
    from agent_runner import (
        compose_agent_messages,
        production_pack_context_source_files,
    )

    config_dir = tmp_path / "config"
    template_dir = tmp_path / "agent_templates"
    project_root = tmp_path / "projects" / "TestProject"
    run_dir = project_root / "runs" / "task_test_001"
    config_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    (config_dir / "agent_registry.yml").write_text(
        """
agents:
  ArtifactProducer:
    template_path: agent_templates/artifact_producer.md
    role: ArtifactProducer
  Verifier:
    template_path: agent_templates/verifier.md
    role: Verifier
""".lstrip(),
        encoding="utf-8",
    )
    (config_dir / "production_packs.yml").write_text("packs: []\n", encoding="utf-8")
    (template_dir / "artifact_producer.md").write_text(
        "# ArtifactProducer\n", encoding="utf-8"
    )
    (template_dir / "verifier.md").write_text("# Verifier\n", encoding="utf-8")
    (run_dir / "user_request.md").write_text(
        "设计沉浸式展览生产包。", encoding="utf-8"
    )
    (run_dir / "workflow_plan.yml").write_text(
        "route:\n  route_key: artifact_production_task\n", encoding="utf-8"
    )
    (run_dir / "domain_research_brief.md").write_text(
        "# Domain Research Brief\n\nresearch_marker\n", encoding="utf-8"
    )
    (run_dir / "production_pack_research_contract.yml").write_text(
        "status: pass\n", encoding="utf-8"
    )
    secret = "sk-" + ("a" * 40)
    (run_dir / "01_supervisor_plan.md").write_text(
        f"# Supervisor\n\nrun path: {run_dir}\ncredential: {secret}\n",
        encoding="utf-8",
    )
    for name in (
        "production_pack_proposal.yml",
        "domain_memory_contract.yml",
        "lifecycle_profile.yml",
        "production_pack_output_contract.yml",
    ):
        (run_dir / name).write_text(f"status: candidate\nmarker: {name}\n", encoding="utf-8")
    plan = _make_plan(tmp_path)
    plan.route.agents = ["Supervisor", "Researcher", "ArtifactProducer", "Verifier"]
    plan.route.route_key = "artifact_production_task"
    plan.production_pack = {
        "status": "synthesis_candidate",
        "pack_id": "pack_synthesis_candidate",
        "agents": SYNTHESIS_AGENTS,
        "required_outputs": [
            "production_pack_proposal.yml",
            "domain_memory_contract.yml",
            "lifecycle_profile.yml",
        ],
    }
    plan.included_agents = {
        "ArtifactProducer": {
            "required_outputs": [
                "runs/task_test_001/production_pack_proposal.yml",
                "runs/task_test_001/domain_memory_contract.yml",
                "runs/task_test_001/lifecycle_profile.yml",
            ]
        },
        "Verifier": {"required_outputs": ["runs/task_test_001/verification_report.md"]},
    }

    artifact_messages = compose_agent_messages(
        tmp_path,
        plan,
        "ArtifactProducer",
        run_dir / "artifact_producer_report.md",
    )
    verifier_messages = compose_agent_messages(
        tmp_path,
        plan,
        "Verifier",
        run_dir / "verification_report.md",
    )
    artifact_sources = production_pack_context_source_files(
        tmp_path,
        plan,
        "ArtifactProducer",
        run_dir / "artifact_producer_report.md",
    )
    verifier_sources = production_pack_context_source_files(
        tmp_path,
        plan,
        "Verifier",
        run_dir / "verification_report.md",
    )

    artifact_user = artifact_messages[-1]["content"]
    verifier_user = verifier_messages[-1]["content"]
    artifact_system = artifact_messages[0]["content"]
    verifier_system = verifier_messages[0]["content"]
    rendered_messages = "\n".join(
        item["content"] for item in [*artifact_messages, *verifier_messages]
    )
    assert "Emit exactly one full-file AGENTLAB_EDIT" in artifact_user
    assert "do not return a generic or" in artifact_user
    assert "research_marker" in artifact_user
    assert "Verify the AgentLab production-pack candidate" in verifier_user
    assert "production_pack_output_contract.yml" in verifier_user
    assert "Do not emit AGENTLAB_EDIT blocks" in verifier_user
    assert str(tmp_path) not in rendered_messages
    assert secret not in rendered_messages
    assert "<RUN_DIR>" in rendered_messages
    assert "[REDACTED_SECRET]" in rendered_messages
    assert "Use only the exact messages and files embedded" in artifact_system
    assert "Use only the exact messages and files embedded" in verifier_system
    assert "Before reading repository/project content" not in artifact_system
    assert "Before reading repository/project content" not in verifier_system
    artifact_source_names = {path.name for path in artifact_sources}
    verifier_source_names = {path.name for path in verifier_sources}
    assert {
        "agent_registry.yml",
        "artifact_producer.md",
        "user_request.md",
        "workflow_plan.yml",
        "domain_research_brief.md",
        "production_pack_research_contract.yml",
        "production_packs.yml",
    } <= artifact_source_names
    assert {
        "agent_registry.yml",
        "verifier.md",
        "user_request.md",
        "workflow_plan.yml",
        "production_pack_proposal.yml",
        "domain_memory_contract.yml",
        "lifecycle_profile.yml",
        "production_pack_output_contract.yml",
    } <= verifier_source_names
    assert "01_REPO_MAP.md" not in artifact_source_names
    assert "01_REPO_MAP.md" not in verifier_source_names


def test_pack_synthesis_direct_api_fallback_cannot_bypass_outbound_gate(
    tmp_path: Path,
) -> None:
    from agent_runner import run_agent_model
    from outbound_context import PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME

    plan = _make_plan(tmp_path)
    plan.production_pack = {
        "status": "synthesis_candidate",
        "pack_id": "pack_synthesis_candidate",
        "agents": SYNTHESIS_AGENTS,
    }
    run_dir = Path(plan.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    source = run_dir / "domain_research_brief.md"
    source.write_text("# Domain research\n", encoding="utf-8")
    settings = SimpleNamespace(provider="deepseek", model="deepseek-test")

    with patch.dict(
        "os.environ",
        {PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME: "0"},
        clear=False,
    ), patch(
        "operational_uploader.maybe_run_operational_agent", return_value=None
    ), patch(
        "agent_runner._resolve_cli_profile_for_agent",
        return_value=({"agent_model_profiles": {}}, "full_api", "artifact_producer", None),
    ), patch(
        "agent_runner.resolve_agent_settings", return_value=(settings, {})
    ), patch(
        "agent_runner.compose_agent_messages",
        return_value=[{"role": "user", "content": "Return candidate YAML."}],
    ), patch(
        "agent_runner.production_pack_context_source_files",
        return_value=[source],
    ), patch(
        "agent_runner.generate_text"
    ) as generate_text:
        result = run_agent_model(
            tmp_path,
            plan,
            "ArtifactProducer",
            run_dir / "artifact_producer_report.md",
        )

    assert result.status == "blocked_user_decision"
    assert result.error == "production_pack_outbound_context_gate_blocked"
    generate_text.assert_not_called()
    manifest_path = run_dir / "outbound_context_manifest_artifactproducer.yml"
    assert manifest_path.exists()
    assert PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME in manifest_path.read_text(
        encoding="utf-8"
    )


def test_pack_synthesis_cli_unavailable_does_not_switch_to_direct_api(
    tmp_path: Path,
) -> None:
    from agent_runner import run_agent_model

    plan = _make_plan(tmp_path)
    plan.production_pack = {
        "status": "synthesis_candidate",
        "pack_id": "pack_synthesis_candidate",
        "agents": SYNTHESIS_AGENTS,
    }
    run_dir = Path(plan.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    cli_profile = {
        "executor_type": "cli_agent",
        "cli_agent": "agy",
        "cli_command": 'agy --sandbox -p "Read {task_packet_path}"',
    }

    with patch(
        "operational_uploader.maybe_run_operational_agent", return_value=None
    ), patch(
        "agent_runner._resolve_cli_profile_for_agent",
        return_value=(
            {"agent_model_profiles": {}},
            "full_cli",
            "artifact_producer",
            cli_profile,
        ),
    ), patch(
        "agent_runner._check_cli_role_binding", return_value=(True, "allowed")
    ), patch(
        "agent_runner.compose_agent_messages",
        return_value=[{"role": "user", "content": "Return candidate YAML."}],
    ), patch(
        "agent_runner.production_pack_context_source_files", return_value=[]
    ), patch(
        "agent_runner.run_cli_agent", return_value=_cli_not_available()
    ), patch(
        "agent_runner.generate_text"
    ) as generate_text:
        result = run_agent_model(
            tmp_path,
            plan,
            "ArtifactProducer",
            run_dir / "artifact_producer_report.md",
        )

    assert result.status == "blocked_user_decision"
    assert result.error == "production_pack_cli_unavailable_no_fallback"
    assert result.raw_usage["direct_api_fallback_attempted"] is False
    generate_text.assert_not_called()


def test_ordinary_researcher_cli_uses_sealed_sources_instead_of_open_workspace(
    tmp_path: Path,
) -> None:
    from agent_runner import run_agent_model

    plan = _make_plan(tmp_path)
    plan.route.agents = ["Supervisor", "Researcher"]
    run_dir = Path(plan.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    source = run_dir / "mission_contract.yml"
    source.write_text("research_scope: public_sources_only\n", encoding="utf-8")
    messages = [{"role": "user", "content": "Collect bounded evidence."}]
    cli_profile = {
        "executor_type": "cli_agent",
        "cli_agent": "grok",
        "invocation_contract": "grok_research",
        "default": "grok_4_3_hermes_oauth",
    }

    def fake_cli(_plan, agent_name, _profile, **kwargs):
        assert agent_name == "Researcher"
        assert kwargs["sealed_messages"] == messages
        assert kwargs["task_messages"] is None
        assert kwargs["outbound_source_paths"] == [source]
        return _cli_success_result()

    with patch(
        "operational_uploader.maybe_run_operational_agent", return_value=None
    ), patch(
        "agent_runner._resolve_cli_profile_for_agent",
        return_value=(
            {"agent_model_profiles": {}},
            "full_cli",
            "researcher",
            cli_profile,
        ),
    ), patch(
        "agent_runner._check_cli_role_binding", return_value=(True, "allowed")
    ), patch(
        "agent_runner.compose_agent_messages", return_value=messages
    ), patch(
        "agent_runner.researcher_context_source_files", return_value=[source]
    ), patch(
        "agent_runner.run_cli_agent", side_effect=fake_cli
    ), patch(
        "agent_runner.generate_text"
    ) as generate_text:
        result = run_agent_model(
            tmp_path,
            plan,
            "Researcher",
            run_dir / "03_research_notes.md",
            apply_patches=False,
        )

    assert result.status == "completed"
    generate_text.assert_not_called()


def test_coder_allowed_files_include_artifact_candidate_root(tmp_path: Path) -> None:
    from agent_runner import _extract_allowed_files

    plan = _make_plan(tmp_path)
    plan.artifact_intent = {
        "allowed_write_roots": [
            str(Path(plan.project_root) / "runs" / plan.task_id / "artifacts"),
        ],
        "declared_production_paths": [],
    }

    assert _extract_allowed_files(plan) == {"runs/task_test_001/artifacts/"}


def test_coder_candidate_artifacts_allow_direct_patch_application(tmp_path: Path) -> None:
    from agent_runner import _candidate_artifact_patch_application_allowed

    plan = _make_plan(tmp_path)
    candidate_dir = Path(plan.run_dir) / "artifacts"
    plan.artifact_intent = {
        "candidate_dir": str(candidate_dir),
        "allowed_write_roots": [str(candidate_dir)],
        "declared_production_paths": [],
        "allowed_overwrite_paths": [],
    }

    assert _candidate_artifact_patch_application_allowed(plan) is True


def test_coder_candidate_artifacts_do_not_allow_production_patch_application(tmp_path: Path) -> None:
    from agent_runner import _candidate_artifact_patch_application_allowed

    plan = _make_plan(tmp_path)
    candidate_dir = Path(plan.run_dir) / "artifacts"
    plan.artifact_intent = {
        "candidate_dir": str(candidate_dir),
        "allowed_write_roots": [str(candidate_dir)],
        "declared_production_paths": ["src/app.py"],
        "allowed_overwrite_paths": [],
    }

    assert _candidate_artifact_patch_application_allowed(plan) is False


def test_coder_candidate_artifacts_must_be_run_local(tmp_path: Path) -> None:
    from agent_runner import _candidate_artifact_patch_application_allowed

    plan = _make_plan(tmp_path)
    outside_candidate_dir = Path(plan.project_root) / "artifacts"
    plan.artifact_intent = {
        "candidate_dir": str(outside_candidate_dir),
        "allowed_write_roots": [str(outside_candidate_dir)],
        "declared_production_paths": [],
        "allowed_overwrite_paths": [],
    }

    assert _candidate_artifact_patch_application_allowed(plan) is False


def test_coder_applies_run_local_candidate_artifact_blocks_when_policy_is_proposal_first(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent_runner import run_agent_model

    plan = _make_plan(tmp_path)
    run_dir = Path(plan.run_dir)
    run_dir.mkdir(parents=True)
    candidate_dir = run_dir / "artifacts"
    plan.artifact_intent = {
        "candidate_dir": str(candidate_dir),
        "allowed_write_roots": [str(candidate_dir)],
        "declared_production_paths": [],
        "allowed_overwrite_paths": [],
    }

    monkeypatch.setattr(
        "agent_runner._resolve_cli_profile_for_agent",
        lambda *a, **kw: (
            {"agent_model_profiles": {"profiles": {}}, "agent_registry": {"agents": {}}},
            "full_api",
            "coder",
            None,
        ),
    )
    monkeypatch.setattr(
        "operational_uploader.maybe_run_operational_agent",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "agent_runner.resolve_agent_settings",
        lambda *a, **kw: (
            SimpleNamespace(
                provider="qwen-coder",
                provider_type="openai_compatible",
                model="qwen3-coder-next",
                base_url=None,
                api_key_configured=True,
                temperature=0.2,
                top_p=1.0,
                max_output_tokens=2000,
                profile_name="",
            ),
            {
                "execution_policy": {
                    "execution_policy": {"patch_application_policy": "patch_proposal_first"},
                    "coder_policy": {"automatic_patch_application": False},
                },
                "model_providers": {},
            },
        ),
    )
    monkeypatch.setattr(
        "agent_runner.compose_agent_messages",
        lambda *a, **kw: [{"role": "user", "content": "test"}],
    )
    monkeypatch.setattr(
        "brain_governor.evaluate_token_status",
        lambda *a, **kw: {},
    )
    monkeypatch.setattr(
        "agent_runner.generate_text",
        lambda *a, **kw: LLMCallResult(
            provider="qwen-coder",
            model="qwen3-coder-next",
            content="""# Coder Report

<!-- AGENTLAB_EDIT: runs/task_test_001/artifacts/web_ui/index.html -->
```html
<html>ok</html>
```
<!-- END AGENTLAB_EDIT -->
""",
            status="completed",
        ),
    )

    result = run_agent_model(tmp_path, plan, "Coder", run_dir / "06_implementation_report.md")

    assert result.raw_usage["patch_applied"] == 1
    assert result.raw_usage["patch_failed"] == 0
    assert "Patch Application Results" in result.content
    assert (
        Path(plan.project_root) / "runs" / "task_test_001" / "artifacts" / "web_ui" / "index.html"
    ).read_text(encoding="utf-8") == "<html>ok</html>\n"


def test_artifact_producer_applies_run_local_candidate_artifact_blocks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent_runner import run_agent_model

    plan = _make_plan(tmp_path)
    plan.route.agents = ["Supervisor", "ArtifactProducer"]
    plan.route.route_key = "article_light_draft"
    run_dir = Path(plan.run_dir)
    run_dir.mkdir(parents=True)
    candidate_dir = run_dir / "artifacts"
    plan.included_agents = {"ArtifactProducer": {"required_outputs": ["runs/task_xxxx/article_draft.md"]}}
    plan.production_pack = {"pack_id": "article_light", "required_outputs": ["article_draft.md"]}
    plan.artifact_intent = {
        "candidate_dir": str(candidate_dir),
        "allowed_write_roots": [str(candidate_dir)],
        "declared_production_paths": [],
        "allowed_overwrite_paths": [],
    }

    monkeypatch.setattr(
        "agent_runner._resolve_cli_profile_for_agent",
        lambda *a, **kw: (
            {"agent_model_profiles": {"profiles": {}}, "agent_registry": {"agents": {}}},
            "full_api",
            "artifact_producer",
            None,
        ),
    )
    monkeypatch.setattr(
        "operational_uploader.maybe_run_operational_agent",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "agent_runner.resolve_agent_settings",
        lambda *a, **kw: (
            SimpleNamespace(
                provider="deepseek",
                provider_type="openai_compatible",
                model="deepseek-v4-flash",
                base_url=None,
                api_key_configured=True,
                temperature=0.2,
                top_p=1.0,
                max_output_tokens=2000,
                profile_name="",
            ),
            {
                "execution_policy": {
                    "execution_policy": {"patch_application_policy": "patch_proposal_first"},
                    "coder_policy": {"automatic_patch_application": False},
                },
                "model_providers": {},
            },
        ),
    )
    monkeypatch.setattr(
        "agent_runner.compose_agent_messages",
        lambda *a, **kw: [{"role": "user", "content": "artifact producer test"}],
    )
    monkeypatch.setattr(
        "brain_governor.evaluate_token_status",
        lambda *a, **kw: {},
    )
    monkeypatch.setattr(
        "agent_runner.generate_text",
        lambda *a, **kw: LLMCallResult(
            provider="deepseek",
            model="deepseek-v4-flash",
            content="""# ArtifactProducer Report

<!-- AGENTLAB_EDIT: runs/task_test_001/artifacts/article_draft.md -->
# Draft

Candidate article.
<!-- END AGENTLAB_EDIT -->
""",
            status="completed",
        ),
    )

    result = run_agent_model(tmp_path, plan, "ArtifactProducer", run_dir / "artifact_producer_report.md", apply_patches=True)

    assert result.raw_usage["patch_applied"] == 1
    assert result.raw_usage["patch_failed"] == 0
    assert "Patch Application Results" in result.content
    assert (
        Path(plan.project_root) / "runs" / "task_test_001" / "artifacts" / "article_draft.md"
    ).read_text(encoding="utf-8") == "# Draft\n\nCandidate article.\n"


def test_coder_does_not_partially_apply_when_edit_blocks_are_truncated(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent_runner import run_agent_model

    plan = _make_plan(tmp_path)
    run_dir = Path(plan.run_dir)
    run_dir.mkdir(parents=True)
    candidate_dir = run_dir / "artifacts"
    plan.artifact_intent = {
        "candidate_dir": str(candidate_dir),
        "allowed_write_roots": [str(candidate_dir)],
        "declared_production_paths": [],
        "allowed_overwrite_paths": [],
    }

    monkeypatch.setattr(
        "agent_runner._resolve_cli_profile_for_agent",
        lambda *a, **kw: (
            {"agent_model_profiles": {"profiles": {}}, "agent_registry": {"agents": {}}},
            "full_api",
            "coder",
            None,
        ),
    )
    monkeypatch.setattr(
        "operational_uploader.maybe_run_operational_agent",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "agent_runner.resolve_agent_settings",
        lambda *a, **kw: (
            SimpleNamespace(
                provider="qwen-coder",
                provider_type="openai_compatible",
                model="qwen3-coder-next",
                base_url=None,
                api_key_configured=True,
                temperature=0.2,
                top_p=1.0,
                max_output_tokens=2000,
                profile_name="",
            ),
            {
                "execution_policy": {
                    "execution_policy": {"patch_application_policy": "patch_proposal_first"},
                    "coder_policy": {"automatic_patch_application": False},
                },
                "model_providers": {},
            },
        ),
    )
    monkeypatch.setattr(
        "agent_runner.compose_agent_messages",
        lambda *a, **kw: [{"role": "user", "content": "test"}],
    )
    monkeypatch.setattr(
        "brain_governor.evaluate_token_status",
        lambda *a, **kw: {},
    )
    monkeypatch.setattr(
        "agent_runner.generate_text",
        lambda *a, **kw: LLMCallResult(
            provider="qwen-coder",
            model="qwen3-coder-next",
            content="""# Coder Report

<!-- AGENTLAB_EDIT: runs/task_test_001/artifacts/web_ui/index.html -->
<html>ok</html>
<!-- END AGENTLAB_EDIT -->

<!-- AGENTLAB_EDIT: runs/task_test_001/artifacts/web_ui/styles.css -->
body {
""",
            status="completed",
        ),
    )

    result = run_agent_model(tmp_path, plan, "Coder", run_dir / "06_implementation_report.md")

    assert result.raw_usage["patch_applied"] == 0
    assert result.raw_usage["patch_failed"] == 1
    assert result.raw_usage["patch_blocked_reason"] == "unclosed_structured_edit_block"
    assert not (
        Path(plan.project_root) / "runs" / "task_test_001" / "artifacts" / "web_ui" / "index.html"
    ).exists()


def test_writer_profile_keeps_full_delivery_output_budget() -> None:
    from model_resolver import resolve_profile_config

    profile = resolve_profile_config(
        "execution_artifact_producer",
        agent_name="Writer",
        model_catalog={
            "models": {
                "deepseek_v4_flash": {
                    "provider": "deepseek_official",
                    "model_id": "deepseek-v4-flash",
                    "max_output": 384000,
                }
            }
        },
        agent_model_profiles={
            "default_mode": "full_api",
            "modes": {
                "full_api": {
                    "tiers": {
                        "performance": {
                            "writer": {
                                "executor_type": "direct_api",
                                "default": "deepseek_v4_flash",
                            }
                        }
                    }
                }
            },
        },
    )

    assert profile["max_output_tokens"] == 8192


# ── Tests ──────────────────────────────────────────────────────────────────


class TestAgentRunnerCliDispatch:
    """Prove that run_agent_model dispatches CLI executor correctly."""

    def test_calls_cli_agent_when_profile_is_cli_backed(self, tmp_path, monkeypatch):
        """run_agent_model calls run_cli_agent when the role profile resolves to CLI."""
        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)

        monkeypatch.setattr(
            "agent_runner.load_agentlab_configs",
            lambda _: {
                "agent_model_profiles": {
                    "profiles": {
                        "balanced": {
                            "supervisor": _cli_role_profile(),
                        },
                    },
                },
                "agent_registry": {"agents": {}},
                "model_providers": {"providers": {}, "defaults": {}},
                "model_profiles": {"profiles": {}},
                "model_catalog": {},
            },
        )
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *a, **kw: None,
        )
        # Patch resolve_agent_settings to avoid needing full config
        monkeypatch.setattr(
            "agent_runner.resolve_agent_settings",
            lambda *a, **kw: (
                SimpleNamespace(
                    provider="deepseek",
                    provider_type="openai_compatible",
                    model="deepseek_v4_flash",
                    base_url=None,
                    api_key_configured=False,
                    temperature=0.2,
                    top_p=1.0,
                    max_output_tokens=2000,
                    profile_name="",
                ),
                {},
            ),
        )
        monkeypatch.setattr(
            "agent_runner.compose_agent_messages",
            lambda *a, **kw: [{"role": "user", "content": "test"}],
        )
        monkeypatch.setattr(
            "brain_governor.evaluate_token_status",
            lambda *a, **kw: {},
        )

        # Scenario A: CLI agent succeeds
        with patch(
            "agent_runner.run_cli_agent",
            return_value=_cli_success_result(),
        ) as mock_cli, patch(
            "agent_runner.generate_text",
            return_value=_api_fallback_result(),
        ) as mock_api:
            from agent_runner import run_agent_model

            output = run_dir / "test_output.md"
            result = run_agent_model(tmp_path, plan, "Supervisor", output, apply_patches=False)

            mock_cli.assert_called_once()
            mock_api.assert_not_called()
            assert result.status == "completed"
            assert result.provider == "agentlab-cli-executor"
            assert "CLI" in result.content

    def test_capacity_failure_uses_only_preapproved_same_role_fallback(
        self, tmp_path, monkeypatch
    ):
        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)
        capacity_policy = {
            "ledger": {"filename": "model_capacity_ledger.yml"},
            "pools": {
                "codex_pool": {},
                "deepseek_pool": {},
            },
            "routes": {
                "Supervisor": {
                    "role": "supervisor",
                    "worker": "hermes",
                    "invocation_contract": "hermes_supervisor",
                    "model_key": "codex_gpt_5_6_sol_xhigh_hermes_oauth",
                    "pool": "codex_pool",
                    "approved_fallbacks": ["SupervisorDeepSeek"],
                    "fallback_on": ["quota_exhausted"],
                },
                "SupervisorDeepSeek": {
                    "role": "supervisor",
                    "worker": "claude_code",
                    "invocation_contract": "claude",
                    "model_key": "deepseek_v4_pro",
                    "pool": "deepseek_pool",
                    "approved_fallbacks": [],
                    "fallback_on": [],
                },
            },
        }
        monkeypatch.setattr(
            "agent_runner.load_agentlab_configs",
            lambda _: {
                "agent_model_profiles": {
                    "profiles": {
                        "balanced": {
                            "supervisor": {
                                **_cli_role_profile(),
                                "capacity_route": "Supervisor",
                            }
                        }
                    }
                },
                "model_capacity": capacity_policy,
            },
        )
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *a, **kw: None,
        )
        attempted_profiles: list[dict] = []

        def fake_cli(_plan, _agent, role_profile, **_kwargs):
            attempted_profiles.append(dict(role_profile))
            if len(attempted_profiles) == 1:
                return LLMCallResult(
                    provider="agentlab-cli-executor",
                    model="hermes",
                    content="subscription quota exhausted; Resets in 5h",
                    status="blocked_user_decision",
                    error="CLI agent quota_exhausted",
                    raw_usage={"failure_class": "quota_exhausted"},
                )
            return _cli_success_result()

        monkeypatch.setattr("agent_runner.run_cli_agent", fake_cli)
        with patch("agent_runner.generate_text") as direct_api:
            from agent_runner import run_agent_model

            result = run_agent_model(
                tmp_path,
                plan,
                "Supervisor",
                run_dir / "test_output.md",
                apply_patches=False,
            )

        direct_api.assert_not_called()
        assert result.status == "completed"
        assert [profile["cli_agent"] for profile in attempted_profiles] == [
            "hermes",
            "claude_code",
        ]
        assert attempted_profiles[1]["default"] == "deepseek_v4_pro"
        assert result.raw_usage["capacity_route_id"] == "SupervisorDeepSeek"
        assert result.raw_usage["capacity_selection_kind"] == "approved_fallback"
        ledger = yaml.safe_load(
            (run_dir / "model_capacity_ledger.yml").read_text(encoding="utf-8")
        )
        assert ledger["pools"]["codex_pool"]["failure_class"] == "quota_exhausted"
        assert ledger["pools"]["deepseek_pool"]["status"] == "closed"

    def test_capacity_reselecting_attempted_route_marks_chain_exhausted(
        self, tmp_path, monkeypatch
    ):
        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)
        capacity_policy = {
            "ledger": {"filename": "model_capacity_ledger.yml"},
            "pools": {"codex_pool": {}},
            "routes": {
                "Supervisor": {
                    "role": "supervisor",
                    "worker": "hermes",
                    "invocation_contract": "hermes_supervisor",
                    "model_key": "codex_gpt_5_6_sol_xhigh_hermes_oauth",
                    "pool": "codex_pool",
                    "approved_fallbacks": [],
                    "fallback_on": [],
                }
            },
        }
        monkeypatch.setattr(
            "agent_runner.load_agentlab_configs",
            lambda _: {
                "agent_model_profiles": {
                    "profiles": {
                        "balanced": {
                            "supervisor": {
                                **_cli_role_profile(),
                                "capacity_route": "Supervisor",
                            }
                        }
                    }
                },
                "model_capacity": capacity_policy,
            },
        )
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "agent_runner.run_cli_agent",
            lambda *_a, **_kw: LLMCallResult(
                provider="agentlab-cli-executor",
                model="hermes",
                content="unexpected provider failure",
                status="blocked_user_decision",
                error="unclassified failure",
            ),
        )

        with patch("agent_runner.generate_text") as direct_api:
            from agent_runner import run_agent_model

            result = run_agent_model(
                tmp_path,
                plan,
                "Supervisor",
                run_dir / "test_output.md",
                apply_patches=False,
            )

        direct_api.assert_not_called()
        assert result.raw_usage["capacity_route_chain_exhausted"] is True
        assert result.raw_usage["capacity_next_route_id"] == "Supervisor"
        assert result.raw_usage["capacity_next_route_already_attempted"] is True

    def test_ad_hoc_cli_model_override_is_blocked_in_favor_of_capacity_policy(
        self, tmp_path, monkeypatch
    ):
        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "agent_runner.load_agentlab_configs",
            lambda _: {
                "agent_model_profiles": {
                    "profiles": {
                        "balanced": {
                            "writer": {
                                "executor_type": "cli_agent",
                                "cli_agent": "claude_code",
                                "invocation_contract": "claude_writer",
                                "default": "deepseek_v4_pro",
                            }
                        }
                    },
                },
            },
        )
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *a, **kw: None,
        )

        from agent_runner import run_agent_model

        with patch("agent_runner.run_cli_agent") as mock_cli:
            result = run_agent_model(
                tmp_path,
                plan,
                "Writer",
                run_dir / "test_output.md",
                cli_model_override="deepseek_v4_flash",
                apply_patches=False,
            )

        mock_cli.assert_not_called()
        assert result.status == "blocked_user_decision"
        assert result.error == "invalid_cli_model_override"
        assert "model_capacity.yml" in result.content

    def test_unregistered_cli_model_override_is_blocked(self, tmp_path, monkeypatch):
        plan = _make_plan(tmp_path)
        profile = _cli_role_profile()
        monkeypatch.setattr(
            "agent_runner.load_agentlab_configs",
            lambda _: {
                "agent_model_profiles": {
                    "profiles": {"balanced": {"supervisor": profile}},
                },
                "model_catalog": {"models": {}},
                "worker_invocation_contracts": {"contracts": {}},
            },
        )
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *a, **kw: None,
        )

        with patch("agent_runner.run_cli_agent") as mock_cli:
            from agent_runner import run_agent_model

            result = run_agent_model(
                tmp_path,
                plan,
                "Supervisor",
                Path(plan.run_dir) / "test_output.md",
                cli_model_override="not_registered",
                apply_patches=False,
            )

        mock_cli.assert_not_called()
        assert result.status == "blocked_user_decision"
        assert result.error == "invalid_cli_model_override"

    def test_cli_unavailable_never_silently_changes_to_direct_api(self, tmp_path, monkeypatch):
        """A configured CLI surface cannot silently fall through to direct API."""
        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)

        monkeypatch.setattr(
            "agent_runner.load_agentlab_configs",
            lambda _: {
                "agent_model_profiles": {
                    "profiles": {
                        "balanced": {
                            "supervisor": _cli_role_profile(),
                        },
                    },
                },
                "agent_registry": {"agents": {}},
                "model_providers": {"providers": {}, "defaults": {}},
                "model_profiles": {"profiles": {}},
                "model_catalog": {},
            },
        )
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "agent_runner.resolve_agent_settings",
            lambda *a, **kw: (
                SimpleNamespace(
                    provider="deepseek",
                    provider_type="openai_compatible",
                    model="deepseek_v4_flash",
                    base_url=None,
                    api_key_configured=False,
                    temperature=0.2,
                    top_p=1.0,
                    max_output_tokens=2000,
                    profile_name="",
                ),
                {},
            ),
        )
        monkeypatch.setattr(
            "agent_runner.compose_agent_messages",
            lambda *a, **kw: [{"role": "user", "content": "test"}],
        )
        monkeypatch.setattr(
            "brain_governor.evaluate_token_status",
            lambda *a, **kw: {},
        )

        with patch(
            "agent_runner.run_cli_agent",
            return_value=_cli_not_available(),
        ) as mock_cli, patch(
            "agent_runner.generate_text",
            return_value=_api_fallback_result(),
        ) as mock_api:
            from agent_runner import run_agent_model

            output = run_dir / "test_output.md"
            result = run_agent_model(tmp_path, plan, "Supervisor", output, apply_patches=False)

            mock_cli.assert_called_once()
            mock_api.assert_not_called()
            assert result.status == "blocked_user_decision"
            assert result.error == "cli_unavailable_no_fallback"
            assert result.raw_usage["provider_surface_changed"] is False
            assert result.raw_usage["direct_api_fallback_attempted"] is False

    def test_no_cli_dispatch_for_direct_api_only_profile(self, tmp_path, monkeypatch):
        """run_agent_model skips CLI dispatch when profile is direct_api_only."""
        plan = _make_plan(tmp_path, budget_mode="balanced")
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)

        monkeypatch.setattr(
            "agent_runner.load_agentlab_configs",
            lambda _: {
                "agent_model_profiles": {
                    "default_mode": "full_api",
                    "modes": {
                        "full_api": {
                            "tiers": {
                                "performance": {
                                    "supervisor": {
                                        "executor_type": "direct_api",
                                        "default": "deepseek_v4_pro",
                                    }
                                }
                            }
                        }
                    },
                },
                "agent_registry": {"agents": {}},
                "model_providers": {"providers": {}, "defaults": {}},
                "model_profiles": {"profiles": {}},
                "model_catalog": {},
            },
        )
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "agent_runner.resolve_agent_settings",
            lambda *a, **kw: (
                SimpleNamespace(
                    provider="deepseek",
                    provider_type="openai_compatible",
                    model="deepseek_v4_pro",
                    base_url=None,
                    api_key_configured=False,
                    temperature=0.2,
                    top_p=1.0,
                    max_output_tokens=2000,
                    profile_name="",
                ),
                {},
            ),
        )
        monkeypatch.setattr(
            "agent_runner.compose_agent_messages",
            lambda *a, **kw: [{"role": "user", "content": "test"}],
        )
        monkeypatch.setattr(
            "brain_governor.evaluate_token_status",
            lambda *a, **kw: {},
        )

        with patch(
            "agent_runner.run_cli_agent",
            return_value=_cli_success_result(),
        ) as mock_cli, patch(
            "agent_runner.generate_text",
            return_value=_api_fallback_result(),
        ) as mock_api:
            from agent_runner import run_agent_model

            output = run_dir / "test_output.md"
            result = run_agent_model(tmp_path, plan, "Supervisor", output, apply_patches=False)

            mock_cli.assert_not_called()
            mock_api.assert_called_once()
            assert result.status == "completed"

    def test_no_real_subprocess_in_tests(self):
        """Sanity: this test file never executes real subprocess calls."""
        # Check that the test file doesn't actually import subprocess to run things
        # (it's fine to mention "subprocess.run" in comments/docstrings)
        import ast

        source = Path(__file__).read_text()
        tree = ast.parse(source)
        has_subprocess_import = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "subprocess":
                        has_subprocess_import = True
            elif isinstance(node, ast.ImportFrom):
                if node.module == "subprocess":
                    has_subprocess_import = True
        assert not has_subprocess_import, (
            "test file must not import subprocess — use mocks via patch()"
        )


def _iter_config_role_groups(data: dict):
    """Yield named role groups from legacy profiles and schema-v4 modes/tiers."""
    for name, profile in (data.get("profiles", {}) or {}).items():
        yield name, profile
    for mode_name, mode in (data.get("modes", {}) or {}).items():
        for tier_name, tier in ((mode or {}).get("tiers", {}) or {}).items():
            yield f"{mode_name}.{tier_name}", tier or {}


# ── Schema v4 dispatch tests ──────────────────────────────────────────────


def _schema_v4_configs() -> dict:
    """Return a minimal config set with schema v4 agent_model_profiles."""
    return {
        "agent_model_profiles": {
            "schema_version": 4.0,
            "default_mode": "full_cli",
            "modes": {
                "full_cli": {
                    "tiers": {
                        "full": {
                            "supervisor": {
                                "executor_type": "cli_agent",
                                "cli_agent": "hermes",
                                "cli_command": 'hermes -z "Read {task_packet_path}"',
                                "default": "deepseek_v4_pro",
                            },
                        },
                    },
                },
            },
        },
        "agent_registry": {"agents": {}},
        "model_providers": {"providers": {}, "defaults": {}},
        "model_profiles": {"profiles": {}},
        "model_catalog": {},
    }


class TestAgentRunnerSchemaV4Dispatch:
    """Prove agent_runner dispatches CLI for schema v4 configs."""

    def test_cli_attempted_before_api_for_schema_v4(self, tmp_path, monkeypatch):
        """With schema v4 full_cli/full/supervisor, run_cli_agent is called before API."""
        plan = _make_plan(tmp_path, budget_mode="full")
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)

        monkeypatch.setattr(
            "agent_runner.load_agentlab_configs",
            lambda _: _schema_v4_configs(),
        )
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "agent_runner.resolve_agent_settings",
            lambda *a, **kw: (
                SimpleNamespace(
                    provider="deepseek", provider_type="openai_compatible",
                    model="deepseek_v4_pro", base_url=None,
                    api_key_configured=False, temperature=0.2, top_p=1.0,
                    max_output_tokens=2000, profile_name="",
                ),
                {},
            ),
        )
        monkeypatch.setattr(
            "agent_runner.compose_agent_messages",
            lambda *a, **kw: [{"role": "user", "content": "test"}],
        )
        monkeypatch.setattr(
            "brain_governor.evaluate_token_status",
            lambda *a, **kw: {},
        )

        with patch(
            "agent_runner.run_cli_agent",
            return_value=_cli_success_result(),
        ) as mock_cli, patch(
            "agent_runner.generate_text",
            return_value=_api_fallback_result(),
        ) as mock_api:
            from agent_runner import run_agent_model

            output = run_dir / "test_output.md"
            result = run_agent_model(tmp_path, plan, "Supervisor", output, apply_patches=False)

            mock_cli.assert_called_once()
            mock_api.assert_not_called()
            assert result.status == "completed"
            # Audit metadata must show CLI was used
            assert result.raw_usage.get("usage_source") == "cli_agent"
            assert result.raw_usage.get("executor_type") == "cli_agent"
            assert result.raw_usage.get("api_fallback_used") is False
            assert result.raw_usage.get("resolved_schema") == "modes_v4"

    def test_cli_unavailable_never_changes_to_direct_api(self, tmp_path, monkeypatch):
        """A configured CLI surface must not silently change to direct API."""
        plan = _make_plan(tmp_path, budget_mode="full")
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)

        monkeypatch.setattr(
            "agent_runner.load_agentlab_configs",
            lambda _: _schema_v4_configs(),
        )
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "agent_runner.resolve_agent_settings",
            lambda *a, **kw: (
                SimpleNamespace(
                    provider="deepseek", provider_type="openai_compatible",
                    model="deepseek_v4_pro", base_url=None,
                    api_key_configured=False, temperature=0.2, top_p=1.0,
                    max_output_tokens=2000, profile_name="",
                ),
                {},
            ),
        )
        monkeypatch.setattr(
            "agent_runner.compose_agent_messages",
            lambda *a, **kw: [{"role": "user", "content": "test"}],
        )
        monkeypatch.setattr(
            "brain_governor.evaluate_token_status",
            lambda *a, **kw: {},
        )

        with patch(
            "agent_runner.run_cli_agent",
            return_value=_cli_not_available(),
        ) as mock_cli, patch(
            "agent_runner.generate_text",
            return_value=_api_fallback_result(),
        ) as mock_api:
            from agent_runner import run_agent_model

            output = run_dir / "test_output.md"
            result = run_agent_model(tmp_path, plan, "Supervisor", output, apply_patches=False)

            mock_cli.assert_called_once()
            mock_api.assert_not_called()
            assert result.status == "blocked_user_decision"
            assert result.error == "cli_unavailable_no_fallback"
            assert result.raw_usage.get("executor_type") == "cli_agent"
            assert result.raw_usage.get("configured_cli_agent") == "hermes"
            assert result.raw_usage.get("provider_surface_changed") is False
            assert result.raw_usage.get("direct_api_fallback_attempted") is False

    def test_cli_unavailable_blocks_when_api_fallback_is_disabled(self, tmp_path, monkeypatch):
        plan = _make_plan(tmp_path, budget_mode="full")
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)

        monkeypatch.setattr("agent_runner.load_agentlab_configs", lambda _: _schema_v4_configs())
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *args, **kwargs: None,
        )

        with patch(
            "agent_runner.run_cli_agent",
            return_value=_cli_not_available(),
        ) as mock_cli, patch("agent_runner.generate_text") as mock_api:
            from agent_runner import run_agent_model

            result = run_agent_model(
                tmp_path,
                plan,
                "Supervisor",
                run_dir / "test_output.md",
                apply_patches=False,
                allow_cli_api_fallback=False,
            )

        mock_cli.assert_called_once()
        mock_api.assert_not_called()
        assert result.status == "blocked_user_decision"
        assert result.error == "cli_unavailable_no_fallback"
        assert result.raw_usage["provider_surface_changed"] is False
        assert result.raw_usage["direct_api_fallback_attempted"] is False

    def test_missing_cli_profile_blocks_when_api_fallback_is_disabled(self, tmp_path, monkeypatch):
        plan = _make_plan(tmp_path, budget_mode="full")
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)

        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(
            "agent_runner._resolve_cli_profile_for_agent",
            lambda *args, **kwargs: ({}, "full_cli", "supervisor", None),
        )

        with patch("agent_runner.run_cli_agent") as mock_cli, patch("agent_runner.generate_text") as mock_api:
            from agent_runner import run_agent_model

            result = run_agent_model(
                tmp_path,
                plan,
                "Supervisor",
                run_dir / "test_output.md",
                apply_patches=False,
                allow_cli_api_fallback=False,
            )

        mock_cli.assert_not_called()
        mock_api.assert_not_called()
        assert result.status == "blocked_user_decision"
        assert result.error == "cli_profile_required_no_fallback"
        assert result.raw_usage["direct_api_fallback_attempted"] is False

    def test_cli_dispatch_blocks_disallowed_role_binding(self, tmp_path, monkeypatch):
        """A CLI worker not authorized for the role is blocked before execution."""
        plan = _make_plan(tmp_path, budget_mode="full")
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)

        bad_config = _schema_v4_configs()
        bad_config["agent_model_profiles"]["modes"]["full_cli"]["tiers"]["full"]["supervisor"]["cli_agent"] = "codex"
        bad_config["agent_model_profiles"]["modes"]["full_cli"]["tiers"]["full"]["supervisor"]["invocation_contract"] = "codex"

        monkeypatch.setattr("agent_runner.load_agentlab_configs", lambda _: bad_config)
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *a, **kw: None,
        )

        with patch("agent_runner.run_cli_agent") as mock_cli, patch("agent_runner.generate_text") as mock_api:
            from agent_runner import run_agent_model

            output = run_dir / "test_output.md"
            result = run_agent_model(tmp_path, plan, "Supervisor", output, apply_patches=False)

            mock_cli.assert_not_called()
            mock_api.assert_not_called()
            assert result.status == "blocked_user_decision"
            assert result.raw_usage.get("reason") == "role_binding_denied"
            assert "Supervisor" in result.content
            assert "codex" in result.content


# ── Config profile tests ───────────────────────────────────────────────────


class TestConfigProfiles:
    """Verify config/agent_model_profiles.yml has required profiles."""

    def test_has_cli_supervisor_profile(self):
        """At least one profile has CLI-backed supervisor."""
        import yaml

        config_path = Path(__file__).parent.parent / "config" / "agent_model_profiles.yml"
        data = yaml.safe_load(config_path.read_text())
        cli_supervisors = []
        for name, profile in _iter_config_role_groups(data):
            sup = profile.get("supervisor", {})
            if sup.get("executor_type") == "cli_agent":
                cli_supervisors.append(name)

        assert cli_supervisors, "No profile has CLI-backed supervisor"
        print(f"CLI-backed supervisor profiles: {cli_supervisors}")

    def test_has_cli_coder_profile(self):
        """At least one profile has CLI-backed coder."""
        import yaml

        config_path = Path(__file__).parent.parent / "config" / "agent_model_profiles.yml"
        data = yaml.safe_load(config_path.read_text())
        cli_coders = []
        for name, profile in _iter_config_role_groups(data):
            coder = profile.get("coder", {})
            if coder.get("executor_type") == "cli_agent":
                cli_coders.append(name)

        assert cli_coders, "No profile has CLI-backed coder"
        print(f"CLI-backed coder profiles: {cli_coders}")

    def test_has_direct_api_only_profile(self):
        """At least one profile is entirely direct_api."""
        import yaml

        config_path = Path(__file__).parent.parent / "config" / "agent_model_profiles.yml"
        data = yaml.safe_load(config_path.read_text())
        direct_api_profiles = []
        for name, profile in _iter_config_role_groups(data):
            all_direct = all(
                role.get("executor_type") == "direct_api"
                for role in profile.values()
                if isinstance(role, dict) and "executor_type" in role
            )
            if all_direct and profile:
                direct_api_profiles.append(name)

        assert direct_api_profiles, "No direct API-only profile found"
        print(f"Direct API-only profiles: {direct_api_profiles}")

    def test_required_execution_modes_exist(self):
        """Config has the schema-v4 execution modes or legacy named profiles."""
        import yaml

        config_path = Path(__file__).parent.parent / "config" / "agent_model_profiles.yml"
        data = yaml.safe_load(config_path.read_text())
        if "modes" in data:
            required = {"full_cli", "full_api", "hybrid_ide"}
            missing = required - set((data.get("modes", {}) or {}).keys())
            assert not missing, f"Missing modes: {missing}"
            return

        profiles = data.get("profiles", {})
        required = {"balanced", "low_cost", "direct_api_only", "hybrid_agent_executor"}
        missing = required - set(profiles.keys())
        assert not missing, f"Missing profiles: {missing}"
        print(f"All required profiles present: {sorted(required)}")

    def test_default_mode_is_full_cli(self):
        """Default execution uses the canonical local CLI company mode."""
        import yaml

        config_path = Path(__file__).parent.parent / "config" / "agent_model_profiles.yml"
        data = yaml.safe_load(config_path.read_text())

        assert data.get("default_mode") == "full_cli"

    def test_cli_profiles_match_role_bindings(self):
        """Every configured CLI worker must be authorized by agent_role_bindings."""
        import yaml
        from agent_runtime.protocols.enforcement import check_role_binding

        root = Path(__file__).parent.parent
        config_path = root / "config" / "agent_model_profiles.yml"
        data = yaml.safe_load(config_path.read_text())
        role_key_map = {
            "supervisor": "Supervisor",
            "reposcout": "RepoScout",
            "researcher": "Researcher",
            "interface_mapper": "InterfaceMapper",
            "prompt_engineer": "PromptEngineer",
            "coder": "Coder",
            "artifact_producer": "ArtifactProducer",
            "narrative_planner": "NarrativePlanner",
            "writer": "Writer",
            "reviewer": "Reviewer",
            "scribe": "Scribe",
            "tester_auditor": "TesterAuditor",
            "verifier": "Verifier",
            "archivist": "Archivist",
        }
        violations = []
        for group_name, profile in _iter_config_role_groups(data):
            for role_key, role_cfg in profile.items():
                if not isinstance(role_cfg, dict) or role_cfg.get("executor_type") != "cli_agent":
                    continue
                role = role_key_map.get(role_key, role_key)
                for field in ("cli_agent", "fallback_cli_agent"):
                    worker = role_cfg.get(field)
                    if not worker:
                        continue
                    ok, reason = check_role_binding(root, str(worker), role)
                    if not ok:
                        violations.append(f"{group_name}.{role_key}.{field}={worker}: {reason}")

        assert not violations, "\n".join(violations)


# ── Text integrity tests ───────────────────────────────────────────────────


class TestTextIntegrityMinimums:
    """Verify key hotfix files meet minimum line counts."""

    def test_cli_executor_min_lines(self):
        path = Path(__file__).parent.parent / "agent_runtime" / "cli_executor.py"
        lines = path.read_text().split("\n")
        assert len(lines) >= 120, f"cli_executor.py has {len(lines)} lines, need >= 120"

    def test_agent_runner_min_lines(self):
        path = Path(__file__).parent.parent / "agent_runtime" / "agent_runner.py"
        lines = path.read_text().split("\n")
        assert len(lines) >= 120, f"agent_runner.py has {len(lines)} lines, need >= 120"

    def test_test_cli_executor_min_lines(self):
        path = Path(__file__).parent.parent / "tests" / "test_cli_executor.py"
        lines = path.read_text().split("\n")
        assert len(lines) >= 100, f"test_cli_executor.py has {len(lines)} lines, need >= 100"

    def test_config_agent_model_profiles_min_lines(self):
        path = Path(__file__).parent.parent / "config" / "agent_model_profiles.yml"
        lines = path.read_text().split("\n")
        assert len(lines) >= 80, f"agent_model_profiles.yml has {len(lines)} lines, need >= 80"

    def test_agents_md_min_lines(self):
        path = Path(__file__).parent.parent / "AGENTS.md"
        lines = path.read_text().split("\n")
        assert len(lines) >= 80, f"AGENTS.md has {len(lines)} lines, need >= 80"

    def test_operating_model_md_min_lines(self):
        path = Path(__file__).parent.parent / "OPERATING_MODEL.md"
        lines = path.read_text().split("\n")
        assert len(lines) >= 80, f"OPERATING_MODEL.md has {len(lines)} lines, need >= 80"


# ── Public doc IP sanitization tests ───────────────────────────────────────


class TestPublicDocSanitization:
    """Verify public docs do not contain private network IPs or ports."""

    # Regex patterns that match private/leaked IPs and ports in public docs.
    # Concrete IPs must never appear in tracking; use generic patterns instead.
    PRIVATE_IP_RE = re.compile(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b")
    # Check for non-standard SSH ports (e.g. :2222) in docs
    PRIVATE_PORT_RE = re.compile(r":(?:2[2-9]\d\d|[3-9]\d{3,})\b|\s-p\s*(?:2[2-9]\d\d|[3-9]\d{3,})\b")

    PUBLIC_FILES = [
        "README.md",
        "AGENTS.md",
        "OPERATING_MODEL.md",
        "DRIVER_PROTOCOL.md",
    ]

    def test_public_docs_no_private_ips(self):
        """No public-facing doc contains private IP addresses."""
        root = Path(__file__).parent.parent
        violations = []
        for fname in self.PUBLIC_FILES:
            fpath = root / fname
            if not fpath.exists():
                continue
            content = fpath.read_text()
            if self.PRIVATE_IP_RE.search(content):
                violations.append(f"{fname}: contains private IP pattern")
        assert not violations, f"Private IPs found: {violations}"

    def test_public_docs_no_private_ports(self):
        """No public-facing doc contains non-standard SSH port."""
        root = Path(__file__).parent.parent
        violations = []
        for fname in self.PUBLIC_FILES:
            fpath = root / fname
            if not fpath.exists():
                continue
            content = fpath.read_text()
            if self.PRIVATE_PORT_RE.search(content):
                violations.append(f"{fname}: contains private port pattern")
        assert not violations, f"Private ports found: {violations}"


# ── PromptEngineer role key mapping ───────────────────────────────────────


class TestPromptEngineerMapping:
    """Verify PromptEngineer maps to ``prompt_engineer`` (schema v4 config key)."""

    def test_promptengineer_maps_to_prompt_engineer(self):
        """Agent name 'PromptEngineer' resolves to role key 'prompt_engineer'."""
        import yaml

        config_path = Path(__file__).parent.parent / "config" / "agent_model_profiles.yml"
        data = yaml.safe_load(config_path.read_text())

        # The config must have a prompt_engineer key (not execution_prompt_engineer)
        modes = data.get("modes", {})
        full_cli = modes.get("full_cli", {})
        tiers = full_cli.get("tiers", {})
        full_tier = tiers.get("full", {})

        assert "prompt_engineer" in full_tier, (
            "Config must have 'prompt_engineer' role key, "
            "not 'execution_prompt_engineer'"
        )
        prom_role = full_tier["prompt_engineer"]
        assert prom_role.get("cli_agent") == "hermes"
        assert prom_role.get("invocation_contract") == "hermes"

    def test_shared_role_key_normalizer_handles_compact_names(self):
        """Role aliases are owned by one shared normalizer, not agent_runner."""
        from agent_runtime.role_keys import normalize_role_key

        assert normalize_role_key("PromptEngineer") == "prompt_engineer"
        assert normalize_role_key("ArtifactProducer") == "artifact_producer"


# ── resolve_cli_profile call signature ────────────────────────────────────


class TestResolveCliProfileCallSignature:
    """Verify agent_runner calls resolve_cli_profile with correct arguments."""

    def test_resolve_cli_profile_called_with_correct_args(self, tmp_path, monkeypatch):
        """resolve_cli_profile receives agent_role and budget_mode correctly."""
        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)

        monkeypatch.setattr(
            "agent_runner.load_agentlab_configs",
            lambda _: {
                "agent_model_profiles": {
                    "schema_version": 4.0,
                    "default_mode": "full_cli",
                    "modes": {
                        "full_cli": {
                            "tiers": {
                                "performance": {
                                    "coder": {
                                        "executor_type": "cli_agent",
                                        "cli_agent": "claude_code",
                                        "binary_candidates": ["claude", "ccs"],
                                        "cli_command": "claude -p test",
                                        "default": "qwen3_coder_plus_dashscope",
                                    },
                                },
                            },
                        },
                    },
                },
                "agent_registry": {"agents": {}},
                "model_providers": {"providers": {}, "defaults": {}},
                "model_profiles": {"profiles": {}},
                "model_catalog": {},
            },
        )
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "agent_runner.resolve_agent_settings",
            lambda *a, **kw: (
                SimpleNamespace(
                    provider="deepseek",
                    provider_type="openai_compatible",
                    model="deepseek_v4_flash",
                    base_url=None,
                    api_key_configured=False,
                    temperature=0.2,
                    top_p=1.0,
                    max_output_tokens=2000,
                    profile_name="",
                ),
                {},
            ),
        )
        monkeypatch.setattr(
            "agent_runner.compose_agent_messages",
            lambda *a, **kw: [{"role": "user", "content": "test"}],
        )
        monkeypatch.setattr(
            "brain_governor.evaluate_token_status",
            lambda *a, **kw: {},
        )

        with patch(
            "agent_runner.run_cli_agent",
            return_value=_cli_success_result(),
        ) as mock_cli_agent, patch(
            "agent_runner.generate_text",
            return_value=_api_fallback_result(),
        ):
            from agent_runner import run_agent_model

            output = run_dir / "test_output.md"
            run_agent_model(tmp_path, plan, "Coder", output, apply_patches=False)

            mock_cli_agent.assert_called_once()
            # The called role_profile should contain claude_code
            call_kwargs = mock_cli_agent.call_args
            role_profile_passed = call_kwargs[0][2]  # third positional arg
            assert role_profile_passed["cli_agent"] == "claude_code"
            assert role_profile_passed["binary_candidates"] == ["claude", "ccs"]

    def test_supervisor_route_gets_supervisor_role(self, tmp_path, monkeypatch):
        """Supervisor agent resolves to 'supervisor' role key."""
        plan = _make_plan(tmp_path)
        run_dir = Path(plan.run_dir)
        run_dir.mkdir(parents=True)

        monkeypatch.setattr(
            "agent_runner.load_agentlab_configs",
            lambda _: {
                "agent_model_profiles": {
                    "schema_version": 4.0,
                    "default_mode": "full_cli",
                    "modes": {
                        "full_cli": {
                            "tiers": {
                                "performance": {
                                    "supervisor": {
                                        "executor_type": "cli_agent",
                                        "cli_agent": "hermes",
                                        "cli_command": "hermes -z test",
                                        "default": "deepseek_v4_pro",
                                    },
                                },
                            },
                        },
                    },
                },
                "agent_registry": {"agents": {}},
                "model_providers": {"providers": {}, "defaults": {}},
                "model_profiles": {"profiles": {}},
                "model_catalog": {},
            },
        )
        monkeypatch.setattr(
            "operational_uploader.maybe_run_operational_agent",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "agent_runner.resolve_agent_settings",
            lambda *a, **kw: (
                SimpleNamespace(
                    provider="deepseek",
                    provider_type="openai_compatible",
                    model="deepseek_v4_pro",
                    base_url=None,
                    api_key_configured=False,
                    temperature=0.2,
                    top_p=1.0,
                    max_output_tokens=2000,
                    profile_name="",
                ),
                {},
            ),
        )
        monkeypatch.setattr(
            "agent_runner.compose_agent_messages",
            lambda *a, **kw: [{"role": "user", "content": "test"}],
        )
        monkeypatch.setattr(
            "brain_governor.evaluate_token_status",
            lambda *a, **kw: {},
        )

        from cli_executor import CliAgentNotAvailable

        with patch(
            "agent_runner.run_cli_agent",
            return_value=CliAgentNotAvailable("hermes", "mock", "mock"),
        ) as mock_cli_agent, patch(
            "agent_runner.generate_text",
            return_value=_api_fallback_result(),
        ):
            from agent_runner import run_agent_model

            output = run_dir / "test_output.md"
            run_agent_model(tmp_path, plan, "Supervisor", output, apply_patches=False)
            # No crash = resolve_cli_profile was called correctly with budget_mode
            # as keyword, not positionally swapped
            call = mock_cli_agent.call_args
            assert call.kwargs["sealed_messages"] == [
                {"role": "user", "content": "test"}
            ]
            assert call.kwargs["outbound_source_paths"] == []
