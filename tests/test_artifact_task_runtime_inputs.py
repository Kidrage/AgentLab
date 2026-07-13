"""Offline runtime tests for hash-bound ArtifactTask input staging."""

from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# ``agent_runner`` supports direct script execution and therefore imports its
# runtime siblings as top-level modules.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent_runtime"))

from agent_runner import (  # noqa: E402
    _resolve_cli_profile_for_agent,
    artifact_producer_context_source_files,
)
from cli_executor import run_cli_agent  # noqa: E402
from protocols.artifact_task import (  # noqa: E402
    ArtifactInputContractError,
    build_artifact_task_contract,
    stage_artifact_task_inputs,
    validate_artifact_task_inputs,
)
from schemas import AgentRoute, WorkflowPlan  # noqa: E402


TASK_ID = "task_artifact_inputs_001"
DECLARED_XLSX = f"runs/{TASK_ID}/deliverable.xlsx"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_minimal_xlsx(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("xl/workbook.xml", "<workbook/>")


def _runtime(tmp_path: Path) -> tuple[Path, WorkflowPlan, Path, dict]:
    root = tmp_path / "agentlab"
    project_root = root / "projects" / "InputProject"
    run_dir = project_root / "runs" / TASK_ID
    run_dir.mkdir(parents=True)
    source = root / "source_data.csv"
    source.write_text("name,value\nalpha,1\n", encoding="utf-8")
    undeclared = root / "secret_not_assigned.csv"
    undeclared.write_text("must,not,be,staged\n", encoding="utf-8")
    contract = build_artifact_task_contract(
        root,
        "Create an xlsx spreadsheet from the assigned CSV.",
        artifact_type="spreadsheet",
        output_path=DECLARED_XLSX,
        project="InputProject",
        task_id=TASK_ID,
        assigned_input_paths=[source],
    )
    contract["validation"] = {"required_paths": [DECLARED_XLSX]}
    (run_dir / "artifact_task.yml").write_text(
        yaml.safe_dump(contract, sort_keys=False),
        encoding="utf-8",
    )
    user_request = run_dir / "user_request.md"
    user_request.write_text("Create the declared workbook.", encoding="utf-8")
    plan = WorkflowPlan(
        project="InputProject",
        task_id=TASK_ID,
        agentlab_root=str(root),
        project_root=str(project_root),
        repo_path=str(project_root),
        run_dir=str(run_dir),
        user_request_path=str(user_request),
        route=AgentRoute(
            route_key="artifact_production_task",
            task_size="small",
            agents=["ArtifactProducer"],
        ),
    )
    return root, plan, source, contract


def _run_fake_artifact_cli(plan: WorkflowPlan):
    return run_cli_agent(
        plan,
        "ArtifactProducer",
        {
            "executor_type": "cli_agent",
            "cli_agent": "offline_fake",
            "cli_command": "offline-fake {task_packet_path}",
        },
        sealed_messages=[
            {"role": "system", "content": "Use only the bounded packet."},
            {"role": "user", "content": "Create the declared workbook."},
        ],
    )


def test_runtime_validator_rechecks_exact_source_hash_and_private_path(
    tmp_path: Path,
) -> None:
    root, _plan, source, contract = _runtime(tmp_path)

    validated = validate_artifact_task_inputs(root, contract)

    assert validated[0]["source_path"] == "source_data.csv"
    assert validated[0]["staged_path"] == "artifact_inputs/01_source_data.csv"
    assert validated[0]["sha256"] == _sha256(source)
    assert validated[0]["_source_path"] == source


@pytest.mark.parametrize(
    ("field", "value", "issue"),
    [
        ("source_path", "/tmp/absolute.csv", "artifact_input_path_invalid"),
        ("source_path", "../escape.csv", "artifact_input_path_invalid"),
        ("source_path", "C:\\escape.csv", "artifact_input_path_invalid"),
        ("source_path", "bad\nname.csv", "artifact_input_path_invalid"),
        (
            "staged_path",
            "artifact_inputs/99_wrong.csv",
            "artifact_input_staged_path_invalid",
        ),
    ],
)
def test_runtime_validator_rejects_unsafe_contract_paths(
    tmp_path: Path,
    field: str,
    value: str,
    issue: str,
) -> None:
    root, _plan, _source, contract = _runtime(tmp_path)
    contract["assigned_inputs"][0][field] = value

    with pytest.raises(ArtifactInputContractError) as raised:
        validate_artifact_task_inputs(root, contract)

    assert raised.value.code == issue


def test_runtime_validator_rejects_duplicate_sources_and_size_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import protocols.artifact_task as artifact_task_module

    root, _plan, _source, contract = _runtime(tmp_path)
    duplicate = dict(contract["assigned_inputs"][0])
    duplicate["staged_path"] = "artifact_inputs/02_source_data.csv"
    contract["assigned_inputs"].append(duplicate)
    with pytest.raises(ArtifactInputContractError) as duplicate_error:
        validate_artifact_task_inputs(root, contract)
    assert duplicate_error.value.code == "artifact_input_duplicate_source"

    contract["assigned_inputs"] = contract["assigned_inputs"][:1]
    monkeypatch.setattr(artifact_task_module, "MAX_ARTIFACT_INPUT_BYTES", 4)
    with pytest.raises(ArtifactInputContractError) as size_error:
        validate_artifact_task_inputs(root, contract)
    assert size_error.value.code == "artifact_input_total_size_limit_exceeded"


def test_runtime_validator_rejects_parent_symlink_and_hash_tamper(
    tmp_path: Path,
) -> None:
    root, _plan, source, contract = _runtime(tmp_path)
    source.write_text("name,value\nbeta!,2\n", encoding="utf-8")
    with pytest.raises(ArtifactInputContractError) as hash_error:
        validate_artifact_task_inputs(root, contract)
    assert hash_error.value.code in {
        "artifact_input_size_mismatch",
        "artifact_input_hash_mismatch",
    }

    real_directory = root / "real"
    real_directory.mkdir()
    real_source = real_directory / "source.csv"
    real_source.write_text("value\n1\n", encoding="utf-8")
    linked_directory = root / "linked"
    try:
        linked_directory.symlink_to(real_directory, target_is_directory=True)
    except OSError as exc:  # pragma: no cover - unsupported host filesystem
        pytest.skip(f"symlink unavailable: {exc}")
    symlink_contract = {
        "assigned_inputs": [
            {
                "source_path": "linked/source.csv",
                "staged_path": "artifact_inputs/01_source.csv",
                "sha256": _sha256(real_source),
                "byte_count": real_source.stat().st_size,
                "read_only": True,
            }
        ]
    }
    with pytest.raises(ArtifactInputContractError) as symlink_error:
        validate_artifact_task_inputs(root, symlink_contract)
    assert symlink_error.value.code == "artifact_input_symlink_not_allowed"


def test_runtime_validator_detects_mutation_during_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import protocols.artifact_task as artifact_task_module

    root, _plan, source, contract = _runtime(tmp_path)
    original_hash = artifact_task_module._hash_open_file_descriptor

    def hash_then_mutate(
        file_fd: int,
        *,
        max_bytes: int | None = None,
    ) -> tuple[str, int]:
        result = original_hash(file_fd, max_bytes=max_bytes)
        source.write_text("name,value\ngamma,3\n", encoding="utf-8")
        return result

    monkeypatch.setattr(
        artifact_task_module,
        "_hash_open_file_descriptor",
        hash_then_mutate,
    )
    with pytest.raises(ArtifactInputContractError) as raised:
        validate_artifact_task_inputs(root, contract)
    assert raised.value.code == "artifact_input_changed_while_hashing"


def test_staging_rechecks_source_after_initial_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import protocols.artifact_task as artifact_task_module

    root, _plan, source, contract = _runtime(tmp_path)
    workspace = tmp_path / "isolated"
    workspace.mkdir()
    original_validate = artifact_task_module.validate_artifact_task_inputs

    def validate_then_tamper(root_path: Path, packet: dict) -> list[dict]:
        rows = original_validate(root_path, packet)
        source.write_text("name,value\nomega,9\n", encoding="utf-8")
        return rows

    monkeypatch.setattr(
        artifact_task_module,
        "validate_artifact_task_inputs",
        validate_then_tamper,
    )
    with pytest.raises(ArtifactInputContractError) as raised:
        stage_artifact_task_inputs(root, contract, workspace)
    assert raised.value.code == "artifact_input_staged_integrity_mismatch"


def test_cli_stages_only_declared_input_read_only_and_materializes_xlsx(
    tmp_path: Path,
) -> None:
    root, plan, source, _contract = _runtime(tmp_path)

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        cwd = Path(str(kwargs["cwd"]))
        packet_path = cwd / "task_packet_artifactproducer.json"
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        staged = cwd / "artifact_inputs" / "01_source_data.csv"

        assert argv == ["offline-fake", str(packet_path)]
        assert packet["context_policy"]["read_scope"] == [
            "this_task_packet",
            "artifact_inputs/*",
        ]
        assert packet["context_policy"]["additional_file_read_boundary"] == (
            "artifact_inputs/*"
        )
        assert packet["artifact_inputs"] == [
            {
                "source_path": "source_data.csv",
                "staged_path": "artifact_inputs/01_source_data.csv",
                "sha256": _sha256(source),
                "byte_count": source.stat().st_size,
                "read_only": True,
            }
        ]
        assert staged.read_bytes() == source.read_bytes()
        assert stat.S_IMODE(staged.stat().st_mode) == 0o400
        assert stat.S_IMODE(staged.parent.stat().st_mode) == 0o500
        assert not (cwd / "secret_not_assigned.csv").exists()
        assert "secret_not_assigned.csv" not in packet_path.read_text(encoding="utf-8")
        assert str(root) not in packet_path.read_text(encoding="utf-8")

        _write_minimal_xlsx(cwd / DECLARED_XLSX)
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout="created workbook",
            stderr="",
        )

    with patch(
        "cli_executor.shutil.which",
        return_value="/usr/bin/offline-fake",
    ), patch(
        "cli_executor.subprocess.run",
        side_effect=fake_run,
    ):
        result = _run_fake_artifact_cli(plan)

    assert result.status == "completed"
    assert (Path(plan.project_root) / DECLARED_XLSX).is_file()
    manifest_path = Path(plan.run_dir) / "artifact_input_manifest.yml"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = yaml.safe_load(manifest_text)
    assert manifest["status"] == "pass"
    assert manifest["phase"] == "postflight"
    assert manifest["input_count"] == 1
    assert manifest["total_bytes"] == source.stat().st_size
    assert manifest["provider_process_started"] is True
    assert manifest["assigned_inputs"][0]["source_path"] == "source_data.csv"
    assert str(root) not in manifest_text
    assert result.raw_usage["artifact_input_count"] == 1


@pytest.mark.parametrize("mutation", ["tamper", "path_escape", "symlink"])
def test_invalid_input_blocks_before_binary_or_provider_subprocess(
    tmp_path: Path,
    mutation: str,
) -> None:
    root, plan, source, contract = _runtime(tmp_path)
    if mutation == "tamper":
        source.write_text("name,value\ntampered,9\n", encoding="utf-8")
    elif mutation == "path_escape":
        contract["assigned_inputs"][0]["source_path"] = "../outside.csv"
    else:
        real = root / "real_source.csv"
        source.rename(real)
        try:
            source.symlink_to(real)
        except OSError as exc:  # pragma: no cover - unsupported host filesystem
            pytest.skip(f"symlink unavailable: {exc}")
    if mutation != "tamper":
        (Path(plan.run_dir) / "artifact_task.yml").write_text(
            yaml.safe_dump(contract, sort_keys=False),
            encoding="utf-8",
        )

    with patch("cli_executor.shutil.which") as binary_lookup, patch(
        "cli_executor.subprocess.run"
    ) as provider_process:
        result = _run_fake_artifact_cli(plan)

    binary_lookup.assert_not_called()
    provider_process.assert_not_called()
    assert result.status == "blocked_user_decision"
    assert result.error == "artifact_input_validation_failed"
    assert result.raw_usage["provider_process_started"] is False
    manifest = yaml.safe_load(
        (Path(plan.run_dir) / "artifact_input_manifest.yml").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["status"] == "fail"
    assert manifest["phase"] == "validation"
    assert manifest["issues"][0]["code"].startswith("artifact_input_")


def test_assigned_inputs_require_an_isolated_bounded_cli_session(
    tmp_path: Path,
) -> None:
    _root, plan, _source, _contract = _runtime(tmp_path)

    with patch("cli_executor.shutil.which") as binary_lookup, patch(
        "cli_executor.subprocess.run"
    ) as provider_process:
        result = run_cli_agent(
            plan,
            "ArtifactProducer",
            {
                "executor_type": "cli_agent",
                "cli_agent": "offline_fake",
                "cli_command": "offline-fake {task_packet_path}",
            },
        )

    binary_lookup.assert_not_called()
    provider_process.assert_not_called()
    assert result.error == "artifact_input_validation_failed"
    assert result.raw_usage["artifact_input_issue"] == (
        "artifact_input_isolated_session_required"
    )


def test_provider_input_mutation_fails_postflight_before_output_materialization(
    tmp_path: Path,
) -> None:
    _root, plan, _source, _contract = _runtime(tmp_path)

    def mutating_provider(
        argv: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        cwd = Path(str(kwargs["cwd"]))
        staged = cwd / "artifact_inputs" / "01_source_data.csv"
        staged.chmod(0o600)
        staged.write_text("provider changed this input\n", encoding="utf-8")
        _write_minimal_xlsx(cwd / DECLARED_XLSX)
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout="created workbook",
            stderr="",
        )

    with patch(
        "cli_executor.shutil.which",
        return_value="/usr/bin/offline-fake",
    ), patch(
        "cli_executor.subprocess.run",
        side_effect=mutating_provider,
    ):
        result = _run_fake_artifact_cli(plan)

    assert result.status == "blocked_user_decision"
    assert result.raw_usage["failure_class"] == "validation_failed"
    assert result.raw_usage["artifact_input_postflight_issue"] in {
        "artifact_input_staged_mode_mutated",
        "artifact_input_staged_integrity_mismatch",
    }
    assert not (Path(plan.project_root) / DECLARED_XLSX).exists()
    manifest = yaml.safe_load(
        (Path(plan.run_dir) / "artifact_input_manifest.yml").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["status"] == "fail"
    assert manifest["phase"] == "postflight"
    assert manifest["provider_process_started"] is True


def test_artifact_context_inventory_only_adds_runtime_validated_sources(
    tmp_path: Path,
) -> None:
    _root, plan, source, _contract = _runtime(tmp_path)
    output = Path(plan.run_dir) / "artifact_producer_report.md"

    sources = artifact_producer_context_source_files(
        Path(plan.agentlab_root),
        plan,
        output,
    )
    assert source in sources
    assert all(path.name != "secret_not_assigned.csv" for path in sources)

    source.write_text("tampered\n", encoding="utf-8")
    sources_after_tamper = artifact_producer_context_source_files(
        Path(plan.agentlab_root),
        plan,
        output,
    )
    assert source not in sources_after_tamper


@pytest.mark.parametrize(
    "assigned_inputs",
    [
        [
            {
                "source_path": "inputs/source.txt",
                "staged_path": "artifact_inputs/01_source.txt",
                "sha256": "0" * 64,
                "byte_count": 1,
                "read_only": True,
            }
        ],
        {},
        "",
    ],
)
def test_full_api_assigned_inputs_fail_with_explicit_capability_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    assigned_inputs: object,
) -> None:
    project_root = tmp_path / "projects" / "ApiInputProject"
    run_dir = project_root / "runs" / TASK_ID
    run_dir.mkdir(parents=True)
    request_path = run_dir / "user_request.md"
    request_path.write_text("Write a markdown report from the input.", encoding="utf-8")
    (run_dir / "artifact_task.yml").write_text(
        yaml.safe_dump(
            {
                "artifact_type": "text",
                "output": {
                    "path": f"runs/{TASK_ID}/report.md",
                    "format": "markdown",
                },
                "assigned_inputs": assigned_inputs,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    plan = WorkflowPlan(
        project="ApiInputProject",
        task_id=TASK_ID,
        agentlab_root=str(REPO_ROOT),
        project_root=str(project_root),
        repo_path=str(project_root),
        run_dir=str(run_dir),
        user_request_path=str(request_path),
        route=AgentRoute(
            route_key="article_light_draft",
            task_size="small",
            agents=["ArtifactProducer"],
        ),
    )
    monkeypatch.setenv("AGENTLAB_MODE", "full_api")

    _configs, mode, _role, profile = _resolve_cli_profile_for_agent(
        REPO_ROOT,
        plan,
        "ArtifactProducer",
    )

    assert mode == "full_api"
    assert profile["executor_type"] == "blocked"
    assert profile["artifact_routing_status"] == "capability_mismatch"
    assert profile["_artifact_task_contract"]["routing"]["mode_blocker"] == (
        "full_api_assigned_inputs_unsupported"
    )
    assert "does not support assigned file inputs" in profile[
        "artifact_routing_reason"
    ]
