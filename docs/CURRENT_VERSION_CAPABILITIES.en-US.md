# AgentLab Current Capability Reference

Language: [English](CURRENT_VERSION_CAPABILITIES.en-US.md) | [中文](CURRENT_VERSION_CAPABILITIES.zh-CN.md)

This is an authority-oriented reference. It does not copy volatile model tables,
provider quotas, command inventories, test counts, or acceptance status.

## Runtime Position

AgentLab is a local-first governed production runtime. It turns a request into a
mission contract, chooses the smallest safe route and production pack, resolves
each role's worker/model, records durable state and evidence, and keeps candidate
generation separate from formal promotion.

Current acceptance status is machine-readable at
`acceptance_runs/agentlab_capability_acceptance/current.yml`. A feature listed
here is a supported contract area, not a claim that every optional live provider
is currently authenticated or available.

## Authority Layers

| Concern | Source |
|---|---|
| Roles and active prompts | `config/agent_registry.yml` |
| Routes | `config/routing_rules.yml` |
| Domain packs and gates | `config/production_packs.yml` |
| Workflow driver | `config/execution_modes.yml` |
| Role worker/model matrix | `config/agent_model_profiles.yml` |
| Worker command contracts | `config/worker_invocation_contracts.yml` |
| Model/provider facts | `config/model_catalog.yml`, `config/model_providers.yml` |
| Capacity routes | `config/model_capacity.yml` |
| Task lifecycle/state | run-local files plus `lifecycle_graph.py` and `task_index.py` |
| Artifact promotion | `project_artifact_steward.py` and project artifact index |

Use `./agentlab.sh --help` and nested `--help` output for the current command
surface. Use `./agentlab.sh models show --role <Role>` for a current resolved
role assignment. Static command/model lists in prose are intentionally avoided.

## Mission, Routing, And Roles

- Mission compilation normalizes intent, domain, size, risk, boundaries, and
  required evidence.
- Routing chooses only the roles needed for the request.
- Production packs define domain lifecycle nodes, required outputs, memory, and
  quality gates.
- Workflow planning resolves each included role through the active mode/tier
  model matrix and invocation contract.
- AgentLab remains the workflow host. A CLI shell is a replaceable worker and may
  use native subagents only inside one assigned role.
- Cross-role shell coalescing and single-shell full-driver execution are retired.

The role registry currently covers planning, repository/interface discovery,
research, observation, coding, artifact/media production, narrative planning and
writing, review/scribing, testing, verification, and archive/promotion duties.
The registry is canonical; documentation does not maintain a parallel role count.

## Production Capabilities

### Code

Narrow fixes through large/risky code work can be routed with repository,
interface, research, implementation, test, verification, and archive roles added
only when required. Source edits remain scope-bound and evidence-backed.

### Narrative

- Light chapter routes produce candidate prose, continuity state, transition
  proposals, and delivery receipts.
- Bounded batch routes preserve chapter order and batch continuity evidence.
- Heavy audit inspects existing drafts and emits review, continuity failure, and
  rewrite proposals without silently modifying production text.
- Rewrite planning is distinct from writing and promotion.

Structured fact snapshots, artifact indexes, chapter packets, ledgers, and state
proposals remain narrative authority. RAG is not required and cannot replace
those facts.

### Articles And Typed Artifacts

Short non-code prose uses an article-light path. Generic artifact work supports
declared text/document/data/media outputs through candidate-first contracts and
format-specific structural checks.

### Media And Observation

Image/video tasks use media contracts, backend preflight, generation ledgers,
asset hashes, independent observation/review, and verification. Producers cannot
accept their own output. Read-only observation can inspect assigned long text,
documents, images, video, or audio without production or promotion authority.

## State, Background, And Recovery

A task is recoverable from `projects/<Project>/runs/<task_id>/`:

- `mission_contract.yml`, `workflow_plan.yml`
- `state.yml`, `lifecycle.yml`, `progress.yml`
- `task_events.jsonl`, decision cards
- role reports, output contracts, and receipts

Web UI, TUI, daemon, watchdog, and later sessions project from these files rather
than chat history. Watchdog detects stale or actionable tasks; daemon writes local
heartbeats/status and can dispatch configured notifications. The specialized
longform background controller is not a generic bypass around task governance.

## Artifacts, Memory, And Skills

Candidate deliverables stay under `runs/<task_id>/artifacts/`. Formal current
deliverables stay under `production/` only after declared promotion gates;
superseded formal deliverables move to `archive/`.

Project memory lives under `agent_docs/` and domain-specific structured records.
`PROJECT_HANDOFF.md` is the single writable repository handoff. Active skills are
tracked packages; usage ledgers are run-local. Staged skills, roles, packs, or
bridges require validation and approval before activation.

## Models, Capacity, And Cost

Provider/model selection is separate from route selection. Subscription/OAuth,
API, and special workers retain explicit capability, auth, usage, and billing
facts. Usage probes record observed remaining capacity and reset information when
the shell exposes them; unknown values remain unknown.

Only declared same-role capacity routes may fallback. An undeclared failure stops
and reports. API-key billing is not inferred from an OAuth call. Cost ledgers
separate reported usage, estimated pricing, media unit pricing, and unknown cost.

## Interfaces

- `agentlab.sh`: canonical local CLI wrapper.
- TUI/Web UI: task/status/decision projections over the same runtime state.
- MCP/role sessions: bounded integration surfaces, not alternate authorities.
- Repository handoff and workspace-entry packets: minimal safe discovery.
- TrueNAS/GitHub sync: explicit delivery/backup operations, never hidden runtime
  state replication.

Web UI model displays come from resolved workflow plans and canonical config. It
does not keep a browser-local model router.

## Safety And Limits

- No implicit provider calls, private context export, production write, promotion,
  fallback, or external publication.
- Credentials and CLI homes are local-only and excluded from repository ingestion.
- Candidate completion is not production acceptance.
- Dry-run/static evidence is not live-provider evidence.
- Generated acceptance artifacts are evidence snapshots, not runtime policy.
- Self-evolution may improve AgentLab components but cannot autonomously expand
  product scope or grant itself credentials/production authority.

## Verification

Common deterministic checks:

```bash
./agentlab.sh model-doctor
./agentlab.sh protocol-doctor
./agentlab.sh repo-hygiene-check --root .
python3 -m pytest -q <focused tests>
```

Shared runtime changes require one full suite before delivery. Current test-suite
policy is documented in `docs/TEST_SUITE_GOVERNANCE.md`.

The pre-pruning snapshot is archived under
`docs/archive/current_capabilities_legacy_20260718/`.
