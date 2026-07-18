from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.run_task import app
from agent_runtime.trusted_live_runner_request import build_trusted_live_runner_request, write_trusted_live_runner_request
from agent_runtime.trusted_live_runner_preflight import build_trusted_live_runner_preflight
from agent_runtime.trusted_live_runner_status import build_trusted_live_runner_status


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_trusted_live_runner_request_materializes_internal_smoke_commands_without_running() -> None:
    report = build_trusted_live_runner_request(ROOT, request_id="trusted_live_test")
    by_id = {item["id"]: item for item in report["items"]}

    assert report["report_type"] == "agentlab_trusted_live_runner_request"
    assert report["status"] == "ready_for_trusted_runner"
    assert report["session_health_evaluated_at_runtime"] is True
    assert "session_health_warnings" not in report
    assert report["runner_boundary"]["frontdesk_agent_executes_commands"] is False
    assert report["runner_boundary"]["requires_trusted_runtime"] is True
    pre_run = report["recommended_pre_run_session_health_checks"]
    assert pre_run["loads_private_project_context"] is False
    assert pre_run["executes_private_live_generation"] is False
    assert pre_run["required_for_clean_live_run"] is True
    assert report["terminology"]["canonical_kind"] == "private_role_session_acceptance_smoke"
    assert report["terminology"]["not_a_default_production_workflow"] is True
    assert report["runner_boundary"]["role_session_acceptance_commands_allowed_only_by_runner"] is True
    assert any(
        "worker-invocation-probe --worker claude_writer" in command
        for command in pre_run["commands"]
    )
    assert any("grok-cli-smoke --live" in command for command in pre_run["commands"])
    assert any("internal-live-readiness" in command for command in pre_run["commands"])
    assert any("internal_live_readiness.yml" in command for command in pre_run["commands"])
    assert by_id["run_crown_internal_writer_eval"]["agentlab_execution_owner"] == "Writer"
    assert by_id["run_crown_internal_writer_eval"]["assigned_worker"] == "claude_code"
    assert "--writer-worker claude_code" in by_id["run_crown_internal_writer_eval"]["command"]
    assert "--writer-worker agy" not in by_id["run_crown_internal_writer_eval"]["command"]
    assert "trusted_live_test_writer" in by_id["run_crown_internal_writer_eval"]["command"]
    assert by_id["run_crown_internal_writer_eval"]["expected_outputs"]["type"] == "narrative_live_smoke"
    assert "fiction_draft.md" in "\n".join(by_id["run_crown_internal_writer_eval"]["expected_outputs"]["required_files"])
    writer_required = "\n".join(
        by_id["run_crown_internal_writer_eval"]["expected_outputs"]["required_files"]
    )
    assert "outbound_context_manifest_writer.yml" in writer_required
    assert "writer_output_contract.yml" in writer_required
    assert by_id["run_crown_internal_media_smoke"]["agentlab_execution_owner"] == "ArtifactProducer"
    assert "--role ArtifactProducer --worker grok" in by_id["run_crown_internal_media_smoke"]["command"]
    assert "trusted_live_test_media" in by_id["run_crown_internal_media_smoke"]["command"]
    assert "<id>" not in by_id["run_crown_internal_media_smoke"]["command"]
    assert "media_backend_live_internal_trusted_live_test_media" in by_id["run_crown_internal_media_smoke"]["command"]
    assert by_id["run_crown_internal_media_smoke"]["expected_outputs"]["type"] == "media_live_smoke"
    media_required = "\n".join(by_id["run_crown_internal_media_smoke"]["expected_outputs"]["required_files"])
    assert "media_backend_live_internal_trusted_live_test_media" in media_required
    assert "generation_ledger.yml" in media_required
    assert "outbound_context_manifest_media.yml" in media_required
    rendered = yaml.safe_dump(report, sort_keys=False, allow_unicode=True)
    assert "sk-" not in rendered
    assert "test-key" not in rendered


def test_trusted_live_runner_request_cli_writes_yaml_and_script(tmp_path: Path) -> None:
    out = tmp_path / "trusted_live_runner_request.yml"

    result = runner.invoke(
        app,
        [
            "trusted-live-runner-request",
            "--out",
            str(out),
            "--request-id",
            "trusted_live_cli_test",
        ],
    )

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    script = out.with_suffix(".sh")
    assert report["status"] == "ready_for_trusted_runner"
    assert report["script_path"] == str(script)
    assert report["local_runner_package"]["entrypoint"] == str(script)
    assert report["local_runner_package"]["status_path"] == str(out.with_name("trusted_live_runner_status.yml"))
    assert report["local_runner_package"]["preflight_report_path"] == str(
        out.with_name("trusted_live_runner_preflight.yml")
    )
    assert report["local_runner_package"]["collect_report_path"] == str(
        out.with_name("trusted_live_runner_collect.yml")
    )
    assert report["local_runner_package"]["refreshes_status_after_run"] is True
    assert report["local_runner_package"]["refreshes_acceptance_after_run"] is True
    assert report["local_runner_package"]["full_run_executes_session_health_checks"] is True
    assert report["local_runner_package"]["session_health_gate_before_private_context"] is True
    assert report["local_runner_package"]["full_run_requires_trusted_status_pass"] is True
    assert report["local_runner_package"]["selective_run_supported"] is True
    assert report["local_runner_package"]["selective_run_executes_session_health_checks"] is True
    assert report["local_runner_package"]["selective_run_requires_selected_item_pass"] is True
    assert report["local_runner_package"]["trusted_runner_env_required"] == "AGENTLAB_TRUSTED_LIVE_RUNNER=1"
    assert (
        report["local_runner_package"]["role_session_acceptance_approval_env_required"]
        == "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1"
    )
    assert report["local_runner_package"]["approval_gate_before_private_context"] is True
    assert report["local_runner_package"]["exact_outbound_context_manifest_required"] is True
    assert report["local_runner_package"]["writer_sealed_context_required"] is True
    assert report["local_runner_package"]["media_prompt_digest_required"] is True
    assert report["local_runner_package"]["secret_pattern_gate_before_provider_call"] is True
    assert report["local_runner_package"]["acceptance_smoke_kind"] == "private_role_session_acceptance_smoke"
    assert report["local_runner_package"]["acceptance_smoke_label"] == "private role-session acceptance smoke"
    assert report["local_runner_package"]["canonical_session_health_reports_require_trusted_runner_env"] is True
    assert report["local_runner_package"]["session_health_only_command"].startswith(
        "AGENTLAB_TRUSTED_LIVE_RUNNER=1 "
    )
    assert report["local_runner_package"]["selective_run_examples"]["writer_only"].endswith(
        " --only run_crown_internal_writer_eval"
    )
    assert report["local_runner_package"]["selective_run_examples"]["writer_only"].startswith(
        "AGENTLAB_TRUSTED_LIVE_RUNNER=1 AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1 "
    )
    assert report["local_runner_package"]["selective_run_examples"]["media_only"].endswith(
        " --only run_crown_internal_media_smoke"
    )
    assert report["local_runner_package"]["selective_run_examples"]["media_only"].startswith(
        "AGENTLAB_TRUSTED_LIVE_RUNNER=1 AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1 "
    )
    assert report["local_runner_package"]["post_run_selected_collect_commands"]["writer_only"].endswith(
        "--item run_crown_internal_writer_eval"
    )
    assert "trusted_live_runner_collect_writer.yml" not in report["local_runner_package"][
        "post_run_selected_collect_commands"
    ]["writer_only"]
    assert report["local_runner_package"]["post_run_selected_collect_commands"]["media_only"].endswith(
        "--item run_crown_internal_media_smoke"
    )
    assert "trusted_live_runner_collect_media.yml" not in report["local_runner_package"][
        "post_run_selected_collect_commands"
    ]["media_only"]
    assert report["local_runner_package"]["preflight_only_command"].endswith(" --preflight-only")
    assert report["local_runner_package"]["session_health_only_command"].endswith(" --session-health-only")
    assert "trusted-live-runner-preflight" in report["local_runner_package"]["preflight_report_command"]
    assert any(
        "worker-invocation-probe --worker claude_writer" in command
        for command in report["local_runner_package"]["recommended_pre_run_session_health_commands"]
    )
    assert any(
        "grok-cli-smoke --live" in command
        for command in report["local_runner_package"]["recommended_pre_run_session_health_commands"]
    )
    assert "command -v claude" in report["local_runner_package"]["preflight_commands"]
    assert "command -v agy" not in report["local_runner_package"]["preflight_commands"]
    assert "command -v hermes" in report["local_runner_package"]["preflight_commands"]
    text = script.read_text(encoding="utf-8")
    assert "require_command claude" in text
    assert "require_command agy" not in text
    assert "require_command hermes" in text
    assert "trusted-live-runner-preflight --request" in text
    assert "trusted-live-runner-collect --request" in text
    assert "--item \"$RUN_ONLY\"" in text
    assert "--preflight-only" in text
    assert "--session-health-only" in text
    assert "--only requires an item id" in text
    assert "RUN_ONLY" in text
    assert "run_session_health_checks" in text
    assert "guard_clean_session_health" in text
    assert "selected_session_health_issue_count" in text
    assert "should_run_session_health_command" in text
    assert "current_claude_writer_session_health" in text
    assert "current_grok_session_health" in text
    assert "skipped_for_selected_item=$RUN_ONLY" in text
    assert "TRUSTED_LIVE_RUNNER=\"${AGENTLAB_TRUSTED_LIVE_RUNNER:-}\"" in text
    assert (
        "ROLE_SESSION_ACCEPTANCE_APPROVED=\"${AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED:-}\""
        in text
    )
    assert "require_trusted_live_runner_env" in text
    assert "require_role_session_acceptance_approval_env" in text
    assert "without AGENTLAB_TRUSTED_LIVE_RUNNER=1" in text
    assert "without AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1" in text
    assert (
        "session health checks can use --session-health-only with AGENTLAB_TRUSTED_LIVE_RUNNER=1"
        in text
    )
    assert text.index("require_trusted_live_runner_env") < text.index("run_session_health_checks")
    assert text.rindex("require_role_session_acceptance_approval_env") < text.index(
        "run_item run_crown_internal_writer_eval"
    )
    assert "should_run_item" in text
    assert "selected_item_ran" in text
    assert "trusted_item_status_value" in text
    assert "trusted_live_runner_item_status[$RUN_ONLY]=$selected_status" in text
    assert "selected trusted live item is not accepted; item status must be pass" in text
    assert "print_session_health_issues" in text
    assert "session_health_issue_report_unreadable" in text
    assert "reason={reason} next_action={next_action}" in text
    assert "session_health_issues" in text
    assert "worker-invocation-probe --worker claude_writer" in text
    assert "claude_writer_session_probe.yml" in text
    assert "grok-cli-smoke --live" in text
    assert "internal-live-readiness" in text
    assert "internal_live_readiness.yml" in text
    assert text.index("--session-health-only") < text.index("run_item run_crown_internal_writer_eval")
    assert text.index("guard_clean_session_health") < text.index("run_item run_crown_internal_writer_eval")
    assert "run_item run_crown_internal_writer_eval" in text
    assert "run_item run_crown_internal_media_smoke" in text
    assert "trusted-live-runner-status --request" in text
    assert "collecting trusted live runner reports" in text
    assert "trusted_status_value" in text
    assert "trusted_live_runner_status=$trusted_status" in text
    assert "trusted live runner artifacts are not accepted; status must be pass" in text
    assert "collect_path=$COLLECT_PATH" in text
    assert "trusted_live_cli_test_writer" in text
    assert "trusted_live_cli_test_media" in text
    assert "narrative-eval run" in text
    assert "media-backend-execute" in text


def test_trusted_live_runner_script_refuses_without_required_env_gates(tmp_path: Path) -> None:
    acceptance_dir = tmp_path / "acceptance_runs" / "agentlab_capability_acceptance"
    acceptance_dir.mkdir(parents=True)
    (acceptance_dir / "frontdesk_live_handoff.yml").write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_user_input",
                "items": [
                    {
                        "id": "run_crown_internal_writer_eval",
                        "status": "ready",
                        "agentlab_execution_owner": "Writer",
                        "assigned_worker": "claude_code",
                        "role_session_required": True,
                        "agentlab_command": (
                            "./agentlab.sh narrative-eval run --project Crown_of_Ash "
                            "--suite suite --mode live --chapters 1 --timestamp <internal_live_run_id> "
                            "--writer-worker claude_code"
                        ),
                    },
                    {
                        "id": "run_crown_internal_media_smoke",
                        "status": "ready",
                        "agentlab_execution_owner": "ArtifactProducer",
                        "assigned_worker": "grok",
                        "role_session_required": True,
                        "agentlab_command": (
                            "./agentlab.sh media-backend-execute --contract media.yml "
                            "--out-dir artifacts/media_backend_live_internal_<id> "
                            "--live --role ArtifactProducer --worker grok"
                        ),
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (acceptance_dir / "internal_live_readiness.yml").write_text(
        yaml.safe_dump({"status": "ready_for_internal_live_smoke", "session_health_issues": []}, sort_keys=False),
        encoding="utf-8",
    )

    call_log = tmp_path / "agentlab_calls.log"
    agentlab = tmp_path / "agentlab.sh"
    agentlab.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> {str(call_log)!r}\nexit 0\n",
        encoding="utf-8",
    )
    agentlab.chmod(0o755)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ("agy", "grok"):
        executable = fake_bin / name
        executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    request_path = acceptance_dir / "trusted_live_runner_request.yml"
    report = write_trusted_live_runner_request(tmp_path, request_path, request_id="guard_test")
    script = Path(report["script_path"])

    env = os.environ.copy()
    env.pop("AGENTLAB_TRUSTED_LIVE_RUNNER", None)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        [str(script), "--session-health-only"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "without AGENTLAB_TRUSTED_LIVE_RUNNER=1" in result.stdout
    calls = call_log.read_text(encoding="utf-8").splitlines()
    assert any(call.startswith("trusted-live-runner-preflight ") for call in calls)
    assert all("agy-cli-smoke" not in call for call in calls)
    assert all("grok-cli-smoke" not in call for call in calls)
    assert all("narrative-eval" not in call for call in calls)
    assert all("media-backend-execute" not in call for call in calls)

    prior_call_count = len(calls)
    env["AGENTLAB_TRUSTED_LIVE_RUNNER"] = "1"
    env.pop("AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED", None)
    result = subprocess.run(
        [str(script)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "without AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1" in result.stdout
    calls = call_log.read_text(encoding="utf-8").splitlines()
    new_calls = calls[prior_call_count:]
    assert any(call.startswith("trusted-live-runner-preflight ") for call in new_calls)
    assert all("agy-cli-smoke" not in call for call in new_calls)
    assert all("grok-cli-smoke" not in call for call in new_calls)
    assert all("narrative-eval" not in call for call in new_calls)
    assert all("media-backend-execute" not in call for call in new_calls)


def test_trusted_live_runner_preflight_checks_local_package_without_provider_calls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    agentlab = tmp_path / "agentlab.sh"
    agentlab.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    agentlab.chmod(0o755)
    script = tmp_path / "trusted_live_runner_request.sh"
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    script.chmod(0o755)
    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "request_id": "preflight_test",
                "local_runner_package": {
                    "entrypoint": str(script),
                    "status_path": str(tmp_path / "trusted_live_runner_status.yml"),
                    "preflight_commands": [
                        "test -x ./agentlab.sh",
                        "command -v claude",
                        "command -v hermes",
                    ],
                    "exact_outbound_context_manifest_required": True,
                    "writer_sealed_context_required": True,
                    "media_prompt_digest_required": True,
                    "secret_pattern_gate_before_provider_call": True,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agent_runtime.trusted_live_runner_preflight.shutil.which",
        lambda command: f"/fake/bin/{command}" if command in {"claude", "hermes"} else None,
    )

    report = build_trusted_live_runner_preflight(tmp_path, request_path=request_path)

    assert report["status"] == "pass"
    assert report["executes_provider_calls"] is False
    assert report["loads_private_project_context"] is False
    assert {check["id"] for check in report["checks"] if check["status"] == "pass"} == {
        "request_yaml",
        "runner_script",
        "agentlab_entrypoint",
        "command:claude",
        "command:hermes",
        "exact_outbound_context_manifest_required",
        "writer_sealed_context_required",
        "media_prompt_digest_required",
        "secret_pattern_gate_before_provider_call",
    }
    rendered = yaml.safe_dump(report, sort_keys=False, allow_unicode=True)
    assert "sk-" not in rendered
    assert "test-key" not in rendered


def test_trusted_live_runner_status_reports_pending_until_outputs_return(
    tmp_path: Path,
) -> None:
    canonical_request = (
        ROOT
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "trusted_live_runner_request.yml"
    )
    request_path = (
        tmp_path
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "trusted_live_runner_request.yml"
    )
    request_path.parent.mkdir(parents=True)
    request_path.write_text(canonical_request.read_text(encoding="utf-8"), encoding="utf-8")

    report = build_trusted_live_runner_status(tmp_path)
    by_id = {item["id"]: item for item in report["items"]}

    assert report["report_type"] == "agentlab_trusted_live_runner_status"
    assert report["status"] == "pending"
    assert by_id["run_crown_internal_writer_eval"]["status"] == "pending"
    assert any(path.endswith("fiction_draft.md") for path in by_id["run_crown_internal_writer_eval"]["missing"])
    assert by_id["run_crown_internal_media_smoke"]["status"] == "pending"
    media_error = by_id["run_crown_internal_media_smoke"].get("observed_error", {})
    assert (
        any(path.endswith("generation_ledger.yml") for path in by_id["run_crown_internal_media_smoke"]["missing"])
        or media_error.get("status") in {"local_cli_timeout", "local_cli_error"}
    )


def test_trusted_live_runner_status_reports_claude_session_gate_for_missing_writer_artifacts(
    tmp_path: Path,
) -> None:
    smoke_dir = tmp_path / "acceptance_runs" / "agentlab_capability_acceptance"
    smoke_dir.mkdir(parents=True)
    (smoke_dir / "claude_writer_session_probe.yml").write_text(
        yaml.safe_dump(
            {
                "worker_id": "claude_writer",
                "installed": True,
                "exit_code": 1,
                "timeout": False,
                "error_class": "auth_required",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "items": [
                    {
                        "id": "run_crown_internal_writer_eval",
                        "assigned_worker": "claude_code",
                        "command": "./agentlab.sh narrative-eval run --writer-worker claude_code",
                        "expected_outputs": {
                            "type": "narrative_live_smoke",
                            "run_dir": "projects/Crown_of_Ash/runs/writer_out",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/writer_out/fiction_draft.md",
                            ],
                        },
                    },
                    {
                        "id": "run_crown_internal_media_smoke",
                        "command": "./agentlab.sh media-backend-execute --worker grok",
                        "expected_outputs": {"type": "media_live_smoke", "required_files": []},
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    writer = {item["id"]: item for item in report["items"]}["run_crown_internal_writer_eval"]

    assert writer["status"] == "pending"
    assert writer["acceptance_blocker"] == "missing_required_files"
    assert writer["pending_reason"] == "claude_writer_session_health_blocked_before_private_writer_smoke"
    assert writer["session_health_gate"]["reason"] == "auth_required"
    assert writer["session_health_gate"]["command_available"] is True


def test_trusted_live_runner_status_reports_observed_error(tmp_path: Path) -> None:
    run_dir = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "task_narrative_eval_ch01_test"
    run_dir.mkdir(parents=True)
    (run_dir / "live_generation_error.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "blocked",
                "provider": "agentlab-cli-executor",
                "model": "agy",
                "error": "CLI agent exited 1.",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "items": [
                    {
                        "id": "run_crown_internal_writer_eval",
                        "command": "./agentlab.sh narrative-eval run --writer-worker agy",
                        "expected_outputs": {
                            "type": "narrative_live_smoke",
                            "run_dir": "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_test",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_test/fiction_draft.md"
                            ],
                        },
                    },
                    {
                        "id": "run_crown_internal_media_smoke",
                        "command": "./agentlab.sh media-backend-execute --worker grok",
                        "expected_outputs": {
                            "type": "media_live_smoke",
                            "out_dir": "projects/Crown_of_Ash/runs/media_out",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/media_out/generation_ledger.yml"
                            ],
                        },
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    writer = {item["id"]: item for item in report["items"]}["run_crown_internal_writer_eval"]

    assert writer["status"] == "pending"
    assert writer["observed_error"]["agent"] is None
    assert writer["observed_error"]["result_status"] is None
    assert writer["observed_error"]["provider"] == "agentlab-cli-executor"
    assert writer["observed_error"]["model"] == "agy"
    assert writer["observed_error"]["error"] == "CLI agent exited 1."
    assert writer["pending_reason"] == "historical_writer_role_session_agy_cli_exit"
    assert writer["next_action"] == (
        "regenerate_trusted_writer_request_for_claude_writer_then_rerun_trusted_writer_smoke"
    )


def test_trusted_live_runner_status_passes_only_after_returned_artifact_qc(tmp_path: Path) -> None:
    narrative_run = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "task_narrative_eval_ch01_ok"
    narrative_run.mkdir(parents=True)
    chapter_lines = [
        "# Chapter 1: Ash at the Gate",
        "Kael woke before the bell because the town had learned to breathe quietly.",
        "Greyvale's roofs held the last rain in black seams, and every seam reflected the watch fires on the hill.",
        "His master had left the forge door open, which meant fear, not welcome.",
        "On the square, the Church banners snapped like wet bone while neighbors pretended not to count the soldiers.",
        "Kael kept his hands low and his eyes lower, but the brand under his sleeve warmed at each shouted prayer.",
        "When the first blade fell, the crowd flinched as one body and then remembered to be still.",
        "Owen found him beside the cistern and pressed the old iron charm into his palm without explanation.",
        "By dusk, the forge was ash, the charm was split, and Kael had blood on both hands.",
        "The voice that answered from the burn was not mercy, but it was alive.",
    ]
    (narrative_run / "fiction_draft.md").write_text(("\n\n".join(chapter_lines) + "\n") * 2, encoding="utf-8")
    (narrative_run / "continuity_ledger.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "chapter": 1, "timeline": {"monotonic": True}}, sort_keys=False),
        encoding="utf-8",
    )
    (narrative_run / "state_transition_proposal.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "candidate",
                "requires_user_promotion": True,
                "events": [{"event_type": "chapter_state_change", "scope": "candidate_only"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (narrative_run / "narrative_delivery_receipt.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "status": "pass", "delivery_check": {"valid": True}}, sort_keys=False),
        encoding="utf-8",
    )
    (narrative_run / "outbound_context_manifest_writer.yml").write_text(
        yaml.safe_dump(
            {
                "status": "pass",
                "execution_allowed": True,
                "role": "Writer",
                "context_boundary": {"sealed_context": True, "exact_payload_hashed": True},
                "payload": {"sha256": "a" * 64, "bytes": 100, "secret_pattern_hit_count": 0},
                "authorization": {"approval_required": True, "approval_observed": True},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (narrative_run / "writer_output_contract.yml").write_text(
        yaml.safe_dump(
            {"status": "pass", "harness_generated_story_state": False},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    eval_dir = tmp_path / "acceptance_runs" / "narrative_eval" / "Crown_of_Ash" / "suite" / "ok"
    eval_dir.mkdir(parents=True)
    (eval_dir / "longform_eval_report.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "pass",
                "layers": {
                    "L2_real_chapter_sample": {
                        "chapters": [
                            {
                                "chapter": 1,
                                "run_dir": "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_ok",
                            }
                        ]
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    media_out = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "media_ok"
    media_out.mkdir(parents=True)
    (media_out / "media_backend_preflight.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "status": "ready", "adapter_kind": "local_grok_cli"}, sort_keys=False),
        encoding="utf-8",
    )
    generated_asset = media_out / "crown_scene_001.mp4"
    generated_asset.write_bytes(b"fake mp4 bytes for structural qc")
    (media_out / "generation_ledger.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "completed",
                "backend": "hermes_grok_oauth",
                "adapter_kind": "local_grok_cli",
                "generated_assets": [str(generated_asset)],
                "text_artifacts": [],
                "artifact_generation_verified": True,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (media_out / "outbound_context_manifest_media.yml").write_text(
        yaml.safe_dump(
            {
                "status": "pass",
                "execution_allowed": True,
                "role": "ArtifactProducer",
                "context_boundary": {"sealed_context": True, "exact_payload_hashed": True},
                "payload": {"sha256": "b" * 64, "bytes": 80, "secret_pattern_hit_count": 0},
                "authorization": {"approval_required": True, "approval_observed": True},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "items": [
                    {
                        "id": "run_crown_internal_writer_eval",
                        "command": "./agentlab.sh narrative-eval run --writer-worker claude_code",
                        "expected_outputs": {
                            "type": "narrative_live_smoke",
                            "run_dir": "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_ok",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_ok/fiction_draft.md",
                                "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_ok/continuity_ledger.yml",
                                "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_ok/state_transition_proposal.yml",
                                "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_ok/narrative_delivery_receipt.yml",
                                "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_ok/outbound_context_manifest_writer.yml",
                                "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_ok/writer_output_contract.yml",
                                "acceptance_runs/narrative_eval/Crown_of_Ash/suite/ok/longform_eval_report.yml",
                            ],
                        },
                    },
                    {
                        "id": "run_crown_internal_media_smoke",
                        "command": "./agentlab.sh media-backend-execute --worker grok",
                        "expected_outputs": {
                            "type": "media_live_smoke",
                            "out_dir": "projects/Crown_of_Ash/runs/media_ok",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/media_ok/media_backend_preflight.yml",
                                "projects/Crown_of_Ash/runs/media_ok/generation_ledger.yml",
                                "projects/Crown_of_Ash/runs/media_ok/outbound_context_manifest_media.yml",
                            ],
                        },
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    by_id = {item["id"]: item for item in report["items"]}

    assert report["status"] == "pass"
    assert by_id["run_crown_internal_writer_eval"]["artifact_qc"]["status"] == "pass"
    assert by_id["run_crown_internal_media_smoke"]["artifact_qc"]["status"] == "pass"
    assert by_id["run_crown_internal_writer_eval"]["required_files_exist"] is True
    assert by_id["run_crown_internal_writer_eval"]["returned_candidate_artifacts_accepted"] is True
    assert by_id["run_crown_internal_writer_eval"]["acceptance_blocker"] == "none"
    assert by_id["run_crown_internal_media_smoke"]["required_files_exist"] is True
    assert by_id["run_crown_internal_media_smoke"]["returned_candidate_artifacts_accepted"] is True
    assert by_id["run_crown_internal_media_smoke"]["acceptance_blocker"] == "none"
    writer_check_ids = {
        check["id"] for check in by_id["run_crown_internal_writer_eval"]["artifact_qc"]["checks"]
    }
    media_check_ids = {
        check["id"] for check in by_id["run_crown_internal_media_smoke"]["artifact_qc"]["checks"]
    }
    assert "writer_output_contract_passed" in writer_check_ids
    assert "outbound_context_manifest_passed" in writer_check_ids
    assert "outbound_context_manifest_passed" in media_check_ids

    eval_path = eval_dir / "longform_eval_report.yml"
    historical_warning = yaml.safe_load(eval_path.read_text(encoding="utf-8"))
    historical_warning["status"] = "warn"
    historical_warning["layers"].update(
        {
            "L0_fact_source_health": {"status": "pass"},
            "L1_historical_audit": {"status": "warn"},
            "L3_series_scale_simulation": {"status": "pass"},
        }
    )
    historical_warning["layers"]["L2_real_chapter_sample"]["status"] = "pass"
    eval_path.write_text(
        yaml.safe_dump(historical_warning, sort_keys=False), encoding="utf-8"
    )
    warning_report = build_trusted_live_runner_status(
        tmp_path, request_path=request_path
    )
    warning_writer = {item["id"]: item for item in warning_report["items"]}[
        "run_crown_internal_writer_eval"
    ]
    assert warning_writer["status"] == "pass"
    eval_check = {
        check["id"]: check for check in warning_writer["artifact_qc"]["checks"]
    }["longform_eval_passed"]
    assert eval_check["historical_warning_only"] is True

    writer_manifest_path = narrative_run / "outbound_context_manifest_writer.yml"
    unsafe_manifest = yaml.safe_load(writer_manifest_path.read_text(encoding="utf-8"))
    unsafe_manifest["payload"]["secret_pattern_hit_count"] = 1
    writer_manifest_path.write_text(yaml.safe_dump(unsafe_manifest, sort_keys=False), encoding="utf-8")
    rejected = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    rejected_writer = {item["id"]: item for item in rejected["items"]}[
        "run_crown_internal_writer_eval"
    ]
    assert rejected_writer["status"] == "pending"
    assert rejected_writer["acceptance_blocker"] == "artifact_qc_failed"
    assert rejected_writer["pending_reason"] == "trusted_live_artifact_qc_failed"
    assert rejected_writer["returned_candidate_artifacts_accepted"] is False


def test_trusted_live_runner_status_rejects_media_text_handoff_as_generated_asset(tmp_path: Path) -> None:
    media_out = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "media_text_handoff"
    media_out.mkdir(parents=True)
    (media_out / "media_backend_preflight.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "status": "ready", "adapter_kind": "local_grok_cli"}, sort_keys=False),
        encoding="utf-8",
    )
    response = media_out / "grok_cli_response.md"
    response.write_text("GROK_CLI_SMOKE_OK", encoding="utf-8")
    (media_out / "generation_ledger.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "completed_text_handoff",
                "backend": "hermes_grok_oauth",
                "adapter_kind": "local_grok_cli",
                "generated_assets": [],
                "text_artifacts": [str(response)],
                "artifact_generation_verified": False,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "items": [
                    {
                        "id": "run_crown_internal_media_smoke",
                        "command": "./agentlab.sh media-backend-execute --worker grok",
                        "expected_outputs": {
                            "type": "media_live_smoke",
                            "out_dir": "projects/Crown_of_Ash/runs/media_text_handoff",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/media_text_handoff/media_backend_preflight.yml",
                                "projects/Crown_of_Ash/runs/media_text_handoff/generation_ledger.yml",
                            ],
                        },
                    },
                    {
                        "id": "run_crown_internal_writer_eval",
                        "command": "./agentlab.sh narrative-eval run --writer-worker claude_code",
                        "expected_outputs": {"type": "narrative_live_smoke", "required_files": []},
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    media = {item["id"]: item for item in report["items"]}["run_crown_internal_media_smoke"]

    assert media["status"] == "pending"
    assert media["pending_reason"] == "trusted_live_artifact_qc_failed"
    assert media["required_files_exist"] is True
    assert media["returned_candidate_artifacts_accepted"] is False
    assert media["acceptance_blocker"] == "artifact_qc_failed"
    assert media["artifact_qc"]["status"] == "fail"
    failed_checks = {check["id"] for check in media["artifact_qc"]["checks"] if check["status"] == "fail"}
    assert {
        "media_generation_completed",
        "media_artifact_generation_verified",
        "media_generated_assets_recorded",
        "media_generated_assets_exist",
    } <= failed_checks


def test_trusted_live_runner_status_rejects_media_assets_outside_out_dir(tmp_path: Path) -> None:
    media_out = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "media_wrong_dir"
    media_out.mkdir(parents=True)
    production_dir = tmp_path / "projects" / "Crown_of_Ash" / "artifacts" / "media"
    production_dir.mkdir(parents=True)
    generated_asset = production_dir / "crown_scene_001.mp4"
    generated_asset.write_bytes(b"fake media bytes outside trusted out_dir")
    (media_out / "media_backend_preflight.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "status": "ready", "adapter_kind": "local_grok_cli"}, sort_keys=False),
        encoding="utf-8",
    )
    (media_out / "generation_ledger.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "completed",
                "backend": "hermes_grok_oauth",
                "adapter_kind": "local_grok_cli",
                "generated_assets": [str(generated_asset)],
                "artifact_generation_verified": True,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "items": [
                    {
                        "id": "run_crown_internal_media_smoke",
                        "command": "./agentlab.sh media-backend-execute --worker grok",
                        "expected_outputs": {
                            "type": "media_live_smoke",
                            "out_dir": "projects/Crown_of_Ash/runs/media_wrong_dir",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/media_wrong_dir/media_backend_preflight.yml",
                                "projects/Crown_of_Ash/runs/media_wrong_dir/generation_ledger.yml",
                            ],
                        },
                    },
                    {
                        "id": "run_crown_internal_writer_eval",
                        "command": "./agentlab.sh narrative-eval run --writer-worker claude_code",
                        "expected_outputs": {"type": "narrative_live_smoke", "required_files": []},
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    media = {item["id"]: item for item in report["items"]}["run_crown_internal_media_smoke"]

    assert media["status"] == "pending"
    assert media["pending_reason"] == "trusted_live_artifact_qc_failed"
    assert media["required_files_exist"] is True
    assert media["returned_candidate_artifacts_accepted"] is False
    assert media["acceptance_blocker"] == "artifact_qc_failed"
    failed_checks = {check["id"] for check in media["artifact_qc"]["checks"] if check["status"] == "fail"}
    assert "media_generated_assets_under_out_dir" in failed_checks


def test_trusted_live_runner_status_rejects_empty_media_asset_file(tmp_path: Path) -> None:
    media_out = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "media_empty_asset"
    media_out.mkdir(parents=True)
    generated_asset = media_out / "crown_scene_001.mp4"
    generated_asset.write_bytes(b"")
    (media_out / "media_backend_preflight.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "status": "ready", "adapter_kind": "local_grok_cli"}, sort_keys=False),
        encoding="utf-8",
    )
    (media_out / "generation_ledger.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "completed",
                "backend": "hermes_grok_oauth",
                "adapter_kind": "local_grok_cli",
                "generated_assets": [str(generated_asset)],
                "artifact_generation_verified": True,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "items": [
                    {
                        "id": "run_crown_internal_media_smoke",
                        "command": "./agentlab.sh media-backend-execute --worker grok",
                        "expected_outputs": {
                            "type": "media_live_smoke",
                            "out_dir": "projects/Crown_of_Ash/runs/media_empty_asset",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/media_empty_asset/media_backend_preflight.yml",
                                "projects/Crown_of_Ash/runs/media_empty_asset/generation_ledger.yml",
                            ],
                        },
                    },
                    {
                        "id": "run_crown_internal_writer_eval",
                        "command": "./agentlab.sh narrative-eval run --writer-worker claude_code",
                        "expected_outputs": {"type": "narrative_live_smoke", "required_files": []},
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    media = {item["id"]: item for item in report["items"]}["run_crown_internal_media_smoke"]

    assert media["status"] == "pending"
    assert media["pending_reason"] == "trusted_live_artifact_qc_failed"
    failed_checks = {check["id"] for check in media["artifact_qc"]["checks"] if check["status"] == "fail"}
    assert "media_generated_assets_nonempty_files" in failed_checks
    assert "media_generated_assets_exist" not in failed_checks


def test_trusted_live_runner_status_rejects_blank_media_asset_path(tmp_path: Path) -> None:
    media_out = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "media_blank_asset_path"
    media_out.mkdir(parents=True)
    (media_out / "media_backend_preflight.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "status": "ready", "adapter_kind": "local_grok_cli"}, sort_keys=False),
        encoding="utf-8",
    )
    (media_out / "generation_ledger.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "completed",
                "backend": "hermes_grok_oauth",
                "adapter_kind": "local_grok_cli",
                "generated_assets": [""],
                "artifact_generation_verified": True,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "items": [
                    {
                        "id": "run_crown_internal_media_smoke",
                        "command": "./agentlab.sh media-backend-execute --worker grok",
                        "expected_outputs": {
                            "type": "media_live_smoke",
                            "out_dir": "projects/Crown_of_Ash/runs/media_blank_asset_path",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/media_blank_asset_path/media_backend_preflight.yml",
                                "projects/Crown_of_Ash/runs/media_blank_asset_path/generation_ledger.yml",
                            ],
                        },
                    },
                    {
                        "id": "run_crown_internal_writer_eval",
                        "command": "./agentlab.sh narrative-eval run --writer-worker claude_code",
                        "expected_outputs": {"type": "narrative_live_smoke", "required_files": []},
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    media = {item["id"]: item for item in report["items"]}["run_crown_internal_media_smoke"]

    assert media["status"] == "pending"
    assert media["pending_reason"] == "trusted_live_artifact_qc_failed"
    failed_checks = {check["id"] for check in media["artifact_qc"]["checks"] if check["status"] == "fail"}
    assert {
        "media_generated_assets_exist",
        "media_generated_assets_nonempty_files",
        "media_generated_assets_under_out_dir",
    } <= failed_checks


def test_trusted_live_runner_status_rejects_thin_returned_narrative_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "task_narrative_eval_ch01_bad"
    run_dir.mkdir(parents=True)
    (run_dir / "fiction_draft.md").write_text("too short", encoding="utf-8")
    (run_dir / "continuity_ledger.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "chapter": 1, "timeline": {"monotonic": False}}, sort_keys=False),
        encoding="utf-8",
    )
    (run_dir / "state_transition_proposal.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "status": "draft", "requires_user_promotion": False}, sort_keys=False),
        encoding="utf-8",
    )
    (run_dir / "narrative_delivery_receipt.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "status": "fail", "delivery_check": {"valid": False}}, sort_keys=False),
        encoding="utf-8",
    )
    eval_dir = tmp_path / "acceptance_runs" / "narrative_eval" / "Crown_of_Ash" / "suite" / "bad"
    eval_dir.mkdir(parents=True)
    (eval_dir / "longform_eval_report.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "status": "fail"}, sort_keys=False),
        encoding="utf-8",
    )
    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "items": [
                    {
                        "id": "run_crown_internal_writer_eval",
                        "command": "./agentlab.sh narrative-eval run --writer-worker claude_code",
                        "expected_outputs": {
                            "type": "narrative_live_smoke",
                            "run_dir": "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_bad",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_bad/fiction_draft.md",
                                "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_bad/continuity_ledger.yml",
                                "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_bad/state_transition_proposal.yml",
                                "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_bad/narrative_delivery_receipt.yml",
                                "acceptance_runs/narrative_eval/Crown_of_Ash/suite/bad/longform_eval_report.yml",
                            ],
                        },
                    },
                    {
                        "id": "run_crown_internal_media_smoke",
                        "command": "./agentlab.sh media-backend-execute --worker grok",
                        "expected_outputs": {"type": "media_live_smoke", "required_files": []},
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    writer = {item["id"]: item for item in report["items"]}["run_crown_internal_writer_eval"]

    assert writer["status"] == "pending"
    assert writer["pending_reason"] == "trusted_live_artifact_qc_failed"
    assert writer["missing"] == []
    assert writer["artifact_qc"]["status"] == "fail"
    assert report["artifact_qc_failures"] == [
        {
            "id": "run_crown_internal_writer_eval",
            "failed_checks": [
                "fiction_draft_substantive",
                "fiction_draft_multiline_chapter",
                "delivery_receipt_passed",
                "state_transition_candidate_only",
                "state_transition_events_present",
                "continuity_timeline_monotonic",
                "longform_eval_passed",
                "longform_eval_matches_run_dir",
            ],
            "next_action": "review_returned_candidate_artifacts_or_rerun_trusted_live_command",
        }
    ]
    failed_checks = {check["id"] for check in writer["artifact_qc"]["checks"] if check["status"] == "fail"}
    assert {
        "fiction_draft_substantive",
        "fiction_draft_multiline_chapter",
        "delivery_receipt_passed",
        "state_transition_candidate_only",
        "state_transition_events_present",
        "continuity_timeline_monotonic",
        "longform_eval_passed",
        "longform_eval_matches_run_dir",
    } <= failed_checks


def test_trusted_live_runner_status_rejects_longform_eval_for_different_run_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "task_narrative_eval_ch01_current"
    run_dir.mkdir(parents=True)
    chapter_text = "\n\n".join(
        [
            "# Chapter 1",
            "Kael crossed the ash road before sunrise and counted each bell as if it were a debt.",
            "The old watchtower leaned over the valley, its windows black with a smoke no rain could clean.",
            "Mara waited beside the broken milestone with a ledger wrapped in oilcloth and a knife in her boot.",
            "They had both promised not to return to Greyvale, which made the distant bells sound almost amused.",
            "When the patrol lanterns appeared, Kael felt the brand under his sleeve answer with a pulse of heat.",
            "Mara did not ask what it meant; she only tore one page from the ledger and fed it to the wind.",
            "The page burned blue before it touched the mud, and every horse on the road screamed.",
            "By noon the valley knew a forbidden name had been spoken, though no mouth would confess it.",
            "Kael understood then that the war had found him before he had found a side.",
        ]
    )
    (run_dir / "fiction_draft.md").write_text((chapter_text + "\n\n") * 2, encoding="utf-8")
    (run_dir / "continuity_ledger.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "chapter": 1, "timeline": {"monotonic": True}}, sort_keys=False),
        encoding="utf-8",
    )
    (run_dir / "state_transition_proposal.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "candidate",
                "requires_user_promotion": True,
                "events": [{"event_type": "chapter_state_change", "scope": "candidate_only"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "narrative_delivery_receipt.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "status": "pass", "delivery_check": {"valid": True}}, sort_keys=False),
        encoding="utf-8",
    )
    eval_dir = tmp_path / "acceptance_runs" / "narrative_eval" / "Crown_of_Ash" / "suite" / "wrong"
    eval_dir.mkdir(parents=True)
    (eval_dir / "longform_eval_report.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "pass",
                "layers": {
                    "L2_real_chapter_sample": {
                        "chapters": [
                            {
                                "chapter": 1,
                                "run_dir": "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_previous",
                            }
                        ]
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "items": [
                    {
                        "id": "run_crown_internal_writer_eval",
                        "command": "./agentlab.sh narrative-eval run --writer-worker claude_code",
                        "expected_outputs": {
                            "type": "narrative_live_smoke",
                            "run_dir": "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_current",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_current/fiction_draft.md",
                                "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_current/continuity_ledger.yml",
                                "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_current/state_transition_proposal.yml",
                                "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_current/narrative_delivery_receipt.yml",
                                "acceptance_runs/narrative_eval/Crown_of_Ash/suite/wrong/longform_eval_report.yml",
                            ],
                        },
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    writer = {item["id"]: item for item in report["items"]}["run_crown_internal_writer_eval"]
    failed_checks = {check["id"]: check for check in writer["artifact_qc"]["checks"] if check["status"] == "fail"}

    assert writer["status"] == "pending"
    assert writer["pending_reason"] == "trusted_live_artifact_qc_failed"
    assert writer["acceptance_blocker"] == "artifact_qc_failed"
    assert set(failed_checks) == {"longform_eval_matches_run_dir"}
    assert failed_checks["longform_eval_matches_run_dir"]["expected_run_dir"].endswith(
        "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_current"
    )
    assert failed_checks["longform_eval_matches_run_dir"]["reported_run_dirs"] == [
        "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_previous"
    ]


def test_trusted_live_runner_status_classifies_agy_localhost_bind_denied(tmp_path: Path) -> None:
    run_dir = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "task_narrative_eval_ch01_test"
    run_dir.mkdir(parents=True)
    (run_dir / "live_generation_error.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "blocked",
                "agent": "Writer",
                "result_status": "blocked_user_decision",
                "provider": "agentlab-cli-executor",
                "model": "agy",
                "error": (
                    "CLI agent exited 1. stderr: CLI failed to start - listen tcp "
                    "127.0.0.1:0: bind: operation not permitted"
                ),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "items": [
                    {
                        "id": "run_crown_internal_writer_eval",
                        "command": "./agentlab.sh narrative-eval run --writer-worker agy",
                        "expected_outputs": {
                            "type": "narrative_live_smoke",
                            "run_dir": "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_test",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_test/fiction_draft.md"
                            ],
                        },
                    },
                    {
                        "id": "run_crown_internal_media_smoke",
                        "command": "./agentlab.sh media-backend-execute --worker grok",
                        "expected_outputs": {
                            "type": "media_live_smoke",
                            "out_dir": "projects/Crown_of_Ash/runs/media_out",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/media_out/generation_ledger.yml"
                            ],
                        },
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    writer = {item["id"]: item for item in report["items"]}["run_crown_internal_writer_eval"]

    assert writer["pending_reason"] == "historical_frontdesk_sandbox_agy_localhost_bind_denied"
    assert writer["next_action"] == (
        "regenerate_trusted_writer_request_for_claude_writer_then_rerun_trusted_writer_smoke"
    )
    assert "local language-server bind" in writer["evidence_interpretation"]


def test_trusted_live_runner_status_keeps_old_agy_smoke_as_historical_evidence(tmp_path: Path) -> None:
    run_dir = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "task_narrative_eval_ch01_test"
    run_dir.mkdir(parents=True)
    error_path = run_dir / "live_generation_error.yml"
    error_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "blocked",
                "agent": "Writer",
                "result_status": "blocked_user_decision",
                "provider": "agentlab-cli-executor",
                "model": "agy",
                "error": (
                    "CLI agent exited 1. stderr: CLI failed to start - listen tcp "
                    "127.0.0.1:0: bind: operation not permitted"
                ),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    smoke_dir = tmp_path / "acceptance_runs" / "agentlab_capability_acceptance"
    smoke_dir.mkdir(parents=True)
    smoke_path = smoke_dir / "agy_cli_session_smoke.yml"
    smoke_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "pass",
                "worker": "agy",
                "reason": None,
                "command_available": True,
                "command_path": "/usr/local/bin/agy",
                "created_at": "2026-07-08T00:28:24+00:00",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    os.utime(error_path, (1_000_000, 1_000_000))
    os.utime(smoke_path, (1_000_100, 1_000_100))
    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "items": [
                    {
                        "id": "run_crown_internal_writer_eval",
                        "command": "./agentlab.sh narrative-eval run --writer-worker agy",
                        "expected_outputs": {
                            "type": "narrative_live_smoke",
                            "run_dir": "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_test",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/task_narrative_eval_ch01_test/fiction_draft.md"
                            ],
                        },
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    writer = {item["id"]: item for item in report["items"]}["run_crown_internal_writer_eval"]

    assert writer["pending_reason"] == "historical_frontdesk_sandbox_agy_localhost_bind_denied"
    assert writer["next_action"] == (
        "regenerate_trusted_writer_request_for_claude_writer_then_rerun_trusted_writer_smoke"
    )
    assert writer["observed_error"]["historical_writer_route"] == "agy"
    assert writer["observed_error"]["historical_writer_route_is_current"] is False
    assert writer["observed_error"]["historical_session_smoke_status"] == "pass"
    assert "stale_after_session_health_pass" not in writer["observed_error"]
    assert report["stale_items"] == []


def test_trusted_live_runner_status_treats_media_timeout_ledger_as_pending(tmp_path: Path) -> None:
    out_dir = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "media_out"
    out_dir.mkdir(parents=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "media_generation_backends.yml").write_text(
        yaml.safe_dump(
            {
                "backends": {
                    "hermes_grok_oauth": {
                        "command_contract": {
                            "oauth_smoke": "grok --oauth -p <prompt> --output-format plain --max-turns 3"
                        }
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (out_dir / "media_backend_preflight.yml").write_text(
        yaml.safe_dump({"status": "ready"}, sort_keys=False),
        encoding="utf-8",
    )
    (out_dir / "media_backend_payload_plan.yml").write_text(
        yaml.safe_dump(
            {
                "args": [
                    "grok",
                    "--oauth",
                    "-p",
                    "non-private test prompt",
                    "--output-format",
                    "plain",
                    "--max-turns",
                    "1",
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (out_dir / "generation_ledger.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "provider_timeout",
                "backend": "hermes_grok_oauth",
                "adapter_kind": "grok_cli_oauth",
                "block_reason": "grok_cli_oauth_timeout",
                "timeout_seconds": 60,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "items": [
                    {
                        "id": "run_crown_internal_writer_eval",
                        "command": "./agentlab.sh narrative-eval run --writer-worker claude_code",
                        "expected_outputs": {
                            "type": "narrative_live_smoke",
                            "run_dir": "projects/Crown_of_Ash/runs/writer_out",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/writer_out/fiction_draft.md"
                            ],
                        },
                    },
                    {
                        "id": "run_crown_internal_media_smoke",
                        "command": "./agentlab.sh media-backend-execute --worker grok",
                        "expected_outputs": {
                            "type": "media_live_smoke",
                            "out_dir": "projects/Crown_of_Ash/runs/media_out",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/media_out/media_backend_preflight.yml",
                                "projects/Crown_of_Ash/runs/media_out/generation_ledger.yml",
                            ],
                        },
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    media = {item["id"]: item for item in report["items"]}["run_crown_internal_media_smoke"]

    assert media["status"] == "pending"
    assert media["missing"] == []
    assert media["required_files_exist"] is True
    assert media["returned_candidate_artifacts_accepted"] is False
    assert media["acceptance_blocker"] == "observed_execution_error_or_stale_ledger"
    assert media["observed_error"]["status"] == "local_cli_timeout"
    assert media["observed_error"]["legacy_status"] == "provider_timeout"
    assert media["observed_error"]["error"] == "grok_cli_timeout"
    assert "returncode" not in media["observed_error"]
    assert media["observed_error"]["stale_after_contract_update"] is True
    assert media["observed_error"]["executed_max_turns"] == "1"
    assert media["observed_error"]["current_max_turns"] == "3"
    assert media["pending_reason"] == "stale_live_evidence_after_backend_contract_update"
    assert media["next_action"] == "rerun_trusted_media_smoke_with_current_backend_contract"
    assert report["stale_items"] == [
        {
            "id": "run_crown_internal_media_smoke",
            "stale_reason": "media_backend_payload_plan_no_longer_matches_current_backend_contract",
            "executed_max_turns": "1",
            "current_max_turns": "3",
            "next_action": "rerun_trusted_media_smoke_with_current_backend_contract",
        }
    ]


def test_trusted_live_runner_status_classifies_current_grok_settings_fetch_failure(tmp_path: Path) -> None:
    out_dir = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "media_out"
    out_dir.mkdir(parents=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "media_generation_backends.yml").write_text(
        yaml.safe_dump(
            {
                "backends": {
                    "hermes_grok_oauth": {
                        "command_contract": {
                            "oauth_smoke": "grok --oauth -p <prompt> --output-format plain --max-turns 3"
                        }
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (out_dir / "media_backend_preflight.yml").write_text(
        yaml.safe_dump({"status": "ready"}, sort_keys=False),
        encoding="utf-8",
    )
    (out_dir / "media_backend_payload_plan.yml").write_text(
        yaml.safe_dump(
            {
                "args": [
                    "grok",
                    "--oauth",
                    "-p",
                    "non-private test prompt",
                    "--output-format",
                    "plain",
                    "--max-turns",
                    "3",
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (out_dir / "generation_ledger.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "provider_timeout",
                "backend": "hermes_grok_oauth",
                "adapter_kind": "grok_cli_oauth",
                "block_reason": "grok_cli_oauth_timeout",
                "timeout_seconds": 60,
                "stderr_excerpt": "ERROR Settings fetch failed after 3 attempts",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    smoke_dir = tmp_path / "acceptance_runs" / "agentlab_capability_acceptance"
    smoke_dir.mkdir(parents=True)
    (smoke_dir / "grok_cli_session_smoke.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "backend_id": "hermes_grok_oauth",
                "adapter_kind": "grok_cli_oauth",
                "status": "blocked",
                "reason": "grok_cli_settings_fetch_failed",
                "created_at": "2026-07-07T23:33:09+00:00",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "items": [
                    {
                        "id": "run_crown_internal_media_smoke",
                        "command": "./agentlab.sh media-backend-execute --worker grok",
                        "expected_outputs": {
                            "type": "media_live_smoke",
                            "out_dir": "projects/Crown_of_Ash/runs/media_out",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/media_out/media_backend_preflight.yml",
                                "projects/Crown_of_Ash/runs/media_out/generation_ledger.yml",
                            ],
                        },
                    },
                    {
                        "id": "run_crown_internal_writer_eval",
                        "command": "./agentlab.sh narrative-eval run --writer-worker claude_code",
                        "expected_outputs": {
                            "type": "narrative_live_smoke",
                            "run_dir": "projects/Crown_of_Ash/runs/writer_out",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/writer_out/fiction_draft.md"
                            ],
                        },
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    media = {item["id"]: item for item in report["items"]}["run_crown_internal_media_smoke"]

    assert media["status"] == "pending"
    assert media["missing"] == []
    assert media["observed_error"]["error"] == "grok_cli_settings_fetch_failed"
    assert media["observed_error"]["settings_fetch_failed"] is True
    assert "returncode" not in media["observed_error"]
    assert media["observed_error"]["backend_contract_current"] is True
    assert media["observed_error"]["executed_max_turns"] == "3"
    assert media["observed_error"]["current_max_turns"] == "3"
    assert media["observed_error"]["current_session_smoke_status"] == "blocked"
    assert media["observed_error"]["current_session_smoke_reason"] == "grok_cli_settings_fetch_failed"
    assert media["observed_error"]["current_session_smoke_path"].endswith("grok_cli_session_smoke.yml")
    assert media["pending_reason"] == "grok_cli_settings_fetch_failed_in_live_smoke"
    assert media["next_action"] == "rerun_same_agentlab_command_from_user_terminal_with_local_grok_session"
    assert media["cli_contract_health"]["worker"] == "grok"
    assert media["cli_contract_health"]["contract_mode"] == "non_interactive_prompt_contract"
    assert media["cli_contract_health"]["failure_scope"] == "local_grok_session_health"
    assert media["cli_contract_health"]["settings_fetch_failed"] is True
    assert media["cli_contract_health"]["current_session_smoke_status"] == "blocked"
    assert media["cli_contract_health"]["current_session_smoke_path"].endswith("grok_cli_session_smoke.yml")
    assert media["cli_contract_health"]["status"] in {
        "entrypoint_available_contract_failed",
        "entrypoint_unverified_contract_failed",
    }
    assert media["cli_contract_health"]["interactive_entrypoint_only_is_not_task_contract_proof"] is True
    assert report["stale_items"] == []


def test_trusted_live_runner_status_classifies_current_grok_transport_failure(tmp_path: Path) -> None:
    out_dir = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "media_out"
    out_dir.mkdir(parents=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "media_generation_backends.yml").write_text(
        yaml.safe_dump(
            {
                "backends": {
                    "hermes_grok_oauth": {
                        "command_contract": {
                            "session_smoke": "grok -p <prompt> --output-format plain --max-turns 3"
                        }
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (out_dir / "media_backend_preflight.yml").write_text(
        yaml.safe_dump({"status": "ready"}, sort_keys=False),
        encoding="utf-8",
    )
    (out_dir / "media_backend_payload_plan.yml").write_text(
        yaml.safe_dump(
            {
                "args": [
                    "grok",
                    "-p",
                    "non-private test prompt",
                    "--output-format",
                    "plain",
                    "--max-turns",
                    "3",
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (out_dir / "generation_ledger.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "local_cli_error",
                "backend": "hermes_grok_oauth",
                "adapter_kind": "local_grok_cli",
                "block_reason": "grok_cli_transport_or_proxy_failed",
                "settings_fetch_failed": True,
                "transport_failure_marker_present": True,
                "stderr_excerpt": (
                    "ERROR Settings fetch failed after 3 attempts\n"
                    "request error: error sending request for url (https://cli-chat-proxy.grok.com/v1/responses)"
                ),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "items": [
                    {
                        "id": "run_crown_internal_media_smoke",
                        "command": "./agentlab.sh media-backend-execute --worker grok",
                        "expected_outputs": {
                            "type": "media_live_smoke",
                            "out_dir": "projects/Crown_of_Ash/runs/media_out",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/media_out/media_backend_preflight.yml",
                                "projects/Crown_of_Ash/runs/media_out/generation_ledger.yml",
                            ],
                        },
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    media = {item["id"]: item for item in report["items"]}["run_crown_internal_media_smoke"]

    assert media["status"] == "pending"
    assert media["observed_error"]["error"] == "grok_cli_transport_or_proxy_failed"
    assert media["observed_error"]["settings_fetch_failed"] is True
    assert media["observed_error"]["transport_failure_marker_present"] is True
    assert media["pending_reason"] == "grok_cli_transport_or_proxy_failed_in_live_smoke"
    assert media["next_action"] == "fix_local_network_or_proxy_for_grok_cli_then_rerun_trusted_media_smoke"
    assert media["cli_contract_health"]["failure_scope"] == "local_grok_network_or_proxy"
    assert media["cli_contract_health"]["transport_failure_marker_present"] is True
    assert media["cli_contract_health"]["status"] in {
        "entrypoint_available_transport_failed",
        "entrypoint_unverified_transport_failed",
    }


def test_trusted_live_runner_status_marks_old_grok_settings_failure_stale_after_session_pass(tmp_path: Path) -> None:
    out_dir = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "media_out"
    out_dir.mkdir(parents=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "media_generation_backends.yml").write_text(
        yaml.safe_dump(
            {
                "backends": {
                    "hermes_grok_oauth": {
                        "command_contract": {
                            "oauth_smoke": "grok -p <prompt> --output-format plain --max-turns 3"
                        }
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (out_dir / "media_backend_preflight.yml").write_text(
        yaml.safe_dump({"status": "ready"}, sort_keys=False),
        encoding="utf-8",
    )
    (out_dir / "media_backend_payload_plan.yml").write_text(
        yaml.safe_dump(
            {
                "args": [
                    "grok",
                    "-p",
                    "non-private test prompt",
                    "--output-format",
                    "plain",
                    "--max-turns",
                    "3",
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (out_dir / "generation_ledger.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "provider_timeout",
                "backend": "hermes_grok_oauth",
                "adapter_kind": "grok_cli_oauth",
                "block_reason": "grok_cli_oauth_timeout",
                "timeout_seconds": 60,
                "stderr_excerpt": "ERROR Settings fetch failed after 3 attempts",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    smoke_dir = tmp_path / "acceptance_runs" / "agentlab_capability_acceptance"
    smoke_dir.mkdir(parents=True)
    (smoke_dir / "grok_cli_session_smoke.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "backend_id": "hermes_grok_oauth",
                "adapter_kind": "grok_cli_oauth",
                "status": "pass",
                "created_at": "2026-07-07T22:32:04+00:00",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "items": [
                    {
                        "id": "run_crown_internal_media_smoke",
                        "command": "./agentlab.sh media-backend-execute --worker grok",
                        "expected_outputs": {
                            "type": "media_live_smoke",
                            "out_dir": "projects/Crown_of_Ash/runs/media_out",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/media_out/media_backend_preflight.yml",
                                "projects/Crown_of_Ash/runs/media_out/generation_ledger.yml",
                            ],
                        },
                    },
                    {
                        "id": "run_crown_internal_writer_eval",
                        "command": "./agentlab.sh narrative-eval run --writer-worker claude_code",
                        "expected_outputs": {
                            "type": "narrative_live_smoke",
                            "run_dir": "projects/Crown_of_Ash/runs/writer_out",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/writer_out/fiction_draft.md"
                            ],
                        },
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    media = {item["id"]: item for item in report["items"]}["run_crown_internal_media_smoke"]

    assert media["status"] == "pending"
    assert media["missing"] == []
    assert media["observed_error"]["settings_fetch_failed"] is True
    assert media["observed_error"]["stale_after_session_health_pass"] is True
    assert media["observed_error"]["current_session_smoke_status"] == "pass"
    assert media["pending_reason"] == "media_live_artifacts_not_rerun_after_grok_session_pass"
    assert media["next_action"] == "rerun_trusted_media_smoke_with_current_grok_session"
    assert media["cli_contract_health"]["status"] == "session_contract_now_passes"
    assert media["cli_contract_health"]["failure_scope"] == "stale_media_backend_ledger"
    assert report["stale_items"] == [
        {
            "id": "run_crown_internal_media_smoke",
            "stale_reason": "current_grok_cli_session_smoke_passed_after_media_ledger",
            "executed_max_turns": "3",
            "current_max_turns": "3",
            "next_action": "rerun_trusted_media_smoke_with_current_grok_session",
            "current_session_smoke_status": "pass",
            "current_session_smoke_path": str(smoke_dir / "grok_cli_session_smoke.yml"),
        }
    ]


def test_trusted_live_runner_status_marks_old_grok_transport_failure_stale_after_session_pass(tmp_path: Path) -> None:
    out_dir = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "media_out"
    out_dir.mkdir(parents=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "media_generation_backends.yml").write_text(
        yaml.safe_dump(
            {
                "backends": {
                    "hermes_grok_oauth": {
                        "command_contract": {
                            "session_smoke": "grok -p <prompt> --output-format plain --max-turns 3"
                        }
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (out_dir / "media_backend_preflight.yml").write_text(
        yaml.safe_dump({"status": "ready"}, sort_keys=False),
        encoding="utf-8",
    )
    (out_dir / "media_backend_payload_plan.yml").write_text(
        yaml.safe_dump(
            {
                "args": [
                    "grok",
                    "-p",
                    "non-private test prompt",
                    "--output-format",
                    "plain",
                    "--max-turns",
                    "3",
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (out_dir / "generation_ledger.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "local_cli_error",
                "backend": "hermes_grok_oauth",
                "adapter_kind": "local_grok_cli",
                "block_reason": "grok_cli_transport_or_proxy_failed",
                "transport_failure_marker_present": True,
                "stderr_excerpt": "request error: error sending request for url",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    smoke_dir = tmp_path / "acceptance_runs" / "agentlab_capability_acceptance"
    smoke_dir.mkdir(parents=True)
    (smoke_dir / "grok_cli_session_smoke.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "backend_id": "hermes_grok_oauth",
                "adapter_kind": "local_grok_cli",
                "status": "pass",
                "created_at": "2026-07-09T01:55:26+00:00",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "items": [
                    {
                        "id": "run_crown_internal_media_smoke",
                        "command": "./agentlab.sh media-backend-execute --worker grok",
                        "expected_outputs": {
                            "type": "media_live_smoke",
                            "out_dir": "projects/Crown_of_Ash/runs/media_out",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/media_out/media_backend_preflight.yml",
                                "projects/Crown_of_Ash/runs/media_out/generation_ledger.yml",
                            ],
                        },
                    },
                    {
                        "id": "run_crown_internal_writer_eval",
                        "command": "./agentlab.sh narrative-eval run --writer-worker claude_code",
                        "expected_outputs": {
                            "type": "narrative_live_smoke",
                            "run_dir": "projects/Crown_of_Ash/runs/writer_out",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/writer_out/fiction_draft.md"
                            ],
                        },
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    media = {item["id"]: item for item in report["items"]}["run_crown_internal_media_smoke"]

    assert media["status"] == "pending"
    assert media["missing"] == []
    assert media["observed_error"]["error"] == "grok_cli_transport_or_proxy_failed"
    assert media["observed_error"]["transport_failure_marker_present"] is True
    assert media["observed_error"]["stale_after_session_health_pass"] is True
    assert media["observed_error"]["current_session_smoke_status"] == "pass"
    assert media["pending_reason"] == "media_live_artifacts_not_rerun_after_grok_session_pass"
    assert media["next_action"] == "rerun_trusted_media_smoke_with_current_grok_session"
    assert media["cli_contract_health"]["status"] == "session_contract_now_passes"
    assert media["cli_contract_health"]["failure_scope"] == "stale_media_backend_ledger"
    assert report["stale_items"] == [
        {
            "id": "run_crown_internal_media_smoke",
            "stale_reason": "current_grok_cli_session_smoke_passed_after_media_ledger",
            "executed_max_turns": "3",
            "current_max_turns": "3",
            "next_action": "rerun_trusted_media_smoke_with_current_grok_session",
            "current_session_smoke_status": "pass",
            "current_session_smoke_path": str(smoke_dir / "grok_cli_session_smoke.yml"),
        }
    ]


def test_trusted_live_runner_status_treats_old_grok_oauth_flag_ledger_as_stale(tmp_path: Path) -> None:
    out_dir = tmp_path / "projects" / "Crown_of_Ash" / "runs" / "media_out"
    out_dir.mkdir(parents=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "media_generation_backends.yml").write_text(
        yaml.safe_dump(
            {
                "backends": {
                    "hermes_grok_oauth": {
                        "command_contract": {
                            "oauth_smoke": "grok -p <prompt> --output-format plain --max-turns 3"
                        }
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (out_dir / "media_backend_preflight.yml").write_text(
        yaml.safe_dump({"status": "ready"}, sort_keys=False),
        encoding="utf-8",
    )
    (out_dir / "media_backend_payload_plan.yml").write_text(
        yaml.safe_dump(
            {
                "args": [
                    "grok",
                    "--oauth",
                    "-p",
                    "non-private test prompt",
                    "--output-format",
                    "plain",
                    "--max-turns",
                    "3",
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (out_dir / "generation_ledger.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "provider_timeout",
                "backend": "hermes_grok_oauth",
                "adapter_kind": "grok_cli_oauth",
                "block_reason": "grok_cli_oauth_timeout",
                "timeout_seconds": 60,
                "stderr_excerpt": "ERROR Settings fetch failed after 3 attempts",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    request_path = tmp_path / "trusted_live_runner_request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "status": "ready_for_trusted_runner",
                "items": [
                    {
                        "id": "run_crown_internal_media_smoke",
                        "command": "./agentlab.sh media-backend-execute --worker grok",
                        "expected_outputs": {
                            "type": "media_live_smoke",
                            "out_dir": "projects/Crown_of_Ash/runs/media_out",
                            "required_files": [
                                "projects/Crown_of_Ash/runs/media_out/media_backend_preflight.yml",
                                "projects/Crown_of_Ash/runs/media_out/generation_ledger.yml",
                            ],
                        },
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = build_trusted_live_runner_status(tmp_path, request_path=request_path)
    media = {item["id"]: item for item in report["items"]}["run_crown_internal_media_smoke"]

    assert media["observed_error"]["settings_fetch_failed"] is True
    assert media["observed_error"]["stale_after_contract_update"] is True
    assert media["observed_error"]["stale_reason"] == (
        "media_backend_payload_plan_no_longer_matches_current_backend_command_contract"
    )
    assert media["observed_error"]["executed_command_shape"] == (
        "grok --oauth -p <prompt> --output-format plain --max-turns 3"
    )
    assert media["observed_error"]["current_command_shape"] == (
        "grok -p <prompt> --output-format plain --max-turns 3"
    )
    assert media["pending_reason"] == "stale_live_evidence_after_backend_contract_update"
    assert report["stale_items"][0]["stale_reason"] == (
        "media_backend_payload_plan_no_longer_matches_current_backend_command_contract"
    )


def test_trusted_live_runner_status_cli_writes_yaml(tmp_path: Path) -> None:
    out = tmp_path / "trusted_live_runner_status.yml"

    result = runner.invoke(app, ["trusted-live-runner-status", "--out", str(out)])

    assert result.exit_code == 0
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["report_type"] == "agentlab_trusted_live_runner_status"
    assert report["status"] in {"pending", "pass"}
