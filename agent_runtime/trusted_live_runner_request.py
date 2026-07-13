"""Build a trusted-runner request for role-session acceptance smokes.

This module deliberately does not execute the commands it writes. It converts
the frontdesk live handoff into a durable request that can be picked up by a
trusted AgentLab runner or a user-operated terminal outside the Codex frontdesk
approval boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import shlex
from typing import Any

import yaml

try:
    from agent_runtime.report_sanitizer import write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import write_report_yaml


TRUSTED_RUNNER_ENV = "AGENTLAB_TRUSTED_LIVE_RUNNER=1"
ROLE_SESSION_APPROVAL_ENV = "AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1"
ACCEPTANCE_SMOKE_KIND = "private_role_session_acceptance_smoke"
ACCEPTANCE_SMOKE_LABEL = "private role-session acceptance smoke"


def _acceptance_smoke_terminology() -> dict[str, Any]:
    return {
        "canonical_kind": ACCEPTANCE_SMOKE_KIND,
        "canonical_label": ACCEPTANCE_SMOKE_LABEL,
        "legacy_terms": ["private live smoke", "private live-smoke", "live-smoke"],
        "meaning": (
            "A minimal trusted-runner acceptance run that loads private project context "
            "through the configured AgentLab role-session worker and returns run-local "
            "candidate artifacts for structural QC."
        ),
        "not_a_default_production_workflow": True,
    }


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _contains_secret_text(data: dict[str, Any]) -> bool:
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    return "sk-" in rendered or "test-key" in rendered


def _request_id() -> str:
    return datetime.now(timezone.utc).strftime("trusted_live_%Y%m%d_%H%M%S")


def _materialize_command(command: str, request_id: str, item_id: str) -> str:
    suffix = "writer" if "writer" in item_id else "media" if "media" in item_id else "run"
    return (
        command.replace("<internal_live_run_id>", f"{request_id}_{suffix}")
        .replace("<approved_live_run_id>", f"{request_id}_{suffix}")
        .replace("<id>", f"{request_id}_{suffix}")
    )


def _current_handoff_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize retained generated handoffs to the current Writer route."""
    if item.get("id") != "run_crown_internal_writer_eval":
        return item
    current = dict(item)
    current["assigned_worker"] = "claude_code"
    for key in ("agentlab_command", "agentlab_command_after_approval"):
        if current.get(key):
            current[key] = str(current[key]).replace(
                "--writer-worker agy",
                "--writer-worker claude_code",
            )
    return current


def _extract_option(argv: list[str], option: str) -> str | None:
    try:
        idx = argv.index(option)
    except ValueError:
        return None
    if idx + 1 >= len(argv):
        return None
    return argv[idx + 1]


def _expected_outputs(command: str, item_id: str) -> dict[str, Any]:
    try:
        argv = shlex.split(command)
    except ValueError:
        argv = []
    if "narrative-eval" in argv and "run" in argv:
        project = _extract_option(argv, "--project") or "Crown_of_Ash"
        suite = _extract_option(argv, "--suite") or "crown_live_single_chapter_probe_20260707"
        timestamp = _extract_option(argv, "--timestamp") or "unknown"
        chapter = "ch01"
        run_dir = f"projects/{project}/runs/task_narrative_eval_{chapter}_{timestamp}"
        acceptance_dir = f"acceptance_runs/narrative_eval/{project}/{suite}/{timestamp}"
        return {
            "type": "narrative_live_smoke",
            "run_dir": run_dir,
            "required_files": [
                f"{run_dir}/fiction_draft.md",
                f"{run_dir}/continuity_ledger.yml",
                f"{run_dir}/state_transition_proposal.yml",
                f"{run_dir}/narrative_delivery_receipt.yml",
                f"{run_dir}/outbound_context_manifest_writer.yml",
                f"{run_dir}/writer_output_contract.yml",
                f"{acceptance_dir}/longform_eval_report.yml",
            ],
            "candidate_only": True,
        }
    if "media-backend-execute" in argv:
        out_dir = _extract_option(argv, "--out-dir") or ""
        return {
            "type": "media_live_smoke",
            "out_dir": out_dir,
            "required_files": [
                f"{out_dir}/media_backend_preflight.yml",
                f"{out_dir}/generation_ledger.yml",
                f"{out_dir}/outbound_context_manifest_media.yml",
            ],
            "candidate_only": True,
            "final_artifact_allowed": False,
        }
    return {"type": "unknown", "item_id": item_id, "required_files": []}


def _status_command(request_path: Path, status_path: Path) -> str:
    return (
        "./agentlab.sh trusted-live-runner-status "
        f"--request {shlex.quote(str(request_path))} "
        f"--out {shlex.quote(str(status_path))}"
    )


def _preflight_command(request_path: Path, preflight_path: Path) -> str:
    return (
        "./agentlab.sh trusted-live-runner-preflight "
        f"--request {shlex.quote(str(request_path))} "
        f"--out {shlex.quote(str(preflight_path))}"
    )


def _collect_command(request_path: Path, collect_path: Path, item_id: str | None = None) -> str:
    command = (
        "./agentlab.sh trusted-live-runner-collect "
        f"--request {shlex.quote(str(request_path))} "
        f"--out {shlex.quote(str(collect_path))}"
    )
    if item_id:
        command += f" --item {shlex.quote(item_id)}"
    return command


def _trusted_script_command(script_path: Path, *args: str) -> str:
    parts = [TRUSTED_RUNNER_ENV, shlex.quote(str(script_path))]
    parts.extend(shlex.quote(arg) for arg in args)
    return " ".join(parts)


def _approved_role_session_script_command(script_path: Path, *args: str) -> str:
    parts = [TRUSTED_RUNNER_ENV, ROLE_SESSION_APPROVAL_ENV, shlex.quote(str(script_path))]
    parts.extend(shlex.quote(arg) for arg in args)
    return " ".join(parts)


def _session_health_probe_commands() -> list[str]:
    return [
        "./agentlab.sh worker-invocation-probe --worker claude_writer > acceptance_runs/agentlab_capability_acceptance/claude_writer_session_probe.yml",
        "./agentlab.sh grok-cli-smoke --live --out acceptance_runs/agentlab_capability_acceptance/grok_cli_session_smoke.yml",
        "./agentlab.sh internal-live-readiness --out acceptance_runs/agentlab_capability_acceptance/internal_live_readiness.yml",
    ]


def _local_runner_package(
    script_path: Path,
    request_path: Path,
    status_path: Path,
    preflight_path: Path,
    collect_path: Path,
) -> dict[str, Any]:
    return {
        "entrypoint": str(script_path),
        "request_path": str(request_path),
        "status_path": str(status_path),
        "preflight_report_path": str(preflight_path),
        "collect_report_path": str(collect_path),
        "preflight_commands": [
            "test -x ./agentlab.sh",
            "command -v claude",
            "command -v hermes",
        ],
        "preflight_only_command": f"{shlex.quote(str(script_path))} --preflight-only",
        "preflight_report_command": _preflight_command(request_path, preflight_path),
        "trusted_runner_env_required": TRUSTED_RUNNER_ENV,
        "role_session_acceptance_approval_env_required": ROLE_SESSION_APPROVAL_ENV,
        "acceptance_smoke_kind": ACCEPTANCE_SMOKE_KIND,
        "acceptance_smoke_label": ACCEPTANCE_SMOKE_LABEL,
        "session_health_only_command": _trusted_script_command(script_path, "--session-health-only"),
        "selective_run_supported": True,
        "selective_run_examples": {
            "writer_only": _approved_role_session_script_command(
                script_path,
                "--only",
                "run_crown_internal_writer_eval",
            ),
            "media_only": _approved_role_session_script_command(
                script_path,
                "--only",
                "run_crown_internal_media_smoke",
            ),
        },
        "selective_run_executes_session_health_checks": True,
        "selective_run_requires_selected_item_pass": True,
        "recommended_pre_run_session_health_commands": _session_health_probe_commands(),
        "post_run_status_command": _status_command(request_path, status_path),
        "post_run_collect_command": _collect_command(request_path, collect_path),
        "post_run_selected_collect_commands": {
            "writer_only": _collect_command(
                request_path,
                collect_path.with_name("trusted_live_runner_collect_writer.yml"),
                "run_crown_internal_writer_eval",
            ),
            "media_only": _collect_command(
                request_path,
                collect_path.with_name("trusted_live_runner_collect_media.yml"),
                "run_crown_internal_media_smoke",
            ),
        },
        "continues_after_item_failure": True,
        "refreshes_status_after_run": True,
        "refreshes_acceptance_after_run": True,
        "full_run_executes_session_health_checks": True,
        "session_health_gate_before_private_context": True,
        "approval_gate_before_private_context": True,
        "exact_outbound_context_manifest_required": True,
        "writer_sealed_context_required": True,
        "media_prompt_digest_required": True,
        "secret_pattern_gate_before_provider_call": True,
        "full_run_requires_trusted_status_pass": True,
        "frontdesk_observes_only": True,
        "canonical_session_health_reports_require_trusted_runner_env": True,
    }


def _script_text(request: dict[str, Any], request_path: Path, status_path: Path) -> str:
    root_path = Path(str(request.get("root") or ".")).resolve()
    script_dir = request_path.resolve().parent
    root_from_script = os.path.relpath(root_path, script_dir)

    def shell_path(path: Path) -> str:
        try:
            relative = path.resolve().relative_to(root_path).as_posix()
        except ValueError:
            return shlex.quote(str(path))
        return f'"$ROOT/{relative}"'

    request_id = str(request.get("request_id") or "trusted_live")
    lines = [
        "#!/usr/bin/env bash",
        "set -uo pipefail",
        "",
        "# Generated by AgentLab. Review before running.",
        "# This script may send private project context through configured AgentLab role-session providers.",
        "# Run it only from a trusted terminal/session that is allowed to execute Crown role-session acceptance smokes.",
        "",
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        f'ROOT="$(cd "$SCRIPT_DIR/{root_from_script}" && pwd)"',
        f"REQUEST_PATH={shell_path(request_path)}",
        f"STATUS_PATH={shell_path(status_path)}",
        f"COLLECT_PATH={shell_path(status_path.with_name('trusted_live_runner_collect.yml'))}",
        "READINESS_PATH=acceptance_runs/agentlab_capability_acceptance/internal_live_readiness.yml",
        f"PREFLIGHT_PATH={shell_path(status_path.with_name('trusted_live_runner_preflight.yml'))}",
        f"REQUEST_ID={shlex.quote(request_id)}",
        'LOG_DIR="$(dirname "$STATUS_PATH")/trusted_live_runner_logs"',
        'RUN_LOG="$LOG_DIR/${REQUEST_ID}_$(date -u +%Y%m%dT%H%M%SZ).log"',
        "mkdir -p \"$LOG_DIR\"",
        "cd \"$ROOT\"",
        "failures=0",
        "health_failures=0",
        "RUN_ONLY=\"\"",
        "TRUSTED_LIVE_RUNNER=\"${AGENTLAB_TRUSTED_LIVE_RUNNER:-}\"",
        "ROLE_SESSION_ACCEPTANCE_APPROVED=\"${AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED:-}\"",
        "",
        "if [ \"${1:-}\" = \"--only\" ]; then",
        "  RUN_ONLY=\"${2:-}\"",
        "  if [ -z \"$RUN_ONLY\" ]; then",
        "    echo \"--only requires an item id\" | tee -a \"$RUN_LOG\"",
        "    exit 1",
        "  fi",
        "elif [ \"${1:-}\" != \"\" ] && [ \"${1:-}\" != \"--preflight-only\" ] && [ \"${1:-}\" != \"--session-health-only\" ]; then",
        "  echo \"unknown argument: ${1:-}\" | tee -a \"$RUN_LOG\"",
        "  exit 1",
        "fi",
        "",
        "require_command() {",
        "  local command_name=\"$1\"",
        "  if ! command -v \"$command_name\" >/dev/null 2>&1; then",
        "    echo \"missing required command: $command_name\" | tee -a \"$RUN_LOG\"",
        "    failures=$((failures + 1))",
        "  fi",
        "}",
        "",
        "require_runtime_commands() {",
        "  require_command claude",
        "  require_command hermes",
        "}",
        "",
        "write_preflight_report() {",
        "  ./agentlab.sh trusted-live-runner-preflight --request \"$REQUEST_PATH\" --out \"$PREFLIGHT_PATH\" >>\"$RUN_LOG\" 2>&1",
        "}",
        "",
        "require_trusted_live_runner_env() {",
        "  if [ \"$TRUSTED_LIVE_RUNNER\" != \"1\" ]; then",
        "    echo \"refusing to run canonical session health or private role-session acceptance smoke without AGENTLAB_TRUSTED_LIVE_RUNNER=1\" | tee -a \"$RUN_LOG\"",
        "    echo \"run from a trusted AgentLab runner or user terminal and prefix the command with AGENTLAB_TRUSTED_LIVE_RUNNER=1\" | tee -a \"$RUN_LOG\"",
        "    write_preflight_report || true",
        "    exit 1",
        "  fi",
        "}",
        "",
        "require_role_session_acceptance_approval_env() {",
        "  if [ \"$ROLE_SESSION_ACCEPTANCE_APPROVED\" != \"1\" ]; then",
        "    echo \"refusing to send private Crown context without AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1\" | tee -a \"$RUN_LOG\"",
        "    echo \"session health checks can use --session-health-only with AGENTLAB_TRUSTED_LIVE_RUNNER=1; role-session acceptance also requires explicit approval env\" | tee -a \"$RUN_LOG\"",
        "    write_preflight_report || true",
        "    exit 1",
        "  fi",
        "}",
        "",
        "collect_reports() {",
        "  if [ -n \"$RUN_ONLY\" ]; then",
        "    ./agentlab.sh trusted-live-runner-collect --request \"$REQUEST_PATH\" --out \"$COLLECT_PATH\" --item \"$RUN_ONLY\" >>\"$RUN_LOG\" 2>&1",
        "  else",
        "    ./agentlab.sh trusted-live-runner-collect --request \"$REQUEST_PATH\" --out \"$COLLECT_PATH\" >>\"$RUN_LOG\" 2>&1",
        "  fi",
        "}",
        "",
        "trusted_status_value() {",
        "  awk '/^status:/ { print $2; exit }' \"$STATUS_PATH\"",
        "}",
        "",
        "trusted_item_status_value() {",
        "  python3 - \"$STATUS_PATH\" \"$RUN_ONLY\" <<'PY'",
        "import sys",
        "from pathlib import Path",
        "",
        "import yaml",
        "",
        "path = Path(sys.argv[1])",
        "item_id = sys.argv[2]",
        "try:",
        "    report = yaml.safe_load(path.read_text(encoding=\"utf-8\")) or {}",
        "except Exception:",
        "    print(\"missing\")",
        "    raise SystemExit(0)",
        "for item in report.get(\"items\") or []:",
        "    if isinstance(item, dict) and item.get(\"id\") == item_id:",
        "        print(item.get(\"status\") or \"missing\")",
        "        raise SystemExit(0)",
        "print(\"missing\")",
        "PY",
        "}",
        "",
        "session_health_issue_count() {",
        "  awk '",
        "    /^session_health_issues: *\\[\\]/ { print 0; found=1; exit }",
        "    /^session_health_issues:/ { in_section=1; found=1; next }",
        "    in_section && /^[^[:space:]-]/ { print count + 0; in_section=0; exit }",
        "    in_section && /^- / { count++ }",
        "    END { if (in_section) print count + 0; else if (!found) print 1 }",
        "  ' \"$READINESS_PATH\"",
        "}",
        "",
        "selected_session_health_issue_count() {",
        "  if [ -z \"$RUN_ONLY\" ]; then",
        "    session_health_issue_count",
        "    return",
        "  fi",
        "  python3 - \"$READINESS_PATH\" \"$RUN_ONLY\" <<'PY'",
        "import sys",
        "from pathlib import Path",
        "",
        "import yaml",
        "",
        "path = Path(sys.argv[1])",
        "item_id = sys.argv[2]",
        "required_by_item = {",
        "    \"run_crown_internal_writer_eval\": {\"current_claude_writer_session_health\"},",
        "    \"run_crown_internal_media_smoke\": {\"current_grok_session_health\"},",
        "}",
        "required = required_by_item.get(item_id)",
        "if not required:",
        "    print(1)",
        "    raise SystemExit(0)",
        "try:",
        "    report = yaml.safe_load(path.read_text(encoding=\"utf-8\")) or {}",
        "except Exception:",
        "    print(1)",
        "    raise SystemExit(0)",
        "issues = report.get(\"session_health_issues\") or []",
        "if not isinstance(issues, list):",
        "    print(1)",
        "    raise SystemExit(0)",
        "count = 0",
        "for issue in issues:",
        "    if isinstance(issue, dict) and issue.get(\"id\") in required:",
        "        count += 1",
        "print(count)",
        "PY",
        "}",
        "",
        "print_session_health_issues() {",
        "  python3 - \"$READINESS_PATH\" <<'PY' | tee -a \"$RUN_LOG\"",
        "import sys",
        "from pathlib import Path",
        "",
        "import yaml",
        "",
        "path = Path(sys.argv[1])",
        "try:",
        "    report = yaml.safe_load(path.read_text(encoding=\"utf-8\")) or {}",
        "except Exception as exc:",
        "    print(f\"session_health_issue_report_unreadable path={path} error={exc}\")",
        "    raise SystemExit(0)",
        "issues = report.get(\"session_health_issues\") or []",
        "if not isinstance(issues, list):",
        "    print(f\"session_health_issue_report_malformed path={path}\")",
        "    raise SystemExit(0)",
        "for index, issue in enumerate(issues, start=1):",
        "    if not isinstance(issue, dict):",
        "        print(f\"session_health_issue[{index}] malformed={issue!r}\")",
        "        continue",
        "    issue_id = issue.get(\"id\") or \"unknown\"",
        "    status = issue.get(\"status\") or \"unknown\"",
        "    reason = issue.get(\"reason\") or \"unspecified\"",
        "    next_action = issue.get(\"next_action\") or \"unspecified\"",
        "    print(",
        "        f\"session_health_issue[{index}] id={issue_id} \"",
        "        f\"status={status} reason={reason} next_action={next_action}\"",
        "    )",
        "PY",
        "}",
        "",
        "guard_clean_session_health() {",
        "  local issue_count",
        "  issue_count=\"$(selected_session_health_issue_count)\"",
        "  if [ \"$issue_count\" != \"0\" ]; then",
        "    echo \"relevant session health still has $issue_count issue(s); refusing to send private Crown context\" | tee -a \"$RUN_LOG\"",
        "    print_session_health_issues",
        "    ./agentlab.sh trusted-live-runner-status --request \"$REQUEST_PATH\" --out \"$STATUS_PATH\" >>\"$RUN_LOG\" 2>&1 || true",
        "    collect_reports || true",
        "    echo \"status_path=$STATUS_PATH\" | tee -a \"$RUN_LOG\"",
        "    echo \"collect_path=$COLLECT_PATH\" | tee -a \"$RUN_LOG\"",
        "    exit 1",
        "  fi",
        "}",
        "",
        "should_run_session_health_command() {",
        "  local command_text=\"$1\"",
        "  if [ \"$RUN_ONLY\" = \"run_crown_internal_writer_eval\" ] && [[ \"$command_text\" == *\"grok-cli-smoke\"* ]]; then",
        "    return 1",
        "  fi",
        "  if [ \"$RUN_ONLY\" = \"run_crown_internal_media_smoke\" ] && [[ \"$command_text\" == *\"worker-invocation-probe --worker claude_writer\"* ]]; then",
        "    return 1",
        "  fi",
        "  return 0",
        "}",
        "",
        "run_session_health_checks() {",
        "  echo \"running non-private session health checks\" | tee -a \"$RUN_LOG\"",
    ]
    for command in (
        request.get("recommended_pre_run_session_health_checks", {}).get("commands", [])
        if isinstance(request.get("recommended_pre_run_session_health_checks"), dict)
        else []
    ):
        lines.extend(
            [
                f"  if should_run_session_health_command {shlex.quote(str(command))}; then",
                f"    bash -lc {shlex.quote(str(command))} >>\"$RUN_LOG\" 2>&1",
                "    local code=$?",
                f"    echo {shlex.quote(str(command))} exit_code=$code | tee -a \"$RUN_LOG\"",
                "    if [ \"$code\" -ne 0 ]; then",
                "      health_failures=$((health_failures + 1))",
                "    fi",
                "  else",
                f"    echo {shlex.quote(str(command))} skipped_for_selected_item=$RUN_ONLY | tee -a \"$RUN_LOG\"",
                "  fi",
            ]
        )
    lines.extend(
        [
            "}",
            "",
        "if [ ! -x ./agentlab.sh ]; then",
        "  echo \"missing executable ./agentlab.sh under $ROOT\" | tee -a \"$RUN_LOG\"",
        "  failures=$((failures + 1))",
        "fi",
        "if [ \"${1:-}\" = \"--preflight-only\" ]; then",
        "  require_runtime_commands",
        "  write_preflight_report || failures=$((failures + 1))",
        "  echo \"preflight_path=$PREFLIGHT_PATH\" | tee -a \"$RUN_LOG\"",
        "  exit \"$failures\"",
        "fi",
        "",
        "if [ \"${1:-}\" = \"--session-health-only\" ]; then",
        "  require_trusted_live_runner_env",
        "  require_runtime_commands",
        "  if [ \"$failures\" -ne 0 ]; then",
        "    write_preflight_report || true",
        "    exit \"$failures\"",
        "  fi",
        "  run_session_health_checks",
        "  guard_clean_session_health",
        "  if [ \"$health_failures\" -ne 0 ]; then",
        "    failures=$((failures + health_failures))",
        "  fi",
        "  echo \"session_health_log=$RUN_LOG\" | tee -a \"$RUN_LOG\"",
        "  exit \"$failures\"",
        "fi",
        "",
        "require_trusted_live_runner_env",
        "require_role_session_acceptance_approval_env",
        "require_runtime_commands",
        "",
        "if [ \"$failures\" -ne 0 ]; then",
        "  echo \"trusted live runner preflight failed; refreshing status\" | tee -a \"$RUN_LOG\"",
        "  write_preflight_report || true",
        "  ./agentlab.sh trusted-live-runner-status --request \"$REQUEST_PATH\" --out \"$STATUS_PATH\" >>\"$RUN_LOG\" 2>&1 || true",
        "  collect_reports || true",
        "  exit 1",
        "fi",
        "",
        "run_session_health_checks",
        "guard_clean_session_health",
        "if [ \"$health_failures\" -ne 0 ]; then",
        "  echo \"trusted live runner session health commands failed; refreshing status\" | tee -a \"$RUN_LOG\"",
        "  ./agentlab.sh trusted-live-runner-status --request \"$REQUEST_PATH\" --out \"$STATUS_PATH\" >>\"$RUN_LOG\" 2>&1 || true",
        "  collect_reports || true",
        "  failures=$((failures + health_failures))",
        "  exit 1",
        "fi",
        "",
        "run_item() {",
        "  local item_id=\"$1\"",
        "  local command_text=\"$2\"",
        "  echo \"running $item_id\" | tee -a \"$RUN_LOG\"",
        "  bash -lc \"$command_text\" >>\"$RUN_LOG\" 2>&1",
        "  local code=$?",
        "  echo \"$item_id exit_code=$code\" | tee -a \"$RUN_LOG\"",
        "  if [ \"$code\" -ne 0 ]; then",
        "    failures=$((failures + 1))",
        "  fi",
            "}",
            "",
        "should_run_item() {",
        "  local item_id=\"$1\"",
        "  if [ -z \"$RUN_ONLY\" ] || [ \"$RUN_ONLY\" = \"$item_id\" ]; then",
        "    return 0",
        "  fi",
        "  return 1",
        "}",
        "",
        "selected_item_ran=0",
        "",
        ]
    )
    for item in request.get("items", []):
        lines.append(f"# {item.get('id')} -> {item.get('agentlab_execution_owner')} / {item.get('assigned_worker')}")
        item_id = str(item.get("id") or "unknown_item")
        lines.extend(
            [
                f"if should_run_item {shlex.quote(item_id)}; then",
                "  selected_item_ran=1",
                "  run_item "
                f"{shlex.quote(item_id)} "
                f"{shlex.quote(str(item.get('command') or ''))}",
                "fi",
            ]
        )
        lines.append("")
    lines.extend(
        [
            "if [ -n \"$RUN_ONLY\" ] && [ \"$selected_item_ran\" -ne 1 ]; then",
            "  echo \"unknown trusted live item: $RUN_ONLY\" | tee -a \"$RUN_LOG\"",
            "  failures=$((failures + 1))",
            "fi",
            "echo \"refreshing trusted live runner status\" | tee -a \"$RUN_LOG\"",
            "./agentlab.sh trusted-live-runner-status --request \"$REQUEST_PATH\" --out \"$STATUS_PATH\" >>\"$RUN_LOG\" 2>&1",
            "status_code=$?",
            "if [ \"$status_code\" -ne 0 ]; then",
            "  failures=$((failures + 1))",
            "fi",
            "echo \"collecting trusted live runner reports\" | tee -a \"$RUN_LOG\"",
            "collect_reports",
            "collect_code=$?",
            "if [ \"$collect_code\" -ne 0 ]; then",
            "  failures=$((failures + 1))",
            "fi",
            "trusted_status=\"$(trusted_status_value)\"",
            "echo \"trusted_live_runner_status=$trusted_status\" | tee -a \"$RUN_LOG\"",
            "if [ -n \"$RUN_ONLY\" ]; then",
            "  selected_status=\"$(trusted_item_status_value)\"",
            "  echo \"trusted_live_runner_item_status[$RUN_ONLY]=$selected_status\" | tee -a \"$RUN_LOG\"",
            "  if [ \"$selected_status\" != \"pass\" ]; then",
            "    echo \"selected trusted live item is not accepted; item status must be pass\" | tee -a \"$RUN_LOG\"",
            "    failures=$((failures + 1))",
            "  fi",
            "elif [ \"$trusted_status\" != \"pass\" ]; then",
            "  echo \"trusted live runner artifacts are not accepted; status must be pass\" | tee -a \"$RUN_LOG\"",
            "  failures=$((failures + 1))",
            "fi",
            "echo \"status_path=$STATUS_PATH\" | tee -a \"$RUN_LOG\"",
            "echo \"collect_path=$COLLECT_PATH\" | tee -a \"$RUN_LOG\"",
            "echo \"run_log=$RUN_LOG\" | tee -a \"$RUN_LOG\"",
            "if [ \"$failures\" -ne 0 ]; then",
            "  exit 1",
            "fi",
        ]
    )
    return "\n".join(lines)


def build_trusted_live_runner_request(root: Path, request_id: str | None = None) -> dict[str, Any]:
    """Build a request from the current frontdesk live handoff without executing it."""
    root = root.resolve()
    request_id = request_id or _request_id()
    handoff_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "frontdesk_live_handoff.yml"
    readiness_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "internal_live_readiness.yml"
    legacy_readiness_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "external_acceptance_readiness.yml"
    handoff = _read_yaml(handoff_path)
    readiness = _read_yaml(readiness_path)
    items: list[dict[str, Any]] = []
    issues: list[str] = []

    if handoff.get("status") not in {
        "ready_for_agentlab_submission",
        "ready_for_user_input",
    }:
        issues.append("frontdesk_live_handoff_not_ready")
    if readiness.get("status") not in {"ready_for_internal_live_smoke", "route_ready_session_blocked"}:
        issues.append("internal_live_smoke_readiness_not_ready")

    for item in handoff.get("items", []) if isinstance(handoff.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        item = _current_handoff_item(item)
        command = str(item.get("agentlab_command") or item.get("agentlab_command_after_approval") or "")
        if not command:
            issues.append(f"missing_command:{item.get('id')}")
            continue
        materialized = _materialize_command(command, request_id, str(item.get("id") or ""))
        items.append(
            {
                "id": item.get("id"),
                "status": item.get("status"),
                "agentlab_execution_owner": item.get("agentlab_execution_owner"),
                "assigned_worker": item.get("assigned_worker"),
                "role_session_required": item.get("role_session_required"),
                "command": materialized,
                "expected_outputs": _expected_outputs(materialized, str(item.get("id") or "")),
                "observe_artifacts": item.get("observe_artifacts") or [],
            }
        )

    if len(items) < 2:
        issues.append("expected_writer_and_media_live_items")

    request = {
        "schema_version": 1,
        "report_type": "agentlab_trusted_live_runner_request",
        "request_id": request_id,
        "root": str(root),
        "status": "ready_for_trusted_runner" if not issues else "fail",
        "source_reports": {
            "frontdesk_live_handoff": str(handoff_path),
            "internal_live_readiness": str(readiness_path),
            "external_acceptance_readiness": str(legacy_readiness_path),
        },
        "terminology": _acceptance_smoke_terminology(),
        "runner_boundary": {
            "frontdesk_agent_executes_commands": False,
            "requires_trusted_runtime": True,
            "role_session_acceptance_commands_allowed_only_by_runner": True,
            "private_live_role_session_commands_allowed_only_by_runner": True,
            "provider_calls_allowed_only_by_runner": True,
            "reason": "Hermes FrontDesk may submit and observe, or AgentLab may use the direct closed loop; role-session execution remains owned by AgentLab workers.",
        },
        "recommended_pre_run_session_health_checks": {
            "required_for_clean_live_run": True,
            "loads_private_project_context": False,
            "executes_private_live_generation": False,
            "purpose": "Confirm the trusted terminal/session can run the Claude Writer contract and Grok non-private prompt contract before sending Crown private project context.",
            "commands": _session_health_probe_commands(),
            "pass_condition": "the internal live readiness report has no session_health_issues before role-session acceptance commands are run",
        },
        "items": items,
        "script_path": None,
        "secret_values_rendered": _contains_secret_text({"handoff": handoff, "readiness": readiness, "items": items}),
        "session_health_warnings": readiness.get("session_health_issues", [])
        if isinstance(readiness.get("session_health_issues"), list)
        else [],
        "issues": issues,
        "notes": [
            "This request does not execute private role-session acceptance commands.",
            "Generated outputs remain run-local candidates until QC and promotion gates pass.",
            "Historical host-policy rejections are evidence about an obsolete Codex external-worker entrypoint, not AgentLab role-session routing.",
        ],
    }
    if request["secret_values_rendered"]:
        request["status"] = "fail"
        request["issues"] = [*issues, "secret_values_rendered"]
    return request


def write_trusted_live_runner_request(root: Path, out: Path, request_id: str | None = None) -> dict[str, Any]:
    request = build_trusted_live_runner_request(root, request_id=request_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    script_path = out.with_suffix(".sh")
    status_path = out.with_name("trusted_live_runner_status.yml")
    preflight_path = out.with_name("trusted_live_runner_preflight.yml")
    collect_path = out.with_name("trusted_live_runner_collect.yml")
    request["script_path"] = str(script_path)
    request["local_runner_package"] = _local_runner_package(script_path, out, status_path, preflight_path, collect_path)
    script_path.write_text(_script_text(request, out, status_path), encoding="utf-8")
    script_path.chmod(0o755)
    write_report_yaml(out, request, root)
    return request
