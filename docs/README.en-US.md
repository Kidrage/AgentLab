# AgentLab

[English](README.en-US.md) | [中文](README.zh-CN.md) |
[Current capability reference](CURRENT_VERSION_CAPABILITIES.en-US.md)

AgentLab is a local-first governed production runtime. It compiles requests into
mission contracts, selects a route and production pack, resolves registered
workers/models per role, persists recoverable state, and separates candidates
from formal promotion.

## Start Here

- [`../README.md`](../README.md): quick start and safety boundary.
- [`../AGENTS.md`](../AGENTS.md): compact repository map.
- [`../OPERATING_MODEL.md`](../OPERATING_MODEL.md): current runtime and state model.
- [`../DRIVER_PROTOCOL.md`](../DRIVER_PROTOCOL.md): external worker boundary.
- [`CURRENT_VERSION_CAPABILITIES.en-US.md`](CURRENT_VERSION_CAPABILITIES.en-US.md): capability domains and authorities.
- [`TEST_SUITE_GOVERNANCE.md`](TEST_SUITE_GOVERNANCE.md): test pruning and execution policy.

Current acceptance status is
`../acceptance_runs/agentlab_capability_acceptance/current.yml`. Do not infer it
from a prose snapshot.

## Operating Commands

```bash
./agentlab.sh repository-handoff --repo .
./agentlab.sh route-probe "<request>"
./agentlab.sh init-task --project <Project> --task-id <task_id> \
  --request-text "<request>"
./agentlab.sh prepare --project <Project> --task-id <task_id> --write-plan
./agentlab.sh run-agent <Role> --project <Project> --task-id <task_id> --execute
./agentlab.sh run-pipeline --project <Project> --task-id <task_id> --execute
```

Use `./agentlab.sh --help` for the current surface. Role assignments come from
`config/agent_model_profiles.yml`; command syntax comes from
`config/worker_invocation_contracts.yml`.

## Artifact Layout

- Run state/evidence: `projects/<Project>/runs/<task_id>/`
- Candidate deliverables: `projects/<Project>/runs/<task_id>/artifacts/`
- Promoted deliverables: `projects/<Project>/production/`
- Superseded formal deliverables: `projects/<Project>/archive/`

`PROJECT_HANDOFF.md` is the only writable repository handoff. Historical reports,
prompt packs, acceptance snapshots, and old handoff aliases are read-only.

## Development

```bash
./agentlab.sh model-doctor
./agentlab.sh protocol-doctor
./agentlab.sh repo-hygiene-check --root .
python3 -m pytest -q <focused tests>
```

Shared runtime changes require a full test run before delivery. Default tests are
offline and must not call live providers.

The previous snapshot-style guide is archived under
`archive/readme_legacy_20260718/`.
