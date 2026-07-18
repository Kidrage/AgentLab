from __future__ import annotations

import subprocess
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from agent_runtime.production_pack_role_session_request import (
    PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME,
    build_production_pack_role_session_request,
    write_production_pack_role_session_request,
)


ROOT = Path(__file__).resolve().parents[1]
ROLE_CHAIN = yaml.safe_load(
    (ROOT / "config" / "production_packs.yml").read_text(encoding="utf-8")
)["pack_synthesis_policy"]["agents"]
SOURCE_REQUEST = (
    "设计一个沉浸式气味剧场装置生产流程。需要长期维护观众动线、气味提示、安全验收、"
    "场次状态、设备校准、异常回滚和多轮生成产物；AgentLab 应先研究所需内部能力与经批准的"
    "外部资源，再产出候选 production pack，不得使用代码壳，不得自动 promotion。"
)


def _portable_request_root(tmp_path: Path) -> Path:
    root = tmp_path / "agentlab"
    shutil.copytree(ROOT / "config", root / "config")
    source_run = (
        root
        / "projects"
        / "AgentLab"
        / "runs"
        / "task_production_pack_role_session_live_20260710"
    )
    source_run.mkdir(parents=True)
    (source_run / "user_request.md").write_text(SOURCE_REQUEST, encoding="utf-8")
    return root


def test_request_builds_fresh_four_role_runner_without_provider_calls(
    tmp_path: Path,
) -> None:
    root = _portable_request_root(tmp_path)
    target_task_id = "task_pytest_pack_role_request_preview_20260710"
    target_run = root / "projects" / "AgentLab" / "runs" / target_task_id
    assert not target_run.exists()
    out = tmp_path / "production_pack_role_session_request.yml"

    report = write_production_pack_role_session_request(
        root,
        out,
        target_task_id=target_task_id,
    )

    assert report["status"] == "ready_for_explicit_approval"
    assert report["provider_calls_executed"] is False
    assert report["role_chain"] == ROLE_CHAIN
    assert report["route_preview"]["production_pack_status"] == (
        "synthesis_candidate"
    )
    assert report["approval"]["env_name"] == (
        PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME
    )
    assert report["context_boundary"]["silent_provider_fallback_allowed"] is False
    assert report["context_boundary"]["workspace_scan_allowed"] is False
    assert report["role_surfaces"]["Supervisor"]["worker"] == "hermes"
    assert report["role_surfaces"]["Researcher"]["worker"] == "grok"
    assert report["role_surfaces"]["ArtifactProducer"]["worker"] == "grok"
    assert report["role_surfaces"]["Verifier"]["worker"] == "hermes"
    assert all(
        item["role_binding_allowed"] is True
        for item in report["role_surfaces"].values()
    )
    assert not target_run.exists()

    script_path = out.with_suffix(".sh")
    script = script_path.read_text(encoding="utf-8")
    assert PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME in script
    assert "mission_contract.yml" in script
    assert "run-pipeline" in script
    assert "--execute" in script
    assert "--require-pass" in script
    assert "沉浸式气味剧场" not in script
    assert subprocess.run(
        ["bash", "-n", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    ).returncode == 0


def test_request_secret_preflight_fails_without_writing_runner(
    tmp_path: Path,
) -> None:
    project = "AgentLab"
    source_task_id = "task_source_secret"
    target_task_id = "task_target_secret"
    source_run = tmp_path / "projects" / project / "runs" / source_task_id
    source_run.mkdir(parents=True)
    secret = "sk-" + ("a" * 40)
    (source_run / "user_request.md").write_text(
        f"design a production pack\ncredential: {secret}\n",
        encoding="utf-8",
    )
    fake_plan = SimpleNamespace(
        production_pack={
            "status": "synthesis_candidate",
            "pack_id": "pack_synthesis_candidate",
            "agents": ROLE_CHAIN,
        },
        route=SimpleNamespace(
            route_key="artifact_production_task",
            agents=ROLE_CHAIN,
        ),
        mission_contract={"compiler_source": "rule_based"},
    )
    surfaces = {
        role: {
            "worker": "test-worker",
            "role_binding_allowed": True,
        }
        for role in ROLE_CHAIN
    }
    out = tmp_path / "request.yml"

    with patch(
        "agent_runtime.production_pack_role_session_request.build_workflow_plan",
        return_value=fake_plan,
    ), patch(
        "agent_runtime.production_pack_role_session_request._role_surfaces",
        return_value=(surfaces, []),
    ):
        report = write_production_pack_role_session_request(
            tmp_path,
            out,
            project=project,
            source_task_id=source_task_id,
            target_task_id=target_task_id,
        )

    assert report["status"] == "fail"
    assert "source_context:secret_pattern_detected" in report["issues"]
    assert report["runner_script"] is None
    assert not out.with_suffix(".sh").exists()
    rendered = out.read_text(encoding="utf-8")
    assert secret not in rendered
    assert yaml.safe_load(rendered)["source_request_contents_rendered"] is False


def test_request_rejects_existing_target_run(tmp_path: Path) -> None:
    root = _portable_request_root(tmp_path)
    target_run = (
        root
        / "projects"
        / "AgentLab"
        / "runs"
        / "task_production_pack_role_session_live_20260710"
    )
    target_run.mkdir(parents=True, exist_ok=True)
    report = build_production_pack_role_session_request(
        root,
        target_task_id="task_production_pack_role_session_live_20260710",
    )

    assert report["status"] == "fail"
    assert "target_run_already_exists" in report["issues"]
