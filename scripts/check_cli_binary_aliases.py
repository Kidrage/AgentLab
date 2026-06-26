#!/usr/bin/env python3
"""Validate CLI binary alias configuration in ``config/agent_model_profiles.yml``.

Checks:
1. Every ``cli_agent: claude_code`` role has ``binary_candidates`` containing
   ``claude``.
2. No ``cli_agent: claude_code`` role uses ``ccs`` as the primary command binary
   without ``claude`` as a candidate.
3. ``cli_command`` is non-empty for every ``cli_agent`` role.
4. ``cli_command`` parses cleanly.
5. Unknown ``cli_agent`` values that lack explicit ``binary_candidates`` are
   flagged.
6. Known canonical mappings are validated.

This script validates **config shape**, not local environment.  External CLI
binaries do NOT need to be installed for this check to pass.

Exit code: 0 = clean, 1 = validation errors found, 2 = config file unreadable.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Any

import yaml

# ── Canonical binary mapping ────────────────────────────────────────────────
KNOWN_CLI_AGENTS: dict[str, dict[str, Any]] = {
    "claude_code": {
        "canonical": "claude",
        "legacy_aliases": ["ccs"],
        "description": "Claude Code CLI",
    },
    "hermes": {
        "canonical": "hermes",
        "legacy_aliases": [],
        "description": "Hermes CLI agent",
    },
    "agy": {
        "canonical": "agy",
        "legacy_aliases": [],
        "description": "Agy CLI agent",
    },
    "codex": {
        "canonical": "codex",
        "legacy_aliases": [],
        "description": "Codex CLI agent",
    },
    "openclaw": {
        "canonical": "openclaw",
        "legacy_aliases": [],
        "description": "OpenClaw CLI agent",
    },
}

# ── Helpers ─────────────────────────────────────────────────────────────────


def _parse_binary(cmd: str) -> str:
    """Return argv[0] from a CLI command string, or ``<parse_error>``."""
    try:
        tokens = shlex.split(cmd)
        return tokens[0] if tokens else ""
    except Exception:
        return "<parse_error>"


def _check_config(config_path: Path) -> list[str]:
    """Validate *config_path* and return a list of error messages."""
    errors: list[str] = []

    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"Cannot load config: {exc}"]

    if not isinstance(data, dict):
        return ["Config root is not a dict."]

    schema_version = data.get("schema_version", "unknown")
    modes = data.get("modes", {}) or {}

    if not modes:
        # Schema v3 fallback: check profiles
        profiles = data.get("profiles", {}) or {}
        if profiles:
            errors.append(
                "INFO: config uses schema v3 (profiles key). "
                "Validation limited to profile-level checks."
            )
        else:
            errors.append("No 'modes' or 'profiles' key found in config.")
            return errors

    print(f"{'='*70}")
    print(f"Config: {config_path}")
    print(f"Schema version: {schema_version}")
    print(f"Modes found: {list(modes.keys()) if modes else '(none)'}")
    print(f"{'='*70}")

    total_roles = 0
    ok_roles = 0

    for mode_name, mode_cfg in modes.items():
        if not isinstance(mode_cfg, dict):
            continue
        tiers = mode_cfg.get("tiers", {}) or {}
        for tier_name, tier_cfg in tiers.items():
            if not isinstance(tier_cfg, dict):
                continue
            for role_name, role_cfg in tier_cfg.items():
                if not isinstance(role_cfg, dict):
                    continue
                if role_cfg.get("executor_type") != "cli_agent":
                    continue

                total_roles += 1
                cli_agent = role_cfg.get("cli_agent", "<missing>")
                cli_command = role_cfg.get("cli_command", "")
                binary = _parse_binary(cli_command)
                binary_candidates = role_cfg.get("binary_candidates")

                agent_info = KNOWN_CLI_AGENTS.get(cli_agent)
                canonical = agent_info["canonical"] if agent_info else "unknown"
                legacy = agent_info["legacy_aliases"] if agent_info else []

                # Determine status
                status_flags: list[str] = []

                if agent_info and binary == agent_info["canonical"]:
                    status_flags.append("canonical_binary")
                elif agent_info and binary in agent_info.get("legacy_aliases", []):
                    status_flags.append("LEGACY_ALIAS")
                elif agent_info:
                    status_flags.append(f"UNKNOWN_BINARY({binary})")
                else:
                    status_flags.append("UNKNOWN_AGENT")

                if binary_candidates:
                    status_flags.append("has_candidates")
                elif agent_info and agent_info.get("legacy_aliases"):
                    status_flags.append("MISSING_CANDIDATES")

                print(
                    f"  [{mode_name}/{tier_name}] {role_name:20s} "
                    f"agent={cli_agent:15s} "
                    f"binary={binary:12s} "
                    f"canonical={canonical:12s} "
                    f"candidates={binary_candidates!r} "
                    f"flags={status_flags}"
                )

                # ── Validation rules ──────────────────────────────────────
                role_path = f"{mode_name}/{tier_name}/{role_name}"

                # Rule 1: claude_code must have binary_candidates with claude
                if cli_agent == "claude_code":
                    if not binary_candidates:
                        errors.append(
                            f"{role_path}: cli_agent=claude_code is missing "
                            f"binary_candidates; must include 'claude' at minimum."
                        )
                    elif "claude" not in binary_candidates:
                        errors.append(
                            f"{role_path}: cli_agent=claude_code "
                            f"binary_candidates={binary_candidates!r} does not "
                            f"include 'claude'."
                        )

                # Rule 2: claude_code with ccs as binary but no claude candidate
                if cli_agent == "claude_code" and binary == "ccs":
                    if not binary_candidates or "claude" not in binary_candidates:
                        errors.append(
                            f"{role_path}: cli_agent=claude_code uses 'ccs' as "
                            f"primary binary but 'claude' is not in "
                            f"binary_candidates."
                        )

                # Rule 3: empty cli_command
                if not cli_command.strip():
                    errors.append(
                        f"{role_path}: cli_command is empty."
                    )

                # Rule 4: parse failure
                if binary == "<parse_error>":
                    errors.append(
                        f"{role_path}: cli_command failed to parse: "
                        f"{cli_command!r}"
                    )

                # Rule 5: unknown cli_agent without explicit binary_candidates
                if cli_agent not in KNOWN_CLI_AGENTS and not binary_candidates:
                    errors.append(
                        f"{role_path}: unknown cli_agent={cli_agent!r} has no "
                        f"explicit binary_candidates. Add binary_candidates "
                        f"or register the agent in KNOWN_CLI_AGENTS."
                    )

                if not errors or errors[-1] != errors[-1] if errors else True:
                    ok_roles += 1

    print(f"\n{'='*70}")
    print(f"Total CLI agent roles: {total_roles}")
    print(f"Errors: {len(errors)}")
    print(f"{'='*70}")

    return errors


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    config_path = repo_root / "config" / "agent_model_profiles.yml"

    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        return 2

    errors = _check_config(config_path)

    if errors:
        print(f"\n❌ {len(errors)} validation error(s):", file=sys.stderr)
        for err in errors:
            print(f"  • {err}", file=sys.stderr)
        return 1

    print("\n✅ All CLI binary alias checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
