# S11 Ops Console

## Purpose

S11 adds a local-only operations console layer for AgentLab. The current MVP is intentionally conservative: it produces a deterministic read-only snapshot for projects, skills, capabilities, evidence, decisions, and budget/resource visibility without starting a public server or exposing secrets.

## CLI

```bash
./agentlab.sh ops-console-status --project AgentLab --out acceptance_runs/s11_dashboard
./agentlab.sh ops-console-serve --host 127.0.0.1 --dry-run
```

`ops-console-status` writes `ops_console_snapshot.yml`.

`ops-console-serve` currently prints a dry-run launch plan. Public bind addresses such as `0.0.0.0` are rejected by policy.

## Policy

Configuration lives in `config/ops_console_policy.yml`.

Defaults:

- bind host: `127.0.0.1`
- mode: `read_only`
- public bind: disabled
- secrets: redacted
- private paths: redacted
- UI failure: non-blocking for CLI core

## Snapshot Sections

- Project Overview
- Project Brain
- Roadmap / Milestones
- Phase Status
- Task Packets
- Skill Registry
- Capability Registry
- Recovery / Failures
- Evidence Artifacts
- Budget / Resource Ledger

## Approval Model

S11 exposes approval intent in the snapshot, but does not bypass existing CLI decision commands. Approve/reject/resume actions remain explicit operations.

## Safety Notes

- No network calls.
- No external agents.
- No model calls.
- No server bind during tests or status generation.
- No secrets or private user paths in generated snapshots.
