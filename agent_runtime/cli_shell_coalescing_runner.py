"""Execute coalesced CLI shell packets behind an explicit trusted-runner gate."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import yaml

try:
    from agent_runtime.report_sanitizer import sanitize_report_value, write_report_yaml
    from agent_runtime.runtime_hygiene.secret_scan import SECRET_PATTERNS
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import sanitize_report_value, write_report_yaml
    from runtime_hygiene.secret_scan import SECRET_PATTERNS


CommandExecutor = Callable[[list[str], int], dict[str, Any]]
TRUSTED_RUNNER_ENV = "AGENTLAB_TRUSTED_CLI_SHELL_RUNNER"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _resolve(root: Path, path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else root / path


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(root.resolve(strict=False)))
    except ValueError:
        return str(path)


def _contains_secret_text(value: Any) -> bool:
    rendered = yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
    return "test-key" in rendered or any(pattern.search(rendered) for pattern in SECRET_PATTERNS.values())


def _execute_command(argv: list[str], timeout: int, cwd: Path | None = None) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"exit_code": None, "stdout": "", "stderr": "", "timed_out": True}
    return {
        "exit_code": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
        "timed_out": False,
    }


def _invoke_executor(
    executor: CommandExecutor,
    argv: list[str],
    timeout: int,
    *,
    cwd: Path | None = None,
) -> dict[str, Any]:
    if executor is _execute_command:
        return _execute_command(argv, timeout, cwd=cwd)
    return executor(argv, timeout)


def _role_slug(role: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in role).strip("_") or "role"


def _packet_sha256(packet: dict[str, Any]) -> str:
    source_hash = str(packet.get("source_packet_sha256") or "")
    if len(source_hash) == 64 and all(char in "0123456789abcdef" for char in source_hash.lower()):
        return source_hash.lower()
    return hashlib.sha256(
        yaml.safe_dump(packet, sort_keys=True, allow_unicode=True).encode("utf-8")
    ).hexdigest()


def _packet_roles(packet: dict[str, Any]) -> list[dict[str, Any]]:
    roles = packet.get("delegated_roles") if isinstance(packet.get("delegated_roles"), list) else []
    return [role for role in roles if isinstance(role, dict) and role.get("role")]


def _claude_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "role_results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string"},
                        "status": {"type": "string", "enum": ["pass", "fail"]},
                        "findings": {"type": "string"},
                        "validation": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["role", "status", "findings", "validation"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["role_results"],
        "additionalProperties": False,
    }


def _claude_command(packet: dict[str, Any]) -> list[str]:
    inline_agents: dict[str, dict[str, str]] = {}
    role_lines = []
    for role in _packet_roles(packet):
        role_name = str(role["role"])
        task = role.get("task") if isinstance(role.get("task"), dict) else {}
        fixture = task.get("synthetic_fixture") if isinstance(task.get("synthetic_fixture"), dict) else {}
        inline_agents[_role_slug(role_name)] = {
            "description": f"AgentLab {role_name} acceptance role",
            "prompt": (
                f"Act only as AgentLab {role_name}. {task.get('objective', '')} "
                f"Synthetic fixture: {json.dumps(fixture, ensure_ascii=True, separators=(',', ':'))}. "
                "Use only this embedded fixture. Do not inspect files, environment, repository, project memory, or "
                "production state. Return concise findings plus concrete validation evidence to the parent session."
            ),
        }
        role_lines.append(
            f"- {role_name}: {task.get('objective', '')}; fixture="
            f"{json.dumps(fixture, ensure_ascii=True, separators=(',', ':'))}"
        )
    prompt = (
        "This is a synthetic AgentLab native-subagent surface smoke. It contains no private project context. "
        "Delegate each listed role to its matching inline agent, use only the embedded fixtures, and return exactly "
        "one role_results entry per role. Do not inspect files, environment, repository, project memory, or "
        "production state.\n" + "\n".join(role_lines)
    )
    return [
        "claude",
        "--print",
        "--output-format",
        "json",
        "--permission-mode",
        "plan",
        "--safe-mode",
        "--no-session-persistence",
        "--tools",
        "Agent",
        "--agents",
        json.dumps(inline_agents, ensure_ascii=True, separators=(",", ":")),
        "--json-schema",
        json.dumps(_claude_schema(), ensure_ascii=True, separators=(",", ":")),
        prompt,
    ]


def _structured_claude_result(stdout: str) -> dict[str, Any]:
    data = json.loads(stdout)
    if not isinstance(data, dict):
        return {}
    structured = data.get("structured_output")
    if isinstance(structured, dict):
        return structured
    if isinstance(data.get("role_results"), list):
        return data
    result = data.get("result")
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _write_role_evidence(
    root: Path,
    packet: dict[str, Any],
    role: dict[str, Any],
    findings: str,
    validation: list[str],
    raw_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    packet_path = _resolve(root, str(packet.get("packet_path") or ""))
    packet_dir = packet_path.parent
    role_name = str(role.get("role") or "")
    slug = _role_slug(role_name)
    artifact_path = packet_dir / "returned_artifacts" / f"{slug}_findings.md"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_lines = [f"# {role_name} Findings", "", findings.strip(), "", "## Validation"]
    artifact_lines.extend(f"- {item}" for item in validation if str(item).strip())
    if raw_evidence:
        safe_evidence = sanitize_report_value(raw_evidence, root)
        artifact_lines.extend(
            ["", "## Native Runtime Evidence", "", "```json", json.dumps(safe_evidence, indent=2), "```"]
        )
    artifact_path.write_text("\n".join(artifact_lines).rstrip() + "\n", encoding="utf-8")

    receipt_path = _resolve(root, str(role.get("receipt_path") or ""))
    validation_path = _resolve(root, str(role.get("validation_evidence_path") or ""))
    receipt = {
        "schema_version": 1,
        "status": "pass",
        "role": role_name,
        "acceptance_scope": "synthetic_native_surface_smoke",
        "private_project_context_loaded": False,
        "source_packet_sha256": _packet_sha256(packet),
        "returned_artifacts": [_rel(root, artifact_path)],
        "production_promotion_attempted": False,
        "production_promotion_allowed": False,
    }
    validation_report = {
        "schema_version": 1,
        "status": "pass",
        "role": role_name,
        "acceptance_scope": "synthetic_native_surface_smoke",
        "private_project_context_loaded": False,
        "source_packet_sha256": _packet_sha256(packet),
        "checks": validation or ["non-empty role findings returned"],
        "production_promotion_attempted": False,
        "production_promotion_allowed": False,
    }
    write_report_yaml(receipt_path, receipt, root)
    write_report_yaml(validation_path, validation_report, root)
    return {
        "role": role_name,
        "status": "pass",
        "artifact_path": _rel(root, artifact_path),
        "receipt_path": _rel(root, receipt_path),
        "validation_evidence_path": _rel(root, validation_path),
    }


def _write_shell_receipt(
    root: Path,
    packet: dict[str, Any],
    *,
    native_surface: str,
    status: str,
    provider_calls_executed: bool = False,
    details: dict[str, Any] | None = None,
) -> Path:
    receipt_path = _resolve(root, str(packet.get("session_receipt_path") or ""))
    receipt = {
        "schema_version": 1,
        "status": status,
        "backend": packet.get("backend"),
        "coalescing_mode": packet.get("coalescing_mode"),
        "native_surface_used": native_surface,
        "delegated_roles": [str(role["role"]) for role in _packet_roles(packet)],
        "acceptance_scope": "synthetic_native_surface_smoke",
        "private_project_context_loaded": False,
        "execution_workspace_isolated": True,
        "project_read_tools_enabled": False,
        "provider_calls_executed_by_shell_session": provider_calls_executed,
        "source_packet_sha256": _packet_sha256(packet),
        "frontdesk_role_invocations": 0,
        "production_promotion_attempted": False,
        "production_promotion_allowed": False,
        "details": details or {},
    }
    write_report_yaml(receipt_path, receipt, root)
    return receipt_path


def _run_claude(
    root: Path,
    packet: dict[str, Any],
    executor: CommandExecutor,
    timeout: int,
) -> dict[str, Any]:
    argv = _claude_command(packet)
    with tempfile.TemporaryDirectory(prefix="agentlab-cli-shell-smoke-") as workdir:
        result = _invoke_executor(executor, argv, timeout, cwd=Path(workdir))
    stdout = str(result.get("stdout") or "")
    if result.get("exit_code") != 0 or result.get("timed_out") is True:
        _write_shell_receipt(
            root,
            packet,
            native_surface="claude_inline_agents",
            status="fail",
            provider_calls_executed=True,
            details={"exit_code": result.get("exit_code"), "timed_out": result.get("timed_out") is True},
        )
        return {
            "backend": "claude_code",
            "status": "fail",
            "native_surface_used": "claude_inline_agents",
            "provider_calls_executed": True,
            "exit_code": result.get("exit_code"),
            "timed_out": result.get("timed_out") is True,
        }
    if _contains_secret_text(stdout):
        _write_shell_receipt(
            root,
            packet,
            native_surface="claude_inline_agents",
            status="fail",
            provider_calls_executed=True,
        )
        return {
            "backend": "claude_code",
            "status": "unsafe_output_rejected",
            "native_surface_used": "claude_inline_agents",
            "provider_calls_executed": True,
        }
    try:
        structured = _structured_claude_result(stdout)
    except (json.JSONDecodeError, TypeError):
        structured = {}
    role_results = structured.get("role_results") if isinstance(structured.get("role_results"), list) else []
    results_by_role = {
        str(item.get("role")): item
        for item in role_results
        if isinstance(item, dict) and item.get("role")
    }
    expected_roles = {str(role["role"]) for role in _packet_roles(packet)}
    valid = set(results_by_role) == expected_roles and all(
        item.get("status") == "pass" and str(item.get("findings") or "").strip()
        for item in results_by_role.values()
    )
    if not valid:
        _write_shell_receipt(
            root,
            packet,
            native_surface="claude_inline_agents",
            status="fail",
            provider_calls_executed=True,
        )
        return {
            "backend": "claude_code",
            "status": "invalid_role_results",
            "native_surface_used": "claude_inline_agents",
            "provider_calls_executed": True,
            "returned_roles": sorted(results_by_role),
        }
    role_evidence = []
    for role in _packet_roles(packet):
        item = results_by_role[str(role["role"])]
        validation = item.get("validation") if isinstance(item.get("validation"), list) else []
        role_evidence.append(
            _write_role_evidence(
                root,
                packet,
                role,
                str(item["findings"]),
                [str(value) for value in validation],
            )
        )
    receipt_path = _write_shell_receipt(
        root,
        packet,
        native_surface="claude_inline_agents",
        status="pass",
        provider_calls_executed=True,
        details={"top_level_shell_invocation_count": 1},
    )
    return {
        "backend": "claude_code",
        "status": "pass",
        "native_surface_used": "claude_inline_agents",
        "provider_calls_executed": True,
        "role_evidence": role_evidence,
        "session_receipt_path": _rel(root, receipt_path),
    }


def _json_result(result: dict[str, Any]) -> Any:
    stdout = str(result.get("stdout") or "")
    if _contains_secret_text(stdout):
        raise ValueError("unsafe command output rejected")
    return json.loads(stdout)


def _hermes_task_status(data: Any) -> str:
    if not isinstance(data, dict):
        return "unknown"
    task = data.get("task") if isinstance(data.get("task"), dict) else data
    return str(task.get("status") or task.get("state") or "unknown")


def _hermes_task_finding(data: Any, role: str) -> str:
    if isinstance(data, dict):
        task = data.get("task") if isinstance(data.get("task"), dict) else data
        for key in ("result", "summary", "output", "completion_summary"):
            if str(task.get(key) or "").strip():
                return str(task[key]).strip()
    return f"{role} completed the bounded Hermes kanban task; native task evidence is attached."


def _nested_config_value(config: dict[str, Any], dotted_key: str) -> Any:
    value: Any = config
    for part in dotted_key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _hermes_profile_preflight(
    packet: dict[str, Any],
    hermes_home: Path,
) -> tuple[dict[str, str], list[str]]:
    profiles: dict[str, str] = {}
    issues: list[str] = []
    for role in _packet_roles(packet):
        role_name = str(role["role"])
        route = role.get("model_route") if isinstance(role.get("model_route"), dict) else {}
        profile_name = str(route.get("workflow_shell_profile") or "")
        required = route.get("required_profile_config") if isinstance(route.get("required_profile_config"), dict) else {}
        if not profile_name:
            issues.append(f"{_role_slug(role_name)}:profile_not_declared")
            continue
        profiles[role_name] = profile_name
        config_path = hermes_home / "profiles" / profile_name / "config.yaml"
        if not config_path.is_file():
            issues.append(f"{profile_name}:profile_missing")
            continue
        config = _read_yaml(config_path)
        for key, expected in required.items():
            actual = _nested_config_value(config, str(key))
            if (actual or "") != (expected or ""):
                issues.append(f"{profile_name}:{key}_mismatch")
    return profiles, sorted(issues)


def provision_hermes_profiles(
    packet: dict[str, Any],
    *,
    hermes_home: Path,
    executor: CommandExecutor,
    timeout: int,
) -> dict[str, Any]:
    """Create/update isolated Hermes profiles declared by a coalesced packet."""
    profile_results: dict[str, dict[str, Any]] = {}
    for role in _packet_roles(packet):
        role_name = str(role["role"])
        route = role.get("model_route") if isinstance(role.get("model_route"), dict) else {}
        profile_name = str(route.get("workflow_shell_profile") or "")
        required = route.get("required_profile_config") if isinstance(route.get("required_profile_config"), dict) else {}
        if not profile_name or not profile_name.replace("_", "").replace("-", "").isalnum():
            return {
                "status": "fail",
                "profiles": profile_results,
                "issues": [f"{_role_slug(role_name)}:invalid_profile_name"],
            }
        profile_dir = hermes_home / "profiles" / profile_name
        created = False
        if not (profile_dir / "config.yaml").is_file():
            create_result = executor(
                [
                    "hermes",
                    "profile",
                    "create",
                    profile_name,
                    "--clone-all",
                    "--clone-from",
                    "default",
                    "--no-alias",
                    "--description",
                    f"Isolated AgentLab {role_name} kanban worker profile.",
                ],
                min(timeout, 120),
            )
            config_materialized = (profile_dir / "config.yaml").is_file()
            if create_result.get("exit_code") != 0 and not config_materialized:
                return {
                    "status": "fail",
                    "profiles": profile_results,
                    "issues": [f"{profile_name}:profile_create_failed"],
                }
            created = config_materialized
        configured_keys = []
        for key, value in required.items():
            config_result = executor(
                ["hermes", "-p", profile_name, "config", "set", str(key), str(value or "")],
                min(timeout, 60),
            )
            if config_result.get("exit_code") != 0:
                return {
                    "status": "fail",
                    "profiles": profile_results,
                    "issues": [f"{profile_name}:{key}_config_set_failed"],
                }
            configured_keys.append(str(key))
        profile_results[profile_name] = {
            "role": role_name,
            "created": created,
            "configured_keys": configured_keys,
        }

    _profiles, issues = _hermes_profile_preflight(packet, hermes_home)
    return {
        "status": "pass" if not issues else "fail",
        "profiles": profile_results,
        "issues": issues,
    }


def _run_hermes(
    root: Path,
    packet: dict[str, Any],
    executor: CommandExecutor,
    timeout: int,
    hermes_home: Path,
    provision_profiles: bool,
) -> dict[str, Any]:
    execution = packet.get("execution_contract") if isinstance(packet.get("execution_contract"), dict) else {}
    command_spec = execution.get("command_spec") if isinstance(execution.get("command_spec"), dict) else {}
    board = str(command_spec.get("board_slug") or "agentlab-cli-shell-acceptance")
    provision_report = None
    if provision_profiles:
        provision_report = provision_hermes_profiles(
            packet,
            hermes_home=hermes_home,
            executor=executor,
            timeout=timeout,
        )
        if provision_report.get("status") != "pass":
            receipt_path = _write_shell_receipt(
                root,
                packet,
                native_surface="hermes_kanban",
                status="fail",
                details={"profile_provisioning_issues": provision_report.get("issues", [])},
            )
            return {
                "backend": "hermes",
                "status": "profile_provisioning_failed",
                "native_surface_used": "hermes_kanban",
                "provider_calls_executed": False,
                "profile_issues": provision_report.get("issues", []),
                "session_receipt_path": _rel(root, receipt_path),
            }
    profiles, profile_issues = _hermes_profile_preflight(packet, hermes_home)
    if profile_issues:
        receipt_path = _write_shell_receipt(
            root,
            packet,
            native_surface="hermes_kanban",
            status="fail",
            details={"profile_issues": profile_issues},
        )
        return {
            "backend": "hermes",
            "status": "profile_preflight_failed",
            "native_surface_used": "hermes_kanban",
            "provider_calls_executed": False,
            "profile_issues": profile_issues,
            "session_receipt_path": _rel(root, receipt_path),
        }
    deadline = time.monotonic() + timeout
    provider_calls_executed = False
    try:
        boards_result = executor(["hermes", "kanban", "boards", "list", "--json"], min(timeout, 60))
        if boards_result.get("exit_code") != 0:
            raise RuntimeError("hermes kanban boards list failed")
        boards = _json_result(boards_result)
        board_exists = isinstance(boards, list) and any(
            isinstance(item, dict) and item.get("slug") == board for item in boards
        )
        if not board_exists:
            create_board = executor(
                [
                    "hermes",
                    "kanban",
                    "boards",
                    "create",
                    board,
                    "--name",
                    "AgentLab CLI Shell Acceptance",
                ],
                min(timeout, 60),
            )
            if create_board.get("exit_code") != 0:
                raise RuntimeError("hermes kanban board creation failed")

        packet_hash = _packet_sha256(packet)[:16]
        attempt_id = uuid.uuid4().hex[:12]
        task_ids: dict[str, str] = {}
        for role in _packet_roles(packet):
            role_name = str(role["role"])
            task = role.get("task") if isinstance(role.get("task"), dict) else {}
            title = f"AgentLab {role_name} native shell acceptance"
            body = (
                f"Act only as AgentLab {role_name}. {task.get('objective', '')} "
                f"Synthetic fixture: {json.dumps(task.get('synthetic_fixture') or {}, ensure_ascii=True)}. "
                "Use only this embedded fixture. Do not inspect files, environment, repository, project memory, or "
                "production state. Return concise findings and validation evidence in the task result."
            )
            create_result = executor(
                [
                    "hermes",
                    "kanban",
                    "--board",
                    board,
                    "create",
                    title,
                    "--body",
                    body,
                    "--assignee",
                    profiles[role_name],
                    "--workspace",
                    "scratch",
                    "--idempotency-key",
                    f"agentlab-{packet_hash}-{attempt_id}-{_role_slug(role_name)}",
                    "--max-runtime",
                    f"{max(60, timeout)}s",
                    "--max-retries",
                    "1",
                    "--json",
                ],
                min(timeout, 60),
            )
            if create_result.get("exit_code") != 0:
                raise RuntimeError(f"hermes kanban task creation failed for {role_name}")
            created = _json_result(create_result)
            task_id = str(created.get("id") or created.get("task_id") or "") if isinstance(created, dict) else ""
            if not task_id:
                raise RuntimeError(f"hermes kanban did not return a task id for {role_name}")
            task_ids[role_name] = task_id

        dispatch = executor(
            ["hermes", "kanban", "--board", board, "dispatch", "--max", str(len(task_ids)), "--json"],
            min(timeout, 60),
        )
        if dispatch.get("exit_code") != 0:
            raise RuntimeError("hermes kanban dispatch failed")
        provider_calls_executed = True

        task_evidence: dict[str, dict[str, Any]] = {}
        pending = dict(task_ids)
        while pending and time.monotonic() < deadline:
            for role_name, task_id in list(pending.items()):
                show_result = executor(
                    ["hermes", "kanban", "--board", board, "show", task_id, "--json"],
                    min(60, max(1, int(deadline - time.monotonic()))),
                )
                if show_result.get("exit_code") != 0:
                    continue
                show = _json_result(show_result)
                status = _hermes_task_status(show)
                if status in {"done", "blocked", "archived"}:
                    runs_result = executor(
                        ["hermes", "kanban", "--board", board, "runs", task_id, "--json"],
                        min(60, max(1, int(deadline - time.monotonic()))),
                    )
                    runs = _json_result(runs_result) if runs_result.get("exit_code") == 0 else []
                    task_evidence[role_name] = {"task": show, "runs": runs, "status": status}
                    pending.pop(role_name)
            if pending:
                time.sleep(2)
        if pending:
            raise TimeoutError(f"Hermes kanban tasks did not finish: {sorted(pending)}")
    except (RuntimeError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        receipt_path = _write_shell_receipt(
            root,
            packet,
            native_surface="hermes_kanban",
            status="fail",
            provider_calls_executed=provider_calls_executed,
            details={"error_type": type(exc).__name__},
        )
        return {
            "backend": "hermes",
            "status": "fail",
            "native_surface_used": "hermes_kanban",
            "provider_calls_executed": provider_calls_executed,
            "error_type": type(exc).__name__,
            "session_receipt_path": _rel(root, receipt_path),
        }

    role_evidence = []
    all_pass = True
    for role in _packet_roles(packet):
        role_name = str(role["role"])
        evidence = task_evidence[role_name]
        role_pass = evidence["status"] == "done"
        all_pass = all_pass and role_pass
        if role_pass:
            role_evidence.append(
                _write_role_evidence(
                    root,
                    packet,
                    role,
                    _hermes_task_finding(evidence["task"], role_name),
                    ["Hermes kanban task reached done", "task run evidence returned"],
                    raw_evidence=evidence,
                )
            )
    receipt_path = _write_shell_receipt(
        root,
        packet,
        native_surface="hermes_kanban",
        status="pass" if all_pass else "fail",
        provider_calls_executed=True,
        details={
            "board_slug": board,
            "attempt_id": attempt_id,
            "task_ids": task_ids,
            "worker_process_count_claimed": False,
        },
    )
    return {
        "backend": "hermes",
        "status": "pass" if all_pass else "fail",
        "native_surface_used": "hermes_kanban",
        "provider_calls_executed": provider_calls_executed,
        "profile_provisioning": provision_report,
        "role_evidence": role_evidence,
        "session_receipt_path": _rel(root, receipt_path),
    }


def _command_preview(packet: dict[str, Any]) -> Any:
    execution = packet.get("execution_contract") if isinstance(packet.get("execution_contract"), dict) else {}
    command_spec = execution.get("command_spec") if isinstance(execution.get("command_spec"), dict) else {}
    return command_spec


def run_cli_shell_coalescing_request(
    root: Path,
    *,
    request_path: Path | None = None,
    backend: str = "all",
    execute: bool = False,
    env: dict[str, str] | None = None,
    executor: CommandExecutor | None = None,
    timeout: int = 600,
    hermes_home: Path | None = None,
    provision_profiles: bool = False,
    provision_only: bool = False,
) -> dict[str, Any]:
    """Plan or execute trusted coalesced shell packets."""
    root = root.resolve()
    request_path = request_path or (
        root / "acceptance_runs" / "agentlab_capability_acceptance" / "cli_shell_coalescing_runner_request.yml"
    )
    request_path = request_path if request_path.is_absolute() else root / request_path
    request = _read_yaml(request_path)
    packets = request.get("packets") if isinstance(request.get("packets"), list) else []
    selected = [
        packet
        for packet in packets
        if isinstance(packet, dict) and (backend == "all" or packet.get("backend") == backend)
    ]
    base_report = {
        "schema_version": 1,
        "report_type": "agentlab_cli_shell_coalescing_runner_result",
        "root": str(root),
        "source_request": _rel(root, request_path),
        "selected_backend": backend,
        "execute_requested": execute,
        "trusted_runner_env": TRUSTED_RUNNER_ENV,
        "provision_hermes_profiles_requested": provision_profiles,
        "provision_only_requested": provision_only,
        "acceptance_scope": "synthetic_native_surface_smoke",
        "private_project_context_loaded": False,
        "isolated_execution_workspace_required": True,
        "project_read_tools_allowed": False,
        "provider_calls_executed": False,
        "secret_values_rendered": False,
    }
    if request.get("status") not in {"ready_for_trusted_runner", "accepted"} or not selected:
        return {
            **base_report,
            "status": "invalid_runner_request",
            "backend_results": [],
            "next_action": "repair_or_regenerate_cli_shell_coalescing_runner_request",
        }
    if _contains_secret_text(request):
        return {
            **base_report,
            "status": "unsafe_request_rejected",
            "backend_results": [],
            "next_action": "remove_secret_values_from_runner_request",
        }
    if not execute:
        return {
            **base_report,
            "status": "ready_for_trusted_runner",
            "backend_results": [
                {
                    "backend": packet.get("backend"),
                    "status": "planned",
                    "native_surface_used": (
                        (packet.get("execution_contract") or {}).get("native_surface")
                        if isinstance(packet.get("execution_contract"), dict)
                        else None
                    ),
                    "command_preview": _command_preview(packet),
                }
                for packet in selected
            ],
            "next_action": f"set {TRUSTED_RUNNER_ENV}=1 and rerun with --execute",
        }

    effective_env = dict(os.environ)
    if env is not None:
        effective_env = dict(env)
    if effective_env.get(TRUSTED_RUNNER_ENV) != "1":
        return {
            **base_report,
            "status": "trusted_runner_env_required",
            "backend_results": [],
            "next_action": f"set {TRUSTED_RUNNER_ENV}=1 in a trusted shell runner",
        }

    executor = executor or _execute_command
    if hermes_home is None:
        configured_home = os.getenv("HERMES_HOME", "").strip()
        hermes_home = Path(configured_home).expanduser() if configured_home else Path.home() / ".hermes"
    if not hermes_home.is_absolute():
        hermes_home = (Path.home() / hermes_home).resolve()
    if provision_only:
        hermes_packet = next(
            (packet for packet in selected if isinstance(packet, dict) and packet.get("backend") == "hermes"),
            None,
        )
        if not provision_profiles or not hermes_packet:
            return {
                **base_report,
                "status": "invalid_provision_only_request",
                "backend_results": [],
                "next_action": "select hermes and pass --provision-hermes-profiles",
            }
        provision_report = provision_hermes_profiles(
            hermes_packet,
            hermes_home=hermes_home,
            executor=executor,
            timeout=timeout,
        )
        return {
            **base_report,
            "status": "pass" if provision_report.get("status") == "pass" else "fail",
            "provider_calls_executed": False,
            "backend_results": [
                {
                    "backend": "hermes",
                    "status": (
                        "profiles_provisioned"
                        if provision_report.get("status") == "pass"
                        else "profile_provisioning_failed"
                    ),
                    "native_surface_used": "hermes_kanban",
                    "provider_calls_executed": False,
                    "profile_provisioning": provision_report,
                }
            ],
            "next_action": (
                "run_hermes_profile_auth_preflight"
                if provision_report.get("status") == "pass"
                else "repair_hermes_profile_provisioning"
            ),
        }
    backend_results = []
    for packet in selected:
        packet_backend = str(packet.get("backend") or "")
        if packet_backend == "claude_code":
            backend_results.append(_run_claude(root, packet, executor, timeout))
        elif packet_backend == "hermes":
            backend_results.append(
                _run_hermes(
                    root,
                    packet,
                    executor,
                    timeout,
                    hermes_home,
                    provision_profiles,
                )
            )
        else:
            backend_results.append(
                {
                    "backend": packet_backend,
                    "status": "unsupported_backend",
                    "native_surface_used": None,
                    "provider_calls_executed": False,
                }
            )
    status = "pass" if backend_results and all(item.get("status") == "pass" for item in backend_results) else "fail"
    report = {
        **base_report,
        "status": status,
        "provider_calls_executed": any(
            item.get("provider_calls_executed") is True for item in backend_results
        ),
        "backend_results": backend_results,
        "next_action": "run_cli_shell_coalescing_collect" if status == "pass" else "inspect_failed_backend_receipts",
    }
    if _contains_secret_text(report):
        return {
            **base_report,
            "status": "unsafe_result_rejected",
            "provider_calls_executed": report["provider_calls_executed"],
            "backend_results": [
                {
                    "backend": item.get("backend"),
                    "status": item.get("status"),
                    "native_surface_used": item.get("native_surface_used"),
                }
                for item in backend_results
            ],
            "next_action": "remove_secret_values_from_returned_shell_evidence",
        }
    return report


def write_cli_shell_coalescing_runner_result(
    root: Path,
    out: Path,
    **kwargs: Any,
) -> dict[str, Any]:
    root = root.resolve()
    out = out if out.is_absolute() else root / out
    report = run_cli_shell_coalescing_request(root, **kwargs)
    write_report_yaml(out, report, root)
    return report
