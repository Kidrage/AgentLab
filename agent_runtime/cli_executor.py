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
   ``CliAgentNotAvailable`` sentinel so the caller can block or select an
   explicitly approved same-role capacity route.

Caller responsibilities
-----------------------
``agent_runner.run_agent_model`` is responsible for:

- resolving the executor profile and detecting ``executor_type == "cli_agent"``
- calling ``run_cli_agent`` with the resolved profile config
- refusing provider-surface changes when this function returns a
  ``CliAgentNotAvailable`` instance
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import textwrap
import zipfile
import yaml
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    from agent_runtime.schemas import LLMCallResult, WorkflowPlan
    from agent_runtime.workers.cli_error_classifier import classify_cli_error
except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
    from schemas import LLMCallResult, WorkflowPlan
    from workers.cli_error_classifier import classify_cli_error


_CLI_CONTRACT_ALIASES = {
    "claude_code": "claude",
}
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")
_APPROX_CHARS_PER_TOKEN = 4
_OBSERVER_STAGED_SUFFIXES = {
    ".aac",
    ".avi",
    ".bmp",
    ".flac",
    ".gif",
    ".heic",
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".ogg",
    ".pdf",
    ".png",
    ".tif",
    ".tiff",
    ".wav",
    ".webm",
    ".webp",
}
_AGY_DIRECT_API_KEY_ENV_VARS = {
    "GEMINI_API_KEY",
    "GENAI_API_KEY",
    "GOOGLE_AI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "GOOGLE_GENAI_API_KEY",
}
_ALLOWED_CONTRACT_ENV_UNSETS = {
    "CLAUDE_CODE_EFFORT_LEVEL",
    *_AGY_DIRECT_API_KEY_ENV_VARS,
}
_CLAUDE_RUNTIME_RECEIPT_CONTRACTS = {
    "claude_supervisor_fallback",
    "claude_writer",
    "claude_writer_ultracode",
}


def _is_agy_direct_api_key_environment(name: str) -> bool:
    normalized = str(name).strip().upper()
    if normalized in _AGY_DIRECT_API_KEY_ENV_VARS:
        return True
    return "API_KEY" in normalized and any(
        marker in normalized
        for marker in ("GEMINI", "GENAI", "GENERATIVE_AI", "GOOGLE")
    )


# ── Sentinel: binary not installed, caller should use API fallback ────────────
@dataclass
class CliAgentNotAvailable:
    """Returned by run_cli_agent when the CLI binary cannot be exec'd.

    This is NOT an ``LLMCallResult`` so agent_runner can detect it with
    ``isinstance`` and refuse an unapproved provider-surface change.
    """

    cli_agent: str
    reason: str
    detail: str = ""


class StagedInputPostflightError(ValueError):
    """Content-free error for a governed staged visual input boundary."""

    def __init__(self, code: str, *, input_index: int | None = None) -> None:
        self.code = str(code)
        self.input_index = input_index
        suffix = f" (input_index={input_index})" if input_index is not None else ""
        super().__init__(f"{self.code}{suffix}")

    def as_issue(self) -> dict[str, Any]:
        issue: dict[str, Any] = {"code": self.code}
        if self.input_index is not None:
            issue["input_index"] = self.input_index
        return issue


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
        "external_ide_allowed": role_cfg.get("external_ide_allowed", False),
        "resolved_mode": legacy_lookup,
        "resolved_tier": "legacy",
        "resolved_schema": "legacy_profiles",
        **{k: v for k, v in role_cfg.items()
           if k not in {"executor_type", "cli_agent", "cli_command",
                         "default", "fallback", "external_ide_allowed"}},
    }


def _writer_activation_packet_fields(
    agent_name: str,
    plan: WorkflowPlan,
) -> dict[str, Any]:
    """Return explicit, machine-readable Writer workflow activation fields."""

    if agent_name != "Writer":
        return {}
    writer_plan = plan.included_agents.get("Writer") or {}
    if not isinstance(writer_plan, dict):
        return {}
    return {
        key: writer_plan[key]
        for key in ("ultracode_opt_in", "writer_mode", "work_type")
        if key in writer_plan
    }


def _task_packet_payload(
    agent_name: str,
    plan: WorkflowPlan,
    sealed_messages: list[dict[str, str]] | None = None,
    task_messages: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    required_outputs = list(
        (plan.included_agents.get(agent_name) or {}).get("required_outputs", [])
    )
    if agent_name == "ArtifactProducer":
        artifact_task_path = Path(plan.run_dir) / "artifact_task.yml"
        try:
            artifact_task = yaml.safe_load(
                artifact_task_path.read_text(encoding="utf-8")
            ) or {}
        except (OSError, yaml.YAMLError):
            artifact_task = {}
        artifact_required = (
            (artifact_task.get("validation") or {}).get("required_paths")
            if isinstance(artifact_task, dict)
            and isinstance(artifact_task.get("validation"), dict)
            else []
        )
        if isinstance(artifact_required, list) and artifact_required:
            required_outputs = [str(item) for item in artifact_required]
    if sealed_messages is not None:
        artifact_session = agent_name == "ArtifactProducer"
        researcher_session = agent_name == "Researcher"
        return {
            "schema_version": 2,
            "packet_type": "agentlab_sealed_role_session",
            "agent": agent_name,
            "project": plan.project,
            "task_id": plan.task_id,
            "workflow_driver": plan.execution_backend,
            "budget_mode": plan.budget_mode,
            "risk_level": plan.risk_level,
            "context_policy": {
                "mode": "sealed_messages_only",
                "read_scope": ["this_task_packet"],
                "additional_file_reads_allowed": False,
                "shell_browser_or_repository_scan_allowed": False,
                "external_domain_research_allowed": researcher_session,
                "provider_managed_external_search_only": researcher_session,
                "workspace_mutation_allowed": artifact_session,
                "write_scope": required_outputs if artifact_session else [],
                "return_stdout_only": not artifact_session,
                "returned_artifacts_require_agentlab_materialization": artifact_session,
            },
            "required_outputs": required_outputs,
            "messages": sealed_messages,
            **_writer_activation_packet_fields(agent_name, plan),
        }

    if task_messages is not None:
        artifact_session = agent_name == "ArtifactProducer"
        researcher_session = agent_name == "Researcher"
        return {
            "schema_version": 2,
            "packet_type": "agentlab_production_pack_role_session",
            "agent": agent_name,
            "project": plan.project,
            "task_id": plan.task_id,
            "workflow_driver": plan.execution_backend,
            "budget_mode": plan.budget_mode,
            "risk_level": plan.risk_level,
            "context_policy": {
                "mode": "embedded_messages_only",
                "read_scope": ["this_task_packet"],
                "additional_file_reads_allowed": False,
                "repository_scan_allowed": False,
                "workspace_mutation_allowed": artifact_session,
                "write_scope": required_outputs if artifact_session else [],
                "external_domain_research_allowed": researcher_session,
                "provider_managed_external_search_only": researcher_session,
                "return_stdout_only": not artifact_session,
                "returned_artifacts_require_agentlab_materialization": artifact_session,
            },
            "required_outputs": required_outputs,
            "messages": task_messages,
            **_writer_activation_packet_fields(agent_name, plan),
        }

    payload = {
        "schema_version": 1,
        "agent": agent_name,
        "project": plan.project,
        "task_id": plan.task_id,
        "agentlab_root": plan.agentlab_root,
        "project_root": plan.project_root,
        "run_dir": plan.run_dir,
        "user_request_path": plan.user_request_path,
        "workflow_driver": plan.execution_backend,
        "budget_mode": plan.budget_mode,
        "risk_level": plan.risk_level,
        "route": plan.route.model_dump(mode="json"),
        "included_agents": plan.included_agents,
        "model_profiles": plan.model_profiles,
        "validation_gates": plan.validation_gates,
        "repository_handoff": {
            "policy": str(Path(plan.agentlab_root) / "config" / "repository_handoff_policy.yml"),
            "canonical_path": str(Path(plan.project_root) / "PROJECT_HANDOFF.md"),
            "legacy_aliases_are_read_only": True,
            "discover_before_read": True,
            "create_if_missing_before_deep_read": True,
            "refresh_after_material_change": True,
            "refresh_before_final_report": True,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **_writer_activation_packet_fields(agent_name, plan),
    }
    return payload


def _write_task_packet(
    run_dir: Path,
    agent_name: str,
    plan: WorkflowPlan,
    sealed_messages: list[dict[str, str]] | None = None,
    task_messages: list[dict[str, str]] | None = None,
) -> Path:
    """Serialise a task packet for the CLI agent and return its path."""
    packet = _task_packet_payload(
        agent_name,
        plan,
        sealed_messages,
        task_messages,
    )
    packet_path = run_dir / f"task_packet_{agent_name.lower()}.json"
    packet_path.write_text(json.dumps(packet, indent=2, ensure_ascii=False), encoding="utf-8")
    return packet_path


def _materialize_isolated_artifact_outputs(
    execution_cwd: Path,
    plan: WorkflowPlan,
    required_outputs: list[str],
) -> dict[str, Any]:
    """Copy only declared ArtifactTask outputs from the isolated workspace."""

    project_root = Path(plan.project_root).resolve(strict=False)
    expected_prefix = ("runs", str(plan.task_id))
    materialized: list[dict[str, Any]] = []
    missing: list[str] = []
    blocked: list[dict[str, str]] = []
    total_bytes = 0
    max_total_bytes = 512 * 1024 * 1024

    def format_issue(path: Path) -> str | None:
        suffix = path.suffix.lower()
        def header(size: int) -> bytes:
            with path.open("rb") as stream:
                return stream.read(size)

        if path.stat().st_size <= 0:
            return "empty_file"
        if suffix in {".xlsx", ".docx", ".pptx"}:
            if not zipfile.is_zipfile(path):
                return "invalid_office_zip"
            required_entry = {
                ".xlsx": "xl/workbook.xml",
                ".docx": "word/document.xml",
                ".pptx": "ppt/presentation.xml",
            }[suffix]
            try:
                with zipfile.ZipFile(path) as package:
                    names = set(package.namelist())
            except (OSError, zipfile.BadZipFile):
                return "invalid_office_zip"
            if "[Content_Types].xml" not in names or required_entry not in names:
                return f"missing_office_entry:{required_entry}"
        elif suffix == ".pdf":
            if header(5) != b"%PDF-":
                return "invalid_pdf_signature"
        elif suffix == ".png":
            if header(8) != b"\x89PNG\r\n\x1a\n":
                return "invalid_png_signature"
        elif suffix in {".jpg", ".jpeg"}:
            if header(3) != b"\xff\xd8\xff":
                return "invalid_jpeg_signature"
        elif suffix == ".webp":
            value = header(12)
            if len(value) < 12 or value[:4] != b"RIFF" or value[8:] != b"WEBP":
                return "invalid_webp_signature"
        elif suffix in {".mp4", ".mov"}:
            value = header(12)
            if len(value) < 12 or value[4:8] != b"ftyp":
                return "invalid_iso_media_signature"
        elif suffix in {".yaml", ".yml"}:
            try:
                yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, yaml.YAMLError):
                return "invalid_yaml"
        elif suffix in {".md", ".markdown", ".txt", ".csv", ".json"}:
            try:
                path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return "invalid_utf8_text"
        return None

    def copy_one(source: Path, target: Path, relative_path: str) -> None:
        nonlocal total_bytes
        if source.is_symlink():
            blocked.append({"path": relative_path, "reason": "symlink_not_allowed"})
            return
        resolved_target = target.resolve(strict=False)
        try:
            resolved_target.relative_to(project_root)
        except ValueError:
            blocked.append({"path": relative_path, "reason": "target_path_escape"})
            return
        current = target.parent
        while current != project_root and current != current.parent:
            if current.is_symlink():
                blocked.append(
                    {"path": relative_path, "reason": "target_parent_symlink"}
                )
                return
            current = current.parent
        issue = format_issue(source)
        if issue:
            blocked.append({"path": relative_path, "reason": issue})
            return
        size = source.stat().st_size
        total_bytes += size
        if total_bytes > max_total_bytes:
            blocked.append(
                {"path": relative_path, "reason": "materialization_size_limit"}
            )
            return
        resolved_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, resolved_target)
        materialized.append(
            {
                "path": relative_path,
                "byte_count": size,
                "sha256": _sha256_file(resolved_target),
            }
        )

    for raw in required_outputs:
        relative = Path(str(raw))
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.parts[:2] != expected_prefix
        ):
            blocked.append(
                {"path": str(raw), "reason": "outside_current_task_run"}
            )
            continue
        source = execution_cwd / relative
        target = (project_root / relative).resolve(strict=False)
        try:
            source.parent.resolve(strict=False).relative_to(
                execution_cwd.resolve(strict=False)
            )
            target.relative_to(project_root)
        except ValueError:
            blocked.append({"path": str(raw), "reason": "path_escape"})
            continue
        if not source.exists():
            missing.append(relative.as_posix())
            continue
        if source.is_file():
            copy_one(source, target, relative.as_posix())
            continue
        if not source.is_dir() or source.is_symlink():
            blocked.append(
                {"path": relative.as_posix(), "reason": "unsupported_file_type"}
            )
            continue
        copied_any = False
        for child in sorted(source.rglob("*")):
            if child.is_dir():
                continue
            child_rel = child.relative_to(execution_cwd)
            copy_one(child, project_root / child_rel, child_rel.as_posix())
            copied_any = True
        if not copied_any:
            missing.append(relative.as_posix())

    status = "pass" if not missing and not blocked else "fail"
    receipt = {
        "schema_version": 1,
        "status": status,
        "role": "ArtifactProducer",
        "task_id": plan.task_id,
        "isolated_workspace": True,
        "required_outputs": required_outputs,
        "materialized": materialized,
        "missing": missing,
        "blocked": blocked,
        "total_bytes": total_bytes,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    receipt_path = Path(plan.run_dir) / "artifact_materialization_receipt.yml"
    receipt_path.write_text(
        yaml.safe_dump(receipt, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return {**receipt, "receipt_path": str(receipt_path)}


def _estimate_text_tokens(*texts: str) -> int:
    """Approximate tokenizer usage when an external CLI hides provider telemetry."""
    chars = sum(len(text or "") for text in texts)
    if chars <= 0:
        return 0
    return max(1, (chars + _APPROX_CHARS_PER_TOKEN - 1) // _APPROX_CHARS_PER_TOKEN)


def _external_cli_usage_estimate(
    packet_path: Path,
    argv: list[str],
    stdout: str = "",
    stderr: str = "",
) -> dict[str, Any]:
    try:
        packet_text = packet_path.read_text(encoding="utf-8")
    except OSError:
        packet_text = ""
    input_tokens = _estimate_text_tokens(packet_text, shlex.join(argv))
    output_tokens = _estimate_text_tokens(stdout, stderr)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "usage_source": "external_cli_estimate",
        "token_estimation_method": "chars_div_4_packet_command_stdout_stderr",
        "exact_usage_available": False,
        "exact_cost_available": False,
    }


def _coerce_usage_payload(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    envelope = raw
    payload = raw.get("agentlab_usage")
    if not isinstance(payload, dict):
        payload = raw.get("usage") if isinstance(raw.get("usage"), dict) else raw
    if not isinstance(payload, dict):
        return None
    usage: dict[str, Any] = {}
    for target, aliases in {
        "input_tokens": ("input_tokens", "prompt_tokens"),
        "output_tokens": ("output_tokens", "completion_tokens"),
        "cache_creation_input_tokens": ("cache_creation_input_tokens",),
        "cache_read_input_tokens": ("cache_read_input_tokens", "cached_input_tokens"),
        "total_tokens": ("total_tokens",),
    }.items():
        for alias in aliases:
            if payload.get(alias) is None:
                continue
            try:
                usage[target] = max(int(payload[alias]), 0)
            except (TypeError, ValueError):
                pass
            break
    if "total_tokens" not in usage and any(
        key in usage
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
    ):
        usage["total_tokens"] = sum(
            int(usage.get(key, 0))
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            )
        )
    if not usage:
        return None
    for key in (
        "estimated_cost",
        "cost_currency",
        "currency",
        "pricing_source",
        "pricing_confidence",
        "exact_cost_available",
        "token_estimation_method",
    ):
        value = payload.get(key)
        if value is None:
            value = envelope.get(key)
        if value is not None:
            usage[key] = value

    provider_cost = envelope.get("total_cost_usd")
    if provider_cost is not None and usage.get("estimated_cost") is None:
        try:
            usage["estimated_cost"] = max(float(provider_cost), 0.0)
        except (TypeError, ValueError):
            pass
        else:
            usage["cost_currency"] = "USD"
            usage["exact_cost_available"] = True
            usage["pricing_source"] = "provider_response"
            usage["pricing_confidence"] = "high"
            usage["billing_mode"] = "provider_reported"

    model_usage = envelope.get("modelUsage")
    if isinstance(model_usage, dict) and model_usage:
        usage["provider_reported_model_ids"] = sorted(str(key) for key in model_usage)
    if envelope.get("model"):
        usage["provider_reported_model_id"] = str(envelope["model"])
    if envelope.get("session_id"):
        usage["provider_reported_session_id"] = str(envelope["session_id"])

    usage["usage_source"] = (
        payload.get("usage_source")
        or envelope.get("usage_source")
        or "external_cli_reported"
    )
    exact_usage = payload.get(
        "exact_usage_available",
        envelope.get("exact_usage_available", True),
    )
    if isinstance(exact_usage, str):
        usage["exact_usage_available"] = exact_usage.strip().lower() not in {"false", "0", "no", "n"}
    else:
        usage["exact_usage_available"] = bool(exact_usage)
    return usage


def _load_cli_usage_sidecar(packet_path: Path, agent_name: str, cli_agent_name: str) -> dict[str, Any] | None:
    candidates = [
        packet_path.with_suffix(".usage.json"),
        packet_path.parent / f"usage_{agent_name.lower()}.json",
        packet_path.parent / f"usage_{cli_agent_name.lower()}.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        usage = _coerce_usage_payload(payload)
        if usage:
            usage["usage_report_path"] = str(path)
            return usage
    return None


def _extract_cli_usage_from_output(stdout: str, stderr: str) -> dict[str, Any] | None:
    whole_stdout = stdout.strip()
    if whole_stdout.startswith(("{", "[")):
        try:
            parsed = json.loads(whole_stdout)
        except json.JSONDecodeError:
            parsed = None
        candidates = reversed(parsed) if isinstance(parsed, list) else [parsed]
        for candidate in candidates:
            usage = _coerce_usage_payload(candidate)
            if usage:
                return usage
    for line in reversed((stdout + "\n" + stderr).splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("AGENTLAB_USAGE:"):
            stripped = stripped.split(":", 1)[1].strip()
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or not any(
            key in payload for key in ("agentlab_usage", "usage", "input_tokens")
        ):
            continue
        usage = _coerce_usage_payload(payload)
        if usage:
            return usage
    return None


def _extract_cli_result_text(stdout: str, cli_agent_name: str) -> str:
    """Return the provider's textual result while retaining raw stdout in logs."""
    if cli_agent_name not in {"claude_code", "qwen", "codex"}:
        return stdout.strip()
    if cli_agent_name == "codex":
        result = ""
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            item = event.get("item") if isinstance(event, dict) else None
            if (
                isinstance(item, dict)
                and item.get("type") == "agent_message"
                and isinstance(item.get("text"), str)
                and item["text"].strip()
            ):
                result = item["text"].strip()
        return result or stdout.strip()
    try:
        payload = json.loads(stdout.strip())
    except (json.JSONDecodeError, TypeError):
        return stdout.strip()
    candidates = reversed(payload) if isinstance(payload, list) else [payload]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        result = candidate.get("result")
        if isinstance(result, str) and result.strip():
            return result.strip()
    return stdout.strip()


def _narrative_heavy_audit_output_schema(
    agent_name: str,
    *,
    blocking_rewrite_required: bool = False,
) -> dict[str, Any]:
    from agent_runtime.narrative_heavy_audit import HEAVY_AUDIT_OUTPUTS_BY_AGENT

    required_outputs = HEAVY_AUDIT_OUTPUTS_BY_AGENT.get(agent_name, ())

    def content_schema(name: str) -> dict[str, Any]:
        properties: dict[str, Any] = {
            "schema_version": {"enum": [1, "1"]},
            "candidate_only": {"enum": [True, "true"]},
            "production_modified": {"enum": [False, "false"]},
        }
        required = ["schema_version", "candidate_only", "production_modified"]
        if name == "fiction_review.yml":
            properties.update(
                {
                    "status": {"enum": ["pass", "warn", "blocked"]},
                    "findings": {"type": "array"},
                }
            )
            required.extend(["status", "findings"])
        elif name == "continuity_failure_report.yml":
            properties.update(
                {
                    "status": {"enum": ["pass", "warn", "blocked"]},
                    "blocking_issue_count": {
                        "anyOf": [
                            {"type": "integer", "minimum": 0},
                            {"type": "string", "pattern": "^[0-9]+$"},
                        ]
                    },
                    "failures": {"type": "array"},
                }
            )
            required.extend(["status", "blocking_issue_count", "failures"])
        elif name == "narrative_quality_scorecard.yml":
            dimension_names = (
                "causal_reasoning",
                "strategic_competence",
                "character_agency",
                "dramatic_tension",
                "reader_curiosity",
                "non_formulaic_progression",
            )
            evidence_schema = {
                "type": "object",
                "required": ["chapter", "scene", "excerpt_or_locator"],
                "properties": {
                    "chapter": {"type": "integer", "minimum": 1},
                    "scene": {"type": "string", "minLength": 1},
                    "excerpt_or_locator": {"type": "string", "minLength": 1},
                },
                "additionalProperties": True,
            }
            dimension_schema = {
                "type": "object",
                "required": [
                    "score",
                    "severity",
                    "evidence",
                    "reason",
                    "revision_target",
                ],
                "properties": {
                    "score": {"type": "integer", "minimum": 1, "maximum": 5},
                    "severity": {"enum": ["blocking", "warn", "pass"]},
                    "evidence": evidence_schema,
                    "reason": {"type": "string", "minLength": 1},
                    "revision_target": {"type": "string", "minLength": 1},
                },
                "additionalProperties": True,
            }
            properties.update(
                {
                    "status": {"enum": ["pass", "warn", "blocked"]},
                    "candidate_sha256": {"type": "string", "minLength": 1},
                    "chapters": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["chapter_id", "status", "dimensions"],
                            "properties": {
                                "chapter_id": {"type": "integer", "minimum": 1},
                                "status": {"enum": ["pass", "warn", "blocked"]},
                                "dimensions": {
                                    "type": "object",
                                    "required": list(dimension_names),
                                    "properties": {
                                        dimension: dimension_schema
                                        for dimension in dimension_names
                                    },
                                    "additionalProperties": False,
                                },
                            },
                            "additionalProperties": False,
                        },
                    },
                }
            )
            required.extend(["status", "candidate_sha256", "chapters"])
        elif name == "state_transition_proposal.yml":
            properties.update(
                {
                    "status": {"const": "candidate"},
                    "requires_user_promotion": {"enum": [True, "true"]},
                    "events": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["scope"],
                            "properties": {
                                "scope": {"const": "candidate_only"},
                            },
                            "additionalProperties": True,
                        },
                    },
                }
            )
            required.extend(["status", "requires_user_promotion", "events"])
        elif name == "revision_or_rewrite_proposal.yml":
            properties.update(
                {
                    "status": (
                        {"const": "proposed"}
                        if blocking_rewrite_required
                        else {"enum": ["not_required", "proposed", "blocked"]}
                    ),
                    "rewrite_required": (
                        {"enum": [True, "true"]}
                        if blocking_rewrite_required
                        else {"enum": [True, False, "true", "false"]}
                    ),
                    "direct_draft_edits": {"enum": [False, "false"]},
                    "proposals": {
                        "type": "array",
                        "minItems": 1 if blocking_rewrite_required else 0,
                        "items": {
                            "type": "object",
                            "required": [
                                "chapter_id",
                                "target_scene",
                                "problem_type",
                                "evidence",
                                "must_preserve",
                                "must_change",
                                "allowed_freedom",
                                "causal_requirements",
                                "character_knowledge_before",
                                "character_knowledge_after",
                                "decision_cost",
                                "new_information",
                                "forbidden_regressions",
                            ],
                            "properties": {
                                "chapter_id": {"type": "integer", "minimum": 1},
                                "target_scene": {"type": "string", "minLength": 1},
                                "problem_type": {"type": "string", "minLength": 1},
                                "evidence": {"type": "string", "minLength": 1},
                                "must_preserve": {"type": "array", "minItems": 1},
                                "must_change": {"type": "array", "minItems": 1},
                                "allowed_freedom": {"type": "string", "minLength": 1},
                                "causal_requirements": {"type": "array", "minItems": 1},
                                "character_knowledge_before": {"type": "array", "minItems": 1},
                                "character_knowledge_after": {"type": "array", "minItems": 1},
                                "decision_cost": {"type": "string", "minLength": 1},
                                "new_information": {"type": "string", "minLength": 1},
                                "forbidden_regressions": {"type": "array", "minItems": 1},
                            },
                            "additionalProperties": True,
                        },
                    },
                }
            )
            required.extend(
                ["status", "rewrite_required", "direct_draft_edits", "proposals"]
            )
        return {
            "type": "object",
            "required": required,
            "properties": properties,
            "additionalProperties": True,
        }

    if len(required_outputs) == 1:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **content_schema(required_outputs[0]),
        }

    output_keys = {
        name: name.removesuffix(".yml")
        for name in required_outputs
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": list(output_keys.values()),
        "properties": {
            output_key: content_schema(name)
            for name, output_key in output_keys.items()
        },
        "additionalProperties": False,
    }


def _find_narrative_heavy_audit_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if isinstance(value.get("files"), list):
            return value
        for child in value.values():
            found = _find_narrative_heavy_audit_payload(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in reversed(value):
            found = _find_narrative_heavy_audit_payload(child)
            if found is not None:
                return found
    elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return _find_narrative_heavy_audit_payload(parsed)
    return None


def _find_narrative_heavy_audit_bundle(
    value: Any,
    required: tuple[str, ...],
) -> dict[str, dict[str, Any]] | None:
    output_keys = {name: name.removesuffix(".yml") for name in required}
    if isinstance(value, dict):
        if all(
            isinstance(value.get(output_key), dict)
            for output_key in output_keys.values()
        ):
            return {
                name: value[output_key]
                for name, output_key in output_keys.items()
            }
        for child in reversed(list(value.values())):
            found = _find_narrative_heavy_audit_bundle(child, required)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in reversed(value):
            found = _find_narrative_heavy_audit_bundle(child, required)
            if found is not None:
                return found
    elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return _find_narrative_heavy_audit_bundle(parsed, required)
    return None


def _narrative_heavy_audit_content_keys(name: str) -> set[str]:
    common = {"schema_version", "candidate_only", "production_modified"}
    role_keys = {
        "fiction_review.yml": {"status", "findings"},
        "continuity_failure_report.yml": {
            "status",
            "blocking_issue_count",
            "failures",
        },
        "narrative_quality_scorecard.yml": {
            "status",
            "candidate_sha256",
            "chapters",
        },
        "state_transition_proposal.yml": {
            "status",
            "requires_user_promotion",
            "events",
        },
        "revision_or_rewrite_proposal.yml": {
            "status",
            "rewrite_required",
            "direct_draft_edits",
            "proposals",
        },
    }
    return common | role_keys.get(name, set())


def _find_narrative_heavy_audit_content(
    value: Any,
    name: str,
) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if _narrative_heavy_audit_content_keys(name) <= set(value):
            return value
        for child in reversed(list(value.values())):
            found = _find_narrative_heavy_audit_content(child, name)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in reversed(value):
            found = _find_narrative_heavy_audit_content(child, name)
            if found is not None:
                return found
    elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return _find_narrative_heavy_audit_content(parsed, name)
    return None


def _canonicalize_narrative_heavy_audit_content(
    content: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(content)
    if normalized.get("schema_version") == "1":
        normalized["schema_version"] = 1
    for key in (
        "candidate_only",
        "production_modified",
        "requires_user_promotion",
        "rewrite_required",
        "direct_draft_edits",
    ):
        value = normalized.get(key)
        if value == "true":
            normalized[key] = True
        elif value == "false":
            normalized[key] = False
    blocking_count = normalized.get("blocking_issue_count")
    if isinstance(blocking_count, str) and blocking_count.isdigit():
        normalized["blocking_issue_count"] = int(blocking_count)
    return normalized


def _narrative_heavy_audit_requires_rewrite(run_dir: Path) -> bool:
    path = run_dir / "continuity_failure_report.yml"
    try:
        report = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return False
    try:
        blocking_count = int(report.get("blocking_issue_count") or 0)
    except (TypeError, ValueError):
        blocking_count = 0
    return blocking_count > 0 or report.get("status") == "blocked"


def _narrative_heavy_audit_blocks_from_output(
    stdout: str,
    agent_name: str,
) -> str | None:
    from agent_runtime.narrative_heavy_audit import HEAVY_AUDIT_OUTPUTS_BY_AGENT

    try:
        parsed: Any = json.loads(stdout.strip())
    except json.JSONDecodeError:
        parsed = []
        for line in stdout.splitlines():
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    required = HEAVY_AUDIT_OUTPUTS_BY_AGENT.get(agent_name, ())
    materialized: dict[str, dict[str, Any]] = {}
    if len(required) == 1:
        content = _find_narrative_heavy_audit_content(parsed, required[0])
        if content is not None:
            materialized[required[0]] = _canonicalize_narrative_heavy_audit_content(
                content
            )
    else:
        bundle = _find_narrative_heavy_audit_bundle(parsed, required)
        if bundle is not None:
            materialized = {
                name: _canonicalize_narrative_heavy_audit_content(content)
                for name, content in bundle.items()
            }
        else:
            payload = _find_narrative_heavy_audit_payload(parsed)
            if payload is None:
                return None
            for item in payload.get("files", []):
                if not isinstance(item, dict):
                    return None
                name = str(item.get("name") or "")
                content = item.get("content")
                if name not in required or name in materialized or not isinstance(content, dict):
                    return None
                materialized[name] = _canonicalize_narrative_heavy_audit_content(
                    content
                )
    if set(materialized) != set(required):
        return None
    blocks = []
    for name in required:
        value = yaml.safe_dump(
            materialized[name],
            sort_keys=False,
            allow_unicode=True,
        ).rstrip()
        blocks.append(
            f"<!-- AGENTLAB_EDIT: {name} -->\n"
            f"{value}\n"
            "<!-- END AGENTLAB_EDIT -->"
        )
    return "\n\n".join(blocks)


def _external_cli_usage(
    packet_path: Path,
    argv: list[str],
    agent_name: str,
    cli_agent_name: str,
    stdout: str = "",
    stderr: str = "",
) -> dict[str, Any]:
    return (
        _load_cli_usage_sidecar(packet_path, agent_name, cli_agent_name)
        or _extract_cli_usage_from_output(stdout, stderr)
        or _external_cli_usage_estimate(packet_path, argv, stdout, stderr)
    )


def _render_command(
    cli_command_template: str,
    task_packet_path: Path,
    *,
    workspace_path: Path | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    model_key: str | None = None,
    append_task_packet_path: bool = True,
) -> list[str]:
    """Expand the CLI command template and split into argv tokens.

    Supported placeholders: ``{task_packet_path}``, ``{workspace_path}``,
    ``{provider}``, ``{model_id}``, and ``{model_key}``. Model placeholders are
    substituted only when the template explicitly contains them; AgentLab does
    not append model flags to CLIs implicitly.
    """
    replacements = {
        "task_packet_path": str(task_packet_path),
        "workspace_path": str(workspace_path or task_packet_path.parent),
        "provider": str(provider or ""),
        "model_id": str(model_id or model_key or ""),
        "model_key": str(model_key or model_id or ""),
    }
    rendered = cli_command_template
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{key}}}", value)

    unresolved = sorted(set(_PLACEHOLDER_RE.findall(rendered)))
    if unresolved:
        raise ValueError(
            "Unsupported CLI command placeholder(s): "
            + ", ".join(f"{{{name}}}" for name in unresolved)
        )

    if append_task_packet_path and str(task_packet_path) not in rendered:
        rendered = rendered.rstrip() + f" {task_packet_path}"
    # Split respecting simple quoting (no shell glob expansion needed here)
    import shlex
    return shlex.split(rendered)


def _ensure_cli_log_file_arg(argv: list[str], run_dir: Path, cli_agent_name: str) -> Path | None:
    if cli_agent_name != "agy" or "--log-file" in argv:
        return None
    log_dir = run_dir / "command_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    log_path = log_dir / f"agy_cli_agent_{stamp}_{uuid4().hex[:8]}.log"
    argv.extend(["--log-file", str(log_path)])
    return log_path


def _read_cli_log_excerpt(path: Path | None, limit: int = 4000) -> str:
    if not path or not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    priority_lines = [
        line
        for line in text.splitlines()
        if "CLI failed to start" in line
        or "operation not permitted" in line
        or "Settings fetch failed" in line
    ]
    if priority_lines:
        text = "\n".join(priority_lines[-8:])
    if len(text) <= limit:
        return text
    return text[-limit:]


def _agy_model_resolution_failed(
    path: Path | None,
    *,
    stdout: str = "",
    stderr: str = "",
) -> bool:
    evidence = [stdout, stderr]
    if path and path.is_file():
        evidence.append(path.read_text(encoding="utf-8", errors="replace"))
    text = "\n".join(evidence).lower()
    exact_markers = (
        "failed to resolve model flag",
        "is not recognized as a known model",
        "falling back to the default model",
        "falling back to default model",
        "using the default model instead",
        "using default model instead",
        "model resolution fallback",
    )
    return any(marker in text for marker in exact_markers)


def _augment_empty_stderr_with_cli_log(
    stderr_text: str,
    *,
    cli_log_path: Path | None,
    cli_agent_name: str,
) -> str:
    if stderr_text or cli_agent_name != "agy":
        return stderr_text
    excerpt = _read_cli_log_excerpt(cli_log_path)
    if not excerpt:
        return stderr_text
    return f"[{cli_agent_name} log excerpt]\n{excerpt}\n[{cli_agent_name} log path: {cli_log_path}]"


def _runtime_provider_for_catalog_model(model_entry: dict[str, Any]) -> str:
    catalog_provider = str(model_entry.get("provider", ""))
    model_id = str(model_entry.get("model_id", ""))

    if model_entry.get("runtime_provider"):
        return str(model_entry["runtime_provider"])
    if model_entry.get("cli_provider"):
        return str(model_entry["cli_provider"])
    if catalog_provider == "deepseek_official":
        return "deepseek"
    if catalog_provider in {"dashscope_cn", "dashscope_intl"}:
        if model_id.startswith("qwen3-coder"):
            return "qwen-coder"
        if "flash" in model_id:
            return "qwen-flash"
        if (
            model_id.startswith("qwen3.7")
            or model_id.startswith("qwen-max")
            or model_id.startswith("qwen3-max")
        ):
            return "qwen3"
        return "qwen"
    return catalog_provider


def _model_invocation_values(
    role_profile: dict[str, Any],
    agentlab_root: str | Path,
) -> dict[str, str]:
    """Resolve model placeholders for CLI templates from the model catalog."""
    model_key = str(role_profile.get("default") or role_profile.get("provider") or "")
    values = {
        "model_key": model_key,
        "model_id": str(role_profile.get("model_id") or model_key),
        "catalog_model_id": str(role_profile.get("model_id") or model_key),
        "catalog_provider": str(role_profile.get("provider") or ""),
        "provider": str(
            role_profile.get("cli_provider")
            or role_profile.get("runtime_provider")
            or role_profile.get("provider")
            or ""
        ),
    }
    if not model_key:
        return values

    catalog_path = Path(agentlab_root) / "config" / "model_catalog.yml"
    try:
        catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return values

    model_entry = (catalog.get("models") or {}).get(model_key) or {}
    if not model_entry:
        return values

    values["model_id"] = str(
        model_entry.get("cli_model_id")
        or model_entry.get("model_id")
        or values["model_id"]
    )
    values["catalog_model_id"] = str(
        model_entry.get("model_id") or values["catalog_model_id"]
    )
    values["catalog_provider"] = str(
        model_entry.get("provider") or values["catalog_provider"]
    )
    values["provider"] = _runtime_provider_for_catalog_model(model_entry)
    return values


def _resolve_invocation_contract(
    role_profile: dict[str, Any],
    agentlab_root: str | Path,
) -> dict[str, Any]:
    """Resolve the central worker invocation contract for a role profile."""
    contract_name = str(role_profile.get("invocation_contract") or "").strip()
    cli_agent = str(role_profile.get("cli_agent") or "").strip()
    contract_key = contract_name or _CLI_CONTRACT_ALIASES.get(cli_agent, cli_agent)
    if not contract_key:
        return {}

    config_path = Path(agentlab_root) / "config" / "worker_invocation_contracts.yml"
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    contract = (data.get("contracts") or {}).get(contract_key) or {}
    return contract if isinstance(contract, dict) else {}


def _resolve_invocation_contract_template(
    role_profile: dict[str, Any],
    agentlab_root: str | Path,
) -> str:
    """Resolve a CLI template from the central worker invocation contract.

    ``agent_model_profiles.yml`` decides *which* worker handles a role.
    ``worker_invocation_contracts.yml`` owns the actual command template.
    Existing ``cli_command`` values are still accepted as a compatibility
    fallback for older profiles and safety-gated special profiles.
    """
    explicit_template = str(role_profile.get("cli_command") or "")
    contract = _resolve_invocation_contract(role_profile, agentlab_root)
    template = str(contract.get("template") or "")
    return template or explicit_template


def _contract_process_environment(
    role_profile: dict[str, Any],
    agentlab_root: str | Path,
) -> tuple[dict[str, str], list[str]]:
    """Apply the narrow, audited environment changes declared by a contract."""
    process_env = os.environ.copy()
    contract = _resolve_invocation_contract(role_profile, agentlab_root)
    environment = contract.get("environment") or {}
    if (
        str(role_profile.get("invocation_contract") or "").strip()
        in {"qwen", "qwen_artifact", "qwen_narrative_audit"}
        and isinstance(environment, dict)
    ):
        source_name = str(environment.get("api_key_source") or "")
        target_name = str(environment.get("api_key_target") or "")
        source_value = process_env.get(source_name) if source_name else None
        if target_name == "OPENAI_API_KEY":
            process_env.pop(target_name, None)
            if source_value:
                process_env[target_name] = source_value
        base_target = str(environment.get("base_url_target") or "")
        base_value = str(environment.get("base_url") or "")
        if base_target == "OPENAI_BASE_URL" and base_value:
            process_env[base_target] = base_value
    configured_unsets = environment.get("unset") if isinstance(environment, dict) else []
    requested_unsets = list(configured_unsets or [])
    if str(role_profile.get("cli_agent") or "").strip() == "agy":
        # Agy's governed Observer/Reviewer paths are OAuth-only. Inheriting a
        # Gemini API key would allow the child CLI to select a different billing
        # and provider surface without AgentLab observing that transition.
        requested_unsets.extend(sorted(_AGY_DIRECT_API_KEY_ENV_VARS))
        requested_unsets.extend(
            name
            for name in process_env
            if _is_agy_direct_api_key_environment(name)
        )
    applied: list[str] = []
    for name in requested_unsets:
        normalized = str(name).strip()
        if (
            normalized not in _ALLOWED_CONTRACT_ENV_UNSETS
            and not _is_agy_direct_api_key_environment(normalized)
        ):
            continue
        was_present = normalized in process_env
        process_env.pop(normalized, None)
        if was_present:
            applied.append(normalized)
    return process_env, sorted(set(applied))


def _agy_oauth_preflight(
    role_profile: dict[str, Any],
    argv: list[str],
    model_values: dict[str, str],
) -> dict[str, Any]:
    """Bind governed Agy execution to the selected OAuth model and command."""
    if str(role_profile.get("cli_agent") or "").strip() != "agy":
        return {"applicable": False, "status": "not_applicable", "issues": []}

    contract_name = str(role_profile.get("invocation_contract") or "").strip()
    governed = contract_name in {"agy_observer", "agy_visual_reviewer"}
    requested_model_key = str(model_values.get("model_key") or "")
    requested_cli_model_id = str(model_values.get("model_id") or "")
    requested_model_id = str(model_values.get("catalog_model_id") or "")
    provider = str(model_values.get("provider") or "")
    profile_binding_verified = bool(requested_model_key) and (
        str(role_profile.get("default") or "") == requested_model_key
    )
    command_binding_verified = False
    if argv and Path(argv[0]).name == "agy" and "--model" in argv:
        model_index = argv.index("--model")
        command_binding_verified = (
            model_index + 1 < len(argv)
            and bool(requested_cli_model_id)
            and argv[model_index + 1] == requested_cli_model_id
        )
        if governed:
            command_binding_verified = command_binding_verified and "--sandbox" in argv

    issues: list[str] = []
    if governed and not profile_binding_verified:
        issues.append("agy_profile_model_binding_mismatch")
    if governed and not command_binding_verified:
        issues.append("agy_command_model_binding_mismatch")
    if governed and provider not in {"agy-gemini-oauth", "agy-claude-oauth"}:
        issues.append("agy_oauth_provider_binding_mismatch")

    return {
        "applicable": True,
        "governed": governed,
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "invocation_contract": contract_name or None,
        "requested_model_key": requested_model_key or None,
        "requested_model_id": requested_model_id or None,
        "requested_cli_model_id": requested_cli_model_id or None,
        "provider": provider or None,
        "profile_binding_verified": profile_binding_verified,
        "command_binding_verified": command_binding_verified,
        "capacity_route": role_profile.get("capacity_selected_route"),
        "capacity_pool": role_profile.get("capacity_pool"),
        "attempt_id": role_profile.get("_runtime_model_execution_attempt_id"),
        "selection_kind": role_profile.get("_runtime_capacity_selection_kind"),
    }


def _qwen_artifact_preflight(
    role_profile: dict[str, Any],
    argv: list[str],
    model_values: dict[str, str],
    process_env: dict[str, str],
) -> dict[str, Any]:
    """Bind Qwen ArtifactProducer to DashScope, the exact model, and sandbox."""

    applicable = (
        str(role_profile.get("cli_agent") or "").strip() == "qwen"
        and str(role_profile.get("invocation_contract") or "").strip()
        == "qwen_artifact"
    )
    if not applicable:
        return {"applicable": False, "status": "not_applicable", "issues": []}

    requested_model_key = str(model_values.get("model_key") or "")
    requested_model_id = str(model_values.get("catalog_model_id") or "")
    requested_cli_model_id = str(model_values.get("model_id") or "")
    selected_provider = str(model_values.get("catalog_provider") or "")
    selected_runtime_provider = str(model_values.get("provider") or "")
    profile_binding_verified = bool(requested_model_key) and (
        str(role_profile.get("default") or "") == requested_model_key
    )

    def option_value(name: str) -> str | None:
        if name not in argv:
            return None
        index = argv.index(name)
        return argv[index + 1] if index + 1 < len(argv) else None

    expected_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    command_binding_verified = bool(argv) and all(
        (
            Path(argv[0]).name == "qwen",
            option_value("--auth-type") == "openai",
            option_value("--openai-base-url") == expected_base_url,
            option_value("--model") == requested_cli_model_id,
            option_value("--approval-mode") == "yolo",
            option_value("--output-format") == "json",
            "--bare" in argv,
            "--sandbox" in argv,
        )
    )
    source_key_configured = bool(process_env.get("DASHSCOPE_API_KEY"))
    target_key_bound = bool(process_env.get("OPENAI_API_KEY")) and (
        process_env.get("OPENAI_API_KEY") == process_env.get("DASHSCOPE_API_KEY")
    )
    base_environment_bound = process_env.get("OPENAI_BASE_URL") == expected_base_url
    issues: list[str] = []
    if not profile_binding_verified:
        issues.append("qwen_artifact_profile_model_binding_mismatch")
    if not command_binding_verified:
        issues.append("qwen_artifact_command_binding_mismatch")
    if selected_provider != "dashscope_cn":
        issues.append("qwen_artifact_provider_binding_mismatch")
    if not source_key_configured:
        issues.append("dashscope_api_key_missing")
    if not target_key_bound:
        issues.append("dashscope_api_key_environment_not_bound")
    if not base_environment_bound:
        issues.append("dashscope_base_url_environment_not_bound")
    return {
        "applicable": True,
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "invocation_contract": "qwen_artifact",
        "selected_provider": selected_provider or None,
        "selected_runtime_provider": selected_runtime_provider or None,
        "selected_model_key": requested_model_key or None,
        "selected_model_id": requested_model_id or None,
        "requested_cli_model_id": requested_cli_model_id or None,
        "profile_binding_verified": profile_binding_verified,
        "command_binding_verified": command_binding_verified,
        "auth_key_source": "DASHSCOPE_API_KEY",
        "auth_key_source_configured": source_key_configured,
        "auth_key_target": "OPENAI_API_KEY",
        "auth_key_target_bound": target_key_bound,
        "base_url": expected_base_url,
        "base_url_environment_bound": base_environment_bound,
        "capacity_route": role_profile.get("capacity_selected_route"),
        "capacity_pool": role_profile.get("capacity_pool"),
        "attempt_id": role_profile.get("_runtime_model_execution_attempt_id"),
        "selection_kind": role_profile.get("_runtime_capacity_selection_kind"),
    }


def _write_agy_model_receipt(
    run_dir: Path,
    agent_name: str,
    preflight: dict[str, Any],
    *,
    status: str,
    provider_process_started: bool,
    environment_unset: list[str],
    exit_code: int | None = None,
    stdout_nonempty: bool = False,
    timed_out: bool = False,
    fallback_detected: bool = False,
    extra_issues: list[str] | None = None,
) -> str | None:
    if not preflight.get("applicable"):
        return None
    issues = list(preflight.get("issues") or []) + list(extra_issues or [])
    if fallback_detected:
        issues.append("model_resolution_fallback_detected")
    receipt = {
        "schema_version": 1,
        "status": status,
        "role": agent_name,
        "worker": "agy",
        "invocation_contract": preflight.get("invocation_contract"),
        "auth_mode": "local_agy_oauth_session",
        "provider": preflight.get("provider"),
        "requested_model_key": preflight.get("requested_model_key"),
        "requested_model_id": preflight.get("requested_model_id"),
        "requested_cli_model_id": preflight.get("requested_cli_model_id"),
        "capacity_route": preflight.get("capacity_route"),
        "capacity_pool": preflight.get("capacity_pool"),
        "profile_binding_verified": preflight.get("profile_binding_verified") is True,
        "command_binding_verified": preflight.get("command_binding_verified") is True,
        "direct_api_key_environment_unset": sorted(
            name
            for name in set(environment_unset)
            if _is_agy_direct_api_key_environment(name)
        ),
        "fallback_chain": [],
        "fallback_detected": fallback_detected,
        "provider_process_started": provider_process_started,
        "provider_response_metadata_observed": False,
        "evidence_source": "runtime_verified_argv_and_selected_role_profile",
        "exit_code": exit_code,
        "stdout_nonempty": stdout_nonempty,
        "timed_out": timed_out,
        "issues": sorted(set(str(item) for item in issues)),
    }
    return _persist_model_execution_receipt(
        run_dir,
        agent_name,
        preflight,
        receipt,
    )


def _nested_config_value(config: dict[str, Any], dotted_key: str) -> Any:
    value: Any = config
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _role_model_execution_receipt_path(
    run_dir: Path,
    agent_name: str,
    preflight: dict[str, Any],
) -> Path:
    role_key = re.sub(r"[^a-z0-9]+", "_", agent_name.strip().lower()).strip("_")
    route_key = re.sub(
        r"[^a-z0-9]+",
        "_",
        str(preflight.get("capacity_route") or "direct").strip().lower(),
    ).strip("_")
    attempt_id = str(preflight.get("attempt_id") or uuid4().hex)
    attempt_key = hashlib.sha256(attempt_id.encode("utf-8")).hexdigest()[:12]
    return run_dir / (
        f"model_execution_receipt_{role_key or 'unknown'}_"
        f"{route_key or 'direct'}_{attempt_key}.yml"
    )


def _model_execution_chain_path(run_dir: Path, agent_name: str) -> Path:
    role_key = re.sub(r"[^a-z0-9]+", "_", agent_name.strip().lower()).strip("_")
    return run_dir / f"model_execution_chain_{role_key or 'unknown'}.yml"


def _persist_model_execution_receipt(
    run_dir: Path,
    agent_name: str,
    preflight: dict[str, Any],
    receipt: dict[str, Any],
) -> str:
    """Write one immutable attempt receipt and advance the role-level chain."""
    receipt_path = _role_model_execution_receipt_path(
        run_dir,
        agent_name,
        preflight,
    )
    chain_path = _model_execution_chain_path(run_dir, agent_name)
    try:
        loaded_chain = yaml.safe_load(chain_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        loaded_chain = {}
    chain = loaded_chain if isinstance(loaded_chain, dict) else {}
    attempts = chain.get("attempts") if isinstance(chain.get("attempts"), list) else []

    current_route = str(preflight.get("capacity_route") or "direct")
    selection_kind = str(preflight.get("selection_kind") or "direct")
    previous_routes = [
        str(item.get("capacity_route") or "direct")
        for item in attempts
        if isinstance(item, dict)
    ]
    route_changed = any(route != current_route for route in previous_routes)
    fallback_detected = bool(receipt.get("fallback_detected")) or (
        selection_kind == "approved_fallback" or route_changed
    )
    fallback_chain = []
    for route in previous_routes:
        if route != current_route and route not in fallback_chain:
            fallback_chain.append(route)

    receipt.update(
        {
            "receipt_path": str(receipt_path),
            "chain_path": str(chain_path),
            "attempt_id": preflight.get("attempt_id"),
            "capacity_route": preflight.get("capacity_route"),
            "capacity_pool": preflight.get("capacity_pool"),
            "selection_kind": selection_kind,
            "fallback_detected": fallback_detected,
            "fallback_chain": fallback_chain,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    receipt_path.write_text(
        yaml.safe_dump(receipt, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    provider = receipt.get("provider") or receipt.get("selected_provider")
    selected_model = (
        receipt.get("requested_model_id")
        or receipt.get("selected_model_id")
        or receipt.get("requested_cli_model_id")
        or receipt.get("model")
    )
    reported_models = receipt.get("provider_reported_model_ids") or []
    attempt_entry = {
        "attempt_id": preflight.get("attempt_id"),
        "capacity_route": preflight.get("capacity_route"),
        "capacity_pool": preflight.get("capacity_pool"),
        "selection_kind": selection_kind,
        "receipt_path": str(receipt_path),
        "status": receipt.get("status"),
        "provider": provider,
        "selected_model": selected_model,
        "provider_reported_model_ids": reported_models,
        "provider_response_metadata_observed": receipt.get(
            "provider_response_metadata_observed"
        ),
        "fallback_detected": fallback_detected,
        "failure_issues": list(receipt.get("issues") or []),
    }
    attempts = [
        item
        for item in attempts
        if isinstance(item, dict)
        and item.get("receipt_path") != str(receipt_path)
    ]
    attempts.append(attempt_entry)
    final_model = reported_models[0] if reported_models else selected_model
    chain = {
        "schema_version": 1,
        "role": agent_name,
        "status": receipt.get("status"),
        "attempts": attempts,
        "fallback_used": any(
            bool(item.get("fallback_detected"))
            or item.get("selection_kind") == "approved_fallback"
            for item in attempts
            if isinstance(item, dict)
        ),
        "final": {
            "attempt_id": preflight.get("attempt_id"),
            "receipt_path": str(receipt_path),
            "status": receipt.get("status"),
            "capacity_route": preflight.get("capacity_route"),
            "selection_kind": selection_kind,
            "provider": provider,
            "model": final_model,
            "provider_response_metadata_observed": receipt.get(
                "provider_response_metadata_observed"
            ),
            "failure_issues": list(receipt.get("issues") or []),
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    chain_path.write_text(
        yaml.safe_dump(chain, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return str(receipt_path)


def _qwen_provider_model_mismatch(
    preflight: dict[str, Any],
    usage: dict[str, Any],
) -> bool:
    if not preflight.get("applicable"):
        return False
    reported = [
        str(item)
        for item in usage.get("provider_reported_model_ids", [])
        if str(item).strip()
    ]
    if not reported and usage.get("provider_reported_model_id"):
        reported = [str(usage["provider_reported_model_id"])]
    if not reported:
        return False
    selected = _normalized_model_identity(
        str(preflight.get("selected_model_id") or "")
    )
    return not selected or not any(
        _normalized_model_identity(item) == selected for item in reported
    )


def _write_qwen_artifact_model_receipt(
    run_dir: Path,
    preflight: dict[str, Any],
    *,
    status: str,
    provider_process_started: bool,
    usage: dict[str, Any] | None = None,
    materialization: dict[str, Any] | None = None,
    exit_code: int | None = None,
    stdout_nonempty: bool = False,
    timed_out: bool = False,
    provider_model_mismatch: bool = False,
    extra_issues: list[str] | None = None,
) -> str | None:
    if not preflight.get("applicable"):
        return None
    usage = usage or {}
    materialization = materialization or {}
    issues = list(preflight.get("issues") or []) + list(extra_issues or [])
    if provider_model_mismatch:
        issues.append("provider_reported_model_mismatch")
    if materialization and materialization.get("status") != "pass":
        issues.append("artifact_materialization_failed")
    reported_model_ids = [
        str(item) for item in usage.get("provider_reported_model_ids", [])
    ]
    if not reported_model_ids and usage.get("provider_reported_model_id"):
        reported_model_ids = [str(usage["provider_reported_model_id"])]
    receipt = {
        "schema_version": 1,
        "status": status,
        "role": "ArtifactProducer",
        "worker": "qwen",
        "invocation_contract": preflight.get("invocation_contract"),
        "selected_provider": preflight.get("selected_provider"),
        "selected_runtime_provider": preflight.get("selected_runtime_provider"),
        "selected_model_key": preflight.get("selected_model_key"),
        "selected_model_id": preflight.get("selected_model_id"),
        "requested_cli_model_id": preflight.get("requested_cli_model_id"),
        "capacity_route": preflight.get("capacity_route"),
        "capacity_pool": preflight.get("capacity_pool"),
        "profile_binding_verified": preflight.get("profile_binding_verified") is True,
        "command_binding_verified": preflight.get("command_binding_verified") is True,
        "auth_key_source": preflight.get("auth_key_source"),
        "auth_key_source_configured": preflight.get("auth_key_source_configured") is True,
        "auth_key_target": preflight.get("auth_key_target"),
        "auth_key_target_bound": preflight.get("auth_key_target_bound") is True,
        "base_url": preflight.get("base_url"),
        "base_url_environment_bound": preflight.get("base_url_environment_bound") is True,
        "provider_response_metadata_observed": bool(reported_model_ids),
        "provider_reported_model_ids": reported_model_ids,
        "provider_model_binding_verified": (
            None if not reported_model_ids else not provider_model_mismatch
        ),
        "artifact_materialization_receipt": materialization.get("receipt_path"),
        "artifact_materialization_status": materialization.get("status"),
        "artifact_materialized_outputs": materialization.get("materialized", []),
        "provider_process_started": provider_process_started,
        "evidence_source": "runtime_verified_qwen_argv_environment_json_and_artifact_hashes",
        "exit_code": exit_code,
        "stdout_nonempty": stdout_nonempty,
        "timed_out": timed_out,
        "issues": sorted(set(str(item) for item in issues)),
    }
    return _persist_model_execution_receipt(
        run_dir,
        "ArtifactProducer",
        preflight,
        receipt,
    )


def _claude_runtime_preflight(
    role_profile: dict[str, Any],
    argv: list[str],
    model_values: dict[str, str],
    packet_payload: dict[str, Any],
    invocation_contract: dict[str, Any],
) -> dict[str, Any]:
    contract_name = str(role_profile.get("invocation_contract") or "").strip()
    if (
        str(role_profile.get("cli_agent") or "").strip() != "claude_code"
        or contract_name not in _CLAUDE_RUNTIME_RECEIPT_CONTRACTS
    ):
        return {"applicable": False, "status": "not_applicable", "issues": []}

    requested_model_key = str(model_values.get("model_key") or "")
    requested_model_id = str(model_values.get("catalog_model_id") or "")
    requested_cli_model_id = str(model_values.get("model_id") or "")
    profile_binding_verified = bool(requested_model_key) and (
        str(role_profile.get("default") or "") == requested_model_key
    )

    # These governed contracts are deliberately exact.  Treat the command as
    # a capability boundary rather than merely checking the selected model:
    # accepting extra flags here could re-enable tools, remote control,
    # browser access, fallback models, or filesystem mutation without the
    # sealed Writer/Supervisor packet authorizing that wider surface.
    expected_arguments = {
        "claude_writer": [
            "--model",
            requested_cli_model_id,
            "--effort",
            "max",
            "--max-budget-usd",
            "1.00",
            "--permission-mode",
            "bypassPermissions",
            "--output-format",
            "json",
            "--tools",
            "",
            "-p",
        ],
        "claude_supervisor_fallback": [
            "--model",
            requested_cli_model_id,
            "--effort",
            "max",
            "--max-budget-usd",
            "1.00",
            "--permission-mode",
            "plan",
            "--output-format",
            "json",
            "--tools",
            "",
            "-p",
        ],
        "claude_writer_ultracode": [
            "--model",
            requested_cli_model_id,
            "--max-budget-usd",
            "2.00",
            "--permission-mode",
            "plan",
            "--output-format",
            "json",
            "-p",
        ],
    }[contract_name]
    command_binding_verified = (
        bool(requested_cli_model_id)
        and len(argv) == len(expected_arguments) + 2
        and Path(argv[0]).name in {"claude", "ccs"}
        and argv[1:-1] == expected_arguments
        and bool(str(argv[-1]).strip())
    )

    forbidden_flag_names = {
        "--add-dir",
        "--allow-dangerously-skip-permissions",
        "--background",
        "--bg",
        "--browser",
        "--chrome",
        "--dangerously-skip-permissions",
        "--fallback-model",
        "--ide",
        "--mcp-config",
        "--plugin-dir",
        "--remote",
        "--remote-control",
        "--worktree",
    }
    forbidden_flags = sorted(
        {
            name
            for token in argv[1:]
            for name in forbidden_flag_names
            if token == name or token.startswith(f"{name}=")
        }
    )
    command_binding_verified = command_binding_verified and not forbidden_flags

    ultracode = contract_name == "claude_writer_ultracode"
    ultracode_opt_in = packet_payload.get("ultracode_opt_in") is True
    writer_mode = str(packet_payload.get("writer_mode") or "").strip()
    work_type = str(packet_payload.get("work_type") or "").strip()
    required_packet = (
        invocation_contract.get("requires_task_packet")
        if isinstance(invocation_contract.get("requires_task_packet"), dict)
        else {}
    )
    expected_writer_mode = str(required_packet.get("writer_mode") or "").strip()
    allowed_work = [
        str(item)
        for item in invocation_contract.get("allowed_work", [])
        if str(item).strip()
    ]
    forbidden_work = [
        str(item)
        for item in invocation_contract.get("forbidden_work", [])
        if str(item).strip()
    ]
    sealed_writer_packet = (
        packet_payload.get("packet_type") == "agentlab_sealed_role_session"
        and packet_payload.get("agent") == "Writer"
    )

    issues: list[str] = []
    if not profile_binding_verified:
        issues.append("claude_profile_model_binding_mismatch")
    if not command_binding_verified:
        issues.append("claude_command_model_binding_mismatch")
    issues.extend(f"claude_forbidden_command_flag:{flag}" for flag in forbidden_flags)
    if ultracode:
        if invocation_contract.get("opt_in_only") is not True:
            issues.append("claude_ultracode_contract_not_opt_in_only")
        if not ultracode_opt_in:
            issues.append("claude_ultracode_explicit_opt_in_missing")
        if not sealed_writer_packet:
            issues.append("claude_ultracode_sealed_writer_packet_missing")
        if not expected_writer_mode or writer_mode != expected_writer_mode:
            issues.append("claude_ultracode_writer_mode_mismatch")
        if work_type in forbidden_work:
            issues.append("claude_ultracode_forbidden_work_type")
        elif not work_type or work_type not in allowed_work:
            issues.append("claude_ultracode_work_type_not_allowed")
    return {
        "applicable": True,
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "invocation_contract": contract_name,
        "selected_provider": str(model_values.get("provider") or "") or None,
        "selected_model_key": requested_model_key or None,
        "selected_model_id": requested_model_id or None,
        "requested_cli_model_id": requested_cli_model_id or None,
        "profile_binding_verified": profile_binding_verified,
        "command_binding_verified": command_binding_verified,
        "forbidden_command_flags": forbidden_flags,
        "ultracode_activation_applicable": ultracode,
        "ultracode_activation_verified": ultracode and not any(
            issue.startswith("claude_ultracode_") for issue in issues
        ),
        "ultracode_opt_in": ultracode_opt_in if ultracode else None,
        "writer_mode": writer_mode or None,
        "expected_writer_mode": expected_writer_mode or None,
        "work_type": work_type or None,
        "allowed_work": allowed_work,
        "forbidden_work": forbidden_work,
        "sealed_writer_packet_verified": sealed_writer_packet if ultracode else None,
        "capacity_route": role_profile.get("capacity_selected_route"),
        "capacity_pool": role_profile.get("capacity_pool"),
        "attempt_id": role_profile.get("_runtime_model_execution_attempt_id"),
        "selection_kind": role_profile.get("_runtime_capacity_selection_kind"),
    }


def _write_ultracode_activation_receipt(
    run_dir: Path,
    preflight: dict[str, Any],
) -> str | None:
    """Persist the explicit developmental-only Ultracode activation decision."""

    if not preflight.get("ultracode_activation_applicable"):
        return None
    path = run_dir / "ultracode_activation_receipt.yml"
    activation_issues = sorted(
        {
            str(issue)
            for issue in preflight.get("issues", [])
            if str(issue).startswith("claude_ultracode_")
        }
    )
    receipt = {
        "schema_version": 1,
        "receipt_type": "agentlab_claude_ultracode_activation",
        "status": "pass" if not activation_issues else "fail",
        "role": "Writer",
        "invocation_contract": "claude_writer_ultracode",
        "opt_in_only": True,
        "explicit_opt_in": preflight.get("ultracode_opt_in") is True,
        "writer_mode": preflight.get("writer_mode"),
        "expected_writer_mode": preflight.get("expected_writer_mode"),
        "work_type": preflight.get("work_type"),
        "allowed_work": list(preflight.get("allowed_work") or []),
        "forbidden_work": list(preflight.get("forbidden_work") or []),
        "sealed_writer_packet_verified": (
            preflight.get("sealed_writer_packet_verified") is True
        ),
        "final_prose_authorized": False,
        "provider_process_started_at_receipt": False,
        "issues": activation_issues,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(
        yaml.safe_dump(receipt, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return str(path)


def _normalized_model_identity(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _claude_provider_model_mismatch(
    preflight: dict[str, Any],
    usage: dict[str, Any],
) -> bool:
    if not preflight.get("applicable"):
        return False
    reported = [
        str(item)
        for item in usage.get("provider_reported_model_ids", [])
        if str(item).strip()
    ]
    if not reported and usage.get("provider_reported_model_id"):
        reported = [str(usage["provider_reported_model_id"])]
    if not reported:
        return False
    selected = _normalized_model_identity(
        str(preflight.get("selected_model_id") or "")
    )
    return not selected or not any(
        _normalized_model_identity(item) == selected for item in reported
    )


def _write_claude_model_receipt(
    run_dir: Path,
    agent_name: str,
    preflight: dict[str, Any],
    *,
    status: str,
    provider_process_started: bool,
    usage: dict[str, Any] | None = None,
    exit_code: int | None = None,
    stdout_nonempty: bool = False,
    timed_out: bool = False,
    provider_model_mismatch: bool = False,
    extra_issues: list[str] | None = None,
) -> str | None:
    if not preflight.get("applicable"):
        return None
    usage = usage or {}
    issues = list(preflight.get("issues") or []) + list(extra_issues or [])
    if provider_model_mismatch:
        issues.append("provider_reported_model_mismatch")
    reported_model_ids = [
        str(item) for item in usage.get("provider_reported_model_ids", [])
    ]
    if not reported_model_ids and usage.get("provider_reported_model_id"):
        reported_model_ids = [str(usage["provider_reported_model_id"])]
    reported_session_id = usage.get("provider_reported_session_id")
    provider_metadata_observed = bool(
        reported_model_ids
        or reported_session_id
        or usage.get("usage_source") == "external_cli_reported"
        or usage.get("pricing_source") == "provider_response"
    )
    observed_usage = {}
    if provider_metadata_observed:
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "total_tokens",
            "estimated_cost",
            "cost_currency",
            "usage_source",
            "pricing_source",
        ):
            if usage.get(key) is not None:
                observed_usage[key] = usage[key]

    receipt = {
        "schema_version": 1,
        "status": status,
        "role": agent_name,
        "worker": "claude_code",
        "invocation_contract": preflight.get("invocation_contract"),
        "selected_provider": preflight.get("selected_provider"),
        "selected_model_key": preflight.get("selected_model_key"),
        "selected_model_id": preflight.get("selected_model_id"),
        "requested_cli_model_id": preflight.get("requested_cli_model_id"),
        "capacity_route": preflight.get("capacity_route"),
        "capacity_pool": preflight.get("capacity_pool"),
        "profile_binding_verified": preflight.get("profile_binding_verified") is True,
        "command_binding_verified": preflight.get("command_binding_verified") is True,
        "provider_response_metadata_observed": provider_metadata_observed,
        "provider_reported_model_ids": reported_model_ids,
        "provider_reported_session_id": reported_session_id,
        "provider_reported_usage": observed_usage,
        "provider_model_binding_verified": (
            None if not reported_model_ids else not provider_model_mismatch
        ),
        "fallback_chain": [],
        "fallback_detected": provider_model_mismatch,
        "provider_process_started": provider_process_started,
        "evidence_source": "runtime_verified_argv_profile_and_claude_json",
        "exit_code": exit_code,
        "stdout_nonempty": stdout_nonempty,
        "timed_out": timed_out,
        "issues": sorted(set(str(item) for item in issues)),
    }
    return _persist_model_execution_receipt(
        run_dir,
        agent_name,
        preflight,
        receipt,
    )


def _hermes_home(process_env: dict[str, str], profile_name: str) -> Path:
    """Resolve Hermes' config root without reading any broad status surface."""
    configured = str(process_env.get("HERMES_HOME") or "").strip()
    root = Path(configured).expanduser() if configured else Path.home() / ".hermes"
    if root.name == profile_name and root.parent.name == "profiles":
        root = root.parent.parent
    elif root.name == "profiles":
        root = root.parent
    return root.resolve(strict=False)


def _grok_research_preflight(
    role_profile: dict[str, Any],
    agentlab_root: str | Path,
    process_env: dict[str, str],
    argv: list[str],
    model_values: dict[str, str],
    *,
    agent_name: str,
    bounded_messages: bool,
    execution_cwd: Path,
    task_packet_path: Path,
    binary_available: bool,
) -> dict[str, Any]:
    """Verify the exact, read-only Hermes xAI Researcher path offline."""

    applicable = (
        agent_name == "Researcher"
        and str(role_profile.get("cli_agent") or "").strip() == "grok"
        and str(role_profile.get("invocation_contract") or "").strip()
        == "grok_research"
    )
    if not applicable:
        return {"applicable": False, "status": "not_applicable", "issues": []}

    requested_model_key = str(model_values.get("model_key") or "")
    requested_model_id = str(model_values.get("catalog_model_id") or "")
    requested_cli_model_id = str(model_values.get("model_id") or "")
    selected_provider = str(model_values.get("provider") or "")
    catalog_provider = str(model_values.get("catalog_provider") or "")
    profile_binding_verified = bool(requested_model_key) and (
        str(role_profile.get("default") or "") == requested_model_key
    )

    expected_prefix = [
        "hermes",
        "--ignore-rules",
        "--provider",
        "xai-oauth",
        "-m",
        requested_cli_model_id,
        "-t",
        "web,x_search",
        "-z",
    ]
    prompt = argv[9] if len(argv) == 10 else ""
    command_binding_verified = (
        len(argv) == 10
        and Path(argv[0]).name == "hermes"
        and argv[1:9] == expected_prefix[1:]
        and str(task_packet_path) in prompt
        and "Researcher" in prompt
        and "task packet" in prompt.lower()
    )
    forbidden_flags = sorted(
        flag
        for flag in {
            "--accept-hooks",
            "--continue",
            "--pass-session-id",
            "--resume",
            "--skills",
            "--worktree",
            "--yolo",
            "-c",
            "-r",
            "-s",
            "-w",
        }
        if flag in argv
    )

    root = Path(agentlab_root).resolve(strict=False)
    cwd = execution_cwd.resolve(strict=False)
    packet = task_packet_path.resolve(strict=False)
    isolated_workspace_verified = (
        bounded_messages
        and cwd != root
        and packet.parent == cwd
    )
    try:
        cwd_read_only = cwd.is_dir() and cwd.stat().st_mode & 0o222 == 0
        packet_read_only = packet.is_file() and packet.stat().st_mode & 0o222 == 0
    except OSError:
        cwd_read_only = False
        packet_read_only = False
    read_only_workspace_verified = (
        isolated_workspace_verified and cwd_read_only and packet_read_only
    )

    hermes_root = _hermes_home(process_env, "")
    auth_path = hermes_root / "auth.json"
    auth_file_present = auth_path.is_file() and not auth_path.is_symlink()
    auth_provider_entry_present = False
    credential_present = False
    if auth_file_present:
        try:
            auth_payload = json.loads(auth_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            auth_payload = {}
        providers = (
            auth_payload.get("providers")
            if isinstance(auth_payload, dict)
            and isinstance(auth_payload.get("providers"), dict)
            else {}
        )
        provider_entry = providers.get("xai-oauth")
        auth_provider_entry_present = isinstance(provider_entry, dict)
        tokens = (
            provider_entry.get("tokens")
            if isinstance(provider_entry, dict)
            and isinstance(provider_entry.get("tokens"), dict)
            else {}
        )
        credential_present = any(
            isinstance(tokens.get(name), str) and bool(tokens.get(name).strip())
            for name in ("access_token", "id_token", "refresh_token")
        )
        credential_pool = (
            auth_payload.get("credential_pool")
            if isinstance(auth_payload, dict)
            and isinstance(auth_payload.get("credential_pool"), dict)
            else {}
        )
        pooled = credential_pool.get("xai-oauth")
        credential_present = credential_present or (
            isinstance(pooled, list) and bool(pooled)
        )

    config_path = hermes_root / "config.yaml"
    config_file_present = config_path.is_file() and not config_path.is_symlink()
    fallback_chain_empty = False
    if config_file_present:
        try:
            loaded_config = yaml.safe_load(
                config_path.read_text(encoding="utf-8")
            ) or {}
        except (OSError, yaml.YAMLError):
            loaded_config = {}
        fallback_chain = (
            loaded_config.get("fallback_providers")
            if isinstance(loaded_config, dict)
            else None
        )
        fallback_chain_empty = isinstance(fallback_chain, list) and not fallback_chain

    issues: list[str] = []
    if not binary_available:
        issues.append("grok_research_binary_missing")
    if not profile_binding_verified:
        issues.append("grok_research_profile_model_binding_mismatch")
    if selected_provider != "xai-oauth" or catalog_provider != "hermes_xai_oauth":
        issues.append("grok_research_provider_binding_mismatch")
    if not command_binding_verified:
        issues.append("grok_research_command_binding_mismatch")
    issues.extend(
        f"grok_research_forbidden_command_flag:{flag}"
        for flag in forbidden_flags
    )
    if not isolated_workspace_verified:
        issues.append("grok_research_sealed_workspace_missing")
    if not read_only_workspace_verified:
        issues.append("grok_research_workspace_not_read_only")
    if not auth_file_present:
        issues.append("hermes_auth_store_missing")
    if not auth_provider_entry_present or not credential_present:
        issues.append("xai_oauth_credential_missing")
    if not config_file_present:
        issues.append("hermes_config_missing")
    if not fallback_chain_empty:
        issues.append("grok_research_fallback_chain_not_empty")

    return {
        "applicable": True,
        "status": "pass" if not issues else "fail",
        "issues": sorted(set(issues)),
        "invocation_contract": "grok_research",
        "provider": selected_provider or None,
        "catalog_provider": catalog_provider or None,
        "requested_model_key": requested_model_key or None,
        "requested_model_id": requested_model_id or None,
        "requested_cli_model_id": requested_cli_model_id or None,
        "profile_binding_verified": profile_binding_verified,
        "binary_available": binary_available,
        "command_binding_verified": command_binding_verified,
        "forbidden_command_flags": forbidden_flags,
        "allowed_toolsets": ["web", "x_search"],
        "sealed_context_verified": bounded_messages,
        "isolated_workspace_verified": isolated_workspace_verified,
        "read_only_workspace_verified": read_only_workspace_verified,
        "auth_store": "auth.json",
        "auth_file_present": auth_file_present,
        "auth_provider_entry_present": auth_provider_entry_present,
        "credential_present": credential_present,
        "credential_values_recorded": False,
        "config_store": "config.yaml",
        "config_file_present": config_file_present,
        "fallback_chain_empty": fallback_chain_empty,
        "capacity_route": role_profile.get("capacity_selected_route"),
        "capacity_pool": role_profile.get("capacity_pool"),
        "attempt_id": role_profile.get("_runtime_model_execution_attempt_id"),
        "selection_kind": role_profile.get("_runtime_capacity_selection_kind"),
    }


def _grok_provider_model_mismatch(
    preflight: dict[str, Any],
    usage: dict[str, Any],
) -> bool:
    if not preflight.get("applicable"):
        return False
    reported = [
        str(item)
        for item in usage.get("provider_reported_model_ids", [])
        if str(item).strip()
    ]
    if not reported and usage.get("provider_reported_model_id"):
        reported = [str(usage["provider_reported_model_id"])]
    if not reported:
        return False
    selected = _normalized_model_identity(
        str(preflight.get("requested_model_id") or "")
    )
    return not selected or not any(
        _normalized_model_identity(item) == selected for item in reported
    )


def _write_grok_research_model_receipt(
    run_dir: Path,
    preflight: dict[str, Any],
    *,
    status: str,
    provider_process_started: bool,
    usage: dict[str, Any] | None = None,
    exit_code: int | None = None,
    stdout_nonempty: bool = False,
    timed_out: bool = False,
    provider_model_mismatch: bool = False,
    extra_issues: list[str] | None = None,
) -> str | None:
    if not preflight.get("applicable"):
        return None
    usage = usage or {}
    issues = list(preflight.get("issues") or []) + list(extra_issues or [])
    if provider_model_mismatch:
        issues.append("provider_reported_model_mismatch")
    reported_model_ids = [
        str(item) for item in usage.get("provider_reported_model_ids", [])
    ]
    if not reported_model_ids and usage.get("provider_reported_model_id"):
        reported_model_ids = [str(usage["provider_reported_model_id"])]
    receipt = {
        "schema_version": 1,
        "status": status,
        "role": "Researcher",
        "worker": "grok",
        "invocation_contract": "grok_research",
        "provider": preflight.get("provider"),
        "model": preflight.get("requested_model_id"),
        "requested_model_key": preflight.get("requested_model_key"),
        "requested_cli_model_id": preflight.get("requested_cli_model_id"),
        "binary_available": preflight.get("binary_available") is True,
        "profile_binding_verified": preflight.get("profile_binding_verified") is True,
        "command_binding_verified": preflight.get("command_binding_verified") is True,
        "allowed_toolsets": list(preflight.get("allowed_toolsets") or []),
        "sealed_context_verified": preflight.get("sealed_context_verified") is True,
        "isolated_workspace_verified": preflight.get("isolated_workspace_verified") is True,
        "read_only_workspace_verified": preflight.get("read_only_workspace_verified") is True,
        "auth_mode": "local_hermes_xai_oauth_session",
        "auth_store": preflight.get("auth_store"),
        "auth_provider_entry_present": preflight.get("auth_provider_entry_present") is True,
        "credential_present": preflight.get("credential_present") is True,
        "credential_values_recorded": False,
        "fallback_chain": [],
        "provider_response_metadata_observed": bool(reported_model_ids),
        "provider_reported_model_ids": reported_model_ids,
        "provider_model_binding_verified": (
            None if not reported_model_ids else not provider_model_mismatch
        ),
        "provider_process_started": provider_process_started,
        "evidence_source": "runtime_verified_argv_auth_presence_config_and_workspace_mode",
        "exit_code": exit_code,
        "stdout_nonempty": stdout_nonempty,
        "timed_out": timed_out,
        "issues": sorted(set(str(item) for item in issues)),
    }
    return _persist_model_execution_receipt(
        run_dir,
        "Researcher",
        preflight,
        receipt,
    )


def _hermes_supervisor_preflight(
    role_profile: dict[str, Any],
    agentlab_root: str | Path,
    process_env: dict[str, str],
    argv: list[str],
    model_values: dict[str, str],
) -> dict[str, Any]:
    """Verify the exact governed Supervisor request path before provider launch.

    Native Codex is verified from its exact argv/model/reasoning binding. The
    retained Hermes compatibility contract additionally verifies its isolated
    profile state. Neither path calls a provider during preflight.
    """
    invocation_contract = str(role_profile.get("invocation_contract") or "")
    contract = _resolve_invocation_contract(role_profile, agentlab_root)
    if invocation_contract == "codex_supervisor":
        expected_model_key = str(contract.get("required_model_key") or "")
        expected_provider = str(contract.get("required_runtime_provider") or "")
        expected_reasoning = str(contract.get("resolved_reasoning_effort") or "")
        configured_values = _model_invocation_values(
            {"default": expected_model_key},
            agentlab_root,
        )
        expected_model = str(configured_values.get("model_id") or "")
        issues: list[str] = []
        if not expected_model_key:
            issues.append("required_model_key_missing")
        if not expected_provider:
            issues.append("required_runtime_provider_missing")
        if not expected_reasoning:
            issues.append("reasoning_effort_missing")
        if str(role_profile.get("default") or "") != expected_model_key:
            issues.append("configured_model_key_mismatch")
        if model_values.get("provider") != expected_provider:
            issues.append("catalog_provider_mismatch")
        if model_values.get("model_id") != expected_model:
            issues.append("catalog_model_mismatch")
        if model_values.get("model_key") != expected_model_key:
            issues.append("catalog_model_key_mismatch")
        if contract.get("resolved_reasoning_effort") != expected_reasoning:
            issues.append("reasoning_effort_mismatch")
        expected_prefix = [
            "exec",
            "--json",
            "--model",
            expected_model,
            "-c",
            f'model_reasoning_effort="{expected_reasoning}"',
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--ignore-rules",
            "--skip-git-repo-check",
            "-C",
        ]
        command_bound = (
            len(argv) == 15
            and Path(argv[0]).name == "codex"
            and argv[1:13] == expected_prefix
            and bool(str(argv[13]).strip())
            and bool(str(argv[14]).strip())
        )
        if not command_bound:
            issues.append("supervisor_command_binding_mismatch")
        return {
            "applicable": True,
            "status": "pass" if not issues else "fail",
            "issues": sorted(set(issues)),
            "worker": "codex",
            "invocation_contract": invocation_contract,
            "required_shell_state": {
                "model.provider": expected_provider,
                "model.default": expected_model,
                "agent.reasoning_effort": expected_reasoning,
            },
            "observed_shell_state": {
                "model.provider": model_values.get("provider"),
                "model.default": model_values.get("model_id"),
                "agent.reasoning_effort": contract.get("resolved_reasoning_effort"),
            },
            "command_binding_verified": command_bound,
            "requested_reasoning_label": contract.get("requested_reasoning_label"),
            "resolved_reasoning_effort": contract.get("resolved_reasoning_effort"),
            "capacity_route": (
                role_profile.get("capacity_selected_route")
                or role_profile.get("capacity_route")
            ),
            "capacity_pool": role_profile.get("capacity_pool"),
            "attempt_id": role_profile.get("_runtime_model_execution_attempt_id"),
            "selection_kind": role_profile.get("_runtime_capacity_selection_kind"),
            "provider_process_started": False,
            "evidence_source": "runtime_verified_codex_argv",
        }

    if invocation_contract != "hermes_supervisor":
        return {"applicable": False, "status": "not_applicable", "issues": []}

    profile_name = str(contract.get("workflow_shell_profile") or "").strip()
    required = (
        contract.get("required_shell_state")
        if isinstance(contract.get("required_shell_state"), dict)
        else {}
    )
    issues: list[str] = []
    observed: dict[str, Any] = {}
    config_sha256: str | None = None
    config_path: Path | None = None

    if not profile_name:
        issues.append("workflow_shell_profile_missing")
    else:
        config_path = _hermes_home(process_env, profile_name) / "profiles" / profile_name / "config.yaml"
        if not config_path.is_file():
            issues.append("profile_config_missing")
        else:
            config_sha256 = _sha256_file(config_path)
            try:
                loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            except Exception:
                loaded = {}
                issues.append("profile_config_unreadable")
            config = loaded if isinstance(loaded, dict) else {}
            if not isinstance(loaded, dict):
                issues.append("profile_config_not_mapping")
            for key, expected in required.items():
                actual = _nested_config_value(config, str(key))
                observed[str(key)] = actual
                if expected is None:
                    if actual is not None and actual != "":
                        issues.append(f"profile_state_mismatch:{key}")
                elif actual != expected:
                    issues.append(f"profile_state_mismatch:{key}")

    expected_provider = str(required.get("model.provider") or "")
    expected_model = str(required.get("model.default") or "")
    if model_values.get("provider") != expected_provider:
        issues.append("catalog_provider_mismatch")
    if model_values.get("model_id") != expected_model:
        issues.append("catalog_model_mismatch")

    expected_tail = [
        "-p",
        profile_name,
        "chat",
        "-Q",
        "--provider",
        expected_provider,
        "-m",
        expected_model,
        "--ignore-rules",
        "--max-turns",
        "6",
        "-q",
    ]
    command_bound = (
        bool(argv)
        and Path(argv[0]).name == "hermes"
        and len(argv) == len(expected_tail) + 2
        and argv[1:-1] == expected_tail
        and bool(str(argv[-1]).strip())
    )
    if not command_bound:
        issues.append("supervisor_command_binding_mismatch")

    return {
        "applicable": True,
        "status": "pass" if not issues else "fail",
        "issues": sorted(set(issues)),
        "workflow_shell_profile": profile_name or None,
        "profile_config_path": (
            f"profiles/{profile_name}/config.yaml" if profile_name else None
        ),
        "profile_config_sha256": config_sha256,
        "required_shell_state": required,
        "observed_shell_state": observed,
        "command_binding_verified": command_bound,
        "requested_reasoning_label": contract.get("requested_reasoning_label"),
        "resolved_reasoning_effort": contract.get("resolved_reasoning_effort"),
        "capacity_route": role_profile.get("capacity_selected_route"),
        "capacity_pool": role_profile.get("capacity_pool"),
        "attempt_id": role_profile.get("_runtime_model_execution_attempt_id"),
        "selection_kind": role_profile.get("_runtime_capacity_selection_kind"),
        "provider_process_started": False,
        "worker": "hermes",
        "invocation_contract": invocation_contract,
        "evidence_source": "runtime_verified_argv_and_hermes_profile",
    }


def _write_hermes_supervisor_model_receipt(
    run_dir: Path,
    preflight: dict[str, Any],
    *,
    status: str,
    provider_process_started: bool,
    exit_code: int | None = None,
    stdout_nonempty: bool = False,
    timed_out: bool = False,
    extra_issues: list[str] | None = None,
) -> str | None:
    if not preflight.get("applicable"):
        return None
    issues = sorted(
        set(str(item) for item in (preflight.get("issues") or []) + (extra_issues or []))
    )
    receipt = {
        "schema_version": 1,
        "status": status,
        "role": "Supervisor",
        "worker": preflight.get("worker") or "hermes",
        "invocation_contract": preflight.get("invocation_contract") or "hermes_supervisor",
        "requested_reasoning_label": preflight.get("requested_reasoning_label"),
        "provider": (preflight.get("required_shell_state") or {}).get("model.provider"),
        "model": (preflight.get("required_shell_state") or {}).get("model.default"),
        "reasoning_effort": preflight.get("resolved_reasoning_effort"),
        "workflow_shell_profile": preflight.get("workflow_shell_profile"),
        "profile_config_path": preflight.get("profile_config_path"),
        "profile_config_sha256": preflight.get("profile_config_sha256"),
        "profile_state_verified": preflight.get("status") == "pass",
        "command_binding_verified": preflight.get("command_binding_verified") is True,
        "fallback_chain": [],
        "provider_process_started": provider_process_started,
        "provider_response_metadata_observed": False,
        "evidence_source": preflight.get("evidence_source") or "runtime_verified_supervisor_argv",
        "exit_code": exit_code,
        "stdout_nonempty": stdout_nonempty,
        "timed_out": timed_out,
        "issues": issues,
    }
    return _persist_model_execution_receipt(
        run_dir,
        "Supervisor",
        preflight,
        receipt,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_artifact_input_contract(plan: WorkflowPlan) -> dict[str, Any]:
    """Load the run-local ArtifactTask without accepting a symlink contract."""

    try:
        from agent_runtime.protocols.artifact_task import ArtifactInputContractError
    except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
        from protocols.artifact_task import ArtifactInputContractError

    contract_path = Path(plan.run_dir) / "artifact_task.yml"
    if not contract_path.exists():
        return {}
    if contract_path.is_symlink() or not contract_path.is_file():
        raise ArtifactInputContractError("artifact_task_contract_path_invalid")
    try:
        artifact_task = yaml.safe_load(
            contract_path.read_text(encoding="utf-8")
        ) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ArtifactInputContractError("artifact_task_contract_unreadable") from exc
    if not isinstance(artifact_task, dict):
        raise ArtifactInputContractError("artifact_task_contract_invalid")
    return artifact_task


def _public_artifact_input_rows(
    validated_inputs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in item.items()
            if not str(key).startswith("_")
        }
        for item in validated_inputs
    ]


def _write_artifact_input_manifest(
    plan: WorkflowPlan,
    *,
    validated_inputs: list[dict[str, Any]] | None = None,
    issue: Any | None = None,
    phase: str,
    provider_process_started: bool = False,
) -> Path:
    """Persist content-free input validation evidence without host paths."""

    try:
        from agent_runtime.protocols.artifact_task import MAX_ARTIFACT_INPUT_BYTES
    except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
        from protocols.artifact_task import MAX_ARTIFACT_INPUT_BYTES

    public_rows = _public_artifact_input_rows(validated_inputs or [])
    issue_row = (
        issue.as_receipt_issue()
        if issue is not None and hasattr(issue, "as_receipt_issue")
        else ({"code": "artifact_input_validation_failed"} if issue else None)
    )
    manifest = {
        "schema_version": 1,
        "packet_type": "agentlab_artifact_input_manifest",
        "status": "fail" if issue_row else "pass",
        "phase": phase,
        "role": "ArtifactProducer",
        "project": plan.project,
        "task_id": plan.task_id,
        "read_only": True,
        "staging_scope": "artifact_inputs/*",
        "max_total_bytes": MAX_ARTIFACT_INPUT_BYTES,
        "input_count": len(public_rows),
        "total_bytes": sum(int(item["byte_count"]) for item in public_rows),
        "assigned_inputs": public_rows,
        "issues": [issue_row] if issue_row else [],
        "provider_process_started": provider_process_started,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = Path(plan.run_dir) / "artifact_input_manifest.yml"
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return manifest_path


def _artifact_input_blocked_result(
    cli_agent_name: str,
    manifest_path: Path,
    issue: Any,
) -> LLMCallResult:
    issue_code = str(getattr(issue, "code", "artifact_input_validation_failed"))
    return LLMCallResult(
        provider="agentlab-protocol",
        model=cli_agent_name,
        content=(
            "# ArtifactProducer input validation blocked\n\n"
            "An explicit ArtifactTask input failed its path, type, size, hash, "
            "read-only, duplicate, or staging binding. No provider process was "
            "started.\n"
        ),
        status="blocked_user_decision",
        error="artifact_input_validation_failed",
        raw_usage={
            "usage_source": "protocol_gate",
            "failure_class": "validation_failed",
            "artifact_input_issue": issue_code,
            "artifact_input_manifest": str(manifest_path),
            "provider_process_started": False,
        },
    )


def _verify_artifact_input_postflight(
    plan: WorkflowPlan,
    execution_cwd: Path,
    validated_inputs: list[dict[str, Any]],
    *,
    phase: str = "postflight",
) -> tuple[Path, str | None]:
    """Rehash staged inputs after a provider process and update its manifest."""

    try:
        from agent_runtime.protocols.artifact_task import (
            ArtifactInputContractError,
            verify_staged_artifact_task_inputs,
        )
    except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
        from protocols.artifact_task import (
            ArtifactInputContractError,
            verify_staged_artifact_task_inputs,
        )

    try:
        verify_staged_artifact_task_inputs(execution_cwd, validated_inputs)
    except ArtifactInputContractError as exc:
        return (
            _write_artifact_input_manifest(
                plan,
                validated_inputs=validated_inputs,
                issue=exc,
                phase=phase,
                provider_process_started=True,
            ),
            exc.code,
        )
    return (
        _write_artifact_input_manifest(
            plan,
            validated_inputs=validated_inputs,
            phase=phase,
            provider_process_started=True,
        ),
        None,
    )


def _observer_input_manifest(
    agent_name: str,
    source_paths: list[Path],
) -> list[dict[str, Any]]:
    if agent_name not in {"Observer", "Reviewer", "Verifier"}:
        return []
    result: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for source in source_paths:
        path = Path(source)
        if path.suffix.lower() not in _OBSERVER_STAGED_SUFFIXES or not path.is_file():
            continue
        resolved = path.resolve(strict=True)
        if resolved in seen:
            continue
        seen.add(resolved)
        index = len(result) + 1
        input_dir = (
            "observer_inputs"
            if agent_name == "Observer"
            else f"{agent_name.lower()}_visual_inputs"
        )
        result.append(
            {
                "source_filename": path.name,
                "staged_path": f"{input_dir}/{index:02d}_{path.name}",
                "media_type": path.suffix.lower().lstrip("."),
                "byte_count": path.stat().st_size,
                "sha256": _sha256_file(path),
                "read_only": True,
                "_source_path": str(resolved),
            }
        )
    return result


def _public_staged_input_rows(
    observer_manifest: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in item.items()
            if not str(key).startswith("_")
        }
        for item in observer_manifest
    ]


def _write_staged_input_manifest(
    plan: WorkflowPlan,
    agent_name: str,
    observer_manifest: list[dict[str, Any]],
    *,
    phase: str,
    provider_process_started: bool,
    issue: StagedInputPostflightError | None = None,
) -> Path:
    """Write role-owned staged-input evidence without host-absolute paths."""

    public_rows = _public_staged_input_rows(observer_manifest)
    role_key = re.sub(r"[^a-z0-9]+", "_", agent_name.lower()).strip("_")
    payload = {
        "schema_version": 1,
        "packet_type": "agentlab_staged_input_manifest",
        "status": "fail" if issue else "pass",
        "phase": phase,
        "role": agent_name,
        "project": plan.project,
        "task_id": plan.task_id,
        "read_only": True,
        "input_count": len(public_rows),
        "total_bytes": sum(int(item["byte_count"]) for item in public_rows),
        "assigned_inputs": public_rows,
        "issues": [issue.as_issue()] if issue else [],
        "provider_process_started": provider_process_started,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = Path(plan.run_dir) / (
        f"staged_input_manifest_{role_key or 'unknown'}.yml"
    )
    manifest_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return manifest_path


def _staged_input_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )


def _verify_staged_read_only_inputs(
    execution_cwd: Path,
    observer_manifest: list[dict[str, Any]],
) -> None:
    """Fail when a governed CLI changed, replaced, or added staged inputs."""

    if not observer_manifest:
        return
    expected_by_directory: dict[str, dict[str, tuple[int, dict[str, Any]]]] = {}
    seen_paths: set[str] = set()
    for input_index, item in enumerate(observer_manifest, start=1):
        raw_path = item.get("staged_path")
        source_filename = item.get("source_filename")
        if (
            not isinstance(raw_path, str)
            or not raw_path
            or re.search(r"[\x00-\x1f\x7f]", raw_path)
            or "\\" in raw_path
            or not isinstance(source_filename, str)
            or not source_filename
        ):
            raise StagedInputPostflightError(
                "staged_input_path_invalid",
                input_index=input_index,
            )
        relative = Path(raw_path)
        if (
            relative.is_absolute()
            or len(relative.parts) != 2
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.name != f"{input_index:02d}_{source_filename}"
            or raw_path in seen_paths
        ):
            raise StagedInputPostflightError(
                "staged_input_path_invalid",
                input_index=input_index,
            )
        if item.get("read_only") is not True:
            raise StagedInputPostflightError(
                "staged_input_read_only_binding_invalid",
                input_index=input_index,
            )
        expected_hash = item.get("sha256")
        expected_size = item.get("byte_count")
        if (
            not isinstance(expected_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
            or type(expected_size) is not int
            or expected_size < 0
        ):
            raise StagedInputPostflightError(
                "staged_input_integrity_binding_invalid",
                input_index=input_index,
            )
        seen_paths.add(raw_path)
        expected_by_directory.setdefault(relative.parts[0], {})[
            relative.parts[1]
        ] = (input_index, item)

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(Path(execution_cwd).resolve(strict=True), directory_flags)
    try:
        for directory_name, expected_files in expected_by_directory.items():
            try:
                directory_lstat = os.stat(
                    directory_name,
                    dir_fd=root_fd,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise StagedInputPostflightError(
                    "staged_input_directory_missing"
                ) from exc
            if stat.S_ISLNK(directory_lstat.st_mode):
                raise StagedInputPostflightError(
                    "staged_input_symlink_not_allowed"
                )
            if (
                not stat.S_ISDIR(directory_lstat.st_mode)
                or stat.S_IMODE(directory_lstat.st_mode) != 0o500
            ):
                raise StagedInputPostflightError(
                    "staged_input_directory_mode_mutated"
                )
            try:
                directory_fd = os.open(
                    directory_name,
                    directory_flags | no_follow,
                    dir_fd=root_fd,
                )
            except OSError as exc:
                raise StagedInputPostflightError(
                    "staged_input_directory_unreadable"
                ) from exc
            try:
                opened_directory = os.fstat(directory_fd)
                if (
                    opened_directory.st_dev,
                    opened_directory.st_ino,
                ) != (
                    directory_lstat.st_dev,
                    directory_lstat.st_ino,
                ) or stat.S_IMODE(opened_directory.st_mode) != 0o500:
                    raise StagedInputPostflightError(
                        "staged_input_directory_replaced"
                    )
                if set(os.listdir(directory_fd)) != set(expected_files):
                    raise StagedInputPostflightError(
                        "staged_input_set_mutated"
                    )
                for filename, (input_index, item) in expected_files.items():
                    try:
                        input_lstat = os.stat(
                            filename,
                            dir_fd=directory_fd,
                            follow_symlinks=False,
                        )
                    except OSError as exc:
                        raise StagedInputPostflightError(
                            "staged_input_missing",
                            input_index=input_index,
                        ) from exc
                    if stat.S_ISLNK(input_lstat.st_mode):
                        raise StagedInputPostflightError(
                            "staged_input_symlink_not_allowed",
                            input_index=input_index,
                        )
                    if not stat.S_ISREG(input_lstat.st_mode):
                        raise StagedInputPostflightError(
                            "staged_input_not_regular_file",
                            input_index=input_index,
                        )
                    try:
                        input_fd = os.open(
                            filename,
                            os.O_RDONLY
                            | no_follow
                            | getattr(os, "O_NONBLOCK", 0),
                            dir_fd=directory_fd,
                        )
                    except OSError as exc:
                        raise StagedInputPostflightError(
                            "staged_input_unreadable",
                            input_index=input_index,
                        ) from exc
                    try:
                        before = os.fstat(input_fd)
                        if (
                            not stat.S_ISREG(before.st_mode)
                            or (before.st_dev, before.st_ino)
                            != (input_lstat.st_dev, input_lstat.st_ino)
                            or stat.S_IMODE(before.st_mode) != 0o400
                        ):
                            raise StagedInputPostflightError(
                                "staged_input_mode_mutated",
                                input_index=input_index,
                            )
                        expected_size = int(item["byte_count"])
                        if before.st_size != expected_size:
                            raise StagedInputPostflightError(
                                "staged_input_integrity_mismatch",
                                input_index=input_index,
                            )
                        digest = hashlib.sha256()
                        observed_size = 0
                        while True:
                            chunk = os.read(input_fd, 1024 * 1024)
                            if not chunk:
                                break
                            observed_size += len(chunk)
                            if observed_size > expected_size:
                                raise StagedInputPostflightError(
                                    "staged_input_integrity_mismatch",
                                    input_index=input_index,
                                )
                            digest.update(chunk)
                        after = os.fstat(input_fd)
                    finally:
                        os.close(input_fd)
                    if (
                        _staged_input_identity(before)
                        != _staged_input_identity(after)
                        or observed_size != expected_size
                        or digest.hexdigest() != item["sha256"]
                    ):
                        raise StagedInputPostflightError(
                            "staged_input_integrity_mismatch",
                            input_index=input_index,
                        )
                directory_after = os.fstat(directory_fd)
                if (
                    _staged_input_identity(opened_directory)
                    != _staged_input_identity(directory_after)
                    or stat.S_IMODE(directory_after.st_mode) != 0o500
                    or set(os.listdir(directory_fd)) != set(expected_files)
                ):
                    raise StagedInputPostflightError(
                        "staged_input_directory_mutated"
                    )
            finally:
                os.close(directory_fd)
    finally:
        os.close(root_fd)


def _run_staged_input_postflight(
    plan: WorkflowPlan,
    agent_name: str,
    execution_cwd: Path,
    observer_manifest: list[dict[str, Any]],
    *,
    phase: str = "postflight",
) -> tuple[Path, str | None]:
    try:
        _verify_staged_read_only_inputs(execution_cwd, observer_manifest)
    except StagedInputPostflightError as exc:
        return (
            _write_staged_input_manifest(
                plan,
                agent_name,
                observer_manifest,
                phase=phase,
                provider_process_started=True,
                issue=exc,
            ),
            exc.code,
        )
    return (
        _write_staged_input_manifest(
            plan,
            agent_name,
            observer_manifest,
            phase=phase,
            provider_process_started=True,
        ),
        None,
    )


def _researcher_source_manifest(
    agentlab_root: str | Path,
    source_paths: list[Path],
) -> list[dict[str, Any]]:
    """Describe the exact local sources already embedded in Researcher messages."""

    root = Path(agentlab_root).resolve(strict=False)
    result: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for source in source_paths:
        path = Path(source)
        if not path.is_file() or path.is_symlink():
            continue
        resolved = path.resolve(strict=True)
        if resolved in seen:
            continue
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError:
            continue
        seen.add(resolved)
        result.append(
            {
                "path": relative,
                "byte_count": path.stat().st_size,
                "sha256": _sha256_file(path),
                "delivery": "embedded_in_sealed_messages",
                "local_file_access_allowed": False,
            }
        )
    return result


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


def _coerce_process_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _append_cli_execution_record(
    run_dir: Path,
    *,
    agent_name: str,
    cli_agent_name: str,
    argv: list[str],
    cwd: str | Path,
    exit_code: int | None,
    timed_out: bool,
    timeout_sec: int,
    status: str,
    stdout: str,
    stderr: str,
    started_at: datetime,
    finished_at: datetime,
    redact_prompt: bool = False,
) -> str | None:
    try:
        from execution_log import append_command_record

        # Sealed role bodies live in the packet, never in argv. The retained
        # compatibility flag is intentionally ignored for older callers.
        logged_argv = list(argv)
        return append_command_record(
            run_dir,
            {
                "node": agent_name,
                "agent": agent_name,
                "cli_agent": cli_agent_name,
                "command": shlex.join(logged_argv),
                "argv": logged_argv,
                "cwd": str(cwd),
                "exit_code": exit_code,
                "timed_out": timed_out,
                "timeout_sec": timeout_sec,
                "status": status,
                "stdout": stdout,
                "stderr": stderr,
                "started_at": started_at.isoformat(),
                "completed_at": finished_at.isoformat(),
            },
        )
    except Exception:
        return None


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
    sealed_messages: list[dict[str, str]] | None = None,
    task_messages: list[dict[str, str]] | None = None,
    outbound_source_paths: list[Path] | None = None,
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
        - ``CLI_AGENT_NOT_AVAILABLE``  — binary not found; caller must block or
          use a separately approved same-role route.
    """
    role_profile = dict(role_profile)
    role_profile.setdefault(
        "_runtime_model_execution_attempt_id",
        str(role_profile.get("capacity_attempt_id") or uuid4().hex),
    )
    role_profile.setdefault(
        "_runtime_capacity_selection_kind",
        str(role_profile.get("capacity_selection_kind") or "direct"),
    )
    resolved_invocation_contract = _resolve_invocation_contract(
        role_profile,
        plan.agentlab_root,
    )
    contract_worker_id = str(
        resolved_invocation_contract.get("worker_id") or ""
    ).strip()
    contract_model_profile = str(
        resolved_invocation_contract.get("model_profile") or ""
    ).strip()
    if contract_worker_id:
        role_profile["cli_agent"] = contract_worker_id
    if contract_model_profile:
        role_profile["default"] = contract_model_profile
    cli_agent_name: str = role_profile.get("cli_agent", "")
    cli_command_template: str = _resolve_invocation_contract_template(
        role_profile,
        plan.agentlab_root,
    )

    if not cli_agent_name or not cli_command_template:
        return CliAgentNotAvailable(
            cli_agent=cli_agent_name or "unknown",
            reason="missing_config",
            detail=(
                "Profile is missing cli_agent or a resolvable "
                "invocation_contract/cli_command."
            ),
        )

    run_dir = Path(plan.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    bounded_messages = sealed_messages is not None or task_messages is not None
    packet_payload = _task_packet_payload(
        agent_name,
        plan,
        sealed_messages,
        task_messages,
    )
    artifact_input_contract: dict[str, Any] = {}
    validated_artifact_inputs: list[dict[str, Any]] = []
    artifact_input_manifest_path: Path | None = None
    staged_input_manifest_path: Path | None = None
    staged_input_postflight_issue: str | None = None
    if agent_name == "ArtifactProducer":
        try:
            from agent_runtime.protocols.artifact_task import (
                ArtifactInputContractError,
                validate_artifact_task_inputs,
            )
        except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
            from protocols.artifact_task import (
                ArtifactInputContractError,
                validate_artifact_task_inputs,
            )
        try:
            artifact_input_contract = _load_artifact_input_contract(plan)
            validated_artifact_inputs = validate_artifact_task_inputs(
                Path(plan.agentlab_root),
                artifact_input_contract,
            )
        except ArtifactInputContractError as exc:
            artifact_input_manifest_path = _write_artifact_input_manifest(
                plan,
                issue=exc,
                phase="validation",
            )
            return _artifact_input_blocked_result(
                cli_agent_name,
                artifact_input_manifest_path,
                exc,
            )
        artifact_input_manifest_path = _write_artifact_input_manifest(
            plan,
            validated_inputs=validated_artifact_inputs,
            phase="validation",
        )
        if validated_artifact_inputs and not bounded_messages:
            exc = ArtifactInputContractError(
                "artifact_input_isolated_session_required"
            )
            artifact_input_manifest_path = _write_artifact_input_manifest(
                plan,
                validated_inputs=validated_artifact_inputs,
                issue=exc,
                phase="validation",
            )
            return _artifact_input_blocked_result(
                cli_agent_name,
                artifact_input_manifest_path,
                exc,
            )
        if validated_artifact_inputs:
            packet_payload["artifact_inputs"] = _public_artifact_input_rows(
                validated_artifact_inputs
            )
            context_policy = dict(packet_payload.get("context_policy") or {})
            context_policy["read_scope"] = [
                "this_task_packet",
                "artifact_inputs/*",
            ]
            context_policy["additional_file_reads_allowed"] = True
            context_policy["additional_file_read_boundary"] = "artifact_inputs/*"
            packet_payload["context_policy"] = context_policy
    if agent_name == "Researcher" and (
        sealed_messages is not None or task_messages is not None
    ):
        packet_payload["declared_sources"] = _researcher_source_manifest(
            plan.agentlab_root,
            outbound_source_paths or [],
        )
    observer_manifest = _observer_input_manifest(
        agent_name,
        outbound_source_paths or [],
    )
    if observer_manifest and not bounded_messages:
        issue = StagedInputPostflightError(
            "staged_input_isolated_session_required"
        )
        staged_input_manifest_path = _write_staged_input_manifest(
            plan,
            agent_name,
            observer_manifest,
            phase="validation",
            provider_process_started=False,
            issue=issue,
        )
        return LLMCallResult(
            provider="agentlab-protocol",
            model=cli_agent_name,
            content=(
                f"# {agent_name} staged input blocked\n\n"
                "Governed visual inputs require an isolated bounded role session. "
                "No provider process was started.\n"
            ),
            status="blocked_user_decision",
            error="staged_input_validation_failed",
            raw_usage={
                "usage_source": "protocol_gate",
                "failure_class": "validation_failed",
                "staged_input_postflight_issue": issue.code,
                "staged_input_manifest": str(staged_input_manifest_path),
                "provider_process_started": False,
            },
        )
    if observer_manifest:
        staged_input_key = (
            "observer_inputs"
            if agent_name == "Observer"
            else "visual_inputs"
        )
        packet_payload[staged_input_key] = [
            {key: value for key, value in item.items() if key != "_source_path"}
            for item in observer_manifest
        ]
        context_policy = packet_payload.get("context_policy") or {}
        staged_scope = str(observer_manifest[0]["staged_path"]).split("/", 1)[0] + "/*"
        context_policy["read_scope"] = ["this_task_packet", staged_scope]
        context_policy["additional_file_reads_allowed"] = True
        context_policy["additional_file_read_boundary"] = staged_scope
        packet_payload["context_policy"] = context_policy
    packet_text = json.dumps(packet_payload, indent=2, ensure_ascii=False)
    model_values = _model_invocation_values(role_profile, plan.agentlab_root)
    process_env, contract_env_unset = _contract_process_environment(
        role_profile,
        plan.agentlab_root,
    )
    manifest_path: Path | None = None
    if bounded_messages:
        try:
            from agent_runtime.outbound_context import (
                PRIVATE_CONTEXT_APPROVAL_ENV_NAME,
                PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME,
                write_outbound_context_manifest,
            )
        except ModuleNotFoundError:  # pragma: no cover - direct script path
            from outbound_context import (
                PRIVATE_CONTEXT_APPROVAL_ENV_NAME,
                PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME,
                write_outbound_context_manifest,
            )

        manifest_path = run_dir / f"outbound_context_manifest_{agent_name.lower()}.yml"
        production_pack_session = task_messages is not None
        pack_role_contracts = (plan.production_pack or {}).get("role_contracts") or {}
        configured_pack_role_session = (
            isinstance(pack_role_contracts, dict)
            and agent_name in pack_role_contracts
        )
        approval_required = (
            production_pack_session
            or configured_pack_role_session
            or bool(
                (getattr(plan, "execution_policy", {}) or {}).get(
                    "external_context_approval_required"
                )
            )
            or (
            str(plan.task_id).startswith("task_narrative_eval_")
            or os.getenv("AGENTLAB_TRUSTED_LIVE_RUNNER") == "1"
            )
        )
        approval_env_name = (
            PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME
            if production_pack_session
            else PRIVATE_CONTEXT_APPROVAL_ENV_NAME
        )
        manifest = write_outbound_context_manifest(
            Path(plan.agentlab_root),
            manifest_path,
            item_id=str(plan.task_id),
            role=agent_name,
            provider_surface=f"cli_agent:{cli_agent_name}",
            payload_kind=(
                "production_pack_cli_role_session_packet"
                if production_pack_session
                else "sealed_cli_role_session_packet"
            ),
            payload_text=packet_text,
            source_paths=outbound_source_paths or [],
            private_context=True,
            exact_payload=True,
            sealed_context=True,
            execution_workspace_isolated=True,
            approval_required=approval_required,
            approval_env_name=approval_env_name,
            provider_shell_or_browser_requested=agent_name == "Researcher",
            source_inventory_required=(
                production_pack_session
                or configured_pack_role_session
                or agent_name == "Researcher"
            ),
        )
        if not manifest.get("execution_allowed"):
            return LLMCallResult(
                provider="agentlab-cli-executor",
                model=cli_agent_name,
                content=(
                    f"# {agent_name} outbound context blocked\n\n"
                    "The deterministic outbound-context gate refused the CLI provider call. "
                    f"Inspect {manifest_path.name} for content-free reasons.\n"
                ),
                status="blocked_user_decision",
                error=f"{agent_name.lower()}_outbound_context_gate_blocked",
                raw_usage={
                    "cli_agent": cli_agent_name,
                    "outbound_context_manifest": str(manifest_path),
                    "outbound_context_status": manifest.get("status"),
                },
            )

    packet_path = run_dir / f"task_packet_{agent_name.lower()}.json"
    packet_path.write_text(packet_text, encoding="utf-8")
    sealed_packet_stdin = (
        bounded_messages
        and resolved_invocation_contract.get("packet_delivery") == "stdin"
    )
    if (
        resolved_invocation_contract.get("packet_delivery") == "stdin"
        and not bounded_messages
    ):
        return CliAgentNotAvailable(
            cli_agent=cli_agent_name,
            reason="stdin_packet_requires_bounded_messages",
            detail="stdin packet delivery is valid only for sealed role sessions",
        )
    try:
        argv = _render_command(
            cli_command_template,
            packet_path,
            workspace_path=Path(plan.agentlab_root),
            provider=model_values["provider"],
            model_id=model_values["model_id"],
            model_key=model_values["model_key"],
            append_task_packet_path=not sealed_packet_stdin,
        )
    except ValueError as exc:
        return CliAgentNotAvailable(
            cli_agent=cli_agent_name,
            reason="invalid_cli_template",
            detail=str(exc),
        )

    # ── Binary candidate resolution ────────────────────────────────────────
    # If the role profile defines ``binary_candidates``, resolve the first
    # available binary and patch argv[0].  This allows the config to list a
    # canonical binary (e.g. ``claude``) while keeping legacy aliases
    # (e.g. ``ccs``) as fallbacks.
    governed_grok_research = (
        agent_name == "Researcher"
        and str(role_profile.get("cli_agent") or "").strip() == "grok"
        and str(role_profile.get("invocation_contract") or "").strip()
        == "grok_research"
    )
    binary_candidates: list[str] | None = role_profile.get("binary_candidates")
    candidate_used: str | None = None
    if binary_candidates:
        resolved = _resolve_binary_candidate(binary_candidates)
        if resolved is None and not governed_grok_research:
            return CliAgentNotAvailable(
                cli_agent=cli_agent_name,
                reason="binary_not_found",
                detail=(
                    f"None of the configured binary candidates "
                    f"{binary_candidates!r} for CLI agent "
                    f"`{cli_agent_name}` were found in PATH. "
                    "AgentLab will not change provider surfaces automatically. "
                    f"To enable the CLI agent, install `{cli_agent_name}` "
                    f"and ensure its binary is on PATH."
                ),
            )
        if resolved is not None:
            argv[0] = resolved
            candidate_used = resolved

    binary_available = _binary_available(argv)
    if not binary_available and not governed_grok_research:
        return CliAgentNotAvailable(
            cli_agent=cli_agent_name,
            reason="binary_not_found",
            detail=(
                f"CLI agent `{argv[0]}` was not found in PATH. "
                "AgentLab will not change provider surfaces automatically. "
                f"To enable the CLI agent, install `{cli_agent_name}` and ensure "
                f"its binary is on PATH."
            ),
        )

    effective_timeout = timeout or int(
        os.getenv("AGENTLAB_CLI_AGENT_TIMEOUT", "600")
    )

    workspace_context = (
        tempfile.TemporaryDirectory(prefix="agentlab-sealed-role-")
        if bounded_messages
        else None
    )
    artifact_materialization: dict[str, Any] | None = None
    artifact_input_postflight_issue: str | None = None
    hermes_preflight: dict[str, Any] = {
        "applicable": False,
        "status": "not_applicable",
        "issues": [],
    }
    agy_preflight: dict[str, Any] = {
        "applicable": False,
        "status": "not_applicable",
        "issues": [],
    }
    claude_preflight: dict[str, Any] = {
        "applicable": False,
        "status": "not_applicable",
        "issues": [],
    }
    qwen_artifact_preflight: dict[str, Any] = {
        "applicable": False,
        "status": "not_applicable",
        "issues": [],
    }
    grok_research_preflight: dict[str, Any] = {
        "applicable": False,
        "status": "not_applicable",
        "issues": [],
    }
    model_receipt_path: str | None = None
    ultracode_activation_receipt_path: str | None = None
    research_workspace_read_only = False
    execution_packet_path = packet_path
    try:
        execution_cwd = Path(plan.agentlab_root)
        if workspace_context is not None:
            execution_cwd = Path(workspace_context.name)
            if (
                resolved_invocation_contract.get("structured_output")
                == "narrative_heavy_audit"
            ):
                (execution_cwd / "narrative_heavy_audit_output.schema.json").write_text(
                    json.dumps(
                        _narrative_heavy_audit_output_schema(
                            agent_name,
                            blocking_rewrite_required=(
                                agent_name == "Verifier"
                                and _narrative_heavy_audit_requires_rewrite(run_dir)
                            ),
                        ),
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            if agent_name == "ArtifactProducer" and validated_artifact_inputs:
                try:
                    from agent_runtime.protocols.artifact_task import (
                        ArtifactInputContractError,
                        stage_artifact_task_inputs,
                    )
                except ModuleNotFoundError:  # pragma: no cover - direct runtime path
                    from protocols.artifact_task import (
                        ArtifactInputContractError,
                        stage_artifact_task_inputs,
                    )
                try:
                    staged_artifact_inputs = stage_artifact_task_inputs(
                        Path(plan.agentlab_root),
                        artifact_input_contract,
                        execution_cwd,
                    )
                except ArtifactInputContractError as exc:
                    artifact_input_manifest_path = _write_artifact_input_manifest(
                        plan,
                        validated_inputs=validated_artifact_inputs,
                        issue=exc,
                        phase="staging",
                    )
                    return _artifact_input_blocked_result(
                        cli_agent_name,
                        artifact_input_manifest_path,
                        exc,
                    )
                artifact_input_manifest_path = _write_artifact_input_manifest(
                    plan,
                    validated_inputs=staged_artifact_inputs,
                    phase="staged",
                )
            if observer_manifest:
                for item in observer_manifest:
                    destination = execution_cwd / str(item["staged_path"])
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(item["_source_path"]), destination)
                    destination.chmod(0o400)
                    staged_hash = _sha256_file(destination)
                    staged_size = destination.stat().st_size
                    if (
                        staged_hash != item["sha256"]
                        or staged_size != item["byte_count"]
                    ):
                        issue = StagedInputPostflightError(
                            "staged_input_integrity_mismatch"
                        )
                        staged_input_manifest_path = _write_staged_input_manifest(
                            plan,
                            agent_name,
                            observer_manifest,
                            phase="staging",
                            provider_process_started=False,
                            issue=issue,
                        )
                        return LLMCallResult(
                            provider="agentlab-protocol",
                            model=cli_agent_name,
                            content=(
                                (
                                    "# Observer input integrity blocked\n\n"
                                    if agent_name == "Observer"
                                    else "# Staged visual input integrity blocked\n\n"
                                )
                                +
                                "An assigned input changed while AgentLab was staging its "
                                "read-only copy. No provider process was started.\n"
                            ),
                            status="blocked_user_decision",
                            error=(
                                "observer_input_integrity_changed"
                                if agent_name == "Observer"
                                else "staged_visual_input_integrity_changed"
                            ),
                            raw_usage={
                                "usage_source": "protocol_gate",
                                "observer_input_count": len(observer_manifest),
                                "observer_input_integrity": "mismatch",
                                "staged_input_postflight_issue": issue.code,
                                "staged_input_manifest": str(
                                    staged_input_manifest_path
                                ),
                                "provider_process_started": False,
                            },
                        )
                for staged_directory in {
                    execution_cwd / Path(str(item["staged_path"])).parts[0]
                    for item in observer_manifest
                }:
                    staged_directory.chmod(0o500)
                try:
                    _verify_staged_read_only_inputs(
                        execution_cwd,
                        observer_manifest,
                    )
                except StagedInputPostflightError as exc:
                    staged_input_manifest_path = _write_staged_input_manifest(
                        plan,
                        agent_name,
                        observer_manifest,
                        phase="staging",
                        provider_process_started=False,
                        issue=exc,
                    )
                    return LLMCallResult(
                        provider="agentlab-protocol",
                        model=cli_agent_name,
                        content=(
                            f"# {agent_name} staged input integrity blocked\n\n"
                            "The read-only staged input boundary did not validate. "
                            "No provider process was started.\n"
                        ),
                        status="blocked_user_decision",
                        error=(
                            "observer_input_integrity_changed"
                            if agent_name == "Observer"
                            else "staged_visual_input_integrity_changed"
                        ),
                        raw_usage={
                            "usage_source": "protocol_gate",
                            "observer_input_count": len(observer_manifest),
                            "observer_input_integrity": "mismatch",
                            "staged_input_postflight_issue": exc.code,
                            "staged_input_manifest": str(
                                staged_input_manifest_path
                            ),
                            "provider_process_started": False,
                        },
                    )
                staged_input_manifest_path = _write_staged_input_manifest(
                    plan,
                    agent_name,
                    observer_manifest,
                    phase="staged",
                    provider_process_started=False,
                )
            execution_packet_path = execution_cwd / packet_path.name
            execution_packet_path.write_text(packet_text, encoding="utf-8")
            argv = _render_command(
                cli_command_template,
                execution_packet_path,
                workspace_path=execution_cwd,
                provider=model_values["provider"],
                model_id=model_values["model_id"],
                model_key=model_values["model_key"],
                append_task_packet_path=not sealed_packet_stdin,
            )
            if candidate_used:
                argv[0] = candidate_used
            if agent_name == "Researcher":
                execution_packet_path.chmod(0o400)
                execution_cwd.chmod(0o500)
                research_workspace_read_only = True

        if agent_name == "Supervisor":
            hermes_preflight = _hermes_supervisor_preflight(
                role_profile,
                plan.agentlab_root,
                process_env,
                argv,
                model_values,
            )
        agy_preflight = _agy_oauth_preflight(
            role_profile,
            argv,
            model_values,
        )
        claude_preflight = _claude_runtime_preflight(
            role_profile,
            argv,
            model_values,
            packet_payload,
            resolved_invocation_contract,
        )
        ultracode_activation_receipt_path = _write_ultracode_activation_receipt(
            run_dir,
            claude_preflight,
        )
        qwen_artifact_preflight = _qwen_artifact_preflight(
            role_profile,
            argv,
            model_values,
            process_env,
        )
        grok_research_preflight = _grok_research_preflight(
            role_profile,
            plan.agentlab_root,
            process_env,
            argv,
            model_values,
            agent_name=agent_name,
            bounded_messages=bounded_messages,
            execution_cwd=execution_cwd,
            task_packet_path=execution_packet_path,
            binary_available=binary_available,
        )
        if hermes_preflight.get("applicable") and hermes_preflight.get("status") != "pass":
            model_receipt_path = _write_hermes_supervisor_model_receipt(
                run_dir,
                hermes_preflight,
                status="fail",
                provider_process_started=False,
            )
            return LLMCallResult(
                provider="agentlab-protocol",
                model=cli_agent_name,
                content=(
                    "# Supervisor model execution blocked\n\n"
                    "The resolved Supervisor provider, model, reasoning effort, or "
                    "exact command binding did not match the governed route. No "
                    "provider process was started.\n"
                ),
                status="blocked_user_decision",
                error="supervisor_model_preflight_failed",
                raw_usage={
                    "cli_agent": cli_agent_name,
                    "cli_runtime_provider": model_values["provider"],
                    "provider_process_started": False,
                    "supervisor_model_preflight": hermes_preflight,
                    **(
                        {"model_execution_receipt": model_receipt_path}
                        if model_receipt_path
                        else {}
                    ),
                    **(
                        {
                            "model_execution_chain": str(
                                _model_execution_chain_path(run_dir, agent_name)
                            )
                        }
                        if model_receipt_path
                        else {}
                    ),
                },
            )
        if (
            agy_preflight.get("governed")
            and agy_preflight.get("status") != "pass"
        ):
            model_receipt_path = _write_agy_model_receipt(
                run_dir,
                agent_name,
                agy_preflight,
                status="fail",
                provider_process_started=False,
                environment_unset=contract_env_unset,
                extra_issues=["agy_oauth_preflight_failed"],
            )
            return LLMCallResult(
                provider="agentlab-protocol",
                model=cli_agent_name,
                content=(
                    f"# {agent_name} Agy model execution blocked\n\n"
                    "The governed Agy command was not bound to the selected "
                    "OAuth model and role profile. No provider process was started.\n"
                ),
                status="blocked_user_decision",
                error="agy_oauth_model_preflight_failed",
                raw_usage={
                    "cli_agent": cli_agent_name,
                    "cli_model_key": model_values["model_key"],
                    "cli_model_id": model_values["model_id"],
                    "cli_catalog_model_id": model_values["catalog_model_id"],
                    "cli_runtime_provider": model_values["provider"],
                    "provider_process_started": False,
                    "agy_oauth_preflight": agy_preflight,
                    "contract_environment_unset": contract_env_unset,
                    **(
                        {"model_execution_receipt": model_receipt_path}
                        if model_receipt_path
                        else {}
                    ),
                    **(
                        {
                            "model_execution_chain": str(
                                _model_execution_chain_path(run_dir, agent_name)
                            )
                        }
                        if model_receipt_path
                        else {}
                    ),
                },
            )
        if (
            claude_preflight.get("applicable")
            and claude_preflight.get("status") != "pass"
        ):
            model_receipt_path = _write_claude_model_receipt(
                run_dir,
                agent_name,
                claude_preflight,
                status="fail",
                provider_process_started=False,
                extra_issues=["claude_model_preflight_failed"],
            )
            return LLMCallResult(
                provider="agentlab-protocol",
                model=cli_agent_name,
                content=(
                    f"# {agent_name} Claude model execution blocked\n\n"
                    "The Claude command, model, JSON output, or explicit "
                    "developmental Ultracode activation did not match the "
                    "governed contract. No provider process was started.\n"
                ),
                status="blocked_user_decision",
                error="claude_model_preflight_failed",
                raw_usage={
                    "cli_agent": cli_agent_name,
                    "cli_model_key": model_values["model_key"],
                    "cli_model_id": model_values["model_id"],
                    "cli_catalog_model_id": model_values["catalog_model_id"],
                    "cli_runtime_provider": model_values["provider"],
                    "provider_process_started": False,
                    "claude_model_preflight": claude_preflight,
                    **(
                        {
                            "ultracode_activation_receipt": (
                                ultracode_activation_receipt_path
                            )
                        }
                        if ultracode_activation_receipt_path
                        else {}
                    ),
                    **(
                        {"model_execution_receipt": model_receipt_path}
                        if model_receipt_path
                        else {}
                    ),
                    **(
                        {
                            "model_execution_chain": str(
                                _model_execution_chain_path(run_dir, agent_name)
                            )
                        }
                        if model_receipt_path
                        else {}
                    ),
                },
            )
        if (
            qwen_artifact_preflight.get("applicable")
            and qwen_artifact_preflight.get("status") != "pass"
        ):
            model_receipt_path = _write_qwen_artifact_model_receipt(
                run_dir,
                qwen_artifact_preflight,
                status="fail",
                provider_process_started=False,
                extra_issues=["qwen_artifact_preflight_failed"],
            )
            return LLMCallResult(
                provider="agentlab-protocol",
                model=cli_agent_name,
                content=(
                    "# ArtifactProducer Qwen execution blocked\n\n"
                    "The exact DashScope key/base URL/model/sandbox binding did "
                    "not pass. No provider process was started.\n"
                ),
                status="blocked_user_decision",
                error="qwen_artifact_preflight_failed",
                raw_usage={
                    "cli_agent": cli_agent_name,
                    "provider_process_started": False,
                    "qwen_artifact_preflight": qwen_artifact_preflight,
                    "model_execution_receipt": model_receipt_path,
                    "model_execution_chain": str(
                        _model_execution_chain_path(run_dir, agent_name)
                    ),
                },
            )
        if (
            grok_research_preflight.get("applicable")
            and grok_research_preflight.get("status") != "pass"
        ):
            model_receipt_path = _write_grok_research_model_receipt(
                run_dir,
                grok_research_preflight,
                status="fail",
                provider_process_started=False,
                extra_issues=["grok_research_preflight_failed"],
            )
            return LLMCallResult(
                provider="agentlab-protocol",
                model=cli_agent_name,
                content=(
                    "# Researcher Grok execution blocked\n\n"
                    "The exact Hermes xAI OAuth model, credential, empty-fallback, "
                    "sealed-context, and read-only workspace binding did not pass. "
                    "No provider process was started.\n"
                ),
                status="blocked_user_decision",
                error="grok_research_preflight_failed",
                raw_usage={
                    "cli_agent": cli_agent_name,
                    "provider_process_started": False,
                    "grok_research_preflight": grok_research_preflight,
                    "model_execution_receipt": model_receipt_path,
                    "model_execution_chain": str(
                        _model_execution_chain_path(run_dir, agent_name)
                    ),
                },
            )

        cli_log_path = _ensure_cli_log_file_arg(argv, run_dir, cli_agent_name)
        started_at = datetime.now(timezone.utc)
        try:
            run_kwargs: dict[str, Any] = {
                "capture_output": True,
                "text": True,
                "timeout": effective_timeout,
                "cwd": execution_cwd,
                "env": process_env,
            }
            if sealed_packet_stdin:
                run_kwargs["input"] = packet_text
            else:
                run_kwargs["stdin"] = subprocess.DEVNULL
            proc = subprocess.run(argv, **run_kwargs)
            if observer_manifest and workspace_context is not None:
                (
                    staged_input_manifest_path,
                    staged_input_postflight_issue,
                ) = _run_staged_input_postflight(
                    plan,
                    agent_name,
                    execution_cwd,
                    observer_manifest,
                )
            if agent_name == "ArtifactProducer" and workspace_context is not None:
                (
                    artifact_input_manifest_path,
                    artifact_input_postflight_issue,
                ) = _verify_artifact_input_postflight(
                    plan,
                    execution_cwd,
                    validated_artifact_inputs,
                )
            if (
                agent_name == "ArtifactProducer"
                and workspace_context is not None
                and proc.returncode == 0
                and artifact_input_postflight_issue is None
            ):
                artifact_materialization = _materialize_isolated_artifact_outputs(
                    execution_cwd,
                    plan,
                    [str(item) for item in packet_payload.get("required_outputs", [])],
                )
        except subprocess.TimeoutExpired as exc:
            finished_at = datetime.now(timezone.utc)
            if observer_manifest and workspace_context is not None:
                (
                    staged_input_manifest_path,
                    staged_input_postflight_issue,
                ) = _run_staged_input_postflight(
                    plan,
                    agent_name,
                    execution_cwd,
                    observer_manifest,
                    phase="provider_timeout_postflight",
                )
            if agent_name == "ArtifactProducer" and workspace_context is not None:
                (
                    artifact_input_manifest_path,
                    artifact_input_postflight_issue,
                ) = _verify_artifact_input_postflight(
                    plan,
                    execution_cwd,
                    validated_artifact_inputs,
                    phase="provider_timeout_postflight",
                )
            stdout_text = _coerce_process_output(exc.stdout)
            stderr_text = _coerce_process_output(exc.stderr)
            stderr_text = _augment_empty_stderr_with_cli_log(
                stderr_text,
                cli_log_path=cli_log_path,
                cli_agent_name=cli_agent_name,
            )
            usage_estimate = _external_cli_usage(
                packet_path,
                argv,
                agent_name,
                cli_agent_name,
                stdout_text,
                stderr_text,
            )
            timeout_failure_class = classify_cli_error(
                None,
                stdout_text,
                stderr_text,
                timeout_occurred=True,
                config_path=(
                    Path(plan.agentlab_root)
                    / "config"
                    / "cli_error_classification.yml"
                ),
            )
            timeout_receipt_issues = [
                "provider_process_timeout",
                f"failure_class:{timeout_failure_class}",
                *(
                    [f"staged_input_postflight_failed:{staged_input_postflight_issue}"]
                    if staged_input_postflight_issue
                    else []
                ),
            ]
            command_id = _append_cli_execution_record(
                run_dir,
                agent_name=agent_name,
                cli_agent_name=cli_agent_name,
                argv=argv,
                cwd=execution_cwd,
                exit_code=None,
                timed_out=True,
                timeout_sec=effective_timeout,
                status="timeout",
                stdout=stdout_text,
                stderr=stderr_text,
                started_at=started_at,
                finished_at=finished_at,
            )
            evidence = (
                f"\n\nEvidence: command_id {command_id} in execution_log.yml"
                if command_id
                else ""
            )
            hermes_receipt_path = _write_hermes_supervisor_model_receipt(
                run_dir,
                hermes_preflight,
                status="fail",
                provider_process_started=True,
                exit_code=None,
                stdout_nonempty=bool(stdout_text.strip()),
                timed_out=True,
                extra_issues=timeout_receipt_issues,
            )
            agy_receipt_path = _write_agy_model_receipt(
                run_dir,
                agent_name,
                agy_preflight,
                status="fail",
                provider_process_started=True,
                environment_unset=contract_env_unset,
                exit_code=None,
                stdout_nonempty=bool(stdout_text.strip()),
                timed_out=True,
                extra_issues=timeout_receipt_issues,
            )
            claude_receipt_path = _write_claude_model_receipt(
                run_dir,
                agent_name,
                claude_preflight,
                status="fail",
                provider_process_started=True,
                usage=usage_estimate,
                exit_code=None,
                stdout_nonempty=bool(stdout_text.strip()),
                timed_out=True,
                provider_model_mismatch=_claude_provider_model_mismatch(
                    claude_preflight,
                    usage_estimate,
                ),
                extra_issues=timeout_receipt_issues,
            )
            qwen_receipt_path = _write_qwen_artifact_model_receipt(
                run_dir,
                qwen_artifact_preflight,
                status="fail",
                provider_process_started=True,
                usage=usage_estimate,
                exit_code=None,
                stdout_nonempty=bool(stdout_text.strip()),
                timed_out=True,
                provider_model_mismatch=_qwen_provider_model_mismatch(
                    qwen_artifact_preflight,
                    usage_estimate,
                ),
                extra_issues=timeout_receipt_issues,
            )
            grok_receipt_path = _write_grok_research_model_receipt(
                run_dir,
                grok_research_preflight,
                status="fail",
                provider_process_started=True,
                usage=usage_estimate,
                exit_code=None,
                stdout_nonempty=bool(stdout_text.strip()),
                timed_out=True,
                provider_model_mismatch=_grok_provider_model_mismatch(
                    grok_research_preflight,
                    usage_estimate,
                ),
                extra_issues=timeout_receipt_issues,
            )
            model_receipt_path = (
                hermes_receipt_path
                or agy_receipt_path
                or claude_receipt_path
                or qwen_receipt_path
                or grok_receipt_path
            )
            return LLMCallResult(
                provider="agentlab-cli-executor",
                model=cli_agent_name,
                content=(
                    f"# {agent_name} CLI Agent Timeout\n\n"
                    f"Process `{argv[0]}` did not complete within {effective_timeout}s.\n\n"
                    f"**Action required**: Check whether `{cli_agent_name}` is stuck, "
                    "then rerun or select an explicitly approved capacity route."
                    f"{evidence}"
                ),
                status="blocked_user_decision",
                error=f"CLI agent timed out after {effective_timeout}s.",
                input_tokens=usage_estimate["input_tokens"],
                output_tokens=usage_estimate["output_tokens"],
                total_tokens=usage_estimate["total_tokens"],
                raw_usage={
                    "cli_agent": cli_agent_name,
                    "cli_model_key": model_values["model_key"],
                    "cli_model_id": model_values["model_id"],
                    "cli_catalog_model_id": model_values["catalog_model_id"],
                    "cli_runtime_provider": model_values["provider"],
                    "failure_class": timeout_failure_class,
                    "timeout": effective_timeout,
                    **usage_estimate,
                    **({"command_id": command_id} if command_id else {}),
                    **({"cli_log_path": str(cli_log_path)} if cli_log_path else {}),
                    **({"outbound_context_manifest": str(manifest_path)} if manifest_path else {}),
                    **(
                        {"staged_input_manifest": str(staged_input_manifest_path)}
                        if staged_input_manifest_path
                        else {}
                    ),
                    **(
                        {
                            "staged_input_postflight_issue": (
                                staged_input_postflight_issue
                            )
                        }
                        if staged_input_postflight_issue
                        else {}
                    ),
                    **(
                        {"artifact_input_manifest": str(artifact_input_manifest_path)}
                        if artifact_input_manifest_path
                        else {}
                    ),
                    **(
                        {
                            "artifact_input_postflight_issue": (
                                artifact_input_postflight_issue
                            )
                        }
                        if artifact_input_postflight_issue
                        else {}
                    ),
                    **({"contract_environment_unset": contract_env_unset} if contract_env_unset else {}),
                    **({"hermes_profile_preflight": hermes_preflight} if hermes_preflight.get("applicable") else {}),
                    **({"agy_oauth_preflight": agy_preflight} if agy_preflight.get("applicable") else {}),
                    **({"claude_model_preflight": claude_preflight} if claude_preflight.get("applicable") else {}),
                    **(
                        {"ultracode_activation_receipt": ultracode_activation_receipt_path}
                        if ultracode_activation_receipt_path
                        else {}
                    ),
                    **({"qwen_artifact_preflight": qwen_artifact_preflight} if qwen_artifact_preflight.get("applicable") else {}),
                    **({"grok_research_preflight": grok_research_preflight} if grok_research_preflight.get("applicable") else {}),
                    **({"model_execution_receipt": model_receipt_path} if model_receipt_path else {}),
                    **(
                        {
                            "model_execution_chain": str(
                                _model_execution_chain_path(run_dir, agent_name)
                            )
                        }
                        if model_receipt_path
                        else {}
                    ),
                },
            )
        except FileNotFoundError:
            hermes_receipt_path = _write_hermes_supervisor_model_receipt(
                run_dir,
                hermes_preflight,
                status="fail",
                provider_process_started=False,
                extra_issues=["provider_process_file_not_found"],
            )
            agy_receipt_path = _write_agy_model_receipt(
                run_dir,
                agent_name,
                agy_preflight,
                status="fail",
                provider_process_started=False,
                environment_unset=contract_env_unset,
                extra_issues=["provider_process_file_not_found"],
            )
            claude_receipt_path = _write_claude_model_receipt(
                run_dir,
                agent_name,
                claude_preflight,
                status="fail",
                provider_process_started=False,
                extra_issues=["provider_process_file_not_found"],
            )
            qwen_receipt_path = _write_qwen_artifact_model_receipt(
                run_dir,
                qwen_artifact_preflight,
                status="fail",
                provider_process_started=False,
                extra_issues=["provider_process_file_not_found"],
            )
            grok_receipt_path = _write_grok_research_model_receipt(
                run_dir,
                grok_research_preflight,
                status="fail",
                provider_process_started=False,
                extra_issues=["provider_process_file_not_found"],
            )
            model_receipt_path = (
                hermes_receipt_path
                or agy_receipt_path
                or claude_receipt_path
                or qwen_receipt_path
                or grok_receipt_path
            )
            if (
                agy_receipt_path
                or claude_receipt_path
                or qwen_receipt_path
                or grok_receipt_path
            ):
                return LLMCallResult(
                    provider="agentlab-cli-executor",
                    model=cli_agent_name,
                    content=(
                        f"# {agent_name} CLI executable unavailable\n\n"
                        f"Binary `{argv[0]}` disappeared before process startup. "
                        "AgentLab did not change provider surfaces.\n"
                    ),
                    status="blocked_user_decision",
                    error="CLI agent file_not_found before provider startup.",
                    raw_usage={
                        "cli_agent": cli_agent_name,
                        "cli_model_key": model_values["model_key"],
                        "cli_model_id": model_values["model_id"],
                        "cli_catalog_model_id": model_values["catalog_model_id"],
                        "cli_runtime_provider": model_values["provider"],
                        "failure_class": "binary_unavailable",
                        "provider_process_started": False,
                        **(
                            {
                                "staged_input_manifest": str(
                                    staged_input_manifest_path
                                )
                            }
                            if staged_input_manifest_path
                            else {}
                        ),
                        "agy_oauth_preflight": agy_preflight,
                        "claude_model_preflight": claude_preflight,
                        "qwen_artifact_preflight": qwen_artifact_preflight,
                        "grok_research_preflight": grok_research_preflight,
                        "contract_environment_unset": contract_env_unset,
                        "model_execution_receipt": model_receipt_path,
                        "model_execution_chain": str(
                            _model_execution_chain_path(run_dir, agent_name)
                        ),
                    },
                )
            return CliAgentNotAvailable(
                cli_agent=cli_agent_name,
                reason="file_not_found",
                detail=f"Binary `{argv[0]}` raised FileNotFoundError at exec time.",
            )
    finally:
        if workspace_context is not None:
            if research_workspace_read_only:
                try:
                    execution_cwd.chmod(0o700)
                    execution_packet_path.chmod(0o600)
                except OSError:
                    pass
            for staged_directory_name in {
                Path(str(item.get("staged_path") or "")).parts[0]
                for item in observer_manifest
                if Path(str(item.get("staged_path") or "")).parts
            }:
                staged_directory = execution_cwd / staged_directory_name
                try:
                    if staged_directory.is_dir() and not staged_directory.is_symlink():
                        staged_directory.chmod(0o700)
                except OSError:
                    pass
            workspace_context.cleanup()

    finished_at = datetime.now(timezone.utc)
    duration_s = (finished_at - started_at).total_seconds()

    # ── Determine success ─────────────────────────────────────────────────────
    stdout_text = proc.stdout.strip()
    stderr_text = proc.stderr.strip()
    stderr_text = _augment_empty_stderr_with_cli_log(
        stderr_text,
        cli_log_path=cli_log_path,
        cli_agent_name=cli_agent_name,
    )
    usage_estimate = _external_cli_usage(
        packet_path,
        argv,
        agent_name,
        cli_agent_name,
        proc.stdout or "",
        stderr_text or proc.stderr or "",
    )
    model_resolution_failed = (
        cli_agent_name == "agy"
        and _agy_model_resolution_failed(
            cli_log_path,
            stdout=proc.stdout or "",
            stderr=stderr_text or proc.stderr or "",
        )
    )
    claude_provider_model_mismatch = _claude_provider_model_mismatch(
        claude_preflight,
        usage_estimate,
    )
    qwen_provider_model_mismatch = _qwen_provider_model_mismatch(
        qwen_artifact_preflight,
        usage_estimate,
    )
    grok_provider_model_mismatch = _grok_provider_model_mismatch(
        grok_research_preflight,
        usage_estimate,
    )
    artifact_materialization_failed = bool(
        qwen_artifact_preflight.get("applicable")
        and (
            artifact_materialization is None
            or artifact_materialization.get("status") != "pass"
        )
    )
    success = (
        proc.returncode == 0
        and bool(stdout_text)
        and not model_resolution_failed
        and not claude_provider_model_mismatch
        and not qwen_provider_model_mismatch
        and not grok_provider_model_mismatch
        and not artifact_materialization_failed
        and artifact_input_postflight_issue is None
        and staged_input_postflight_issue is None
    )
    failure_class = (
        None
        if success
        else (
            "validation_failed"
            if (
                artifact_materialization_failed
                or artifact_input_postflight_issue
                or staged_input_postflight_issue
            )
            else (
                "model_unavailable"
                if (
                    model_resolution_failed
                    or claude_provider_model_mismatch
                    or qwen_provider_model_mismatch
                    or grok_provider_model_mismatch
                )
                else classify_cli_error(
                proc.returncode,
                stdout_text,
                stderr_text,
                config_path=(
                    Path(plan.agentlab_root)
                    / "config"
                    / "cli_error_classification.yml"
                ),
            )
            )
        )
    )
    receipt_failure_issues = (
        [] if success else [f"failure_class:{failure_class or 'unknown'}"]
    )
    if staged_input_postflight_issue:
        receipt_failure_issues.append(
            f"staged_input_postflight_failed:{staged_input_postflight_issue}"
        )
    command_id = _append_cli_execution_record(
        run_dir,
        agent_name=agent_name,
        cli_agent_name=cli_agent_name,
        argv=argv,
        cwd=execution_cwd,
        exit_code=proc.returncode,
        timed_out=False,
        timeout_sec=effective_timeout,
        status=(
            "success" if success else "failed"
        ),
        stdout=proc.stdout or "",
        stderr=stderr_text,
        started_at=started_at,
        finished_at=finished_at,
    )

    agy_receipt_path = _write_agy_model_receipt(
        run_dir,
        agent_name,
        agy_preflight,
        status=(
            "pass" if success else "fail"
        ),
        provider_process_started=True,
        environment_unset=contract_env_unset,
        exit_code=proc.returncode,
        stdout_nonempty=bool(stdout_text),
        timed_out=False,
        fallback_detected=model_resolution_failed,
        extra_issues=receipt_failure_issues,
    )
    if agy_receipt_path:
        model_receipt_path = agy_receipt_path
    claude_receipt_path = _write_claude_model_receipt(
        run_dir,
        agent_name,
        claude_preflight,
        status=(
            "pass" if success else "fail"
        ),
        provider_process_started=True,
        usage=usage_estimate,
        exit_code=proc.returncode,
        stdout_nonempty=bool(stdout_text),
        timed_out=False,
        provider_model_mismatch=claude_provider_model_mismatch,
        extra_issues=receipt_failure_issues,
    )
    if claude_receipt_path:
        model_receipt_path = claude_receipt_path
    qwen_receipt_path = _write_qwen_artifact_model_receipt(
        run_dir,
        qwen_artifact_preflight,
        status="pass" if success else "fail",
        provider_process_started=True,
        usage=usage_estimate,
        materialization=artifact_materialization,
        exit_code=proc.returncode,
        stdout_nonempty=bool(stdout_text),
        timed_out=False,
        provider_model_mismatch=qwen_provider_model_mismatch,
        extra_issues=receipt_failure_issues,
    )
    if qwen_receipt_path:
        model_receipt_path = qwen_receipt_path
    grok_receipt_path = _write_grok_research_model_receipt(
        run_dir,
        grok_research_preflight,
        status="pass" if success else "fail",
        provider_process_started=True,
        usage=usage_estimate,
        exit_code=proc.returncode,
        stdout_nonempty=bool(stdout_text),
        timed_out=False,
        provider_model_mismatch=grok_provider_model_mismatch,
        extra_issues=receipt_failure_issues,
    )
    if grok_receipt_path:
        model_receipt_path = grok_receipt_path

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

    hermes_receipt_path = _write_hermes_supervisor_model_receipt(
        run_dir,
        hermes_preflight,
        status="pass" if success else "fail",
        provider_process_started=True,
        exit_code=proc.returncode,
        stdout_nonempty=bool(stdout_text),
        timed_out=False,
        extra_issues=receipt_failure_issues,
    )
    if hermes_receipt_path:
        model_receipt_path = hermes_receipt_path

    # ── Build the canonical AgentLab report ──────────────────────────────────
    header = textwrap.dedent(f"""\
        # {agent_name} Report (CLI Agent: {cli_agent_name})

        - **Task**: {plan.task_id}
        - **Project**: {plan.project}
        - **CLI command**: `{shlex.join(argv)}`
        - **Exit code**: {proc.returncode}
        - **Duration**: {duration_s:.1f}s
        - **Started**: {started_at.isoformat()}
        - **Evidence**: {f'command_id {command_id} in execution_log.yml' if command_id else 'execution_log unavailable'}
    """)

    body = _extract_cli_result_text(proc.stdout or "", cli_agent_name)
    if (
        resolved_invocation_contract.get("structured_output")
        == "narrative_heavy_audit"
    ):
        body = (
            _narrative_heavy_audit_blocks_from_output(
                proc.stdout or "",
                agent_name,
            )
            or body
        )
    body = body if body else "(no stdout output)"
    stderr_section = (
        f"\n\n## stderr\n\n```\n{stderr_text}\n```" if stderr_text else ""
    )
    if model_resolution_failed:
        stderr_section += (
            "\n\n## Model Resolution\n\n"
            "Agy rejected the requested --model label; AgentLab blocked its "
            "silent default-model substitution."
        )
    if claude_provider_model_mismatch:
        stderr_section += (
            "\n\n## Provider Model Binding\n\n"
            "Claude reported a model different from the selected AgentLab route; "
            "AgentLab blocked the result and recorded the mismatch."
        )

    full_content = header + "\n## Output\n\n" + body + stderr_section

    result_status: str
    result_error: str | None
    if success:
        result_status = "completed"
        result_error = None
    else:
        result_status = "blocked_user_decision"
        result_error = f"CLI agent {failure_class} (exit {proc.returncode})."

    return LLMCallResult(
        provider="agentlab-cli-executor",
        model=cli_agent_name,
        content=full_content,
        status=result_status,
        error=result_error,
        input_tokens=usage_estimate["input_tokens"],
        output_tokens=usage_estimate["output_tokens"],
        total_tokens=usage_estimate["total_tokens"],
        raw_usage={
            "cli_agent": cli_agent_name,
            "binary": argv[0],
            "cli_model_key": model_values["model_key"],
            "cli_model_id": model_values["model_id"],
            "cli_catalog_model_id": model_values["catalog_model_id"],
            "cli_runtime_provider": model_values["provider"],
            "exit_code": proc.returncode,
            "duration_s": duration_s,
            "stdout_bytes": len(proc.stdout),
            "stderr_bytes": len(proc.stderr),
            "model_resolution_failed": model_resolution_failed,
            "provider_model_mismatch": claude_provider_model_mismatch,
            "qwen_provider_model_mismatch": qwen_provider_model_mismatch,
            "grok_provider_model_mismatch": grok_provider_model_mismatch,
            **({"failure_class": failure_class} if failure_class else {}),
            "task_packet_path": str(packet_path),
            "sealed_context": bounded_messages,
            "execution_workspace_isolated": bounded_messages,
            "inline_sealed_prompt": False,
            "sealed_packet_stdin": sealed_packet_stdin,
            "structured_output": resolved_invocation_contract.get(
                "structured_output"
            ),
            "observer_input_count": len(observer_manifest),
            "artifact_input_count": len(validated_artifact_inputs),
            **(
                {"staged_input_postflight_issue": staged_input_postflight_issue}
                if staged_input_postflight_issue
                else {}
            ),
            **(
                {"staged_input_manifest": str(staged_input_manifest_path)}
                if staged_input_manifest_path
                else {}
            ),
            **(
                {"artifact_input_postflight_issue": artifact_input_postflight_issue}
                if artifact_input_postflight_issue
                else {}
            ),
            **usage_estimate,
            **({"command_id": command_id} if command_id else {}),
            **({"binary_candidate_used": candidate_used} if candidate_used else {}),
            **({"cli_log_path": str(cli_log_path)} if cli_log_path else {}),
            **({"outbound_context_manifest": str(manifest_path)} if manifest_path else {}),
            **(
                {"artifact_input_manifest": str(artifact_input_manifest_path)}
                if artifact_input_manifest_path
                else {}
            ),
            **({"contract_environment_unset": contract_env_unset} if contract_env_unset else {}),
            **({"hermes_profile_preflight": hermes_preflight} if hermes_preflight.get("applicable") else {}),
            **({"agy_oauth_preflight": agy_preflight} if agy_preflight.get("applicable") else {}),
            **({"claude_model_preflight": claude_preflight} if claude_preflight.get("applicable") else {}),
            **(
                {"ultracode_activation_receipt": ultracode_activation_receipt_path}
                if ultracode_activation_receipt_path
                else {}
            ),
            **({"qwen_artifact_preflight": qwen_artifact_preflight} if qwen_artifact_preflight.get("applicable") else {}),
            **({"grok_research_preflight": grok_research_preflight} if grok_research_preflight.get("applicable") else {}),
            **({"model_execution_receipt": model_receipt_path} if model_receipt_path else {}),
            **(
                {
                    "artifact_materialization_receipt": artifact_materialization.get(
                        "receipt_path"
                    ),
                    "artifact_materialization_status": artifact_materialization.get(
                        "status"
                    ),
                    "artifact_materialized_outputs": artifact_materialization.get(
                        "materialized",
                        [],
                    ),
                    "artifact_materialization_missing": artifact_materialization.get(
                        "missing",
                        [],
                    ),
                    "artifact_materialization_blocked": artifact_materialization.get(
                        "blocked",
                        [],
                    ),
                }
                if artifact_materialization
                else {}
            ),
            **(
                {
                    "model_execution_chain": str(
                        _model_execution_chain_path(run_dir, agent_name)
                    )
                }
                if model_receipt_path
                else {}
            ),
        },
    )
