# Claude Code Repository Guide

This file contains only Claude Code-specific entry rules. Do not treat it as a
second AgentLab architecture manual.

## Read Order

1. `AGENTS.md` for the compact repository map.
2. `_shared/AGENT_PROTOCOL.md` for collaboration, safety, Git, and evidence rules.
3. `OPERATING_MODEL.md` for current AgentLab roles and production packs.
4. `DRIVER_PROTOCOL.md` for the external worker boundary.
5. The exact `config/*.yml` owner named by those maps.

Current role/model/worker facts come from configuration, not this file:

- `config/agent_registry.yml`: role contract and active template.
- `config/routing_rules.yml`: route membership and order.
- `config/production_packs.yml`: domain lifecycle and output contract.
- `config/agent_model_profiles.yml`: role backend/model matrix.
- `config/worker_invocation_contracts.yml`: exact CLI command contract.
- `config/model_capacity.yml`: approved same-role fallback routes.

## Claude Boundary

Claude Code is a worker shell, not an AgentLab role.

- Outside an AgentLab role session, act as an external repository worker or
  dispatch/acceptance layer according to the user's request.
- Inside `role-session`, execute only the assigned role, paths, inputs, outputs,
  tools, and promotion boundary from the task packet.
- Never infer authority from the `claude` binary or its configured model.
- Never emulate the entire role chain. `codex_full_driver` and equivalent
  single-shell full-route behavior are retired.
- Claude native agents/background/plan features may help complete one assigned
  role, but their results must return through that role's AgentLab receipt.
- Do not silently change worker, provider, or model. Use only a capacity route
  declared by AgentLab and record its evidence.

## Repository Entry

Before deep reads:

```bash
./agentlab.sh repository-handoff --repo <repo> --write
git status --short --branch
git ls-files
```

`PROJECT_HANDOFF.md` is the only writable repository handoff. Legacy
`.agentlab/HandOff.md`, `agent_docs/HandOff.md`, and root `HandOff.md` names are
read-only discovery inputs.

Use targeted `rg`, `git diff`, and focused file reads. Do not recursively read
dependencies, CLI homes, caches, logs, credentials, binary assets, or all
project runs.

## Common Commands

```bash
# Plan without a model call
./agentlab.sh prepare --project <Project> --task-id <task_id> --write-plan

# Inspect the deterministic route without creating a task
./agentlab.sh route-probe "<request>"

# Execute one configured role or a full route
./agentlab.sh run-agent <Role> --project <Project> --task-id <task_id> --execute
./agentlab.sh run-pipeline --project <Project> --task-id <task_id> --execute

# Explicit scoped shell handoff
./agentlab.sh role-session --role <Role> --worker claude_code \
  --project <Project> --task-id <task_id>

# Local governance
./agentlab.sh model-doctor
./agentlab.sh repo-hygiene-check --root .
python3 -m pytest -q <focused tests>
```

The default workflow driver is `agentlab_orchestrated_cli`. Role backends are
resolved from `agent_model_profiles.yml`; the driver label does not make Claude,
Codex, Hermes, or another shell the task host.

## Edit And Artifact Rules

- Preserve unrelated user changes and edit the smallest relevant file set.
- Use atomic I/O helpers for runtime persistent writes.
- Source edits require a Coder-scoped assignment or explicit external-worker
  authorization from the user.
- Candidate outputs belong in `projects/<Project>/runs/<task_id>/artifacts/`.
- Formal deliverables belong only in `projects/<Project>/production/` after
  declared review, approval, and promotion.
- Runtime state, CLI homes, credentials, caches, and generated ledgers stay out
  of Git.
- Active prompts are only those registered by `agent_registry.yml`. Retired
  full-driver prompts are historical material under `docs/archive/`.

## Verification And Delivery

- Run focused tests while editing and one full suite for broad shared-runtime
  changes.
- A test file merge is useful only when it removes duplicated setup or behavior;
  file count alone is not a performance metric.
- Check actual files, diff, task state, receipts, and promotion status rather
  than trusting a worker summary.
- Before final reporting, refresh `PROJECT_HANDOFF.md`, scan for secrets, inspect
  Git status/diff, commit the intended scope, push the feature branch when
  appropriate, and verify CI.

The superseded long Claude guide is retained at
`docs/archive/root_agent_guides_legacy_20260718/CLAUDE_PRE_PRUNING.md` and is not
runtime authority.
