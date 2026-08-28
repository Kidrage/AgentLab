from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from agent_runtime.narrative.blueprint_bootstrap import (
    authorize_blueprint_outbound,
    create_blueprint_task,
)
from agent_runtime.narrative.outbound_transfer import evaluate_narrative_auto_approval
from agent_runtime.project_truth import ProjectTruthStore
from agent_runtime.production_protocols import ProductionProtocolRunner
from agent_runtime.task_runtime_v2 import InvalidTransition
from agent_runtime.task_runtime_v2.role_executor import RoleAttemptExecutor


ROOT = Path(__file__).resolve().parents[1]


def _copy_authorities(root: Path) -> None:
    config = root / "config"
    config.mkdir()
    for name in (
        "production_packs.yml",
        "task_input_tiers.yml",
        "agent_model_profiles.yml",
        "production_role_profiles.yml",
        "narrative_author_team.yml",
        "agent_registry.yml",
        "model_catalog.yml",
        "model_providers.yml",
        "model_capacity.yml",
        "worker_invocation_contracts.yml",
        "agent_role_bindings.yml",
    ):
        shutil.copy2(ROOT / "config" / name, config / name)


def test_creative_brief_creates_hash_bound_full_team_task_without_production(
    tmp_path: Path,
) -> None:
    _copy_authorities(tmp_path)
    brief_path = tmp_path / "inputs" / "creative_brief.yml"
    brief_path.parent.mkdir()
    brief_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "narrative-blueprint-request/v1",
                "project": "ShanHeYouJia",
                "title": "山河有约",
                "genres": ["wuxia", "commerce", "politics", "cosmic_fantasy"],
                "target_total_chapters": 600,
                "target_han_characters": 2_800_000,
                "creative_seed": {
                    "premise": "A river porter rises through trade, politics, and rule.",
                    "ending": "One universe has one formless True Immortal.",
                },
                "content_boundary": {
                    "all_romance_participants_adults": True,
                    "contextual_consent": True,
                    "exit_right": True,
                    "explicitness": "non_graphic",
                },
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    first = create_blueprint_task(
        tmp_path,
        project="ShanHeYouJia",
        task_id="task-blueprint-001",
        request_path=brief_path,
    )
    second = create_blueprint_task(
        tmp_path,
        project="ShanHeYouJia",
        task_id="task-blueprint-001",
        request_path=brief_path,
    )

    assert second == first
    assert first["status"] == "prepared"
    assert first["task"]["protocol_ref"] == "narrative.blueprint.v1"
    assert first["task"]["input_profile"]["source_creative_brief_sha256"] == (
        hashlib.sha256(brief_path.read_bytes()).hexdigest()
    )
    governed_brief = (
        tmp_path
        / first["task"]["input_profile"]["source_creative_brief"]
    )
    assert governed_brief.is_file()
    assert governed_brief.is_relative_to(
        tmp_path
        / "projects"
        / "ShanHeYouJia"
        / "runtime"
        / "tasks"
        / "task-blueprint-001"
    )
    assert len(first["work_items"]) == 13
    assert first["work_items"]["authorial_director"]["status"] == "ready"
    execution = first["execution_inputs"]
    messages_path = tmp_path / execution["messages_path"]
    external_request_path = tmp_path / execution["external_context_request_path"]
    assert messages_path.is_file()
    assert external_request_path.is_file()
    messages = json.loads(messages_path.read_text(encoding="utf-8"))
    assert messages[0]["role"] == "user"
    assert "600" in messages[0]["content"]
    runner = ProductionProtocolRunner(tmp_path, project="ShanHeYouJia")
    projection = runner.runtime.load_task("task-blueprint-001")
    binding = next(
        item
        for item in projection["task"]["compiled_protocol"]["role_bindings"]
        if item["node_id"] == "authorial_director"
    )
    assert runner._governed_sources(
        "task-blueprint-001",
        projection=projection,
        binding=binding,
        source_paths=[],
    ) == [governed_brief.resolve()]
    role_executor = RoleAttemptExecutor(tmp_path, project="ShanHeYouJia")
    assert role_executor._source_allowed_by_protocol(
        governed_brief.resolve(),
        projection=projection,
        work_item=projection["work_items"]["authorial_director"],
        task_id="task-blueprint-001",
    ) is True
    assert not (tmp_path / "projects" / "ShanHeYouJia" / "production").exists()

    governed_brief.write_text("tampered: true\n", encoding="utf-8")
    with pytest.raises(InvalidTransition, match="hash mismatch"):
        runner._governed_sources(
            "task-blueprint-001",
            projection=projection,
            binding=binding,
            source_paths=[],
        )
    assert role_executor._source_allowed_by_protocol(
        governed_brief.resolve(),
        projection=projection,
        work_item=projection["work_items"]["authorial_director"],
        task_id="task-blueprint-001",
    ) is False


def test_generate_blueprint_cli_prepares_the_governed_task(tmp_path: Path) -> None:
    _copy_authorities(tmp_path)
    (tmp_path / "agentlab.sh").touch()
    (tmp_path / "agent_runtime").mkdir()
    brief_path = tmp_path / "creative_brief.yml"
    brief_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "narrative-blueprint-request/v1",
                "project": "ShanHeYouJia",
                "title": "山河有约",
                "genres": ["wuxia"],
                "target_total_chapters": 600,
                "target_han_characters": 2_800_000,
                "creative_seed": {"premise": "Rise from nothing.", "ending": "One True Immortal."},
                "content_boundary": {
                    "all_romance_participants_adults": True,
                    "contextual_consent": True,
                    "exit_right": True,
                    "explicitness": "non_graphic",
                },
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            str(ROOT / "agentlab.sh"),
            "narrative",
            "generate-blueprint",
            "--project",
            "ShanHeYouJia",
            "--task-id",
            "task-blueprint-cli",
            "--request",
            str(brief_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "AGENTLAB_ROOT": str(tmp_path),
            "NO_COLOR": "1",
            "COLUMNS": "240",
        },
    )

    assert result.returncode == 0, result.stderr
    payload = yaml.safe_load(result.stdout)
    assert payload["status"] == "prepared"
    assert payload["task"]["protocol_ref"] == "narrative.blueprint.v1"


def test_invalid_brief_does_not_leave_a_partial_runtime_task(tmp_path: Path) -> None:
    _copy_authorities(tmp_path)
    brief_path = tmp_path / "creative_brief.yml"
    brief_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "narrative-blueprint-request/v1",
                "project": "ShanHeYouJia",
                "title": "山河有约",
                "genres": ["wuxia"],
                "target_total_chapters": 600,
                "target_han_characters": 2_800_000,
                "risk_flags": ["undeclared-risk"],
                "creative_seed": {
                    "premise": "Rise from nothing.",
                    "ending": "One True Immortal.",
                },
                "content_boundary": {
                    "all_romance_participants_adults": True,
                    "contextual_consent": True,
                    "exit_right": True,
                    "explicitness": "non_graphic",
                },
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown_risk_flag"):
        create_blueprint_task(
            tmp_path,
            project="ShanHeYouJia",
            task_id="task-invalid-brief",
            request_path=brief_path,
        )

    assert not (
        tmp_path
        / "projects"
        / "ShanHeYouJia"
        / "runtime"
        / "tasks"
        / "task-invalid-brief"
    ).exists()


def test_blueprint_outbound_authority_is_task_scoped_and_candidate_only(
    tmp_path: Path,
) -> None:
    _copy_authorities(tmp_path)
    brief_path = tmp_path / "creative_brief.yml"
    brief_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "narrative-blueprint-request/v1",
                "project": "ShanHeYouJia",
                "title": "山河有约",
                "genres": ["wuxia"],
                "target_total_chapters": 600,
                "target_han_characters": 2_800_000,
                "creative_seed": {
                    "premise": "Rise from nothing.",
                    "ending": "One True Immortal.",
                },
                "content_boundary": {
                    "all_romance_participants_adults": True,
                    "contextual_consent": True,
                    "exit_right": True,
                    "explicitness": "non_graphic",
                },
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    create_blueprint_task(
        tmp_path,
        project="ShanHeYouJia",
        task_id="task-blueprint-authorized",
        request_path=brief_path,
    )

    first = authorize_blueprint_outbound(
        tmp_path,
        project="ShanHeYouJia",
        task_id="task-blueprint-authorized",
        authorized_by="user_saintpeter",
    )
    request_path = (
        tmp_path
        / "projects"
        / "ShanHeYouJia"
        / "runtime"
        / "tasks"
        / "task-blueprint-authorized"
        / "inputs"
        / "external-context-request.yml"
    )
    request_bytes = request_path.read_bytes()
    second = authorize_blueprint_outbound(
        tmp_path,
        project="ShanHeYouJia",
        task_id="task-blueprint-authorized",
        authorized_by="user_saintpeter",
    )

    assert second == first
    assert request_path.read_bytes() == request_bytes
    policy = yaml.safe_load(
        (tmp_path / first["policy_path"]).read_text(encoding="utf-8")
    )
    assert policy["constraints"]["allowed_task_ids"] == [
        "task-blueprint-authorized"
    ]
    assert "allowed_task_prefixes" not in policy["constraints"]
    assert policy["constraints"]["allowed_source_roots"] == ["runtime"]
    assert policy["constraints"]["candidate_only"] is True
    assert policy["constraints"]["state_projection_requires_user_acceptance"] is True
    assert policy["authorization"]["user_responsibility"] == (
        "candidate_acceptance_only"
    )
    truth = ProjectTruthStore(
        tmp_path / "projects" / "ShanHeYouJia"
    ).current()
    authority = truth.resources[
        "policies.outbound_context_auto_approval"
    ]
    assert authority.actor_id == "user_saintpeter"
    assert authority.content["policy_sha256"] == first["policy_sha256"]
    collision = evaluate_narrative_auto_approval(
        tmp_path,
        project="ShanHeYouJia",
        task_id="task-blueprint-authorized-extra",
        recipient=policy["constraints"]["allowed_recipients"][0],
        role=policy["constraints"]["allowed_roles"][0],
        purpose="Attempt a prefix-collision transfer.",
        source_paths=[request_path],
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    )
    assert collision["status"] == "blocked"
    assert "task_not_allowed" in collision["issues"]


def test_blueprint_outbound_truth_failure_does_not_overwrite_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _copy_authorities(tmp_path)
    brief_path = tmp_path / "creative_brief.yml"
    brief_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "narrative-blueprint-request/v1",
                "project": "AtomicPolicy",
                "title": "山河有约",
                "genres": ["wuxia"],
                "target_total_chapters": 600,
                "target_han_characters": 2_800_000,
                "creative_seed": {
                    "premise": "Rise from nothing.",
                    "ending": "One True Immortal.",
                },
                "content_boundary": {
                    "all_romance_participants_adults": True,
                    "contextual_consent": True,
                    "exit_right": True,
                    "explicitness": "non_graphic",
                },
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    create_blueprint_task(
        tmp_path,
        project="AtomicPolicy",
        task_id="task-atomic-policy",
        request_path=brief_path,
    )
    policy_path = (
        tmp_path / "projects" / "AtomicPolicy" / "production" /
        "outbound_context_policy.yml"
    )
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text("sentinel: preserved\n", encoding="utf-8")

    def fail_commit(*_args, **_kwargs):
        raise RuntimeError("truth commit failed")

    monkeypatch.setattr(ProjectTruthStore, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="truth commit failed"):
        authorize_blueprint_outbound(
            tmp_path,
            project="AtomicPolicy",
            task_id="task-atomic-policy",
            authorized_by="user_saintpeter",
        )

    assert policy_path.read_text(encoding="utf-8") == "sentinel: preserved\n"


def test_governance_only_production_allows_renamed_blueprint_retry(
    tmp_path: Path,
) -> None:
    _copy_authorities(tmp_path)
    production = tmp_path / "projects" / "ShanHeYouJia" / "production"
    production.mkdir(parents=True)
    (production / "outbound_context_policy.yml").write_text(
        "schema_version: outbound-context-policy/v1\n",
        encoding="utf-8",
    )
    brief_path = tmp_path / "creative_brief.yml"
    brief_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "narrative-blueprint-request/v1",
                "project": "ShanHeYouJia",
                "title": "山河有约",
                "genres": ["wuxia"],
                "target_total_chapters": 600,
                "target_han_characters": 2_800_000,
                "creative_seed": {
                    "premise": "Rise from nothing.",
                    "ending": "One True Immortal.",
                },
                "content_boundary": {
                    "all_romance_participants_adults": True,
                    "contextual_consent": True,
                    "exit_right": True,
                    "explicitness": "non_graphic",
                },
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    result = create_blueprint_task(
        tmp_path,
        project="ShanHeYouJia",
        task_id="task-blueprint-renamed",
        request_path=brief_path,
    )

    assert "《山河有约》" in result["task"]["user_goal"]
    assert (production / "outbound_context_policy.yml").is_file()
