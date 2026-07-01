# M3 Upgrade Plan Review

Last updated: 2026-07-01
Depends on: `docs/M2_STABLE_BASELINE_REPAIR_PLAN.md`

## Scope

M3 should begin only after the M2 stable baseline exits with hard governance
gates. M3 is not the commercial/revenue layer. In the current project-mainline
wording, M3 is the Operator OS / Transparent Control Plane:

- WebUI/TUI that can show, control, pause, resume, approve, reject, and retry.
- Config Center that explains active defaults, overrides, and risks.
- Cost System v2 with budgets, attribution, alerts, and efficiency reports.
- Observability timeline, logs, evidence, executor results, recovery state, and
  failure reasons.
- AgentLab Assistant Modes that explain system state from ledgers and project
  brain data.

Business Contract, Asset Registry, Production Pipeline, Revenue Ledger,
Market/Channel Brain, CRM, and Compliance belong to M4 except for narrow
read-only placeholders needed to avoid future migration pain.

## Current Repository Baseline

Useful M3 skeletons already exist:

- `agentlab_tui/` provides a headless TUI skeleton and strict command handlers.
- `web_ui/` provides a local-only, read-only WebUI dashboard skeleton.
- `agent_runtime/ops_console/` can generate deterministic read-only operations
  snapshots.
- `agent_runtime/costing/` has budget, ledger, pricing, and usage modules.
- M2 phase acceptance now writes Project Brain `acceptance_history.yml` and
  refreshes `next_actions.yml`, giving M3 a durable source for phase progress
  and next safe action.
- Existing M2/M3 docs describe assistant modes, control panels, observability,
  and local-only UI safety boundaries.

The skeleton is useful, but it is not yet a complete Operator OS:

- WebUI is read-only and intentionally not a production frontend.
- TUI covers control intent, but not the full daily operator workflow.
- Cost visibility exists at the module level, but budget attribution and
  project/phase/executor efficiency views are not complete.
- Observability snapshots exist, but the timeline is not yet the single
  operator narrative for "what happened, who did it, what evidence exists, what
  it cost, and what should happen next."
- Assistant modes must be grounded in ledgers, Project Brain, phase acceptance,
  and evidence records, not free-form advice.

## M3 Workstreams

### M3-0: Operator OS Alignment

Goal:

- Make M3 executable by lower-intelligence coding agents without letting them
  confuse Operator OS with Project-to-Revenue work.

Implemented alignment contracts:

- `docs/M3_0_OPERATOR_OS_ALIGNMENT.md` is the entry document for M3 coding
  agents.
- `agent_runtime.operator_os.stage_scope` freezes current repair labels:
  M2 = Long-Project Governance Stable Baseline, M3 = Operator OS, M4 =
  Project-to-Revenue OS.
- `agent_runtime.operator_os.state_model.build_operator_state()` defines the
  single read model for UI, TUI, CLI status, ops console, and assistant modes.
- `agent_runtime.operator_os.action_contract` defines supported operator
  actions and forbidden effects.

Acceptance:

- Lower-intelligence agents may work on read-only rendering and simple wiring
  against Operator State.
- Lower-intelligence agents must not change acceptance, evidence, Project Brain,
  or mutation rules.
- M3 UI/TUI/assistant progress must be derived from
  `acceptance_history.yml` and `next_actions.yml`, not raw directory layout.

### M3-1: Operator State Model

Goal:

- Define one read model for UI/TUI/assistant modes.

Required state:

- project status,
- active phase and milestone,
- Project Brain health,
- task queue,
- executor packets and results,
- phase acceptance status,
- Project Brain acceptance history and derived next action,
- approvals,
- recovery plans,
- capability gaps,
- artifact index,
- evidence ledger,
- cost/budget state,
- timeline events.

Acceptance:

- WebUI, TUI, CLI status, and assistant modes read the same normalized state.
- State records distinguish `accepted`, `rejected`, `needs_human_review`,
  `needs_evidence`, `paused`, `blocked`, and `retryable`.
- Phase progress is derived from Project Brain acceptance history, not from UI
  local state or raw directory layout.

### M3-2: WebUI Operator Console

Goal:

- Upgrade the current read-only WebUI skeleton into a local-first operator
  console without weakening safety gates.

Required views:

- Projects,
- phases,
- tasks,
- executor results,
- approvals,
- evidence,
- artifacts,
- Project Brain,
- content project facts,
- capability gaps,
- recovery,
- costs,
- settings.

Required actions:

- approve,
- reject,
- pause,
- resume,
- retry,
- open artifact,
- export handoff,
- inspect diff/evidence,
- request missing evidence.

Acceptance:

- All mutations call existing CLI/runtime contracts; the UI must not bypass
  acceptance, approval, or evidence gates.
- Public bind remains disabled by default.
- Secrets and private paths are redacted in every JSON response.

### M3-3: TUI Daily-Driver Flow

Goal:

- Make the TUI usable as the fastest operator surface for long-running projects.

Required flows:

- show current project health,
- select phase/task,
- inspect evidence,
- approve/reject with actor and reason,
- pause/resume/retry,
- open artifact paths,
- show cost and budget pressure,
- export current handoff.

Acceptance:

- A full M2 demo can be operated from the TUI without reading raw YAML files.
- Every mutation creates an auditable event.

### M3-4: Config Center

Goal:

- Make runtime policy legible and editable with guardrails.

Required views:

- global defaults,
- project overrides,
- executor enablement,
- skill/capability enablement,
- approval thresholds,
- budget policy,
- recovery policy,
- UI/server safety policy.

Acceptance:

- The operator can see where every active value came from.
- Risky changes require explicit approval and produce an audit event.
- Disabled-by-default external execution remains disabled unless policy and
  approval both allow it.

### M3-5: Cost System v2

Goal:

- Move from ledger existence to operator-grade cost control.

Required features:

- project budget,
- phase budget,
- executor/model usage ledger,
- per-task cost attribution,
- budget alerts,
- cost efficiency report,
- retry cost impact,
- projected cost to next milestone.

Acceptance:

- The operator can answer: what did this phase cost, why, which executor/model
  spent it, what was accepted, and what is the estimated remaining cost?

### M3-6: Observability Timeline

Goal:

- Make the timeline the main explanation of system behavior.

Required event classes:

- task packet created,
- executor assigned,
- executor result received,
- evidence consumed,
- phase acceptance verdict,
- Project Brain acceptance-history entry written,
- next action recalculated from acceptance history,
- state transition proposed/applied/rejected,
- approval requested/resolved,
- capability gap raised,
- recovery started/resolved,
- budget warning,
- artifact promoted/archived.

Acceptance:

- Every UI page can deep-link to the relevant timeline/evidence events.
- Failure state includes root cause, impacted phase/task, recovery option, and
  next safe action.

### M3-7: Content Project Operator Surface

Goal:

- Make NovelGen/Crown-style content governance understandable and controllable.

Required views:

- production/candidate/archive layout,
- current artifact index,
- fact snapshot,
- state transition proposals,
- artifact lineage,
- continuity warnings,
- chapter batch status,
- promotion readiness.
- archive receipts and replaced-production lineage,
- phase acceptance state-transition application status.

Acceptance:

- The operator can see why a candidate chapter is not canon yet.
- The operator can see exactly which fact snapshot and artifact index a worker
  consumed.
- Multiple-current artifacts or unregistered legacy roots are visible as blocking
  hygiene errors.
- The operator can inspect the same Crown-style promotion chain covered by
  `tests/test_content_project_long_chain.py`: candidate artifact, lineage,
  state transition proposal, archive receipt, updated artifact index, and updated
  fact snapshot.

### M3-8: Assistant Modes

Goal:

- Let AgentLab explain itself without hallucinating system state.

Supported questions:

- Why is this project blocked?
- What evidence is missing?
- Which executor result failed and why?
- What should I approve or reject?
- What changed in the current fact snapshot?
- Where did cost go this phase?
- What is the next safe action?

Acceptance:

- Answers cite Project Brain, phase acceptance, executor result, evidence,
  timeline, cost ledger, or config records.
- "Next safe action" answers cite `acceptance_history.yml` and
  `next_actions.yml`; they do not infer progress from candidate/archive
  directories or loose artifacts.
- If the relevant record is missing, the assistant says it is missing and points
  to the required evidence or command.

## M3 Must Not Do

M3 must not absorb M4:

- No revenue ledger beyond placeholder fields.
- No CRM/client delivery loop.
- No market/channel automation.
- No automatic platform posting.
- No legally binding contract automation.
- No full commercial asset registry beyond artifact visibility needed by the
  operator console.

M3 also must not weaken M2:

- UI approval cannot bypass phase acceptance.
- UI mutation cannot write production content directly.
- UI cannot mark media verified without an observation/evidence record.
- UI cannot enable external execution without policy and approval.

## M3 Entry Gates

Start M3 only when M2 stable closure has:

- hard executor result validation,
- phase acceptance evidence gating,
- mandatory Project Brain consumption,
- expanded generalization demos,
- content long-chain regression,
- text-integrity and forbidden-file guards passing,
- local full pytest passing,
- CI passing.

## M3 Exit Gates

M3 is complete when an operator can run a real long-project demo through WebUI or
TUI and can:

- inspect project and phase state,
- inspect executor packets/results/evidence,
- approve/reject/pause/resume/retry safely,
- see config sources and risky overrides,
- see cost by project/phase/task/executor/model,
- see capability gaps and recovery plans,
- understand content production/candidate/archive status,
- export a handoff,
- receive grounded assistant explanations,
- pass local full pytest and CI.
