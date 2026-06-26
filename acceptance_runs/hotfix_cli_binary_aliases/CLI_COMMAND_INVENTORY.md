# CLI Command Inventory Report

**Date**: 2026-06-26
**Hotfix**: `hotfix-cli-binary-alias`
**Schema version**: 4.0
**Active mode**: `full_cli`

---

## Inventory Summary

| cli_agent    | Canonical Binary | Legacy Aliases | Roles                                                                                       | Status    |
|-------------|------------------|----------------|---------------------------------------------------------------------------------------------|-----------|
| `hermes`    | `hermes`         | —              | supervisor                                                                                  | unchanged |
| `agy`       | `agy`            | —              | reposcout, interface_mapper, prompt_engineer, tester_auditor, verifier, archivist           | unchanged |
| `claude_code` | `claude`       | `ccs`          | researcher, coder (full tier), coder (performance tier), coder (low tier)                   | **fixed** |

---

## Detailed Role Inventory

### hermes

| Mode      | Tier       | Role       | Command Binary | Canonical | binary_candidates | Status    |
|-----------|-----------|------------|----------------|-----------|-------------------|-----------|
| full_cli  | full      | supervisor | hermes         | ✅        | None              | unchanged |
| full_cli  | performance | supervisor | hermes       | ✅        | None              | unchanged |
| full_cli  | low       | supervisor | hermes         | ✅        | None              | unchanged |

**Status**: Unchanged. Hermes binary `hermes` is the canonical name. No aliases needed.

### agy

| Mode      | Tier        | Role              | Command Binary | Canonical | binary_candidates | Status    |
|-----------|------------|-------------------|----------------|-----------|-------------------|-----------|
| full_cli  | full       | reposcout         | agy            | ✅        | None              | unchanged |
| full_cli  | full       | interface_mapper  | agy            | ✅        | None              | unchanged |
| full_cli  | full       | prompt_engineer   | agy            | ✅        | None              | unchanged |
| full_cli  | full       | tester_auditor    | agy            | ✅        | None              | unchanged |
| full_cli  | full       | verifier          | agy            | ✅        | None              | unchanged |
| full_cli  | full       | archivist         | agy            | ✅        | None              | unchanged |
| full_cli  | performance | reposcout        | agy            | ✅        | None              | unchanged |
| full_cli  | performance | interface_mapper | agy            | ✅        | None              | unchanged |
| full_cli  | performance | prompt_engineer  | agy            | ✅        | None              | unchanged |
| full_cli  | performance | tester_auditor   | agy            | ✅        | None              | unchanged |
| full_cli  | performance | verifier         | agy            | ✅        | None              | unchanged |
| full_cli  | performance | archivist        | agy            | ✅        | None              | unchanged |
| full_cli  | low        | reposcout        | agy            | ✅        | None              | unchanged |
| full_cli  | low        | prompt_engineer  | agy            | ✅        | None              | unchanged |
| full_cli  | low        | tester_auditor   | agy            | ✅        | None              | unchanged |
| full_cli  | low        | archivist        | agy            | ✅        | None              | unchanged |

**Status**: Unchanged. Agy binary `agy` is the canonical name. Validated by config shape;
actual binary availability checked at runtime via `shutil.which`.

### claude_code

| Mode      | Tier        | Role       | Command Binary | Canonical | binary_candidates | Status  |
|-----------|------------|------------|----------------|-----------|-------------------|---------|
| full_cli  | full       | researcher | claude         | ✅        | `[claude, ccs]`   | **fixed** |
| full_cli  | full       | coder      | claude         | ✅        | `[claude, ccs]`   | **fixed** |
| full_cli  | performance | researcher | claude       | ✅        | `[claude, ccs]`   | **fixed** |
| full_cli  | performance | coder      | claude       | ✅        | `[claude, ccs]`   | **fixed** |
| full_cli  | low        | coder      | claude         | ✅        | `[claude, ccs]`   | **fixed** |

**Status**: **Fixed**. All claude_code roles now use `claude` as the primary binary
with `ccs` as a legacy fallback via `binary_candidates: [claude, ccs]`.

---

## Resolution Logic

1. If `binary_candidates` is defined in the role profile → iterate candidates,
   use `shutil.which()` to find the first available binary, replace `argv[0]`.
2. If no `binary_candidates` → fall through to existing behavior: check `argv[0]`
   from the rendered `cli_command` template.
3. If none of the candidates resolve → return `CliAgentNotAvailable` with details
   listing all candidates that were checked.

---

## Unknown Binaries

None. All configured `cli_agent` values (`hermes`, `agy`, `claude_code`) have
known canonical mappings. No `codex` or `openclaw` entries exist in the current
config.

---

## Local Installation Requirements

| Binary   | Required For     | Notes                                  |
|----------|-----------------|----------------------------------------|
| `hermes` | Supervisor       | Must be on PATH for CLI supervisor     |
| `agy`    | 6 agent roles    | Must be on PATH for those roles        |
| `claude` | researcher, coder | Primary; `ccs` is legacy fallback     |

CI does NOT require these binaries. The config validation script
(`scripts/check_cli_binary_aliases.py`) validates config shape only.
