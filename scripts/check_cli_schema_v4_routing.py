#!/usr/bin/env python3
"""Acceptance check: schema v4 CLI agent profile routing.

Reads ``config/agent_model_profiles.yml`` and validates that:
- Schema v4 ``modes`` layout resolves CLI profiles correctly.
- Legacy ``profiles`` layout is still detectable (if present).
- No YAML parse errors.

Exits 0 when all checks pass, nonzero on failure.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure agent_runtime/ is importable
_agent_runtime = Path(__file__).resolve().parent.parent / "agent_runtime"
sys.path.insert(0, str(_agent_runtime))

import yaml


def _load_config() -> dict:
    """Load the canonical config file."""
    config_path = Path(__file__).resolve().parent.parent / "config" / "agent_model_profiles.yml"
    if not config_path.exists():
        print(f"FATAL: config not found at {config_path}")
        sys.exit(2)
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def _resolve_all(data: dict):
    """Iterate over role/mode/tier combos and resolve each."""
    from cli_executor import resolve_cli_profile

    modes = data.get("modes", {}) or {}
    results: list[dict] = []

    # Define check combinations
    checks = [
        ("full_cli", "alter", "supervisor"),
        ("full_cli", "full", "supervisor"),
        ("full_cli", "performance", "supervisor"),
        ("full_cli", "low", "supervisor"),
        ("full_cli", "full", "coder"),
        ("full_cli", "performance", "coder"),
        ("full_cli", "low", "interface_mapper"),
    ]

    for mode, tier, role in checks:
        # Map tier to budget_mode arg expected by resolve_cli_profile
        budget_mode_arg = tier  # "full", "performance", "low" are valid budget_mode values
        result = resolve_cli_profile(
            data,
            agent_role=role,
            budget_mode=budget_mode_arg,
            mode=mode,
        )
        entry = {
            "role": role,
            "mode": mode,
            "tier": tier,
            "resolved": result is not None,
        }
        if result:
            entry["executor_type"] = result.get("executor_type", "")
            entry["cli_agent"] = result.get("cli_agent", "")
            entry["default"] = result.get("default", "")
            entry["resolved_schema"] = result.get("resolved_schema", "")
            entry["resolution_source"] = result.get("resolved_schema", "")
        else:
            # Determine why: check the raw config
            tier_cfg = (
                (modes.get(mode, {}) or {}).get("tiers", {}) or {}
            ).get(tier, {}) or {}
            role_cfg_raw = tier_cfg.get(role)
            if role_cfg_raw is None:
                entry["resolution_source"] = "role_missing"
            elif isinstance(role_cfg_raw, str):
                entry["resolution_source"] = "skip" if "skip" in str(role_cfg_raw) else "string_value"
            elif isinstance(role_cfg_raw, dict):
                et = role_cfg_raw.get("executor_type", "")
                if et == "direct_api":
                    entry["resolution_source"] = "direct_api"
                elif et == "special":
                    entry["resolution_source"] = "special"
                else:
                    entry["resolution_source"] = f"unexpected_executor_type:{et}"
            else:
                entry["resolution_source"] = "unknown"
        results.append(entry)

    return results


def main() -> int:
    print("=" * 64)
    print("check_cli_schema_v4_routing — acceptance check")
    print("=" * 64)

    # 1. Load config
    try:
        data = _load_config()
    except Exception as exc:
        print(f"FATAL: YAML parse failed: {exc}")
        return 2

    schema_version = data.get("schema_version")
    default_mode = data.get("default_mode")
    has_modes = "modes" in data
    has_profiles = "profiles" in data

    print(f"schema_version: {schema_version}")
    print(f"default_mode: {default_mode}")
    print(f"has_modes: {has_modes}")
    print(f"has_profiles: {has_profiles}")

    errors: list[str] = []

    # 2. Schema v4 detection
    if not has_modes:
        if has_profiles:
            print("WARN: Config uses legacy 'profiles' layout (no 'modes' key).")
        else:
            print("WARN: Config has neither 'modes' nor 'profiles'.")
    else:
        print(f"Modes found: {sorted(data['modes'].keys())}")
        if set(data["modes"]) != {"full_cli"}:
            errors.append(
                "agent_model_profiles.yml must configure only the full_cli mode"
            )

    # 3. Resolve all check combos
    results = _resolve_all(data)
    print()
    print(f"{'Role':<20} {'Mode':<20} {'Tier':<15} {'Resolved':<10} {'Source'}")
    print("-" * 80)
    for r in results:
        src = r.get("resolution_source", "unknown")
        resolved = "CLI" if r["resolved"] else "—"
        cli_agent = r.get("cli_agent", "")
        detail = f"→ {cli_agent}" if cli_agent else ""
        print(f"{r['role']:<20} {r['mode']:<20} {r['tier']:<15} {resolved:<10} {src} {detail}")

    # 4. Critical assertions
    # full_cli/full/supervisor MUST resolve as CLI when modes present
    if has_modes:
        sup_result = next(
            (r for r in results
             if r["role"] == "supervisor" and r["mode"] == "full_cli" and r["tier"] == "full"),
            None,
        )
        if sup_result is None:
            errors.append("full_cli/full/supervisor: not found in results")
        elif not sup_result["resolved"]:
            errors.append(
                f"full_cli/full/supervisor: should resolve as CLI, "
                f"got source={sup_result.get('resolution_source')}"
            )
        else:
            print(f"\n✓ full_cli/full/supervisor → CLI ({sup_result.get('cli_agent')})")

    # Legacy profiles: if config has both modes AND profiles, that's fine
    # but only-modes + only-profiles is already handled above.

    # 5. Report
    print()
    if errors:
        print(f"FAIL: {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("PASS: All schema v4 routing checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
