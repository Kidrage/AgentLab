# CLI Binary Aliases

> How AgentLab resolves CLI agent binary commands across environments.

## Concepts

### `cli_agent` — Logical Worker Identity

The `cli_agent` field in `config/agent_model_profiles.yml` is the **logical
worker identity**. It names the agent system (e.g. `claude_code`, `hermes`,
`agy`), not the OS binary.  Examples:

- `claude_code` → Claude Code (Anthropic)
- `hermes` → Hermes CLI agent
- `agy` → Agy CLI agent

### `invocation_contract` — Executable Command Template Reference

The normal runtime profile field is `invocation_contract`. It points to
`config/worker_invocation_contracts.yml`, which owns the shell command template
that AgentLab renders and executes. Contract templates support the placeholder
`{task_packet_path}`, which is replaced with the path to the JSON task packet;
role-runner contracts may also use `{workspace_path}`. Contracts requiring
frontdesk-only placeholders are not valid in normal role profiles.

Example:
```yaml
coder:
  executor_type: cli_agent
  cli_agent: claude_code
  invocation_contract: claude
  binary_candidates: [claude, ccs]
```

Direct `cli_command` in `agent_model_profiles.yml` is reserved for explicit
safety-gated profiles such as `trusted_headless_cli`.

### `binary_candidates` — Environment-Specific Binary Resolution

The `binary_candidates` field is an **ordered list of binary names** to try.
AgentLab resolves the first one found on `PATH` via `shutil.which()` and uses
it as `argv[0]`.

This allows the config to specify a canonical binary (e.g. `claude`) while
keeping legacy aliases (e.g. `ccs`) as fallbacks for machines that haven't
updated.

Example:
```yaml
cli_agent: claude_code
invocation_contract: claude
binary_candidates:
  - claude      # canonical — tried first
  - ccs         # legacy alias — fallback
```

## Known Mappings

| cli_agent    | Canonical Binary | Legacy Aliases |
|-------------|------------------|----------------|
| `claude_code` | `claude`         | `ccs`          |
| `hermes`      | `hermes`         | —              |
| `agy`         | `agy`            | —              |
| `codex`       | `codex`          | —              |
| `openclaw`    | `openclaw`       | —              |

## Resolution Logic

1. Resolve `invocation_contract` to a command template.
2. Render command template → `argv` list.
3. If `binary_candidates` is defined:
   a. Iterate candidates in order, check each via `shutil.which()`.
   b. First match → replace `argv[0]` with that binary.
   c. No matches → return `CliAgentNotAvailable` with all candidates listed.
4. If no `binary_candidates`:
   a. Check `argv[0]` via `shutil.which()` (existing behavior).
   b. Not found → return `CliAgentNotAvailable`.

## What `default` Means

The `default` field on each role is the **API fallback model** — the model
AgentLab uses when the CLI binary is not available and execution falls through
to the direct API path.

```yaml
coder:
  executor_type: cli_agent
  cli_agent: claude_code
  invocation_contract: claude
  binary_candidates: [claude, ccs]
  default: qwen3_coder_plus_dashscope   # ← API fallback, NOT injected into CLI command
```

AgentLab **never** injects `default` into the CLI command as `--model`.

## Trusted Headless CLI

A "trusted headless" profile uses `--allow-dangerously-skip-permissions` in the
command template. This is **not the default** — it must be explicitly opted into
via an environment gate or human-approval policy.

```yaml
# Example only — NOT active by default; direct cli_command is only allowed here.
cli_command: 'claude -p "..." --output-format json --allow-dangerously-skip-permissions'
```

## Validation

Run `scripts/check_cli_binary_aliases.py` to validate config shape:

```bash
python scripts/check_cli_binary_aliases.py
```

This checks:
- Every `claude_code` role has `binary_candidates` with `claude`.
- No `ccs`-only configs.
- Normal CLI profiles reference a valid `invocation_contract`.
- Resolved command templates parse correctly.
- Unknown `cli_agent` values have explicit `binary_candidates`.

The script validates **config shape**, not local binary availability.
External CLI binaries do NOT need to be installed in CI for this check to pass.

## CI / Testing

- Unit tests mock `shutil.which` and `subprocess.run` — no real CLI binaries
  are invoked.
- Config validation tests check schema shape only.
- Hermes, agy, codex, openclaw are validated by config inventory and local
  PATH checks outside CI.
