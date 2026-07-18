# AgentLab v1.0 Internal Closed Loop Plan

Last updated: 2026-07-01

## Scope

AgentLab v1.0 is the stable internal baseline for M1-M3:

- Long-project governance has one Project Brain, one artifact index, and one fact snapshot.
- Operator surfaces read one normalized Operator State.
- Mutations pass through Operator Action contracts and runtime audit.
- Timeline is the canonical observability narrative.
- Cost state comes from the Cost System v2 facade.
- Content projects promote candidates only through lineage, state transition, archive, and acceptance gates.
- Repository hygiene prevents generated artifacts, private paths, compressed text, and artificial padding from entering mainline.

v1.0 does not implement M4 Project-to-Revenue features. Business Contract,
Asset Registry, Production Pipeline, Revenue Ledger, channel automation, CRM,
and compliance operations start from this baseline.

## Stable Gates

- `build_operator_state()` must call `operator_os.timeline.build_timeline()` and `costing.facade.build_cost_state()`.
- WebUI/TUI/CLI mutations must call `operator_os.action_runtime.execute_operator_action()`.
- WebUI must not directly write cost ledgers or launch external executors.
- External execution remains blocked by default unless policy and scoped approval explicitly allow it.
- Assistant answers must be grounded in Operator State, timeline, Project Brain, content surface, and cost facade records.
- Content promotion must require `artifact_lineage.yml`, `state_transition_proposal.yml`, archive receipt, and exactly one current artifact.
- Text integrity tests must reject artificial padding lines.

## Release Evidence

The v1 acceptance report must record:

- focused v1 guard test results,
- content governance demo result,
- code repair executor-result demo result,
- research/document archive demo result,
- failure recovery demo result,
- full pytest result,
- CI result and commit hash,
- clean `git status --short`.
