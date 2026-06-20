# AgentLab Repo Guide

Last updated: 2026-06-20

## Purpose

AgentLab is a local-first, semi-managed agentic development workflow. It stores
project memory, task runs, routing policy, validation artifacts, and handoff
records locally. It is not intended to be exposed directly as a public SaaS API.

## Repository State

- Path: `/Users/saintpeter/Desktop/AgentLab`
- Branch: `main`
- Remote: `origin https://github.com/Kidrage/AgentLab.git`
- Existing local untracked docs at onboarding time:
  - `AGENTLAB_M_SERIES_MAINLINE_HANDOFF.md`
  - `CLAUDE.md`
  - `Root AgentLab Mainline Repair Handoff.md`

Treat unrelated untracked/dirty files as user work.

## Read First

- `AGENTS.md` for repository-specific agent rules.
- `README.md` for architecture, CLI commands, lifecycle, and tests.
- `docs/MAINLINE_BASELINE_STATUS.md` for current long-running staged status.
- `docs/EXTERNAL_AGENT_HANDOFF.md` for external agent safety boundaries.
- `docs/P2_ACCEPTANCE_RETRY_LOOP.md` for retry/acceptance constraints.
- `.codex/source_index.txt` for high-value tracked files.
- `.codex/repo_files.txt` for filtered tracked files.

## Main Entrypoints

- CLI wrapper: `./agentlab.sh`
- Runtime CLI target: `agent_runtime/run_task.py`
- Project ops CLI target: `agent_runtime/project_ops/cli.py`
- Web UI server: `web_ui/server.py`
- Config: `config/*.yml`
- Project memory and runs: `projects/<ProjectName>/`

`agentlab.sh` prefers `agent_runtime/.venv/bin/python`, then a Python with
`typer` and `yaml` available.

## Useful Commands

- Show all CLI commands: `./agentlab.sh --help`
- Health check: `./agentlab.sh doctor`
- Policy check: `./agentlab.sh policy-status --project AgentLab`
- Model wiring check: `./agentlab.sh models`
- Prepare a task: `./agentlab.sh prepare --project AgentLab --task-id <task_id> --write-plan`
- Run one agent dry-run: `./agentlab.sh run-agent Supervisor --project AgentLab --task-id <task_id>`
- Run pipeline dry-run: `./agentlab.sh run-pipeline --project AgentLab --task-id <task_id> --dry-run`
- Test core suites: `cd tests && python -m pytest test_artifact_gate.py test_task_closure.py -v`

## Current Mainline

`docs/MAINLINE_BASELINE_STATUS.md` says P0/P1/P2 and S7/S8 are active. S7 is
deterministic and planning-only. S8 produces phase-aware executor task packets
and ingests evidence, but external executors are still approval-gated.

External agent integrations are handoff-only. AgentLab creates artifacts for a
human to pass to an external agent; it does not automatically execute Codex,
Cline, ECC, or other external agents.

## Safety Boundaries

- Do not expose AgentLab directly to the public internet.
- Do not store secrets in project memory or handoff artifacts.
- Do not auto-dispatch external agents.
- Do not treat external results as accepted without evidence and review.
- Do not enable external skills, AnySearch, CodeGraph, or networked execution
  unless the task explicitly requires it and policy permits it.

## Avoid Reading Or Editing By Default

- `.git/`
- `agent_runtime/.venv/`
- `__pycache__/`
- `acceptance_runs/` unless checking a specific acceptance artifact.
- Generated logs, caches, archives, media, and binary assets.
- Unrelated files under `projects/<ProjectName>/runs/`.

## Before Modifying Code

1. Run `git status --short`.
2. Identify the intended task, project, phase, and acceptance criteria.
3. Read only the relevant source/config/test/docs from `.codex/source_index.txt`.
4. Preserve unrelated local changes and untracked user files.
5. Prefer minimal patches and existing runtime/config patterns.

## Before Commit Or Push

1. Review `git diff`.
2. Run targeted tests or CLI checks for the touched area.
3. Confirm branch and remote.
4. Commit only task-relevant files.
5. Push only when the branch/remote are unambiguous and verification is clean.
6. Check CI status after pushing when available.
