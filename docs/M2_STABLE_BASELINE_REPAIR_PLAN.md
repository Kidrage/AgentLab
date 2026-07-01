# M2 Stable Baseline Repair Plan

Last updated: 2026-06-30
Baseline under review: `752b3789ebdd60cbc89bb0ebd431efeda855d256`

## Scope Note

This document uses the current project-mainline wording from the latest
operator discussion:

- M2 means long-project governance, external CLI-agent collaboration, content
  governance, evidence gates, and generalized project stability.
- M3 means Operator OS / Transparent Control Plane: TUI, WebUI, config
  transparency, cost control, observability, and operator assistant modes.
- M4 means Project-to-Revenue OS: business contracts, asset registry, production
  pipelines, revenue ledgers, market/channel/CRM/compliance loops.

Older repository docs may call the governance phase M1 and the Operator OS phase
M2. When there is a conflict, use this document and `docs/M3_UPGRADE_PLAN_REVIEW.md`
as the current handoff for the next upgrading agent.

## Current Reality

AgentLab now has a solid M2 MVP baseline, but not a fully closed M2. It can
represent long projects, generate phase plans, create executor task packets,
ingest executor results, apply phase acceptance, protect content-project
canonical facts, and run offline generalization checks.

The remaining risk is not missing vocabulary. The remaining risk is that several
contracts are still too soft or too fixture-bound:

- Real executor dispatch/result ingest is mostly contract-first and mock-first.
- Phase acceptance can still treat human-review-needed states too much like
  accepted states.
- Generalization eval has only a small offline fixture set.
- Content governance is protected by protocol tests, but not yet by a long
  real-world regression demo.
- Project Brain artifacts exist, but every downstream actor must be forced to
  consume them instead of rediscovering context.
- Text integrity and local artifact pollution guards exist, but must stay
  release-blocking because this repository has repeatedly produced damaged
  generated files and tracked runtime artifacts.

Therefore `752b378` is acceptable as the M2 governance MVP baseline. It is not
the final M2 closure.

## M2 Fix Tracks

### M2-fix-1: Real Executor Result Contract Hardening

Current evidence:

- `agent_runtime/executors/phase_connector.py` can ingest an executor result
  directory and bridge it into phase acceptance.
- S8 tests use a mock executor fixture and explicitly keep external auto
  execution disabled.
- 2026-06-30 update: `agent_runtime/executors/result_contract.py` now validates
  executor result envelopes before ingestion. Ingested reports include
  `contract_validation`, malformed results fail before phase acceptance, and
  executor fixtures now use explicit task identity, executor identity, source,
  status, test evidence summary, artifact evidence, and safety attestation.

Gap:

- The result contract is not yet proven against real CLI-agent outputs from
  Codex, Claude Code, Hermes, or similar executors.
- The runtime can receive evidence, but the contract is not strict enough to
  reject malformed, incomplete, or unverifiable external results across all
  project types.

Required work:

- Standardize `executor_result.yml` and `execution_result_envelope.yml` with a
  schema-backed validator.
- Require executor identity, command envelope, task packet id, changed file
  manifest, evidence list, test output summary, risk notes, and completion
  status.
- Reject results that claim completion without file-scope evidence, test
  evidence, or explicit no-change rationale.
- Keep external auto-dispatch disabled unless an explicit policy permits it.

Acceptance:

- A malformed result fails before phase acceptance. Implemented locally on
  2026-06-30 for missing executor identity and related required fields.
- A result without evidence cannot close a phase.
- A no-change result must include a reviewer-readable rationale and evidence.
- The same contract works for at least one real local Codex result fixture and
  one non-Codex external-agent fixture.

### M2-fix-2: External CLI Handoff/Result Fixtures

Current evidence:

- S8 can create phase-aware task packets.
- External executors are represented as approval-gated actors.
- 2026-06-30 update: repository fixtures now cover `codex_local_pass`,
  `claude_code_pass`, `hermes_pass`, and `generic_contractor_fail` under
  `tests/fixtures/executor_results/`. Tests ingest these real fixture files,
  validate the result contract, bridge them through phase acceptance, and prove
  that the failing contractor result cannot close a phase.

Gap:

- The repo does not yet prove a full real handoff/result loop with external CLI
  agents.

Required work:

- Add offline fixtures for `codex_local`, `claude_code`, `hermes`, and
  `generic_contractor`.
- Each fixture must include task packet, executor result envelope, changed files
  manifest, evidence ledger, and review verdict.
- Include both passing and failing examples.

Acceptance:

- `pytest` covers all fixtures.
- Implemented locally on 2026-06-30 for Codex-local, Claude Code, Hermes, and a
  failing generic contractor fixture.
- One local smoke run creates a task packet, executes or simulates a real CLI
  result format, ingests it, rejects/accepts it correctly, and writes the
  acceptance history.

### M2-fix-3: Phase Acceptance Must Consume Executor Evidence

Current evidence:

- `phase_acceptance.py` reads evidence ledgers and result directories.
- It can apply state transitions when a proposal is accepted.
- 2026-06-30 update: `ask_user` is no longer mapped to `PASS`. Human-review
  gates and scope-drift review states now produce `NEEDS_HUMAN_REVIEW` with
  `accepted: false`; the policy records `human_review_blocks_acceptance: true`.
- 2026-06-30 update: executor-backed phase acceptance now requires supporting
  evidence beyond the result envelope itself. A ledger that contains only
  `executor_result.yml` or `execution_result_envelope.yml` records
  `executor_result_supporting_evidence` as missing and cannot close the phase.

Gap:

- Human-review-needed and approval-needed states are too close to successful
  acceptance in the current compatibility layer.
- Phase close can become a paperwork event if evidence is not treated as a hard
  dependency.

Required work:

- Split verdicts into `accepted`, `rejected`, `needs_human_review`,
  `needs_evidence`, and `blocked`.
- Never map `ask_user` or `needs_human_review` to accepted.
- Require executor evidence for executor-produced phase closure.
- Require artifact lineage and state transition evidence for durable content
  fact changes.

Acceptance:

- A phase cannot close with missing evidence.
- An executor result cannot close a phase with only the result envelope and no
  supporting evidence file. Implemented locally on 2026-06-30.
- A phase cannot close with only human-review-needed status. Implemented locally
  on 2026-06-30 for direct phase acceptance and S8 executor review.
- A phase cannot close if changed files are outside the task packet scope unless
  the scope expansion is explicitly approved.
- Acceptance history records which evidence was consumed. Implemented locally on
  2026-07-01: `accept_phase()` now appends Project Brain
  `acceptance_history.yml` entries and refreshes `next_actions.yml` when a
  phase has a valid `project_brain_dir`.

### M2-fix-4: Project Brain Mandatory Consumption

Current evidence:

- S7 writes project brief, roadmap, milestone graph, phase summaries, snapshots,
  acceptance history, and next actions.
- 2026-06-30 update: `create_task_packet` now enforces Project Brain consumption
  for long-running phases. A long-project phase without `project_brain_dir` is
  rejected, an incomplete brain is rejected, and valid task packets record
  `project_brain_consumption` with the exact consumed brain files.

Gap:

- The existence of Project Brain files does not prove every planner, executor,
  reviewer, and context packer consumes them.

Required work:

- Block long-running project actions without a valid `project_brain/`.
- Require next task generation to read the previous acceptance result and
  `next_actions.yml`.
- Require context packers to use snapshot/index/state files as their source of
  truth.
- Record consumed Project Brain files in task packet metadata.

Acceptance:

- Missing Project Brain blocks long-project task creation. Implemented locally
  on 2026-06-30 for longform/codebase/video project phase dispatch.
- Next actions cannot be generated from scratch when prior acceptance history
  exists. Implemented locally on 2026-07-01 for phase acceptance: accepted
  phases advance the Project Brain next action through
  `acceptance_history.yml`, while blocked/human-review phases remain
  auditable history without closing the milestone.
- Task packets list the exact Project Brain inputs used. Implemented locally on
  2026-06-30 through `project_brain_consumption`.

### M2-fix-5: Content Project Governance Long-Chain Regression

Current evidence:

- `config/content_project_governance.yml` defines active projects, canonical
  layout, allowed frontdesk sources, formal/candidate/archive roots, legacy
  patterns, and required outputs.
- Tests prove narrative context packers exclude candidates and archives by
  default.
- Tests reject active content tasks that modify canon without
  `artifact_lineage.yml` and `state_transition_proposal.yml`.
- 2026-06-30 update: `tests/test_content_project_long_chain.py` now runs a
  Crown-style long-chain regression that promotes a candidate chapter into
  `production/`, archives the replaced production chapter, updates
  `project_artifact_index.yml`, applies `state_transition_proposal.yml` into
  `project_fact_snapshot.yml`, and verifies artifact governance has no fatal
  issues.

Gap:

- The rules have not yet been proven by a realistic long-chain Crown/NovelGen
  writing demo.

Required work:

- Run a multi-step Crown demo with production facts, a candidate chapter batch,
  a continuity review, a state transition proposal, artifact lineage, and a
  controlled promotion into production.
- Add regression tests for:
  - old setting files cannot pollute production,
  - candidates cannot be read as canon,
  - archive only enters context through explicit index references,
  - multiple current artifacts fail phase acceptance,
  - state transition proposals update fact snapshots only after evidence review.

Acceptance:

- Crown has exactly one current world/setting source in the artifact index.
- Workers default to `PROJECT_HANDOFF.md`, `project_artifact_index.yml`, and
  `project_brain/project_fact_snapshot.yml`.
- Any root-level `*_rebuild`, `v2_*`, or `legacy` fact directory outside the
  index triggers a hygiene warning or failure.
- A Crown-style candidate promotion can update production, archive the replaced
  production artifact, and apply durable fact-state changes in one verified
  regression. Implemented locally on 2026-06-30.

### M2-fix-6: Generalization Eval Expansion

Current evidence:

- S10 has six offline fixtures: docs, cli, capability_gap, recovery,
  project_brain, and search_repo_mock.
- 2026-06-30 update: S10 required fixture domains now include longform novel,
  research archive, codebase repair, video/story skeleton, and document
  ingestion governance fixtures. The suite remains offline-only and
  external-execution-blocked.

Gap:

- Six offline fixtures prove that the skeleton moves; they do not prove robust
  governance across long novels, research archives, code repair, video/story
  projects, and document ingestion.

Required work:

- Add governance eval demos for:
  - long-form novel project,
  - research archive project,
  - codebase repair project,
  - video/story-production skeleton,
  - document/material ingestion project.
- Keep them offline and deterministic, but make the fixture artifacts realistic
  enough to exercise Project Brain, evidence, phase acceptance, context packing,
  and recovery.

Acceptance:

- Every fixture produces required artifacts and passes CI.
- Every fixture has at least one negative case that proves the gate fails for
  missing evidence, wrong source of truth, or invalid capability assumptions.

### M2-fix-7: Text Integrity and Local Artifact Pollution Guard

Current evidence:

- CI runs `scripts/audit_text_integrity.py --fail-on-suspicious`.
- CI runs `scripts/check_forbidden_tracked_files.sh`.
- Runtime performance ledger has been moved out of tracked mainline state.

Gap:

- This is a recurring foundation risk, not a one-time cleanup.

Required work:

- Keep text-integrity and forbidden-file checks mandatory in local gates and CI.
- Add tracked-file deny rules for content production dumps, raw logs, private
  paths, media binaries, and runtime ledgers.
- Keep only minimal fixtures in Git.

Acceptance:

- `git ls-files` does not include stale content assets, raw run dumps, private
  paths, or runtime ledgers.
- Full pytest and CI remain green after M2 closure.

### M2-fix-8: Capability Gap Contracts

Current evidence:

- Capability gap resolver can produce blocked decision cards for missing
  capabilities and recommends safe actions.

Gap:

- M2 must reliably admit when it cannot inspect image/video/audio/PDF evidence.
  It does not need a full production OCR/VLM/audio/video backend.

Required work:

- Ensure every media-heavy task emits a capability gap decision card when the
  required backend is unavailable.
- Require media evidence contracts to name expected observation, evidence,
  confidence, and risk fields.
- Prohibit pretending that uninspected media was verified.

Acceptance:

- Missing image/video/audio/PDF capability blocks or routes the task to an
  explicit external evidence provider.
- No media artifact can be accepted as reviewed without an observation record.

## Crown of Ash Trilogy Readiness

AgentLab is not yet ready to autonomously and reliably finish the full Crown of
Ash trilogy at production quality with no operator intervention.

It can be made ready after M2 closure if the task is treated as a governed
long-running content project, not as one huge generation request. The required
pipeline is:

1. `crown-volume-plan`: lock trilogy premise, volume arcs, character arcs,
   timeline, canon snapshot, and acceptance criteria.
2. `crown-batch-plan`: plan 3-5 chapters at a time from the current production
   snapshot and artifact index.
3. `crown-draft-batch`: draft the batch into `candidates/<task_id>/`, never
   directly into production.
4. `crown-continuity-check`: verify timeline, character state, world facts,
   unresolved promises, tone, and prior-chapter dependency.
5. `crown-rewrite-batch`: repair only the flagged issues, preserving lineage.
6. `crown-promote-batch`: write `artifact_lineage.yml` and
   `state_transition_proposal.yml`, then promote accepted text/facts into
   production.
7. `crown-volume-acceptance`: close the volume only after continuity, outline,
   manuscript, and fact snapshot gates pass.

The old "seven agents for one chapter" shape should not be the default. The
stable route should be lower cost and more predictable:

- One planner/supervisor at volume and batch boundaries.
- One writer for a chapter batch.
- One continuity reviewer for canon/timeline/character checks.
- One deterministic artifact steward for index, lineage, and promotion gates.
- Optional style editor only when quality gates fail or at volume polish time.

This makes normal chapter production a 2-3 active-agent loop plus deterministic
gates, not a 7-agent loop per chapter.

## M2 Closure Definition

M2 can be called stable only when all of the following are true:

- Real executor result fixtures pass for at least Codex-local and one external
  CLI-agent format.
- Phase acceptance cannot close without consumed evidence.
- Project Brain is mandatory for long-running project actions.
- Crown or NovelGen passes a realistic multi-step content-governance demo.
- Generalization eval covers novel, research archive, code repair, video/story
  skeleton, and document ingestion domains.
- Capability gap decision cards block unsupported media verification.
- Text integrity and forbidden tracked-file gates pass locally and in CI.
- Full pytest passes.
- CI passes on the pushed mainline.
