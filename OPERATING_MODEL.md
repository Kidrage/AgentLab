# AgentLab Operating Model

This document describes the current runtime shape. It deliberately excludes
model tables, generated acceptance counts, provider session health, and project
progress snapshots. Those facts have machine-readable owners listed below.

## 1. Authority Map

| Concern | Authority |
|---|---|
| Role identity and prompt | `config/agent_registry.yml` |
| Route membership and order | `config/routing_rules.yml` |
| Domain lifecycle and deliverables | `config/production_packs.yml` |
| Workflow driver | `config/execution_modes.yml` |
| Role worker/model selection | `config/agent_model_profiles.yml` |
| Shell command syntax | `config/worker_invocation_contracts.yml` |
| Provider and model facts | `config/model_providers.yml`, `config/model_catalog.yml` |
| Capacity fallback | `config/model_capacity.yml` |
| Lifecycle graph | `agent_runtime/lifecycle_graph.py` plus the selected production pack |
| Task state and event projection | run-local state files and `agent_runtime/task_index.py` |
| Promotion | `agent_runtime/project_artifact_steward.py` and project artifact index |
| Structured project facts | Project Brain events and the projected fact snapshot |
| Current project artifacts | `production/` plus `project_artifact_index.yml` |
| Task evidence | run-local evidence bundles, traces, reports, and receipts |
| Operator-maintained memory | project `agent_docs/` governed by `config/memory_policy.yml` |
| Derived knowledge retrieval | `agent_runtime/knowledge_system/` and `config/knowledge_system.yml` |
| Current acceptance | `acceptance_runs/agentlab_capability_acceptance/current.yml` |

No lower layer may redefine an upper-layer concern. In particular, route config
does not choose models, a CLI name does not imply a role, and documentation does
not override configuration.

## 2. Task Flow

The normal flow is:

```text
user request
  -> mission contract
  -> route decision + production pack
  -> workflow plan with resolved role profiles
  -> Supervisor plan
  -> only the configured route roles
  -> deterministic local checks and declared review gates
  -> run-local receipts and task events
  -> completed candidate or explicit blocked/paused state
  -> separate approval and promotion when required
```

`init-task` creates a run boundary. `prepare --write-plan` resolves the route,
pack, lifecycle, budgets, model profiles, inputs, outputs, and artifact intent
without needing a production model call. `run-agent` executes one assigned role;
`run-pipeline` advances the configured route. Neither command grants promotion.

The strategy is `smallest_safe_route`. Optional roles are omitted when their
function is unnecessary. A full code pipeline or heavy narrative audit is not a
default quality ritual.

## 3. Route Families

The exact list is in `routing_rules.yml`. Current route families are:

- Code: narrow, medium, interface-sensitive, research-sensitive, and large/risky.
- Narrative generation: one-chapter light and bounded multi-chapter candidate runs.
- Narrative governance: heavy audit of existing drafts and rewrite planning.
- Article: light non-code prose draft plus deterministic structure check.
- Artifact/media: generic artifact production and continuity-aware media production.
- Read-only: observation, workspace analysis, and evaluation routes.

`fiction_chapter_pipeline` is read-only legacy compatibility and is not selectable
for new tasks. Creative writing must resolve to a current narrative route rather
than a code route.

Production packs decide domain-specific lifecycle nodes, required inputs,
required outputs, memory records, and quality gates. They do not select a worker
or model. Unknown complex domains may propose a candidate pack; a proposal does
not become active policy without validation and approval.

## 4. Role And Shell Boundary

AgentLab roles are stable contracts. Worker shells and models are replaceable
execution resources.

- AgentLab owns route, state, context boundary, output contract, evidence, and
  promotion.
- A role profile selects its worker and model from the canonical matrix.
- An invocation contract translates that selection into one audited CLI command.
- A worker may use native shell features or subagents within one assigned role.
- All native subagent results return through the assigned role receipt.
- Cross-role coalescing is disabled; one shell cannot impersonate a whole route.
- Undeclared fallback stops and reports rather than silently changing resources.

The active driver is normally `agentlab_orchestrated_cli`. This means AgentLab is
the workflow host and local CLIs are workers. It does not mean Codex, Hermes,
Claude, or another shell owns the task. Retired full-driver prompts remain under
`docs/archive/` only.

## 5. State Machine

Each task is recoverable from files under
`projects/<Project>/runs/<task_id>/`. Important records are:

- `mission_contract.yml`: normalized intent, risk, route basis, and boundaries.
- `workflow_plan.yml`: resolved route, pack, lifecycle, profiles, budgets, gates,
  and artifact intent.
- `state.yml`: current task status, current role, completed roles, and reports.
- `lifecycle.yml`: node-level statuses and dependencies.
- `progress.yml`: operator-facing progress projection and heartbeat timestamps.
- `task_events.jsonl`: append-only event stream.
- `decision_cards/*.yml`: explicit approval or recovery decisions.
- role reports and receipts: evidence that a node actually completed.

The canonical task index normalizes legacy aliases such as `complete` to
`completed`, `in_progress` to `running`, and `failed_recoverable` to
`recoverable`. New operator surfaces should use:

```text
new -> planned -> running -> completed
                    |  |-> paused
                    |  |-> blocked
                    |  |-> recoverable
                    |  `-> failed
                    `----> archived (after retention/archive handling)
```

Lifecycle nodes separately use `pending`, `running`, `completed`, `skipped`,
`paused`, or `failed`. A task cannot be called complete merely because a worker
process exited; required node receipts and gates must also close.

## 6. Background And Feedback

Normal task execution is receipt-driven. The daemon/watchdog layer observes task
files; it is not a second orchestrator and does not invent work.

- `watchdog-scan` detects stale running tasks and can create a decision card.
- `daemon --once` scans configured projects, writes heartbeat/status under
  `.agentlab_runtime/daemon/`, and optionally dispatches actionable webhooks.
- Web UI and later sessions rebuild status from run-local files and events.
- Background services must leave a durable PID/service receipt and task event.
- Provider retries must obey the declared capacity/retry policy and remain
  visible as paused, blocked, or recoverable states.

The Crown background-job controller is a specialized longform batch controller,
not the generic task state machine. Its job files are durable, but it may launch
provider-backed work only with explicit execution authorization.

## 7. Artifact And Memory Boundaries

```text
projects/<Project>/runs/<task_id>/
  process state, reports, prompts, evidence
projects/<Project>/runs/<task_id>/artifacts/
  candidate deliverables from this task
projects/<Project>/production/
  explicitly promoted current deliverables
projects/<Project>/archive/
  superseded formal deliverables
```

Candidate generation never writes production. Promotion validates lineage,
declared targets, review/approval evidence, and archive receipts before updating
`project_artifact_index.yml`.

For longform narrative work, the minimum memory closure is the fact snapshot,
artifact index, chapter packet, previous continuity ledger, current draft,
continuity ledger, and state-transition proposal. New facts hidden only in prose
are not durable facts. RAG or external MCP retrieval may provide evidence later,
but cannot replace the structured fact authority.

The local knowledge catalog and its per-space SQLite shards live under
`.agentlab_runtime/knowledge/`. They are rebuildable indexes, not project memory,
are never promoted or replicated as truth, and may only propose updates for the
existing acceptance, promotion, and Project Brain mechanisms to commit.

## 8. Cost And Capacity

Route size, role count, and model tier are separate decisions. The default is one
necessary production call plus deterministic local checks whenever the pack
allows it. Heavy review is scheduled by risk, cadence, dispute, or promotion gate.

Subscription/OAuth workers should query their native usage/status surface when
available and record the observation. Low remaining capacity may trigger only a
declared same-role capacity route or a pause until reset. API-key auth is
fallback-only when configuration says so; it does not use API keys as the default
unblock path. Exact costs come from receipts and the cost ledger, never estimates
presented as actual billing.

## 9. Quality And Promotion

- Code routes require tests appropriate to blast radius and independent evidence
  for shared behavior.
- Narrative light routes produce candidates and continuity/state proposals.
- Heavy narrative routes audit existing text; blocking findings create rewrite
  proposals rather than silently editing the draft.
- Media producers cannot accept their own output; visual review is independent.
- No route automatically promotes because all agents reported success.

Current acceptance status is read from
`acceptance_runs/agentlab_capability_acceptance/current.yml`. Generated reports
may summarize it, but this operating model must not embed volatile counts or live
provider blockers.

## 10. Self-Evolution Boundary

AgentLab may propose a new role, skill, pack, bridge, or validation gate when a
repeatable capability gap is evidenced. The proposal must declare ownership,
inputs, outputs, editable scope, worker compatibility, tests, and rollback. It
becomes active only after deterministic validation and explicit approval.

Self-evolution may improve AgentLab's own governance and component composition.
It does not authorize autonomous product scope expansion, credential creation,
external publication, production promotion, or silent model registration.

The cumulative pre-pruning operating record is archived at
`docs/archive/root_agent_guides_legacy_20260718/OPERATING_MODEL.md`.
