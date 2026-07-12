"""Project-local CLI entrypoint bootstrap and doctor utilities."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib
import os
import shutil
import stat
from typing import Any

import yaml


def _read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or default
    except Exception:
        return default


def _write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _load_policy(root: Path) -> dict[str, Any]:
    return _read_yaml(root / "config" / "cli_entrypoint_policy.yml", {}) or {}


def _load_bindings(root: Path) -> dict[str, Any]:
    return _read_yaml(root / "config" / "agent_role_bindings.yml", {}) or {}


def _agent_command(agent_cfg: dict[str, Any]) -> str | None:
    if agent_cfg.get("command"):
        return str(agent_cfg["command"])
    for candidate in agent_cfg.get("command_candidates") or []:
        if shutil.which(str(candidate)):
            return str(candidate)
    candidates = agent_cfg.get("command_candidates") or []
    return str(candidates[0]) if candidates else None


def _is_installed(agent_cfg: dict[str, Any]) -> bool:
    command = agent_cfg.get("command")
    if command:
        return shutil.which(str(command)) is not None
    return any(shutil.which(str(candidate)) for candidate in agent_cfg.get("command_candidates") or [])


def scan_cli_entrypoints(root: Path) -> dict[str, Any]:
    root = Path(root)
    policy = _load_policy(root)
    bindings = _load_bindings(root)
    workers = bindings.get("workers") or {}
    recognized: dict[str, Any] = {}
    ignored: dict[str, Any] = {}

    for agent_id, cfg in (policy.get("agents") or {}).items():
        if not cfg.get("enabled", False):
            ignored[agent_id] = {"reason": "disabled_by_policy"}
            continue
        binding = workers.get(agent_id) or {}
        installed = _is_installed(cfg)
        profiles = []
        if binding.get("frontdesk_capable"):
            profiles.append("frontdesk")
        if binding.get("worker_capable"):
            profiles.append("worker")
        recognized[agent_id] = {
            "installed": installed,
            "configurable": True,
            "command": _agent_command(cfg),
            "profiles": profiles,
            "project_dir": cfg.get("project_dir"),
            "entrypoint_file": cfg.get("entrypoint_file"),
            "wrapper_kind": cfg.get("wrapper_kind"),
            "auto_read_confidence": cfg.get("auto_read_confidence", "unknown"),
        }

    for agent_id, reason in (policy.get("ignored_known_agents") or {}).items():
        ignored.setdefault(agent_id, {"reason": reason})

    return {
        "schema_version": 1,
        "recognized": recognized,
        "ignored": ignored,
    }


def _managed_body(agent_id: str, root: Path, scan_item: dict[str, Any]) -> str:
    profiles = ", ".join(scan_item.get("profiles") or ["unbound"])
    return f"""# AgentLab Project Entry

This file is managed by AgentLab for project-local CLI entrypoint discovery.

When running inside this AgentLab workspace, do not infer your role from the CLI
name. Use AgentLab-generated packets as the source of truth.

Required first step:

```bash
./agentlab.sh workspace-entry --agent {agent_id}
```

If acting as frontdesk:

```bash
./agentlab.sh frontdesk-session --agent {agent_id}
```

If assigned an AgentLab role:

```bash
./agentlab.sh role-session --role <Role> --worker {agent_id} --project <Project> --task-id <task_id>
```

Run protocol verification before work:

```bash
./agentlab.sh protocol-doctor
```

Allowed profiles for this CLI in this workspace: {profiles}.

Do not implement tasks as frontdesk. Do not bypass role binding. Do not
rediscover AgentLab by scanning the whole repository when a generated packet is
available.

Reliable launchers are generated under:

```text
{root / ".agentlab" / "cli_entrypoints" / "wrappers"}
```
"""


def _managed_block(agent_id: str, root: Path, scan_item: dict[str, Any], policy: dict[str, Any]) -> str:
    body = _managed_body(agent_id, root, scan_item)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    start = (policy.get("managed_block") or {}).get("start_marker", "<!-- AGENTLAB_MANAGED_START")
    end = (policy.get("managed_block") or {}).get("end_marker", "<!-- AGENTLAB_MANAGED_END -->")
    return f"{start} hash:{digest} -->\n{body.rstrip()}\n{end}\n"


def _replace_managed_block(existing: str, block: str, policy: dict[str, Any]) -> str:
    start = (policy.get("managed_block") or {}).get("start_marker", "<!-- AGENTLAB_MANAGED_START")
    end = (policy.get("managed_block") or {}).get("end_marker", "<!-- AGENTLAB_MANAGED_END -->")
    start_index = existing.find(start)
    end_index = existing.find(end)
    if start_index != -1 and end_index != -1 and end_index >= start_index:
        end_index += len(end)
        prefix = existing[:start_index].rstrip()
        suffix = existing[end_index:].lstrip()
        parts = [part for part in [prefix, block.rstrip(), suffix] if part]
        return "\n\n".join(parts) + "\n"
    if existing.strip():
        return existing.rstrip() + "\n\n" + block
    return block


def _wrapper_invocation(command_template: str) -> str:
    # The command template is policy-owned shell code using AGENTLAB_SESSION_TEXT.
    return f"exec {command_template} \"$@\""


def _frontdesk_wrapper(root: Path, agent_id: str, command_template: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
AGENTLAB_ROOT={str(root)!r}
cd "$AGENTLAB_ROOT"
./agentlab.sh protocol-doctor >/dev/null
mkdir -p "$AGENTLAB_ROOT/.agentlab/runtime/frontdesk_sessions"
session_file="$(mktemp "$AGENTLAB_ROOT/.agentlab/runtime/frontdesk_sessions/{agent_id}.XXXXXX.md")"
./agentlab.sh frontdesk-session --agent {agent_id} > "$session_file"
AGENTLAB_SESSION_TEXT="$(cat "$session_file")"
export AGENTLAB_SESSION_TEXT
{_wrapper_invocation(command_template)}
"""


def _role_wrapper(root: Path, agent_id: str, command_template: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
AGENTLAB_ROOT={str(root)!r}
cd "$AGENTLAB_ROOT"
: "${{AGENTLAB_ROLE:?Set AGENTLAB_ROLE to a bound AgentLab role.}}"
: "${{AGENTLAB_TASK_ID:?Set AGENTLAB_TASK_ID to the target task id.}}"
AGENTLAB_PROJECT="${{AGENTLAB_PROJECT:-AgentLab}}"
./agentlab.sh protocol-doctor >/dev/null
./agentlab.sh role-doctor --role "$AGENTLAB_ROLE" --worker {agent_id} >/dev/null
mkdir -p "$AGENTLAB_ROOT/.agentlab/runtime/role_sessions"
session_file="$(mktemp "$AGENTLAB_ROOT/.agentlab/runtime/role_sessions/{agent_id}.XXXXXX.yml")"
./agentlab.sh role-session --role "$AGENTLAB_ROLE" --worker {agent_id} --project "$AGENTLAB_PROJECT" --task-id "$AGENTLAB_TASK_ID" > "$session_file"
AGENTLAB_SESSION_TEXT="$(cat "$session_file")"
export AGENTLAB_SESSION_TEXT
{_wrapper_invocation(command_template)}
"""


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_cli_entrypoints(root: Path, *, agent: str | None = None, write: bool = False) -> dict[str, Any]:
    root = Path(root)
    policy = _load_policy(root)
    scan = scan_cli_entrypoints(root)
    targets = scan["recognized"]
    if agent:
        targets = {agent: targets[agent]} if agent in targets else {}

    installed: dict[str, Any] = {}
    planned: dict[str, Any] = {}
    wrapper_root = root / str(policy.get("wrapper_root", ".agentlab/cli_entrypoints/wrappers"))

    for agent_id, item in targets.items():
        cfg = (policy.get("agents") or {}).get(agent_id) or {}
        entrypoint_path = root / str(cfg.get("project_dir")) / str(cfg.get("entrypoint_file", "AGENTLAB_ENTRYPOINT.md"))
        block = _managed_block(agent_id, root, item, policy)
        invocation = cfg.get("invocation") or {}
        wrapper_kind = str(cfg.get("wrapper_kind", "both"))
        wrappers: dict[str, str] = {}

        if wrapper_kind in {"frontdesk", "both"} and "frontdesk" in (item.get("profiles") or []) and invocation.get("frontdesk"):
            wrappers["frontdesk"] = str(wrapper_root / "frontdesk" / f"{agent_id}-agentlab")
        if wrapper_kind in {"role", "both"} and "worker" in (item.get("profiles") or []) and invocation.get("role"):
            wrappers["role"] = str(wrapper_root / "workers" / f"{agent_id}-role-agentlab")

        record = {
            "entrypoint_path": str(entrypoint_path),
            "entrypoint_required": bool(cfg.get("entrypoint_required", True)),
            "wrappers": wrappers,
            "installed": bool(item.get("installed")),
            "profiles": item.get("profiles") or [],
            "removed_wrappers": [],
        }
        planned[agent_id] = record

        if write:
            existing = entrypoint_path.read_text(encoding="utf-8") if entrypoint_path.exists() else ""
            try:
                entrypoint_path.parent.mkdir(parents=True, exist_ok=True)
                entrypoint_path.write_text(
                    _replace_managed_block(existing, block, policy),
                    encoding="utf-8",
                )
                record["entrypoint_status"] = "installed"
            except OSError as exc:
                record["entrypoint_status"] = "required_write_failed" if record["entrypoint_required"] else "optional_write_skipped"
                record["entrypoint_error"] = f"{type(exc).__name__}: {exc}"

            if wrappers.get("frontdesk"):
                _write_executable(Path(wrappers["frontdesk"]), _frontdesk_wrapper(root, agent_id, invocation["frontdesk"]))
            if wrappers.get("role"):
                _write_executable(Path(wrappers["role"]), _role_wrapper(root, agent_id, invocation["role"]))

            managed_wrapper_candidates = {
                wrapper_root / "frontdesk" / f"{agent_id}-agentlab",
                wrapper_root / "workers" / f"{agent_id}-role-agentlab",
            }
            expected_wrappers = {Path(path) for path in wrappers.values()}
            for stale_wrapper in sorted(managed_wrapper_candidates - expected_wrappers):
                if stale_wrapper.exists():
                    stale_wrapper.unlink()
                    record["removed_wrappers"].append(str(stale_wrapper))

            installed[agent_id] = record

    result = {
        "schema_version": 1,
        "write": write,
        "planned": planned,
        "installed": installed,
    }
    state_root = root / str(policy.get("local_state_root", ".agentlab/cli_entrypoints"))
    if write:
        _write_yaml(root / str(policy.get("inventory_path", state_root / "inventory.yml")), scan)
        _write_yaml(root / str(policy.get("install_report_path", state_root / "install_report.yml")), result)
    return result


@dataclass
class EntrypointCheck:
    id: str
    status: str
    severity: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _check(ok: bool, check_id: str, message: str, severity: str = "fail") -> EntrypointCheck:
    return EntrypointCheck(check_id, "pass" if ok else "fail", severity, message)


def _file_contains(path: Path, parts: list[str]) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    return all(part in text for part in parts)


def doctor_cli_entrypoints(root: Path, *, agent: str | None = None) -> dict[str, Any]:
    root = Path(root)
    install_plan = install_cli_entrypoints(root, agent=agent, write=False)
    checks: list[EntrypointCheck] = []

    for agent_id, item in install_plan["planned"].items():
        entrypoint_path = Path(item["entrypoint_path"])
        entrypoint_required = bool(item.get("entrypoint_required", True))
        entrypoint_severity = "fail" if entrypoint_required else "warn"
        checks.append(_check(
            entrypoint_path.exists(),
            "entrypoint_exists",
            f"{agent_id} entrypoint exists: {entrypoint_path}",
            severity=entrypoint_severity,
        ))
        checks.append(_check(
            _file_contains(entrypoint_path, ["AGENTLAB_MANAGED_START", "workspace-entry", "frontdesk-session", "role-session", "protocol-doctor"]),
            "entrypoint_managed_block_valid",
            f"{agent_id} entrypoint managed block is present and complete",
            severity=entrypoint_severity,
        ))

        wrappers = item.get("wrappers") or {}
        for kind, wrapper in wrappers.items():
            wrapper_path = Path(wrapper)
            checks.append(_check(wrapper_path.exists(), "wrapper_exists", f"{agent_id} {kind} wrapper exists: {wrapper_path}"))
            checks.append(_check(os.access(wrapper_path, os.X_OK), "wrapper_executable", f"{agent_id} {kind} wrapper is executable"))
            required = ["protocol-doctor"]
            required.append("frontdesk-session" if kind == "frontdesk" else "role-session")
            if kind == "role":
                required.append("role-doctor")
            checks.append(_check(
                _file_contains(wrapper_path, required),
                "wrapper_protocol_compliant",
                f"{agent_id} {kind} wrapper calls required AgentLab protocol gates",
            ))

        profiles = set(item.get("profiles") or [])
        if profiles == {"frontdesk"}:
            checks.append(_check("role" not in wrappers, "frontdesk_only_has_no_role_wrapper", f"{agent_id} frontdesk-only agent has no role wrapper"))

    failed = [c for c in checks if c.status != "pass" and c.severity == "fail"]
    warnings = [c for c in checks if c.status != "pass" and c.severity == "warn"]
    return {
        "doctor": "cli_entrypoint_doctor",
        "status": "pass" if not failed else "fail",
        "summary": {
            "checks": len(checks),
            "failed": len(failed),
            "warnings": len(warnings),
        },
        "checks": [c.to_dict() for c in checks],
        "policy": str(root / "config" / "cli_entrypoint_policy.yml"),
    }
