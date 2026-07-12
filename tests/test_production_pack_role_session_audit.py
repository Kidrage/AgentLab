from __future__ import annotations

from pathlib import Path
import sys

import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from pipeline_runner import _pack_candidate_payload  # noqa: E402
from outbound_context import (  # noqa: E402
    PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME,
    write_outbound_context_manifest,
)
from production_pack_output_materializer import (  # noqa: E402
    REQUIRED_SYNTHESIS_OUTPUTS,
    materialize_production_pack_candidate_result,
    write_production_pack_verification_receipt,
)
from production_pack_role_session_audit import (  # noqa: E402
    build_production_pack_role_session_audit,
)
from schemas import LLMCallResult  # noqa: E402
from run_task import app  # noqa: E402


def _shell_pack() -> dict:
    return {
        "status": "synthesis_candidate",
        "pack_id": "pack_synthesis_candidate",
        "route_key": "artifact_production_task",
        "project_type": "experiential_installation",
        "task_domain": "scent_theater",
        "artifact_type": "show_package",
        "required_outputs": list(REQUIRED_SYNTHESIS_OUTPUTS),
    }


def _artifact_result(task_id: str) -> LLMCallResult:
    blocks = []
    for name in REQUIRED_SYNTHESIS_OUTPUTS:
        payload = _pack_candidate_payload(
            "pack_synthesis_candidate",
            name,
            "AgentLab",
            task_id,
            execution_mode="execute",
            pack=_shell_pack(),
        )
        payload["generated_by"] = "ArtifactProducer role session"
        blocks.append(
            f"<!-- AGENTLAB_EDIT: runs/{task_id}/{name} -->\n"
            f"```yaml\n{yaml.safe_dump(payload, sort_keys=False).rstrip()}\n```\n"
            "<!-- END AGENTLAB_EDIT -->"
        )
    return LLMCallResult(
        provider="agentlab-cli-executor",
        model="agy",
        content="\n\n".join(blocks),
        status="completed",
        raw_usage={"cli_agent": "agy", "command_id": "cmd_artifact"},
    )


def _complete_run(root: Path, task_id: str) -> Path:
    run_dir = root / "projects" / "AgentLab" / "runs" / task_id
    run_dir.mkdir(parents=True)
    (root / "config").mkdir()
    catalog = root / "config" / "production_packs.yml"
    catalog.write_text("packs: []\n", encoding="utf-8")
    (run_dir / "workflow_plan.yml").write_text(
        yaml.safe_dump({"production_pack": _shell_pack()}, sort_keys=False),
        encoding="utf-8",
    )
    (run_dir / "mission_contract.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "task_id": task_id,
                "project_id": "AgentLab",
                "compiler_source": "rule_based",
                "route_decision": {
                    "selected_route": "artifact_production_task"
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "lifecycle.yml").write_text(
        yaml.safe_dump(
            {
                "nodes": {
                    "SUPERVISOR_PLAN": {"status": "completed"},
                    "RESEARCH_OPTIONAL": {"status": "completed"},
                    "ARTIFACT_PRODUCTION": {"status": "completed"},
                    "VERIFY": {"status": "completed"},
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "domain_research_brief.md").write_text(
        "# Domain Research Brief\n\nReturned research.\n", encoding="utf-8"
    )
    (run_dir / "01_supervisor_plan.md").write_text(
        "# Supervisor Plan\n\nCandidate-only synthesis route assigned.\n",
        encoding="utf-8",
    )
    (run_dir / "production_pack_research_contract.yml").write_text(
        yaml.safe_dump(
            {
                "status": "pass",
                "execution_mode": "execute",
                "provider_returned_research": True,
                "source_provider": "agentlab-cli-executor",
                "source_model": "claude_code",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert materialize_production_pack_candidate_result(
        _artifact_result(task_id),
        run_dir,
        task_id,
        catalog,
        execution_mode="execute",
    )
    verifier = LLMCallResult(
        provider="agentlab-cli-executor",
        model="hermes",
        content="# Verification\n\nDecision: pass.\n",
        status="completed",
        raw_usage={"cli_agent": "hermes", "command_id": "cmd_verify"},
    )
    (run_dir / "verification_report.md").write_text(verifier.content, encoding="utf-8")
    receipt = write_production_pack_verification_receipt(
        verifier,
        run_dir,
        catalog,
        execution_mode="execute",
    )
    assert receipt["status"] == "pass"
    for role in ("Supervisor", "Researcher", "ArtifactProducer", "Verifier"):
        write_outbound_context_manifest(
            root,
            run_dir / f"outbound_context_manifest_{role.lower()}.yml",
            item_id=task_id,
            role=role,
            provider_surface="cli_agent:agy",
            payload_kind="production_pack_cli_role_session_packet",
            payload_text=f"safe exact {role} packet",
            source_paths=[run_dir / "workflow_plan.yml"],
            private_context=True,
            exact_payload=True,
            sealed_context=True,
            execution_workspace_isolated=True,
            approval_required=True,
            approval_granted=True,
            approval_env_name=PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME,
            provider_shell_or_browser_requested=role == "Researcher",
            source_inventory_required=True,
        )
    return run_dir


def test_audit_is_candidate_before_role_session_returns(tmp_path: Path) -> None:
    report = build_production_pack_role_session_audit(
        tmp_path,
        task_id="task_missing",
    )

    assert report["status"] == "candidate"
    assert report["provider_calls_executed_by_audit"] is False
    assert report["missing"]


def test_audit_passes_only_complete_returned_role_session_chain(
    tmp_path: Path,
) -> None:
    task_id = "task_pack_live"
    _complete_run(tmp_path, task_id)

    report = build_production_pack_role_session_audit(
        tmp_path,
        task_id=task_id,
    )

    assert report["status"] == "pass"
    assert report["failed_checks"] == []
    assert report["candidate_only"] is True
    assert report["production_modified"] is False


def test_audit_fails_fake_provider_provenance(tmp_path: Path) -> None:
    task_id = "task_pack_live"
    run_dir = _complete_run(tmp_path, task_id)
    contract_path = run_dir / "production_pack_research_contract.yml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    contract["source_provider"] = "fake_provider"
    contract_path.write_text(
        yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
    )

    report = build_production_pack_role_session_audit(
        tmp_path,
        task_id=task_id,
    )

    assert report["status"] == "fail"
    assert "researcher_role_session_returned" in report["failed_checks"]


def test_audit_requires_governed_outbound_manifests(tmp_path: Path) -> None:
    task_id = "task_pack_live"
    run_dir = _complete_run(tmp_path, task_id)
    manifest_path = run_dir / "outbound_context_manifest_artifactproducer.yml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["authorization"]["approval_observed"] = False
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )

    report = build_production_pack_role_session_audit(
        tmp_path,
        task_id=task_id,
    )

    assert report["status"] == "fail"
    assert "artifactproducer_outbound_context_governed" in report["failed_checks"]


def test_audit_cli_require_pass_rejects_candidate(tmp_path: Path) -> None:
    report_path = tmp_path / "role_session_audit.yml"

    result = CliRunner().invoke(
        app,
        [
            "production-pack-role-session-audit",
            "--project",
            "AgentLab",
            "--task-id",
            "task_missing_role_session",
            "--out",
            str(report_path),
            "--require-pass",
        ],
    )

    assert result.exit_code == 1
    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "candidate"
