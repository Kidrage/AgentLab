# M3-0 Operator OS Alignment

Last updated: 2026-07-01

## Active Label Contract

For the current repair mainline:

- M2 means Long-Project Governance Stable Baseline.
- M3 means Operator OS / Transparent Control Plane.
- M4 means Project-to-Revenue OS.

Older repository documents may call Operator OS "M2" and Project-to-Revenue
"M3". Those are historical release-roadmap labels. New M3 implementation agents
must follow this document and `docs/M3_UPGRADE_PLAN_REVIEW.md`.

## M3-0 Deliverables

M3-0 exists so lower-intelligence coding agents can work without guessing the
mainline.

Hard contracts now exist in code:

- `agent_runtime.operator_os.stage_scope.active_stage_scope()`
- `agent_runtime.operator_os.state_model.build_operator_state()`
- `agent_runtime.operator_os.action_contract.build_operator_action_catalog()`
- `agent_runtime.operator_os.action_contract.validate_operator_action()`

## Single Read Model

All M3 surfaces must consume the normalized Operator State before adding their
own display formatting:

- WebUI
- TUI
- CLI status
- ops console snapshots
- AgentLab Assistant Modes

Progress must come from:

- `project_brain/acceptance_history.yml`
- `project_brain/next_actions.yml`

Facts and artifact currentness must come from:

- `project_brain/project_fact_snapshot.yml`
- `project_artifact_index.yml`

Directory names, candidate folders, archive folders, rebuild folders, and raw UI
state are not truth sources.

## Mutation Contract

Every M3 mutation must pass through the Operator Action contract. UI/TUI agents
must not invent local mutation rules.

Supported actions:

- `approve`
- `reject`
- `pause`
- `resume`
- `retry`
- `request_missing_evidence`
- `inspect_evidence`
- `open_artifact`
- `export_handoff`

Forbidden effects:

- direct production content writes
- phase acceptance bypass
- evidence gate bypass
- Project Brain bypass
- external executor enablement
- public server bind
- secret exposure

## Work Safe For Lower-Intelligence Coding Agents

Safe tickets:

- Render the normalized Operator State in WebUI.
- Render the normalized Operator State in TUI.
- Add read-only filters, tabs, and sorting.
- Wire read-only evidence/artifact inspectors.
- Add tests that compare UI/TUI output to Operator State fields.

Do not assign these tickets to lower-intelligence coding agents:

- Changing acceptance, evidence, or Project Brain rules.
- Implementing real mutation behavior.
- Enabling external executors.
- Writing production content.
- Reinterpreting M3 as business/revenue/P2R.
- Assistant explanations that do not cite concrete records.

## Acceptance

M3-0 is accepted when:

- stage labels are explicit,
- Operator State builds without UI code,
- Operator Actions validate before any surface mutates state,
- ops console exposes the normalized read model,
- tests prove next action comes from acceptance history,
- tests prove forbidden effects are blocked.
