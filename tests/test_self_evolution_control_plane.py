from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest
import yaml

from agent_runtime.protocols.enforcement import build_role_session, check_role_binding
from agent_runtime.routing.role_assignment import RoleAssignmentEngine
from agent_runtime.runtime_registry import RuntimeRegistry
from agent_runtime.run_task import _write_self_evolution_verifier_execution_binding
from agent_runtime.agent_runner import _bind_component_role_session
from agent_runtime.self_evolution.compiler import RoleComponentCompiler
from agent_runtime.self_evolution.artifact_materializer import (
    materialize_component_role_result,
)
from agent_runtime.self_evolution.control_plane import (
    _evolution_workspace_id,
    _runtime_doctor_semantic_issues,
    _verification_report_issues,
    collect_verifier_receipt,
    mark_review_ready,
    materialize_component,
    prepare_verifier_request,
    propose_component,
    record_gap_observation,
    validate_evolution,
    write_rollback_candidate,
)
from agent_runtime.self_evolution.evidence import build_observation, evaluate_gap_eligibility
from agent_runtime.self_evolution.models import ComponentManifest, ManifestValidationError
from agent_runtime.self_evolution.role_catalog import RoleCatalog
from agent_runtime.self_evolution.workspace import (
    EvolutionWorkspaceError,
    _workspace_identity,
)


ROOT = Path(__file__).resolve().parents[1]


def _copy_root(tmp_path: Path) -> Path:
    root = tmp_path / "AgentLab"
    shutil.copytree(ROOT / "config", root / "config")
    return root


def _task_run(root: Path, task_id: str = "task_self_evolution") -> Path:
    run = root / "projects" / "AgentLab" / "runs" / task_id
    run.mkdir(parents=True, exist_ok=True)
    return run


def _agent_manifest(
    *,
    component_id: str = "context_consistency_editor",
    display_name: str = "ContextConsistencyEditor",
    required_capabilities: list[str] | None = None,
    allowed_workers: list[str] | None = None,
    output: str = "runs/task_xxxx/context_consistency_report.yml",
) -> dict:
    workers = allowed_workers or ["claude_code"]
    contracts = {worker: "claude" for worker in workers}
    return {
        "api_version": "agentlab/v1",
        "kind": "agent_role",
        "metadata": {
            "id": component_id,
            "display_name": display_name,
            "version": "1.0.0",
            "status": "active",
        },
        "spec": {
            "responsibility": "Propose bounded cross-section consistency repairs.",
            "boundary": "Writes a candidate repair report only and cannot promote it.",
            "template_path": "agent_templates/context_consistency_editor.md",
            "default_report": Path(output).name,
            "init_artifacts": {Path(output).name: "status: tbd\nfindings: []\n"},
            "artifacts": {
                "inputs": ["runs/task_xxxx/candidate.md"],
                "outputs": [output],
            },
            "role_requirements": {
                "required_capabilities": required_capabilities
                or ["long_context", "state_ledger"],
                "preferred_capabilities": ["evidence_quality_review"],
                "forbidden_capabilities": ["unapproved_source_edit"],
                "default_risk_ceiling": "medium",
            },
            "worker_binding": {
                "allowed_workers": workers,
                "required_session": True,
                "invocation_contracts": contracts,
            },
            "runtime_demand": {
                "capability_weights": {"reasoning": 0.6, "audit": 0.4},
                "quality_floor": 0.82,
                "data_class": "private",
            },
            "permissions": {
                "can_edit_source": False,
                "direct_production_write": False,
                "credential_management": False,
                "install_provider": False,
                "register_provider": False,
                "secret_access": False,
                "auto_merge": False,
            },
        },
    }


def _write_yaml(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _write_verifier_receipt(
    root: Path,
    evolution_dir: Path,
    *,
    remove_declared_input: bool = False,
    restore_packet_before_binding: bool = False,
) -> Path:
    run = evolution_dir.parent
    request = prepare_verifier_request(
        root,
        evolution_dir=evolution_dir,
        worker="claude_code",
    )
    role_session = yaml.safe_load(
        Path(request["role_session"]).read_text(encoding="utf-8")
    )
    verifier_task_packet_path = run / "self_evolution_verifier_task_packet.yml"
    original_verifier_task_packet = verifier_task_packet_path.read_bytes()
    verifier_task_packet = yaml.safe_load(
        verifier_task_packet_path.read_text(encoding="utf-8")
    )
    assert any(
        str(path).endswith("bridge_bundle/worker_prompt.md")
        for path in verifier_task_packet["must_read_artifacts"]
    )
    if remove_declared_input:
        verifier_task_packet["must_read_artifacts"].pop()
        _write_yaml(verifier_task_packet_path, verifier_task_packet)
    (run / "verification_report.md").write_text(
        "# Verification\n\n"
        "AGENTLAB_SELF_EVOLUTION_VERDICT: PASS\n"
        f"AGENTLAB_COMPONENT_ID: {verifier_task_packet['component_id']}\n"
        "AGENTLAB_MANIFEST_FINGERPRINT: "
        f"{verifier_task_packet['manifest_fingerprint']}\n"
        f"AGENTLAB_ROLE_SESSION_ID: {role_session['role_session_id']}\n"
        "AGENTLAB_BLOCKING_FINDINGS_JSON: []\n",
        encoding="utf-8",
    )
    execution_task_packet = run / "task_packet_verifier.json"
    execution_task_packet.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "packet_type": "agentlab_sealed_role_session",
                "agent": "Verifier",
                "messages": [
                    {
                        "role": "user",
                        "content": verifier_task_packet_path.read_text(encoding="utf-8"),
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    outbound_manifest = run / "outbound_context_manifest_verifier.yml"
    outbound_sources = [
        verifier_task_packet_path,
        *[
            root / str(path)
            for path in verifier_task_packet["must_read_artifacts"]
        ],
    ]
    outbound_source_records = [
        {
            "path": str(path.relative_to(root)),
            "inside_agentlab_root": True,
            "exists": True,
            "is_symlink": False,
            "forbidden_name": False,
            "bytes": path.stat().st_size,
            "sha256": sha256(path.read_bytes()).hexdigest(),
        }
        for path in outbound_sources
    ]
    _write_yaml(
        outbound_manifest,
        {
            "schema_version": 1,
            "report_type": "agentlab_outbound_context_manifest",
            "role": "Verifier",
            "status": "pass",
            "execution_allowed": True,
            "context_boundary": {
                "sealed_context": True,
                "exact_payload_hashed": True,
            },
            "payload": {
                "sha256": sha256(execution_task_packet.read_bytes()).hexdigest()
            },
            "source_inventory": {
                "count": len(outbound_source_records),
                "required": False,
                "content_rendered": False,
                "files": outbound_source_records,
            },
        },
    )
    execution_receipt = run / "model_execution_receipt_verifier_test.yml"
    execution_chain = run / "model_execution_chain_verifier.yml"
    attempt_id = "verifier-attempt-1"
    command_id = "cmd_0001"
    provider_stdout = run / "command_logs" / f"{command_id}.stdout.txt"
    provider_stdout.parent.mkdir(parents=True, exist_ok=True)
    provider_stdout.write_text("provider stdout", encoding="utf-8")
    _write_yaml(
        run / "execution_log.yml",
        {
            "version": 1,
            "commands": [
                {
                    "command_id": command_id,
                    "agent": "Verifier",
                    "exit_code": 0,
                    "status": "success",
                    "stdout_path": str(provider_stdout.relative_to(run)),
                    "stdout_sha256": sha256(
                        provider_stdout.read_bytes()
                    ).hexdigest(),
                }
            ],
        },
    )
    _write_yaml(
        execution_receipt,
        {
            "schema_version": 1,
            "status": "pass",
            "role": "Verifier",
            "worker": role_session["worker"],
            "attempt_id": attempt_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "receipt_path": str(execution_receipt),
            "chain_path": str(execution_chain),
            "selection_kind": "direct",
            "provider_process_started": True,
            "profile_binding_verified": True,
            "command_binding_verified": True,
            "fallback_detected": False,
            "stdout_nonempty": True,
            "exit_code": 0,
            "task_packet_sha256": sha256(
                execution_task_packet.read_bytes()
            ).hexdigest(),
            "outbound_context_manifest_sha256": sha256(
                outbound_manifest.read_bytes()
            ).hexdigest(),
            "provider_stdout_sha256": sha256(
                provider_stdout.read_bytes()
            ).hexdigest(),
            "returned_content_sha256": sha256(
                (run / "verification_report.md").read_bytes()
            ).hexdigest(),
            "execution_command_id": command_id,
            "issues": [],
        },
    )
    execution_receipt_sha256 = sha256(execution_receipt.read_bytes()).hexdigest()
    _write_yaml(
        execution_chain,
        {
            "schema_version": 1,
            "role": "Verifier",
            "status": "pass",
            "attempts": [
                {
                    "attempt_id": attempt_id,
                    "receipt_path": str(execution_receipt),
                    "receipt_sha256": execution_receipt_sha256,
                    "status": "pass",
                    "selection_kind": "direct",
                    "fallback_detected": False,
                    "failure_issues": [],
                }
            ],
            "fallback_used": False,
            "final": {
                "attempt_id": attempt_id,
                "receipt_path": str(execution_receipt),
                "receipt_sha256": execution_receipt_sha256,
                "status": "pass",
                "selection_kind": "direct",
                "failure_issues": [],
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    if restore_packet_before_binding:
        verifier_task_packet_path.write_bytes(original_verifier_task_packet)
    binding_issues = _write_self_evolution_verifier_execution_binding(
        run,
        output_path=run / "verification_report.md",
        raw_usage={
            "task_packet_path": str(execution_task_packet),
            "outbound_context_manifest": str(outbound_manifest),
            "model_execution_receipt": str(execution_receipt),
            "model_execution_chain": str(execution_chain),
            "command_id": command_id,
        },
    )
    assert binding_issues == []
    return collect_verifier_receipt(
        root,
        evolution_dir=evolution_dir,
        execution_receipt_path=execution_receipt,
    )


def test_narrative_planner_is_component_managed_and_has_all_runtime_bridges():
    catalog = RoleCatalog.load(ROOT)
    role = catalog.require("NarrativePlanner")

    assert role.source == "component_manifest"
    assert role.default_report == "revision_or_rewrite_proposal.yml"
    initial_report = yaml.safe_load(role.init_artifacts[role.default_report])
    assert initial_report["status"] == "tbd"
    assert initial_report["candidate_only"] is True
    assert initial_report["direct_draft_edits"] is False
    assert role.allowed_workers == ("claude_code",)
    assert role.template_path == (
        "config/generated/roles/narrative_planner/worker_prompt.md"
    )
    effective_config = RoleCatalog.load(ROOT).agent_configs()["NarrativePlanner"]
    assert effective_config["required_outputs"] == [
        "runs/task_xxxx/revision_or_rewrite_proposal.yml"
    ]
    assert effective_config["model_profile"] == "execution_narrative_planner_deepseek"
    assert catalog.validate() == []

    generated = ROOT / "config" / "generated" / "roles" / "narrative_planner"
    compatibility = yaml.safe_load(
        (generated / "compatibility_manifest.yml").read_text(encoding="utf-8")
    )
    receipt = yaml.safe_load(
        (generated / "model_selection_receipt.yml").read_text(encoding="utf-8")
    )
    profile = yaml.safe_load(
        (generated / "agent_profile.yml").read_text(encoding="utf-8")
    )
    workflow_binding = yaml.safe_load(
        (generated / "workflow_binding.yml").read_text(encoding="utf-8")
    )
    prompt = (generated / "worker_prompt.md").read_text(encoding="utf-8")
    assert compatibility["status"] == "pass"
    assert receipt["decision"]["route_id"] == "narrative_planner_pro"
    assert receipt["invocation_contract_override"] == "claude_longform_governance"
    assert profile["template_path"] == role.template_path
    assert workflow_binding["activation_mode"] == "registered_route"
    assert workflow_binding["registered_routes"] == ["narrative_heavy_audit"]
    assert workflow_binding["normal_route_selection"] is True
    assert "Convert accepted long-form audit evidence" in prompt
    assert "`not_required`, `proposed`, or `blocked`" in prompt
    assert "`no_change`" not in prompt


def test_manifest_rejects_inline_provider_identity_and_elevated_permissions():
    data = _agent_manifest()
    data["spec"]["runtime_demand"]["model_id"] = "some-model"
    data["spec"]["permissions"]["network"] = ["public_internet"]

    with pytest.raises(ManifestValidationError) as exc_info:
        ComponentManifest.from_mapping(data)

    assert any("must not hardcode" in issue for issue in exc_info.value.issues)
    assert any("security_approval_ref" in issue for issue in exc_info.value.issues)

    traversal = _agent_manifest()
    traversal["spec"]["init_artifacts"] = {
        "../../production/escaped.yml": "status: pass\n"
    }
    with pytest.raises(ManifestValidationError, match="safe relative path"):
        ComponentManifest.from_mapping(traversal)

    unsafe_template = _agent_manifest()
    unsafe_template["spec"]["template_path"] = "config/model_providers.yml"
    with pytest.raises(ManifestValidationError, match=r"agent_templates/\*\.md"):
        ComponentManifest.from_mapping(unsafe_template)

    multiple_outputs = _agent_manifest()
    multiple_outputs["spec"]["artifacts"]["outputs"].append(
        "runs/task_xxxx/second_report.yml"
    )
    with pytest.raises(ManifestValidationError, match="exactly one output"):
        ComponentManifest.from_mapping(multiple_outputs)

    for reserved_name in (
        "workflow_plan.yml",
        "USER_DECISION_REQUIRED.md",
        "archive_receipt.yml",
        "artifact_promotion_plan.yml",
        "verification_report.md",
    ):
        with pytest.raises(ManifestValidationError, match="reserved run-control"):
            ComponentManifest.from_mapping(
                _agent_manifest(output=f"runs/task_xxxx/{reserved_name}")
            )


def test_gap_gate_requires_explicit_request_or_two_independent_tasks(tmp_path: Path):
    root = _copy_root(tmp_path)
    manifest = ComponentManifest.from_mapping(_agent_manifest())
    catalog = RoleCatalog.load(root)
    now = datetime.now(timezone.utc)
    first = build_observation(
        task_id="task_a",
        capability_id="cross_section_consistency",
        reason="first recurrence",
        required_capabilities=["long_context", "state_ledger"],
        observed_at=now,
    )

    one = evaluate_gap_eligibility([first], manifest=manifest, catalog=catalog, now=now)
    repeated = evaluate_gap_eligibility(
        [
            first,
            build_observation(
                task_id="task_b",
                capability_id="cross_section_consistency",
                reason="second recurrence",
                required_capabilities=["long_context", "state_ledger"],
                observed_at=now,
            ),
        ],
        manifest=manifest,
        catalog=catalog,
        now=now,
    )
    explicit = evaluate_gap_eligibility(
        [
            build_observation(
                task_id="task_explicit",
                capability_id="cross_section_consistency",
                reason="user requested a distinct governed role",
                explicit_user_request=True,
                required_capabilities=["long_context", "state_ledger"],
                observed_at=now,
            )
        ],
        manifest=manifest,
        catalog=catalog,
        now=now,
    )

    assert one["status"] == "observed"
    assert repeated["status"] == "eligible"
    assert explicit["status"] == "eligible"


def test_gap_gate_suppresses_new_role_when_existing_role_covers_capability(tmp_path: Path):
    root = _copy_root(tmp_path)
    manifest = ComponentManifest.from_mapping(
        _agent_manifest(required_capabilities=["planning"])
    )
    observation = build_observation(
        task_id="task_explicit",
        capability_id="planning",
        reason="request can be composed from Supervisor",
        explicit_user_request=True,
        required_capabilities=["planning"],
    )

    result = evaluate_gap_eligibility(
        [observation],
        manifest=manifest,
        catalog=RoleCatalog.load(root),
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "existing_component_composition_available"
    assert any(item["role"] == "Supervisor" for item in result["composition_candidates"])
    runtime_check = result["composition_checks"][
        "existing_worker_and_runtime_route"
    ]
    assert runtime_check["status"] == "checked"
    assert runtime_check["reusable_route_templates"]
    assert runtime_check["satisfies_missing_role_governance"] is False


def test_role_compiler_is_deterministic_and_uses_runtime_whitelist(tmp_path: Path):
    root = _copy_root(tmp_path)
    manifest = ComponentManifest.from_mapping(_agent_manifest())
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_result = RoleComponentCompiler(root).compile(manifest, first)
    second_result = RoleComponentCompiler(root).compile(manifest, second)

    assert first_result["status"] == "pass"
    assert second_result == first_result
    for item in first_result["generated_files"]:
        assert (first / item["path"]).read_bytes() == (second / item["path"]).read_bytes()
    receipt = yaml.safe_load((first / "model_selection_receipt.yml").read_text(encoding="utf-8"))
    registry = RuntimeRegistry.load(root)
    assert receipt["decision"]["route_id"] in registry.whitelisted_route_templates(
        allowed_workers=["claude_code"]
    )
    assert receipt["decision"]["identity"]["provider_id"] in registry.providers


def test_active_component_role_routes_assigns_and_defaults_denies_workers(tmp_path: Path):
    root = _copy_root(tmp_path)
    manifest_path = _write_yaml(
        root / "config" / "components" / "agents" / "context_consistency_editor.yml",
        _agent_manifest(),
    )
    manifest = ComponentManifest.load(manifest_path)
    RoleComponentCompiler(root).compile(
        manifest,
        root / "config" / "generated" / "roles" / manifest.component_id,
    )
    catalog = RoleCatalog.load(root)

    assert catalog.require("ContextConsistencyEditor").source == "component_manifest"
    assert check_role_binding(root, "claude_code", "ContextConsistencyEditor")[0] is True
    assert check_role_binding(root, "qwen", "ContextConsistencyEditor")[0] is False
    decision = RoleAssignmentEngine(root).assign(
        "ContextConsistencyEditor",
        available_workers=["claude_code", "qwen"],
    )
    role_session = build_role_session(
        root,
        "context_consistency_editor",
        "claude_code",
        project="AgentLab",
        task_id="task_component_role",
    )
    assert decision.selected_worker == "claude_code"
    assert RuntimeRegistry.load(root).candidates_for("ContextConsistencyEditor")
    assert role_session["binding"]["allowed"] is True
    assert role_session["identity"].startswith("Propose bounded")
    assert role_session["required_outputs"] == [
        "runs/task_xxxx/context_consistency_report.yml"
    ]

    run = _task_run(root, "task_component_role")
    (run / "candidate.md").write_text("# Candidate\n", encoding="utf-8")
    component_session, issue = _bind_component_role_session(
        root,
        SimpleNamespace(
            project="AgentLab",
            task_id="task_component_role",
            run_dir=str(run),
        ),
        "ContextConsistencyEditor",
        "claude_code",
        run / "context_consistency_report.yml",
    )
    assert issue is None
    assert component_session is not None
    bound = yaml.safe_load(component_session.read_text(encoding="utf-8"))
    assert bound["required_session_enforced"] is True
    assert bound["resolved_required_inputs"] == [
        "projects/AgentLab/runs/task_component_role/candidate.md"
    ]
    assert bound["resolved_required_inputs"][0] in bound["must_read_artifacts"]
    assert bound["component_manifest_sha256"] == sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    _wrong_session, wrong_output_issue = _bind_component_role_session(
        root,
        SimpleNamespace(
            project="AgentLab",
            task_id="task_component_role",
            run_dir=str(run),
        ),
        "ContextConsistencyEditor",
        "claude_code",
        run / "undeclared_report.yml",
    )
    assert "declared default report" in str(wrong_output_issue)

    artifact_result = SimpleNamespace(
        content=(
            "# CLI wrapper\n\n"
            "<!-- AGENTLAB_EDIT: context_consistency_report.yml -->\n"
            "status: proposed\nfindings: []\n"
            "<!-- END AGENTLAB_EDIT -->"
        )
    )
    artifact_path = run / "context_consistency_report.yml"
    materialized, artifact_issues, output_contract = (
        materialize_component_role_result(
            root,
            SimpleNamespace(
                project="AgentLab",
                task_id="task_component_role",
                run_dir=str(run),
            ),
            "ContextConsistencyEditor",
            artifact_result,
            artifact_path,
        )
    )
    assert materialized is True
    assert artifact_issues == []
    assert output_contract.is_file()
    assert artifact_path.read_text(encoding="utf-8") == (
        "status: proposed\nfindings: []"
    )
    assert "CLI wrapper" not in artifact_path.read_text(encoding="utf-8")


def test_component_role_session_rejects_symlinked_required_input(tmp_path: Path):
    root = _copy_root(tmp_path)
    manifest_path = _write_yaml(
        root / "config" / "components" / "agents" / "context_consistency_editor.yml",
        _agent_manifest(),
    )
    manifest = ComponentManifest.load(manifest_path)
    RoleComponentCompiler(root).compile(
        manifest,
        root / "config" / "generated" / "roles" / manifest.component_id,
    )
    run = _task_run(root, "task_component_symlink")
    (run / "substitute.md").write_text("# Substitute\n", encoding="utf-8")
    (run / "candidate.md").symlink_to("substitute.md")

    component_session, issue = _bind_component_role_session(
        root,
        SimpleNamespace(
            project="AgentLab",
            task_id="task_component_symlink",
            run_dir=str(run),
        ),
        "ContextConsistencyEditor",
        "claude_code",
        run / "context_consistency_report.yml",
    )

    assert component_session is None
    assert "contains a symlink" in str(issue)
    assert not (run / "component_role_session_context_consistency_editor.yml").exists()


def test_component_role_catalog_rejects_tampered_or_symlinked_bridge(
    tmp_path: Path,
) -> None:
    root = _copy_root(tmp_path)
    manifest_path = _write_yaml(
        root / "config" / "components" / "agents" / "context_consistency_editor.yml",
        _agent_manifest(),
    )
    manifest = ComponentManifest.load(manifest_path)
    generated = root / "config" / "generated" / "roles" / manifest.component_id
    RoleComponentCompiler(root).compile(manifest, generated)
    prompt = generated / "worker_prompt.md"
    original = prompt.read_text(encoding="utf-8")
    prompt.write_text(original + "tampered\n", encoding="utf-8")

    tampered = RoleCatalog.load(root)
    assert tampered.get("ContextConsistencyEditor") is None
    assert any("generated file hash mismatch" in issue for issue in tampered.validate())

    RoleComponentCompiler(root).compile(manifest, generated)
    prompt.unlink()
    target = tmp_path / "outside_prompt.md"
    target.write_text(original, encoding="utf-8")
    prompt.symlink_to(target)
    symlinked = RoleCatalog.load(root)
    assert symlinked.get("ContextConsistencyEditor") is None
    assert any("contains symlink" in issue for issue in symlinked.validate())


def test_invalid_replacement_manifest_cannot_reactivate_legacy_role(
    tmp_path: Path,
) -> None:
    root = _copy_root(tmp_path)
    manifest_path = root / "config" / "components" / "agents" / "narrative_planner.yml"
    manifest_path.write_text("metadata: [invalid\n", encoding="utf-8")

    malformed = RoleCatalog.load(root)
    assert malformed.get("NarrativePlanner") is None
    assert malformed.component_role_blocked("NarrativePlanner")

    manifest_path.unlink()
    target = tmp_path / "outside_manifest.yml"
    target.write_text("metadata: {}\n", encoding="utf-8")
    manifest_path.symlink_to(target)
    symlinked = RoleCatalog.load(root)
    assert symlinked.get("NarrativePlanner") is None
    assert symlinked.component_role_blocked("NarrativePlanner")


def test_agent_role_lifecycle_stays_candidate_until_independent_review(tmp_path: Path):
    root = _copy_root(tmp_path)
    run = _task_run(root)
    manifest_path = _write_yaml(run / "candidate.yml", _agent_manifest())
    observation = record_gap_observation(
        root,
        run / "observation",
        task_id="task_self_evolution",
        capability_id="cross_section_consistency",
        reason="explicitly requested internal role",
        explicit_user_request=True,
        required_capabilities=["long_context", "state_ledger"],
    )
    evolution_dir = run / "evolution"

    proposal = propose_component(
        root,
        manifest_path=manifest_path,
        evidence_paths=[observation],
        evolution_dir=evolution_dir,
    )
    materialized = materialize_component(
        root,
        evolution_dir=evolution_dir,
        create_worktree=False,
    )
    validation = validate_evolution(root, evolution_dir=evolution_dir)

    assert proposal["status"] == "proposed"
    assert materialized["status"] == "materialized"
    assert validation["status"] == "partial"
    assert validation["structural_status"] == "pass"
    assert yaml.safe_load(
        (evolution_dir / "independent_verification.yml").read_text(encoding="utf-8")
    )["status"] == "pending"
    assert not (root / "config" / "components" / "agents" / "context_consistency_editor.yml").exists()
    with pytest.raises(ValueError, match="validation_report"):
        mark_review_ready(root, evolution_dir=evolution_dir)


def test_materialization_rejects_manifest_replacement_after_proposal(
    tmp_path: Path,
) -> None:
    root = _copy_root(tmp_path)
    run = _task_run(root)
    manifest_path = _write_yaml(run / "candidate.yml", _agent_manifest())
    observation = record_gap_observation(
        root,
        run / "observation",
        task_id="task_self_evolution",
        capability_id="cross_section_consistency",
        reason="explicitly requested internal role",
        explicit_user_request=True,
        required_capabilities=["long_context", "state_ledger"],
    )
    evolution_dir = run / "evolution"
    propose_component(
        root,
        manifest_path=manifest_path,
        evidence_paths=[observation],
        evolution_dir=evolution_dir,
    )
    replacement = yaml.safe_load(
        (evolution_dir / "component_manifest.yml").read_text(encoding="utf-8")
    )
    replacement["spec"]["responsibility"] = "A swapped responsibility."
    _write_yaml(evolution_dir / "component_manifest.yml", replacement)

    with pytest.raises(ValueError, match="changed after the proposal"):
        materialize_component(
            root,
            evolution_dir=evolution_dir,
            create_worktree=False,
        )


def test_materialization_recomputes_blocked_proposal_eligibility(
    tmp_path: Path,
) -> None:
    root = _copy_root(tmp_path)
    run = _task_run(root)
    manifest_path = _write_yaml(run / "candidate.yml", _agent_manifest())
    observation = record_gap_observation(
        root,
        run / "observation",
        task_id="task_self_evolution",
        capability_id="cross_section_consistency",
        reason="single unapproved observation",
        required_capabilities=["long_context", "state_ledger"],
    )
    evolution_dir = run / "evolution"
    proposal = propose_component(
        root,
        manifest_path=manifest_path,
        evidence_paths=[observation],
        evolution_dir=evolution_dir,
    )
    assert proposal["status"] == "blocked"
    proposal["status"] = "proposed"
    _write_yaml(evolution_dir / "component_proposal.yml", proposal)

    with pytest.raises(ValueError, match="no longer eligible"):
        materialize_component(
            root,
            evolution_dir=evolution_dir,
            create_worktree=False,
        )


def test_candidate_agent_role_cannot_materialize_as_runnable(
    tmp_path: Path,
) -> None:
    root = _copy_root(tmp_path)
    run = _task_run(root)
    data = _agent_manifest()
    data["metadata"]["status"] = "candidate"
    manifest_path = _write_yaml(run / "candidate.yml", data)
    observation = record_gap_observation(
        root,
        run / "observation",
        task_id="task_self_evolution",
        capability_id="cross_section_consistency",
        reason="explicit candidate role proposal",
        explicit_user_request=True,
        required_capabilities=["long_context", "state_ledger"],
    )
    evolution_dir = run / "evolution"
    propose_component(
        root,
        manifest_path=manifest_path,
        evidence_paths=[observation],
        evolution_dir=evolution_dir,
    )

    with pytest.raises(ValueError, match="must be active"):
        materialize_component(
            root,
            evolution_dir=evolution_dir,
            create_worktree=False,
        )


def test_workspace_identity_uses_full_task_relative_path(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    first = _task_run(root, "task_a") / "evolution"
    second = _task_run(root, "task_b") / "evolution"
    first.mkdir()
    second.mkdir()

    assert _evolution_workspace_id(root, first) != _evolution_workspace_id(
        root, second
    )

    same_name_a = tmp_path / "first" / "AgentLab"
    same_name_b = tmp_path / "second" / "AgentLab"
    assert _workspace_identity(
        same_name_a, "evolution-shared", "component"
    )[1] != _workspace_identity(
        same_name_b, "evolution-shared", "component"
    )[1]


def test_runtime_doctor_semantics_block_candidate_scoped_findings(
    tmp_path: Path,
) -> None:
    out = tmp_path / "doctor"
    _write_yaml(
        out / "M2_RUNTIME_HYGIENE_REPORT.yml",
        {
            "runtime_layout": {"warnings": []},
            "symlink_audit": {"symlinks": [], "warnings": []},
            "gitignore_audit": {"missing_rules": [], "warnings": []},
            "secret_scan": {
                "findings": [
                    {
                        "file": (
                            "config/generated/roles/context_consistency_editor/"
                            "worker_prompt.md"
                        )
                    }
                ],
                "warnings": ["candidate finding"],
            },
        },
    )

    issues, evidence = _runtime_doctor_semantic_issues(
        ["./agentlab.sh", "runtime-doctor", "--out", str(out)],
        component_id="context_consistency_editor",
    )

    assert issues == ["runtime_doctor_candidate_secret_finding"]
    assert evidence["candidate_secret_finding_count"] == 1


def test_verification_report_must_explicitly_pass_without_blocking_findings(
    tmp_path: Path,
) -> None:
    manifest = ComponentManifest.from_mapping(_agent_manifest())
    report = tmp_path / "verification_report.md"
    report.write_text(
        "AGENTLAB_SELF_EVOLUTION_VERDICT: FAIL\n"
        f"AGENTLAB_COMPONENT_ID: {manifest.component_id}\n"
        f"AGENTLAB_MANIFEST_FINGERPRINT: {manifest.fingerprint}\n"
        "AGENTLAB_ROLE_SESSION_ID: role-session-1\n"
        'AGENTLAB_BLOCKING_FINDINGS_JSON: ["hash mismatch"]\n',
        encoding="utf-8",
    )

    issues = _verification_report_issues(
        report,
        manifest=manifest,
        role_session_id="role-session-1",
    )

    assert "invalid_verification_report_marker:AGENTLAB_SELF_EVOLUTION_VERDICT" in issues
    assert "verification_report_contains_blocking_findings" in issues


def test_open_proposal_with_same_gap_fingerprint_is_not_duplicated(tmp_path: Path):
    root = _copy_root(tmp_path)
    first_run = _task_run(root, "task_first")
    second_run = _task_run(root, "task_second")
    first_manifest = _write_yaml(first_run / "candidate.yml", _agent_manifest())
    second_manifest = _write_yaml(second_run / "candidate.yml", _agent_manifest())
    first_observation = record_gap_observation(
        root,
        first_run / "observation",
        task_id="task_first",
        capability_id="cross_section_consistency",
        reason="explicitly requested internal role",
        explicit_user_request=True,
        required_capabilities=["long_context", "state_ledger"],
    )
    second_observation = record_gap_observation(
        root,
        second_run / "observation",
        task_id="task_second",
        capability_id="cross_section_consistency",
        reason="same explicit gap in an independent task",
        explicit_user_request=True,
        required_capabilities=["long_context", "state_ledger"],
    )
    first_dir = first_run / "evolution"
    second_dir = second_run / "evolution"

    first = propose_component(
        root,
        manifest_path=first_manifest,
        evidence_paths=[first_observation],
        evolution_dir=first_dir,
    )
    second = propose_component(
        root,
        manifest_path=second_manifest,
        evidence_paths=[second_observation],
        evolution_dir=second_dir,
    )

    assert first["status"] == "proposed"
    assert second["status"] == "blocked"
    assert second["eligibility"]["reason"] == "duplicate_open_proposal"


def test_repeated_gap_uses_two_bound_task_runs_and_rejects_forged_fingerprint(
    tmp_path: Path,
):
    root = _copy_root(tmp_path)
    first_run = _task_run(root, "task_gap_a")
    second_run = _task_run(root, "task_gap_b")
    proposal_run = _task_run(root, "task_gap_proposal")
    first = record_gap_observation(
        root,
        first_run / "observation",
        task_id="task_gap_a",
        capability_id="cross_section_consistency",
        reason="first independent observation",
        required_capabilities=["long_context", "state_ledger"],
    )
    second = record_gap_observation(
        root,
        second_run / "observation",
        task_id="task_gap_b",
        capability_id="cross_section_consistency",
        reason="second independent observation",
        required_capabilities=["long_context", "state_ledger"],
    )
    manifest = _write_yaml(proposal_run / "candidate.yml", _agent_manifest())

    proposal = propose_component(
        root,
        manifest_path=manifest,
        evidence_paths=[first, second],
        evolution_dir=proposal_run / "evolution",
    )

    assert proposal["status"] == "proposed"
    assert proposal["eligibility"]["reason"] == "repeated_independent_gap"

    forged = yaml.safe_load(second.read_text(encoding="utf-8"))
    forged["fingerprint"] = "0" * 64
    _write_yaml(second, forged)
    with pytest.raises(ValueError, match="fingerprint"):
        propose_component(
            root,
            manifest_path=manifest,
            evidence_paths=[first, second],
            evolution_dir=proposal_run / "forged_evolution",
        )


def test_worktree_review_flow_never_mutates_source_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    root = _copy_root(tmp_path)
    policy_path = root / "config" / "self_evolution_policy.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["validation"]["commands"] = [
        ["python3", "-c", "import time; print(time.time_ns())"]
    ]
    _write_yaml(policy_path, policy)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "agentlab@test.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "AgentLab Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=root, check=True)
    subprocess.run(["git", "add", "config"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=root, check=True)
    base_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    temp_worktrees = tmp_path / "managed_tmp"
    temp_worktrees.mkdir()
    monkeypatch.setattr(
        "agent_runtime.self_evolution.workspace.tempfile.gettempdir",
        lambda: str(temp_worktrees),
    )
    run = _task_run(root)
    manifest_path = _write_yaml(run / "candidate.yml", _agent_manifest())
    observation = record_gap_observation(
        root,
        run / "observation",
        task_id="task_self_evolution",
        capability_id="cross_section_consistency",
        reason="explicitly requested internal role",
        explicit_user_request=True,
        required_capabilities=["long_context", "state_ledger"],
    )
    evolution_dir = run / "evolution"
    propose_component(
        root,
        manifest_path=manifest_path,
        evidence_paths=[observation],
        evolution_dir=evolution_dir,
    )
    result = materialize_component(root, evolution_dir=evolution_dir, create_worktree=True)
    worktree = Path(result["workspace"]["worktree"])
    workspace_path = evolution_dir / "workspace_receipt.yml"
    workspace_receipt = yaml.safe_load(workspace_path.read_text(encoding="utf-8"))
    tampered_receipt = {**workspace_receipt, "worktree": str(tmp_path)}
    _write_yaml(workspace_path, tampered_receipt)
    with pytest.raises(EvolutionWorkspaceError, match="managed worktree identity"):
        validate_evolution(root, evolution_dir=evolution_dir)
    _write_yaml(workspace_path, workspace_receipt)
    poison = worktree / "tests" / "poison_validation.py"
    poison.parent.mkdir(parents=True, exist_ok=True)
    poison.write_text("raise SystemExit('unreviewed validation override')\n", encoding="utf-8")
    with pytest.raises(EvolutionWorkspaceError, match="component allowlist"):
        validate_evolution(root, evolution_dir=evolution_dir, execute_commands=True)
    poison.unlink()
    validate_evolution(
        root,
        evolution_dir=evolution_dir,
        execute_commands=True,
    )
    validation_snapshot = (evolution_dir / "validation_report.yml").read_bytes()
    forged_validation = yaml.safe_load(validation_snapshot)
    forged_validation["command_receipts"] = []
    _write_yaml(evolution_dir / "validation_report.yml", forged_validation)
    with pytest.raises(ValueError, match="validation evidence"):
        prepare_verifier_request(root, evolution_dir=evolution_dir)
    (evolution_dir / "validation_report.yml").write_bytes(validation_snapshot)
    fake_verifier = _write_yaml(
        run / "fake_verifier.yml",
        {"status": "pass", "role": "Verifier"},
    )
    rejected_attachment = validate_evolution(
        root,
        evolution_dir=evolution_dir,
        execute_commands=True,
        independent_verification_path=fake_verifier,
    )
    assert rejected_attachment["status"] == "fail"
    assert rejected_attachment["validation_snapshot_status"] == "pass"
    assert rejected_attachment["verification_status"] == "fail"
    assert yaml.safe_load(
        (evolution_dir / "independent_verification.yml").read_text(encoding="utf-8")
    )["status"] == "fail"
    assert (evolution_dir / "validation_report.yml").read_bytes() == validation_snapshot
    rejected_verifier = _write_verifier_receipt(
        root,
        evolution_dir,
        remove_declared_input=True,
    )
    rejected_receipt = yaml.safe_load(
        rejected_verifier.read_text(encoding="utf-8")
    )
    assert rejected_receipt["status"] == "fail"
    assert "invalid_verifier_task_packet" in rejected_receipt["issues"]
    restored_verifier = _write_verifier_receipt(
        root,
        evolution_dir,
        remove_declared_input=True,
        restore_packet_before_binding=True,
    )
    restored_receipt = yaml.safe_load(
        restored_verifier.read_text(encoding="utf-8")
    )
    assert restored_receipt["status"] == "fail"
    assert (
        "verifier_execution_used_different_prepared_packet"
        in restored_receipt["issues"]
    )
    verifier = _write_verifier_receipt(root, evolution_dir)
    validation = validate_evolution(
        root,
        evolution_dir=evolution_dir,
        execute_commands=True,
        independent_verification_path=verifier,
    )
    assert (evolution_dir / "validation_report.yml").read_bytes() == validation_snapshot
    generated_prompt = (
        worktree
        / "config"
        / "generated"
        / "roles"
        / "context_consistency_editor"
        / "worker_prompt.md"
    )
    original_prompt = generated_prompt.read_text(encoding="utf-8")
    generated_prompt.write_text(original_prompt + "tampered\n", encoding="utf-8")
    with pytest.raises(EvolutionWorkspaceError, match="changed after validation"):
        mark_review_ready(root, evolution_dir=evolution_dir, publish=False)
    generated_prompt.write_text(original_prompt, encoding="utf-8")
    generated_prompt.unlink()
    generated_prompt.symlink_to(
        evolution_dir / "bridge_bundle" / "worker_prompt.md"
    )
    with pytest.raises(EvolutionWorkspaceError, match="symlink"):
        mark_review_ready(root, evolution_dir=evolution_dir, publish=False)
    generated_prompt.unlink()
    generated_prompt.write_text(original_prompt, encoding="utf-8")
    review = mark_review_ready(root, evolution_dir=evolution_dir, publish=False)
    rollback = write_rollback_candidate(root, evolution_dir)

    assert validation["status"] == "pass"
    assert review["status"] == "local_review_ready"
    assert review["human_merge_required"] is True
    assert review["auto_merge"] is False
    assert rollback["status"] == "rollback_review_ready"
    rollback_patch = root / rollback["rollback_patch"]
    assert rollback_patch.is_file()
    assert sha256(rollback_patch.read_bytes()).hexdigest() == rollback[
        "rollback_patch_sha256"
    ]
    assert (worktree / "config/components/agents/context_consistency_editor.yml").exists()
    assert not (root / "config/components/agents/context_consistency_editor.yml").exists()
    current_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    assert current_head == base_head


def test_core_module_uses_proposal_lifecycle_without_implementing_rag(tmp_path: Path):
    root = _copy_root(tmp_path)
    run = _task_run(root, "task_rag")
    manifest_path = _write_yaml(
        run / "rag.yml",
        {
            "api_version": "agentlab/v1",
            "kind": "core_module",
            "metadata": {
                "id": "evidence_rag",
                "display_name": "EvidenceRag",
                "version": "0.1.0",
                "status": "candidate",
            },
            "spec": {
                "objective": "Retrieve evidence without becoming a fact authority.",
                "interfaces": {"input": "query", "output": "evidence_bundle"},
                "validation": {"required": ["retrieval_benchmark", "fact_authority_gate"]},
                "permissions": {},
            },
        },
    )
    observation = record_gap_observation(
        root,
        run / "rag_observation",
        task_id="task_rag",
        capability_id="evidence_retrieval",
        reason="explicit framework extensibility check",
        explicit_user_request=True,
    )
    evolution_dir = run / "rag_evolution"

    proposal = propose_component(
        root,
        manifest_path=manifest_path,
        evidence_paths=[observation],
        evolution_dir=evolution_dir,
    )
    result = materialize_component(root, evolution_dir=evolution_dir, create_worktree=False)

    assert proposal["materializer_status"] == "proposal_only"
    assert result["status"] == "design_ready"
    assert not (evolution_dir / "bridge_bundle").exists()


def test_self_evolution_artifacts_cannot_escape_task_run(tmp_path: Path):
    root = _copy_root(tmp_path)

    with pytest.raises(ValueError, match="projects/<Project>/runs/<task_id>"):
        record_gap_observation(
            root,
            tmp_path / "outside_run",
            task_id="task_escape",
            capability_id="escape_attempt",
            reason="path boundary regression",
            explicit_user_request=True,
        )


def test_proposal_only_components_cannot_request_control_plane_permissions():
    data = {
        "api_version": "agentlab/v1",
        "kind": "core_module",
        "metadata": {
            "id": "unsafe_module",
            "display_name": "UnsafeModule",
            "version": "0.1.0",
            "status": "candidate",
        },
        "spec": {
            "objective": "Attempt an unsafe control-plane proposal.",
            "interfaces": {"input": "request", "output": "candidate"},
            "validation": {"required": ["security_review"]},
            "permissions": {"auto_merge": True, "credential_management": True},
        },
    }

    with pytest.raises(ManifestValidationError) as exc_info:
        ComponentManifest.from_mapping(data)

    assert any("auto_merge" in issue for issue in exc_info.value.issues)
    assert any("credential_management" in issue for issue in exc_info.value.issues)
