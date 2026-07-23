from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from pipeline_runner import _pack_candidate_payload  # noqa: E402
from production_pack_output_materializer import (  # noqa: E402
    REQUIRED_SYNTHESIS_OUTPUTS,
    materialize_production_pack_candidate_result,
    write_production_pack_verification_receipt,
)
from schemas import LLMCallResult  # noqa: E402


def _shell_pack() -> dict:
    return {
        "pack_id": "pack_synthesis_candidate",
        "route_key": "artifact_production_task",
        "project_type": "experiential_installation",
        "task_domain": "scent_theater",
        "artifact_type": "show_package",
    }


def _write_research_contract(run_dir: Path) -> None:
    (run_dir / "production_pack_research_contract.yml").write_text(
        yaml.safe_dump(
            {
                "status": "pass",
                "execution_mode": "execute",
                "provider_returned_research": True,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _candidate_values(task_id: str) -> dict[str, str]:
    values: dict[str, str] = {}
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
        values[name] = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    return values


def _result(
    task_id: str, *, omit: str | None = None, wrong_run: bool = False
) -> LLMCallResult:
    blocks = []
    for name, value in _candidate_values(task_id).items():
        if name == omit:
            continue
        target_task = (
            "task_other"
            if wrong_run and name == "production_pack_proposal.yml"
            else task_id
        )
        blocks.append(
            f"<!-- AGENTLAB_EDIT: runs/{target_task}/{name} -->\n"
            f"```yaml\n{value.rstrip()}\n```\n"
            "<!-- END AGENTLAB_EDIT -->"
        )
    return LLMCallResult(
        provider="agentlab-cli-executor",
        model="agy",
        content="\n\n".join(blocks),
        status="completed",
        raw_usage={"cli_agent": "agy", "command_id": "cmd_test"},
    )


def test_materializes_complete_same_run_pack_candidate(tmp_path: Path) -> None:
    task_id = "task_pack_live"
    run_dir = tmp_path / "runs" / task_id
    run_dir.mkdir(parents=True)
    _write_research_contract(run_dir)
    catalog = tmp_path / "production_packs.yml"
    catalog.write_text("packs: []\n", encoding="utf-8")

    ok = materialize_production_pack_candidate_result(
        _result(task_id),
        run_dir,
        task_id,
        catalog,
        execution_mode="execute",
    )

    assert ok is True
    contract = yaml.safe_load(
        (run_dir / "production_pack_output_contract.yml").read_text(encoding="utf-8")
    )
    assert contract["status"] == "pass"
    assert contract["provider_returned_outputs"] is True
    assert contract["harness_generated_pack_content"] is False
    assert contract["proposal_validation"]["valid"] is True
    assert contract["materialized_outputs"] == sorted(REQUIRED_SYNTHESIS_OUTPUTS)
    assert all((run_dir / name).exists() for name in REQUIRED_SYNTHESIS_OUTPUTS)


def test_accepts_hash_verified_native_isolated_cli_outputs(tmp_path: Path) -> None:
    task_id = "task_pack_native_cli"
    run_dir = tmp_path / "runs" / task_id
    run_dir.mkdir(parents=True)
    _write_research_contract(run_dir)
    catalog = tmp_path / "production_packs.yml"
    catalog.write_text("packs: []\n", encoding="utf-8")

    materialized = []
    for name, value in _candidate_values(task_id).items():
        raw = value.encode("utf-8")
        (run_dir / name).write_bytes(raw)
        materialized.append(
            {
                "path": f"runs/{task_id}/{name}",
                "byte_count": len(raw),
                "sha256": sha256(raw).hexdigest(),
            }
        )
    receipt_path = run_dir / "artifact_materialization_receipt.yml"
    receipt_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "pass",
                "role": "ArtifactProducer",
                "task_id": task_id,
                "required_outputs": [
                    f"runs/{task_id}/{name}" for name in REQUIRED_SYNTHESIS_OUTPUTS
                ],
                "materialized": materialized,
                "missing": [],
                "blocked": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    result = LLMCallResult(
        provider="agentlab-cli-executor",
        model="qwen",
        content="Created and validated the three declared pack candidates.",
        status="completed",
        raw_usage={
            "cli_agent": "qwen",
            "command_id": "cmd_native_pack",
            "artifact_materialization_status": "pass",
            "artifact_materialization_receipt": str(receipt_path),
        },
    )

    assert materialize_production_pack_candidate_result(
        result,
        run_dir,
        task_id,
        catalog,
        execution_mode="execute",
    )
    contract = yaml.safe_load(
        (run_dir / "production_pack_output_contract.yml").read_text(encoding="utf-8")
    )
    assert contract["status"] == "pass"
    assert contract["returned_artifact_source"] == "isolated_cli_declared_files"
    assert contract["materialized_outputs"] == sorted(REQUIRED_SYNTHESIS_OUTPUTS)


def test_missing_pack_output_is_transactionally_blocked(tmp_path: Path) -> None:
    task_id = "task_pack_live"
    run_dir = tmp_path / "runs" / task_id
    run_dir.mkdir(parents=True)
    _write_research_contract(run_dir)
    catalog = tmp_path / "production_packs.yml"
    catalog.write_text("packs: []\n", encoding="utf-8")

    ok = materialize_production_pack_candidate_result(
        _result(task_id, omit="lifecycle_profile.yml"),
        run_dir,
        task_id,
        catalog,
        execution_mode="execute",
    )

    assert ok is False
    assert not any((run_dir / name).exists() for name in REQUIRED_SYNTHESIS_OUTPUTS)
    contract = yaml.safe_load(
        (run_dir / "production_pack_output_contract.yml").read_text(encoding="utf-8")
    )
    assert "missing_production_pack_output:lifecycle_profile.yml" in contract["issues"]


def test_cross_run_pack_output_is_rejected(tmp_path: Path) -> None:
    task_id = "task_pack_live"
    run_dir = tmp_path / "runs" / task_id
    run_dir.mkdir(parents=True)
    _write_research_contract(run_dir)
    catalog = tmp_path / "production_packs.yml"
    catalog.write_text("packs: []\n", encoding="utf-8")

    ok = materialize_production_pack_candidate_result(
        _result(task_id, wrong_run=True),
        run_dir,
        task_id,
        catalog,
        execution_mode="execute",
    )

    assert ok is False
    contract = yaml.safe_load(
        (run_dir / "production_pack_output_contract.yml").read_text(encoding="utf-8")
    )
    assert (
        "production_pack_output_wrong_run:runs/task_other/production_pack_proposal.yml"
        in contract["issues"]
    )


def test_verifier_receipt_requires_returned_verifier_and_valid_contract(
    tmp_path: Path,
) -> None:
    task_id = "task_pack_live"
    run_dir = tmp_path / "runs" / task_id
    run_dir.mkdir(parents=True)
    _write_research_contract(run_dir)
    catalog = tmp_path / "production_packs.yml"
    catalog.write_text("packs: []\n", encoding="utf-8")
    assert materialize_production_pack_candidate_result(
        _result(task_id),
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
    )

    receipt = write_production_pack_verification_receipt(
        verifier,
        run_dir,
        catalog,
        execution_mode="execute",
    )

    assert receipt["status"] == "pass"
    assert receipt["verifier_role_session_returned"] is True
    assert receipt["proposal_validation"]["valid"] is True
