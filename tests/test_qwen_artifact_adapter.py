"""Offline contract tests for the bounded Qwen ArtifactProducer adapter."""

from __future__ import annotations

import json
import os
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from agent_runtime.cli_executor import run_cli_agent
from agent_runtime.schemas import AgentRoute, WorkflowPlan


_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_MODEL_KEY = "qwen3_7_max_dashscope"
_MODEL_ID = "qwen3.7-max"
_TASK_ID = "task_qwen_artifact_001"
_DECLARED_XLSX = f"runs/{_TASK_ID}/deliverable.xlsx"
_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def qwen_artifact_runtime(tmp_path: Path) -> tuple[WorkflowPlan, dict[str, object]]:
    """Create temp run state while exercising the repository's real config."""

    project_root = tmp_path / "projects" / "ArtifactProject"
    run_dir = project_root / "runs" / _TASK_ID
    run_dir.mkdir(parents=True)
    (run_dir / "artifact_task.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "artifact_type": "spreadsheet",
                "validation": {"required_paths": [_DECLARED_XLSX]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    plan = WorkflowPlan(
        project="ArtifactProject",
        task_id=_TASK_ID,
        agentlab_root=str(_ROOT),
        project_root=str(project_root),
        repo_path=str(project_root),
        run_dir=str(run_dir),
        user_request_path=str(run_dir / "user_request.md"),
        route=AgentRoute(task_size="small", agents=["ArtifactProducer"]),
    )
    role_profile: dict[str, object] = {
        "executor_type": "cli_agent",
        "cli_agent": "qwen",
        "invocation_contract": "qwen_artifact",
        "default": _MODEL_KEY,
        "capacity_selected_route": "ArtifactProducerQwenMax",
        "capacity_pool": "dashscope_metered_api",
        "capacity_attempt_id": f"{_TASK_ID}:ArtifactProducer:primary",
        "capacity_selection_kind": "primary",
    }
    return plan, role_profile


def _write_minimal_xlsx(path: Path) -> None:
    """Write a small valid OOXML spreadsheet using only the standard library."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>
""",
        )
        package.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
""",
        )
        package.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>
</workbook>
""",
        )
        package.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>
""",
        )
        package.writestr(
            "xl/worksheets/sheet1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>ok</t></is></c></row></sheetData>
</worksheet>
""",
        )


def _completed_qwen_process() -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["qwen"],
        returncode=0,
        stdout=json.dumps(
            {
                "result": "created declared spreadsheet",
                "model": _MODEL_ID,
                "usage": {"input_tokens": 12, "output_tokens": 5},
            }
        ),
        stderr="",
    )


def _run(
    plan: WorkflowPlan,
    role_profile: dict[str, object],
):
    return run_cli_agent(
        plan,
        "ArtifactProducer",
        role_profile,
        sealed_messages=[
            {"role": "system", "content": "Use only this bounded task."},
            {"role": "user", "content": "Create the declared spreadsheet."},
        ],
    )


def test_exact_qwen_command_provider_environment_and_allowlisted_materialization(
    qwen_artifact_runtime: tuple[WorkflowPlan, dict[str, object]],
) -> None:
    plan, role_profile = qwen_artifact_runtime
    observed: dict[str, object] = {}
    dashscope_key = "dashscope-test-key"
    inherited_openai_key = "must-not-reach-qwen"

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        cwd = Path(str(kwargs["cwd"]))
        env = dict(kwargs["env"])
        packet_path = cwd / "task_packet_artifactproducer.json"
        observed.update({"argv": list(argv), "env": env, "cwd": cwd})

        _write_minimal_xlsx(cwd / _DECLARED_XLSX)
        undeclared = cwd / "runs" / _TASK_ID / "undeclared.txt"
        undeclared.write_text("must remain isolated", encoding="utf-8")
        (cwd / "outside-run.txt").write_text(
            "must remain isolated", encoding="utf-8"
        )

        expected_prompt = (
            f"Read only the bounded ArtifactTask packet at {packet_path}. Work only "
            "inside this isolated workspace. Create every exact required output "
            "path declared by the packet, validate each artifact, and return a "
            "concise report. Do not read any unlisted host path, use network tools "
            "beyond the selected model provider, or claim an artifact that does "
            "not exist. AgentLab copies only declared outputs and owns all runtime "
            "receipts."
        )
        assert argv == [
            "qwen",
            "--bare",
            "--auth-type",
            "openai",
            "--openai-base-url",
            _DASHSCOPE_BASE_URL,
            "--model",
            _MODEL_ID,
            "--sandbox",
            "--approval-mode",
            "yolo",
            "--output-format",
            "json",
            "--max-wall-time",
            "10m",
            "--max-tool-calls",
            "50",
            expected_prompt,
        ]
        assert env["DASHSCOPE_API_KEY"] == dashscope_key
        assert env["OPENAI_API_KEY"] == dashscope_key
        assert env["OPENAI_API_KEY"] != inherited_openai_key
        assert env["OPENAI_BASE_URL"] == _DASHSCOPE_BASE_URL
        return _completed_qwen_process()

    with patch.dict(
        os.environ,
        {
            "DASHSCOPE_API_KEY": dashscope_key,
            "OPENAI_API_KEY": inherited_openai_key,
        },
        clear=True,
    ), patch(
        "agent_runtime.cli_executor.shutil.which", return_value="/usr/bin/qwen"
    ), patch(
        "agent_runtime.cli_executor.subprocess.run", side_effect=fake_run
    ):
        result = _run(plan, role_profile)

    project_root = Path(plan.project_root)
    declared_target = project_root / _DECLARED_XLSX
    assert result.status == "completed"
    assert declared_target.is_file()
    assert zipfile.is_zipfile(declared_target)
    assert not (project_root / "runs" / _TASK_ID / "undeclared.txt").exists()
    assert not (project_root / "outside-run.txt").exists()
    assert not Path(observed["cwd"]).exists()

    preflight = result.raw_usage["qwen_artifact_preflight"]
    assert preflight["status"] == "pass"
    assert preflight["selected_provider"] == "dashscope_cn"
    assert preflight["selected_runtime_provider"] == "qwen3"
    assert preflight["selected_model_id"] == _MODEL_ID
    assert preflight["command_binding_verified"] is True
    assert preflight["auth_key_target_bound"] is True
    assert result.raw_usage["artifact_materialization_status"] == "pass"
    assert [
        item["path"]
        for item in result.raw_usage["artifact_materialized_outputs"]
    ] == [_DECLARED_XLSX]


def test_missing_dashscope_key_blocks_before_subprocess_and_scrubs_inherited_openai_key(
    qwen_artifact_runtime: tuple[WorkflowPlan, dict[str, object]],
) -> None:
    plan, role_profile = qwen_artifact_runtime
    inherited_openai_key = "inherited-openai-secret"

    with patch.dict(
        os.environ,
        {"OPENAI_API_KEY": inherited_openai_key},
        clear=True,
    ), patch(
        "agent_runtime.cli_executor.shutil.which", return_value="/usr/bin/qwen"
    ), patch("agent_runtime.cli_executor.subprocess.run") as provider_process:
        result = _run(plan, role_profile)

    provider_process.assert_not_called()
    assert result.status == "blocked_user_decision"
    assert result.error == "qwen_artifact_preflight_failed"
    assert result.raw_usage["provider_process_started"] is False
    preflight = result.raw_usage["qwen_artifact_preflight"]
    assert preflight["status"] == "fail"
    assert "dashscope_api_key_missing" in preflight["issues"]
    assert "dashscope_api_key_environment_not_bound" in preflight["issues"]
    assert preflight["auth_key_source_configured"] is False
    assert preflight["auth_key_target_bound"] is False

    evidence = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    run_evidence = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in Path(plan.run_dir).rglob("*")
        if path.is_file()
    )
    assert inherited_openai_key not in evidence
    assert inherited_openai_key not in run_evidence


def test_fake_text_xlsx_is_blocked_and_not_materialized(
    qwen_artifact_runtime: tuple[WorkflowPlan, dict[str, object]],
) -> None:
    plan, role_profile = qwen_artifact_runtime

    def fake_run(_argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        fake_xlsx = Path(str(kwargs["cwd"])) / _DECLARED_XLSX
        fake_xlsx.parent.mkdir(parents=True, exist_ok=True)
        fake_xlsx.write_text("not an xlsx package", encoding="utf-8")
        return _completed_qwen_process()

    with patch.dict(
        os.environ,
        {"DASHSCOPE_API_KEY": "dashscope-test-key"},
        clear=True,
    ), patch(
        "agent_runtime.cli_executor.shutil.which", return_value="/usr/bin/qwen"
    ), patch(
        "agent_runtime.cli_executor.subprocess.run", side_effect=fake_run
    ):
        result = _run(plan, role_profile)

    assert result.status == "blocked_user_decision"
    assert result.error == "CLI agent validation_failed (exit 0)."
    assert result.raw_usage["failure_class"] == "validation_failed"
    assert result.raw_usage["artifact_materialization_status"] == "fail"
    assert result.raw_usage["artifact_materialization_missing"] == []
    assert result.raw_usage["artifact_materialization_blocked"] == [
        {"path": _DECLARED_XLSX, "reason": "invalid_office_zip"}
    ]
    assert not (Path(plan.project_root) / _DECLARED_XLSX).exists()


def test_missing_declared_output_blocks_completion(
    qwen_artifact_runtime: tuple[WorkflowPlan, dict[str, object]],
) -> None:
    plan, role_profile = qwen_artifact_runtime

    with patch.dict(
        os.environ,
        {"DASHSCOPE_API_KEY": "dashscope-test-key"},
        clear=True,
    ), patch(
        "agent_runtime.cli_executor.shutil.which", return_value="/usr/bin/qwen"
    ), patch(
        "agent_runtime.cli_executor.subprocess.run",
        return_value=_completed_qwen_process(),
    ):
        result = _run(plan, role_profile)

    assert result.status == "blocked_user_decision"
    assert result.error == "CLI agent validation_failed (exit 0)."
    assert result.raw_usage["failure_class"] == "validation_failed"
    assert result.raw_usage["artifact_materialization_status"] == "fail"
    assert result.raw_usage["artifact_materialization_missing"] == [_DECLARED_XLSX]
    assert result.raw_usage["artifact_materialization_blocked"] == []
    assert not (Path(plan.project_root) / _DECLARED_XLSX).exists()
