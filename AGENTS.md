# AgentLab Repository Map

This file is a compact entry map. It is not a second architecture manual and
must not duplicate model assignments, route lists, or generated acceptance
results.

## Read Order

1. `_shared/AGENT_PROTOCOL.md` for collaboration, safety, Git, and evidence.
2. `OPERATING_MODEL.md` for the current task lifecycle and ownership map.
3. `DRIVER_PROTOCOL.md` for external worker and CLI-shell boundaries.
4. The specific project memory and `config/*.yml` authority needed by the task.

Before deep repository reads, use the canonical handoff:

```bash
./agentlab.sh repository-handoff --repo .
./agentlab.sh repository-handoff --repo . --write  # only when absent or stale
```

`PROJECT_HANDOFF.md` is the only writable repository handoff. Root `HandOff.md`,
`.agentlab/HandOff.md`, and `agent_docs/HandOff.md` are read-only legacy inputs.

## Configuration Authorities

- `config/agent_registry.yml`: role contracts and active templates.
- `config/frontdesk_policy.yml`: Frontdesk F0-F4 intent classification,
  required-capability labels, and approval signals. It does not select
  execution agents.
- `config/routing_rules.yml`: route membership and order.
- `config/production_packs.yml`: domain lifecycle, outputs, memory, and gates.
- `config/execution_modes.yml`: active AgentLab workflow drivers.
- `config/agent_model_profiles.yml`: per-role worker and model selection.
- `config/worker_invocation_contracts.yml`: exact shell command contracts.
- `config/model_catalog.yml` and `config/model_providers.yml`: model/provider facts.
- `config/model_capacity.yml`: declared capacity fallback routes.
- `config/repository_handoff_policy.yml`: repository discovery and handoff rules.
- `config/knowledge_system.yml`: derived knowledge retrieval rollout, storage, and evidence policy.

The governed knowledge system is part of normal task preparation. Its validated
default is non-blocking `assist`; use `./agentlab.sh knowledge doctor` to verify
the local build and `./agentlab.sh knowledge status` to inspect namespaces.
`config/knowledge_system.yml#indexing.project_allowlist` is the sole authority
for projects that may own project/domain RAG records. Projects outside it may
still run, but can read only system and project-neutral domain evidence; they
cannot read another project's records or create/sync durable derived memory.
Formal project and narrative promotions, plus accepted Project Brain phase and
revision transitions, update their project and domain shards automatically.
After accepted AgentLab code, configuration, governance, or docs changes, run
`./agentlab.sh knowledge build --project AgentLab` before handoff so the system
scaffold reflects the new repository state. Never edit SQLite shards directly or
treat them as source authority.

Never infer a role, model, provider, fallback, or command from a CLI name or an
old report. Configuration wins.

Do not generalize a correction for one default role into a global worker/model
rule. The canonical role/tier matrix lives only in
`config/agent_model_profiles.yml`; provider/model facts live in
`config/model_catalog.yml` and fallback policy lives in
`config/model_capacity.yml`. Documentation must point to those authorities
instead of copying the volatile matrix.

CLI-owned model surfaces must also agree with the selected worker: a Codex
worker uses a Codex CLI provider/model key, while DeepSeek models require a
contracted DeepSeek-capable shell such as Claude Code. Never label a foreign
provider model as if the selected worker could execute it natively.

## Repository Layout

- `agent_runtime/`: runtime, routing, lifecycle, state, and CLI implementation.
- `agent_templates/`: only active role templates registered in the agent registry.
- `config/`: machine-readable policy authorities.
- `docs/`: current specifications; `docs/archive/` contains non-authoritative history.
- `projects/<Project>/agent_docs/`: durable project memory.
- `projects/<Project>/runs/<task_id>/`: one task's state, evidence, and reports.
- `projects/<Project>/runs/<task_id>/artifacts/`: candidate deliverables only.
- `projects/<Project>/production/`: formally promoted current deliverables only.
- `projects/<Project>/archive/`: superseded project deliverables.
- `outputs/<Project>/`: Git-ignored, rebuildable human-facing result projection.
- `skills/active/`: active tracked skills; runtime usage belongs in the run.
- `acceptance_runs/`: generated acceptance evidence, not runtime policy.
- `.agentlab_runtime/`: local daemon/runtime state, never source authority.

Do not write task outputs, logs, prompts, snapshots, or ad hoc handoffs to the
repository root or Desktop. Do not treat `runs/`, `candidates/`, `*_rebuild`, or
legacy folders as production facts unless the project artifact index explicitly
selects them.

Before reporting a project result to the user, run
`./agentlab.sh project-results-export --project <Project> [--task <task_id>]`.
Only this managed command may populate `outputs/<Project>/`; never hand-copy
files into it. The projection must preserve candidate/production labels and must
not be treated as promotion, canon, or Task authority.

## Execution Boundary

- AgentLab owns mission compilation, route selection, lifecycle state, evidence,
  validation gates, and promotion decisions.
- A shell such as Hermes, Claude Code, Codex, Agy, Grok, or Qwen is a worker, not
  an AgentLab role and not the workflow host.
- One shell may use native subagents to finish one assigned AgentLab role. Their
  work must return through that role's declared receipt.
- Cross-role coalescing is disabled. A shell may not silently complete an entire
  route or invent missing AgentLab receipts.
- Do not silently switch worker, provider, or model. Only a declared capacity
  route may fallback, and it must record the trigger and receipt.
- Candidate generation never implies production promotion.

## Editing Rules

- Preserve unrelated user changes and keep edits to the smallest relevant scope.
- Use `apply_patch` for manual edits and atomic I/O helpers for runtime writes.
- Prefer targeted `rg`, `git diff`, and focused reads over full-tree scans.
- Do not read or commit credentials, private CLI homes, caches, virtualenvs, or
  generated task ledgers.
- Active templates must be registered; retired prompts belong under
  `docs/archive/` and have no runtime loader.
- Keep policy in its owning config file. Documentation should link to authority,
  not copy volatile tables.

## Verification

Use focused tests while editing. For shared routing, lifecycle, state, or config
changes, run the full suite once before delivery. Test-file count is not a quality
metric; merge tests only when behavior or expensive setup is genuinely duplicated.

```bash
./agentlab.sh model-doctor
./agentlab.sh repo-hygiene-check --root .
python3 -m pytest -q <focused tests>
```

Before delivery, refresh `PROJECT_HANDOFF.md`, inspect the complete diff, scan for
secrets, commit the intended files, push the intended branch, and check CI.

The pre-pruning guide is retained at
`docs/archive/root_agent_guides_legacy_20260718/AGENTS.md` for history only.
