"""CLI Agent Executor for AgentLab.

This module handles ``executor_type: cli_agent`` entries in
``config/agent_model_profiles.yml``.  When a role (Supervisor, Coder, …) is
configured to run via a local CLI agent such as *hermes* or *claude_code*,
``run_cli_agent`` is called in place of the normal API path.

Contract
--------
1. The task packet is written to ``<run_dir>/task_packet_<agent>.json`` before
   the CLI process is invoked.  This is the canonical handoff artefact required
   by the execution rules.
2. The CLI command template in the profile is rendered with the packet path.
3. The process is run with a configurable timeout (default 600 s).
4. stdout + stderr are captured and returned as an ``LLMCallResult`` so the
   rest of the pipeline (report writing, memory updates, audit) is unchanged.
5. If the CLI binary is **not found** the function returns a
   ``CliAgentNotAvailable`` sentinel so the caller can fall through to the API
   path without touching ``LLMCallResult``.

Caller responsibilities
-----------------------
``agent_runner.run_agent_model`` is responsible for:

- resolving the executor profile and detecting ``executor_type == "cli_agent"``
- calling ``run_cli_agent`` with the resolved profile config
- falling back to ``generate_text`` when this function returns a
  ``CliAgentNotAvailable`` instance
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from schemas import LLMCallResult, WorkflowPlan


# ── Sentinel: binary not installed, caller should use API fallback ────────────
@dataclass
class CliAgentNotAvailable:
    """Returned by run_cli_agent when the CLI binary cannot be exec'd.

    This is NOT an ``LLMCallResult`` so agent_runner can detect it with
    ``isinstance`` and transparently fall through to the direct API path.
    """

    cli_agent: str
    reason: str
    detail: str = ""


def budget_mode_to_tier(budget_mode: str) -> str:
    """Map the budget mode to one of the three tiers: full, performance, low."""
    mode_lower = str(budget_mode or "").lower().replace("-", "_")
    if mode_lower in {"frugal", "low", "low_cost"}:
        return "low"
    if mode_lower in {"balanced", "performance", "brain_allocated"}:
        return "performance"
    if mode_lower in {"max_quality", "full"}:
        return "full"
    return "performance"


def resolve_cli_profile(
    agent_model_profiles: dict[str, Any],
    agent_role: str,
    profile_name: str | None = None,
    budget_mode: str | None = None,
    mode: str | None = None,
) -> dict[str, Any] | None:
    """Return the CLI profile config for *agent_role*.

    Supports both schema v4 (``modes`` → tiers → role) and legacy
    (``profiles`` → role) config layouts.  Returns ``None`` when:

    - the profile or role is not found,
    - ``executor_type`` is not ``cli_agent``,
    - the role is configured as ``"skip"``, or
    - the role config is a plain string (not a dict).

    Args:
        agent_model_profiles: Parsed contents of ``config/agent_model_profiles.yml``.
        agent_role: Lower-cased role key, e.g. ``"supervisor"``, ``"coder"``.
        profile_name: Legacy profile name e.g. ``"balanced"`` — used only when
            the config has the old ``profiles`` key.
        budget_mode: Budget mode string (``"full"``, ``"performance"``, ``"low"``,
            ``"frugal"``, ``"balanced"``, ``"max_quality"``, …).  Mapped to tier.
        mode: Execution mode override (``"full_cli"``, ``"full_api"``, …).
            Falls back to ``AGENTLAB_MODE`` env var, then ``default_mode``,
            then ``"full_cli"``.
    """
    # ── Schema v4: modes → tiers → role ─────────────────────────────────
    modes = agent_model_profiles.get("modes", {}) or {}
    if modes:
        import os

        # Resolve mode
        resolved_mode: str | None = mode
        if not resolved_mode:
            resolved_mode = os.getenv("AGENTLAB_MODE")
        if not resolved_mode:
            resolved_mode = agent_model_profiles.get("default_mode", "full_cli")
        resolved_mode = str(resolved_mode or "full_cli").strip().lower()

        # Resolve tier
        resolved_tier = budget_mode_to_tier(budget_mode or os.getenv("AGENTLAB_BUDGET_MODE", "performance"))

        # Traverse: modes → mode_cfg → tiers → tier_cfg → role_cfg
        mode_cfg = modes.get(resolved_mode, {}) or {}
        tiers = mode_cfg.get("tiers", {}) or {}
        tier_cfg = tiers.get(resolved_tier, {}) or {}
        role_cfg_raw = tier_cfg.get(agent_role)

        # String "skip" → None
        if isinstance(role_cfg_raw, str):
            if role_cfg_raw.strip().lower() in {"skip", "skip_unless_required"}:
                return None
            return None  # other plain string: not a valid CLI profile

        if not isinstance(role_cfg_raw, dict):
            return None

        role_cfg = role_cfg_raw

        # Safety gate: trusted_headless_cli requires explicit env opt-in
        if resolved_mode == "trusted_headless_cli":
            safety = mode_cfg.get("safety", {}) or {}
            requires_env = safety.get("requires_env", {}) or {}
            for env_key, env_val in requires_env.items():
                if os.getenv(env_key) != str(env_val):
                    return None  # gate not satisfied
            if safety.get("never_default") and not mode:
                # Only allow when explicitly requested via mode arg, not from env or default
                if not (os.getenv("AGENTLAB_MODE") == "trusted_headless_cli"):
                    return None

        if role_cfg.get("executor_type") != "cli_agent":
            return None

        return {
            "executor_type": "cli_agent",
            "cli_agent": role_cfg.get("cli_agent", ""),
            "cli_command": role_cfg.get("cli_command", ""),
            "default": role_cfg.get("default", ""),
            "fallback": role_cfg.get("fallback", role_cfg.get("default", "")),
            "external_ide_allowed": role_cfg.get("external_ide_allowed", False),
            "resolved_mode": resolved_mode,
            "resolved_tier": resolved_tier,
            "resolved_schema": "modes_v4",
            # Pass through any extra keys (provider, temperature overrides, etc.)
            **{k: v for k, v in role_cfg.items()
               if k not in {"executor_type", "cli_agent", "cli_command",
                             "default", "fallback", "external_ide_allowed"}},
        }

    # ── Legacy schema: profiles → role ──────────────────────────────────
    profiles = agent_model_profiles.get("profiles", {}) or {}
    legacy_name = profile_name or budget_mode or "balanced"
    # Normalize budget_mode style names to legacy profile names
    _legacy_map = {
        "full": "max_quality",
        "performance": "balanced",
        "low": "frugal",
    }
    legacy_lookup = _legacy_map.get(legacy_name, legacy_name)
    profile = profiles.get(legacy_lookup, {}) or {}
    role_cfg = profile.get(agent_role, {}) or {}
    if not isinstance(role_cfg, dict):
        return None
    if role_cfg.get("executor_type") != "cli_agent":
        return None
    return {
        "executor_type": "cli_agent",
        "cli_agent": role_cfg.get("cli_agent", ""),
        "cli_command": role_cfg.get("cli_command", ""),
        "default": role_cfg.get("default", ""),
        "fallback": role_cfg.get("fallback", role_cfg.get("default", "")),
        "external_ide_allowed": role_cfg.get("external_ide_allowed", False),
        "resolved_mode": legacy_lookup,
        "resolved_tier": "legacy",
        "resolved_schema": "legacy_profiles",
        **{k: v for k, v in role_cfg.items()
           if k not in {"executor_type", "cli_agent", "cli_command",
                         "default", "fallback", "external_ide_allowed"}},
    }


def _write_task_packet(run_dir: Path, agent_name: str, plan: WorkflowPlan) -> Path:
    """Serialise a minimal task packet for the CLI agent and return its path."""
    packet = {
        "schema_version": 1,
        "agent": agent_name,
        "project": plan.project,
        "task_id": plan.task_id,
        "agentlab_root": plan.agentlab_root,
        "project_root": plan.project_root,
        "run_dir": plan.run_dir,
        "user_request_path": plan.user_request_path,
        "execution_backend": plan.execution_backend,
        "budget_mode": plan.budget_mode,
        "risk_level": plan.risk_level,
        "route": plan.route.model_dump(mode="json"),
        "included_agents": plan.included_agents,
        "model_profiles": plan.model_profiles,
        "validation_gates": plan.validation_gates,
        "repository_handoff": {
            "policy": str(Path(plan.agentlab_root) / "config" / "repository_handoff_policy.yml"),
            "project_local_candidates": [
                str(Path(plan.project_root) / ".agentlab" / "HandOff.md"),
                str(Path(plan.project_root) / "agent_docs" / "HandOff.md"),
            ],
            "discover_before_read": True,
            "create_if_missing_before_deep_read": True,
            "refresh_after_material_change": True,
            "refresh_before_final_report": True,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    packet_path = run_dir / f"task_packet_{agent_name.lower()}.json"
    packet_path.write_text(json.dumps(packet, indent=2, ensure_ascii=False), encoding="utf-8")
    return packet_path


def _render_command(cli_command_template: str, task_packet_path: Path) -> list[str]:
    """Expand the CLI command template and split into argv tokens.

    Supported placeholder: ``{task_packet_path}``.
    Falls back to appending the packet path if no placeholder is present.
    """
    rendered = cli_command_template.replace(
        "{task_packet_path}", str(task_packet_path)
    )
    if str(task_packet_path) not in rendered:
        rendered = rendered.rstrip() + f" {task_packet_path}"
    # Split respecting simple quoting (no shell glob expansion needed here)
    import shlex
    return shlex.split(rendered)


def _resolve_binary_candidate(candidates: list[str]) -> str | None:
    """Return the first available binary from *candidates*, or ``None``.

    Each candidate is checked via :func:`shutil.which`.  The first match
    wins; order matters — put the canonical binary first and legacy
    aliases later.
    """
    for candidate in candidates:
        if shutil.which(candidate):
            return candidate
    return None


def _binary_available(argv: list[str]) -> bool:
    """Return True if the first token of *argv* resolves to an executable."""
    if not argv:
        return False
    return shutil.which(argv[0]) is not None


def _looks_like_cli_usage_error(stderr_text: str) -> bool:
    """Return True when a present CLI rejected AgentLab's command template.

    Argparse-style usage failures mean the binary exists, but the configured
    template is incompatible with the real CLI surface. Treat that like an
    unavailable CLI executor so callers can use the configured direct-API
    fallback instead of blocking the whole run.
    """
    lowered = stderr_text.lower()
    return "usage:" in lowered and (
        "unrecognized arguments" in lowered
        or "no such option" in lowered
        or "unknown option" in lowered
        or "invalid option" in lowered
    )


def run_cli_agent(
    plan: WorkflowPlan,
    agent_name: str,
    role_profile: dict[str, Any],
    *,
    timeout: int | None = None,
) -> LLMCallResult:
    """Invoke the CLI agent described in *role_profile* and return its output.

    Args:
        plan: The active ``WorkflowPlan``.
        agent_name: AgentLab canonical agent name, e.g. ``"Supervisor"``.
        role_profile: The resolved role config dict from
            ``config/agent_model_profiles.yml`` (already confirmed
            ``executor_type == "cli_agent"``).
        timeout: Override process timeout in seconds.  Defaults to the
            ``AGENTLAB_CLI_AGENT_TIMEOUT`` env var, or 600 s.

    Returns:
        An ``LLMCallResult`` whose ``status`` is:

        - ``"completed"``  — CLI agent exited 0.
        - ``"blocked_user_decision"``  — CLI agent failed or produced no output.
        - ``CLI_AGENT_NOT_AVAILABLE``  — binary not found; caller should fall
          back to the direct API path.
    """
    cli_agent_name: str = role_profile.get("cli_agent", "")
    cli_command_template: str = role_profile.get("cli_command", "")

    if not cli_agent_name or not cli_command_template:
        return CliAgentNotAvailable(
            cli_agent=cli_agent_name or "unknown",
            reason="missing_config",
            detail="Profile is missing cli_agent or cli_command.",
        )

    run_dir = Path(plan.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    packet_path = _write_task_packet(run_dir, agent_name, plan)
    argv = _render_command(cli_command_template, packet_path)

    # ── Binary candidate resolution ────────────────────────────────────────
    # If the role profile defines ``binary_candidates``, resolve the first
    # available binary and patch argv[0].  This allows the config to list a
    # canonical binary (e.g. ``claude``) while keeping legacy aliases
    # (e.g. ``ccs``) as fallbacks.
    binary_candidates: list[str] | None = role_profile.get("binary_candidates")
    candidate_used: str | None = None
    if binary_candidates:
        resolved = _resolve_binary_candidate(binary_candidates)
        if resolved is None:
            return CliAgentNotAvailable(
                cli_agent=cli_agent_name,
                reason="binary_not_found",
                detail=(
                    f"None of the configured binary candidates "
                    f"{binary_candidates!r} for CLI agent "
                    f"`{cli_agent_name}` were found in PATH. "
                    f"AgentLab will route this agent call through the direct "
                    f"API (configured fallback: "
                    f"`{role_profile.get('default', 'unset')}`). "
                    f"To enable the CLI agent, install `{cli_agent_name}` "
                    f"and ensure its binary is on PATH."
                ),
            )
        argv[0] = resolved
        candidate_used = resolved

    if not _binary_available(argv):
        return CliAgentNotAvailable(
            cli_agent=cli_agent_name,
            reason="binary_not_found",
            detail=(
                f"CLI agent `{argv[0]}` was not found in PATH. "
                f"AgentLab will route this agent call through the direct API "
                f"(configured fallback: `{role_profile.get('default', 'unset')}`). "
                f"To enable the CLI agent, install `{cli_agent_name}` and ensure "
                f"its binary is on PATH."
            ),
        )

    effective_timeout = timeout or int(
        os.getenv("AGENTLAB_CLI_AGENT_TIMEOUT", "600")
    )

    started_at = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
            cwd=plan.agentlab_root,
        )
    except subprocess.TimeoutExpired:
        return LLMCallResult(
            provider="agentlab-cli-executor",
            model=cli_agent_name,
            content=(
                f"# {agent_name} CLI Agent Timeout\n\n"
                f"Process `{argv[0]}` did not complete within {effective_timeout}s.\n\n"
                f"**Action required**: Check whether `{cli_agent_name}` is stuck, "
                f"then rerun or switch to API fallback."
            ),
            status="blocked_user_decision",
            error=f"CLI agent timed out after {effective_timeout}s.",
            raw_usage={"cli_agent": cli_agent_name, "timeout": effective_timeout},
        )
    except FileNotFoundError:
        return CliAgentNotAvailable(
            cli_agent=cli_agent_name,
            reason="file_not_found",
            detail=f"Binary `{argv[0]}` raised FileNotFoundError at exec time.",
        )

    finished_at = datetime.now(timezone.utc)
    duration_s = (finished_at - started_at).total_seconds()

    # ── Determine success ─────────────────────────────────────────────────────
    stdout_text = proc.stdout.strip()
    stderr_text = proc.stderr.strip()

    # Exit 127 means "command not found" in sh-style shells.
    if proc.returncode == 127:
        return CliAgentNotAvailable(
            cli_agent=cli_agent_name,
            reason="exit_127",
            detail=f"Shell exit 127: `{argv[0]}` not found.",
        )

    # Exit 2 + argparse usage usually means AgentLab's cli_command template is
    # stale for the installed CLI, e.g. `hermes --task ...` against Hermes,
    # which only supports `hermes -z PROMPT` / `hermes chat -q PROMPT`.
    if proc.returncode == 2 and _looks_like_cli_usage_error(stderr_text):
        return CliAgentNotAvailable(
            cli_agent=cli_agent_name,
            reason="invalid_cli_invocation",
            detail=(
                f"CLI agent `{argv[0]}` rejected the configured command template "
                f"with an argparse usage error. stderr: {stderr_text[:500]}"
            ),
        )

    success = proc.returncode == 0 and bool(stdout_text)

    # ── Build the canonical AgentLab report ──────────────────────────────────
    header = textwrap.dedent(f"""\
        # {agent_name} Report (CLI Agent: {cli_agent_name})

        - **Task**: {plan.task_id}
        - **Project**: {plan.project}
        - **CLI command**: `{' '.join(argv)}`
        - **Exit code**: {proc.returncode}
        - **Duration**: {duration_s:.1f}s
        - **Started**: {started_at.isoformat()}
    """)

    body = stdout_text if stdout_text else "(no stdout output)"
    stderr_section = (
        f"\n\n## stderr\n\n```\n{stderr_text}\n```" if stderr_text else ""
    )

    full_content = header + "\n## Output\n\n" + body + stderr_section

    result_status: str
    result_error: str | None
    if success:
        result_status = "completed"
        result_error = None
    else:
        result_status = "blocked_user_decision"
        result_error = (
            f"CLI agent exited {proc.returncode}."
            + (f" stderr: {stderr_text[:200]}" if stderr_text else "")
        )

    return LLMCallResult(
        provider="agentlab-cli-executor",
        model=cli_agent_name,
        content=full_content,
        status=result_status,
        error=result_error,
        raw_usage={
            "cli_agent": cli_agent_name,
            "binary": argv[0],
            "exit_code": proc.returncode,
            "duration_s": duration_s,
            "stdout_bytes": len(proc.stdout),
            "stderr_bytes": len(proc.stderr),
            "task_packet_path": str(packet_path),
            **({"binary_candidate_used": candidate_used} if candidate_used else {}),
        },
    )
