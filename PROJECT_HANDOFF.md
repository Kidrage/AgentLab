# Project Handoff

> Deterministically generated repository/project memory for cross-agent handoff.
> Update after every material project change and before final reporting.

## Repository Identity

- Repository ID: `AgentLab-de62d90289e0`
- Working root: `.`
- Repository name: `AgentLab`
- Git repository: `true`
- Generated at: `2026-07-19T04:01:02.640094+00:00`

## Current State

- Branch: `feature/narrative-production-closure`
- HEAD: `047e1e6`
- Indexed paths: 1832
- Inventory truncated: `false`
- Inaccessible paths: 0
- Scan mode: complete path/metadata inventory; no bulk content read; no symlink traversal.

## Project Progress Dashboard

- Current progress: derive from branch, HEAD, current changes, and manual Agent Notes below.
- Work already changed: see Change History and Current Changes.
- Active work: any dirty Git status entries listed under Current Changes.
- Remaining work / ETA: maintain in Agent Notes when it cannot be inferred deterministically.
- Pending decisions: maintain in Agent Notes and refresh before final reporting.
- Pending files / plans / acceptance artifacts: maintain in Agent Notes and task run ledgers.
- Fast reporting source: this canonical root file; use the shared mirror only when explicitly written.

## Active Work and Pending Items

- In progress: inspect Current Changes and Agent Notes.
- Pending decisions: record durable choices in Agent Notes before handoff.
- Pending files to modify: record intended paths in Agent Notes before dispatch.
- Pending plans to confirm: link task/run plans in Agent Notes.
- Pending acceptance artifacts: link deliverables and validation evidence in Agent Notes.
- Next safe entry point: run `./agentlab.sh repository-handoff --repo <path>` before deep work.

## Directory Routes

| Route | Files |
|---|---:|
| `agent_runtime` | 523 |
| `tests` | 441 |
| `docs` | 310 |
| `acceptance_runs` | 300 |
| `docs/archive` | 222 |
| `config` | 122 |
| `tests/fixtures` | 110 |
| `acceptance_runs/narrative_eval` | 59 |
| `skills` | 47 |
| `skills/active` | 46 |
| `acceptance_runs/agentlab_capability_acceptance` | 41 |
| `acceptance_runs/s10_generalization_eval` | 32 |
| `scripts` | 22 |
| `agent_runtime/program_manager` | 21 |
| `agent_runtime/recovery` | 21 |
| `agent_runtime/workers` | 21 |
| `acceptance_runs/mainline_r0_r5` | 20 |
| `agent_runtime/context_governance` | 20 |
| `agent_runtime/executors` | 18 |
| `.` | 16 |
| `acceptance_runs/m2_operator_demo` | 16 |
| `agent_templates` | 16 |
| `agent_runtime/capabilities` | 15 |
| `agent_runtime/ingestion` | 15 |
| `agent_runtime/cli` | 14 |
| `agent_runtime/config_center` | 13 |
| `acceptance_runs/p2_closure` | 12 |
| `agent_runtime/goals` | 12 |
| `agent_runtime/brain` | 11 |
| `agent_runtime/capability_broker` | 11 |
| `agent_runtime/costs` | 11 |
| `agent_runtime/execution_economy` | 11 |
| `agent_runtime/skills` | 11 |
| `acceptance_runs/e2e_minimal_task` | 10 |
| `acceptance_runs/p2_provider_governance` | 10 |
| `acceptance_runs/s0_remote_raw_repair` | 10 |
| `agent_runtime/intelligence` | 10 |
| `agent_runtime/router_update` | 10 |
| `acceptance_runs/s12_productization` | 9 |
| `agent_runtime/control_panel` | 9 |

## Data and File Structure

### Categories

- code: 904 files, 7286273 bytes
- literature: 394 files, 2120086 bytes
- other: 12 files, 74102 bytes
- structured_data: 522 files, 2976192 bytes

### Common Extensions

- `.py`: 891
- `.yml`: 500
- `.md`: 355
- `.txt`: 39
- `.json`: 17
- `.sh`: 8
- `[no extension]`: 5
- `.js`: 5
- `.csv`: 3
- `.html`: 2
- `.css`: 2
- `.diff`: 1
- `.ini`: 1
- `.jsonl`: 1
- `.log`: 1
- `.toml`: 1

### Schema / Model / Interface Candidates

- `OPERATING_MODEL.md`
- `acceptance_runs/ccs_migration_safety/CCS_MIGRATION_SAFETY_REPORT.md`
- `acceptance_runs/hotfix_cli_schema_v4_routing/HOTFIX_CLI_SCHEMA_V4_ROUTING_REPORT.md`
- `acceptance_runs/m2_operator_demo/migration_doctor_summary.yml`
- `acceptance_runs/m2_worker_invocation_contracts/classified_cli_failures.yml`
- `acceptance_runs/m2_worker_invocation_contracts/invalid_templates.yml`
- `acceptance_runs/m2_worker_invocation_contracts/worker_invocation_contract_report.md`
- `acceptance_runs/m2_worker_invocation_contracts/worker_invocation_contract_report.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_live_single_chapter_probe_20260707/trusted_live_20260712_0505_writer_contract_v1_writer/chapter_quality_matrix.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_live_single_chapter_probe_20260707/trusted_live_20260712_0505_writer_contract_v1_writer/chapter_state_plan.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_live_single_chapter_probe_20260707/trusted_live_20260712_0505_writer_contract_v1_writer/character_arc_ledger.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_live_single_chapter_probe_20260707/trusted_live_20260712_0505_writer_contract_v1_writer/continuity_failure_report.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_live_single_chapter_probe_20260707/trusted_live_20260712_0505_writer_contract_v1_writer/foreshadowing_ledger.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_live_single_chapter_probe_20260707/trusted_live_20260712_0505_writer_contract_v1_writer/longform_eval_report.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_live_single_chapter_probe_20260707/trusted_live_20260712_0505_writer_contract_v1_writer/manuscript_reset_proposal.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_live_single_chapter_probe_20260707/trusted_live_20260712_0505_writer_contract_v1_writer/series_arc_ledger.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_live_single_chapter_probe_20260707/trusted_live_20260712_0505_writer_contract_v1_writer/series_scale_simulation.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_live_single_chapter_probe_20260707/trusted_live_20260712_0505_writer_contract_v1_writer/timeline_worldline_ledger.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_mock_chain_receipt_contract_20260707/mock_chain_receipt_contract_ch01_ch03_20260707/chapter_quality_matrix.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_mock_chain_receipt_contract_20260707/mock_chain_receipt_contract_ch01_ch03_20260707/chapter_state_plan.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_mock_chain_receipt_contract_20260707/mock_chain_receipt_contract_ch01_ch03_20260707/character_arc_ledger.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_mock_chain_receipt_contract_20260707/mock_chain_receipt_contract_ch01_ch03_20260707/continuity_failure_report.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_mock_chain_receipt_contract_20260707/mock_chain_receipt_contract_ch01_ch03_20260707/foreshadowing_ledger.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_mock_chain_receipt_contract_20260707/mock_chain_receipt_contract_ch01_ch03_20260707/longform_eval_report.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_mock_chain_receipt_contract_20260707/mock_chain_receipt_contract_ch01_ch03_20260707/manuscript_reset_proposal.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_mock_chain_receipt_contract_20260707/mock_chain_receipt_contract_ch01_ch03_20260707/series_arc_ledger.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_mock_chain_receipt_contract_20260707/mock_chain_receipt_contract_ch01_ch03_20260707/series_scale_simulation.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_mock_chain_receipt_contract_20260707/mock_chain_receipt_contract_ch01_ch03_20260707/timeline_worldline_ledger.yml`
- `acceptance_runs/s10_generalization_eval/fixtures/video_story_skeleton_governance/evidence_contract.yml`
- `agent_runtime/artifact_contract.py`
- `agent_runtime/assistant/models.py`
- `agent_runtime/brain/artifact_contract_builder.py`
- `agent_runtime/brain/mission_contract.py`
- `agent_runtime/capabilities/audio_contract.py`
- `agent_runtime/capabilities/capability_contract.py`
- `agent_runtime/capabilities/capability_schema.py`
- `agent_runtime/capabilities/document_contract.py`
- `agent_runtime/capabilities/vision_contract.py`
- `agent_runtime/cli/capability_contracts.py`
- `agent_runtime/cli/models.py`
- `agent_runtime/config_center/schema.py`
- `agent_runtime/context_governance/schemas.py`
- `agent_runtime/costs/model_cost_profile.py`
- `agent_runtime/executors/connector_contract.py`
- `agent_runtime/executors/models.py`
- `agent_runtime/executors/result_contract.py`
- `agent_runtime/external_projects/adapter_contract.py`
- `agent_runtime/external_projects/models.py`
- `agent_runtime/goals/action_schema.py`
- `agent_runtime/goals/models.py`
- `agent_runtime/governance/models.py`
- `agent_runtime/ingestion/ingestion_contract.py`
- `agent_runtime/langgraph_schema.py`
- `agent_runtime/migration_doctor.py`
- `agent_runtime/model_capacity.py`
- `agent_runtime/model_resolver.py`
- `agent_runtime/observation_contract.py`
- `agent_runtime/operator_os/action_contract.py`
- `agent_runtime/operator_os/state_model.py`
- `agent_runtime/p2_closure/models.py`
- `agent_runtime/program_manager/acceptance_contract.py`
- `agent_runtime/program_manager/models.py`
- `agent_runtime/program_manager/project_state_contract.py`
- `agent_runtime/project_ops/models.py`
- `agent_runtime/project_workflows/models.py`
- `agent_runtime/retry/models.py`
- `agent_runtime/review/models.py`
- `agent_runtime/router_update/models.py`
- `agent_runtime/schemas.py`
- `agent_runtime/workers/invocation_contract.py`
- `agent_templates/interface_mapper.md`
- `agentlab_tui/models.py`
- `config/agent_model_profiles.yml`
- `config/capability_schema.yml`
- `config/config_ui_schema.yml`
- `config/hermes_brain_model_groups.yml`
- `config/migration_profile.yml`
- `config/model_capacity.yml`
- `config/model_catalog.yml`
- `config/model_cost_profiles.yml`

## Key Entrypoints and Guides

- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- `agent_runtime/README.md`
- `agent_runtime/requirements.txt`
- `config/README.md`
- `docs/README.en-US.md`
- `docs/README.zh-CN.md`
- `docs/archive/acceptance_docs_legacy_20260718/README.md`
- `docs/archive/acceptance_legacy_20260718/cli_shell_coalescing/README.md`
- `docs/archive/codex_full_driver_legacy_20260718/README.md`
- `docs/archive/config_specs_legacy_20260718/README.md`
- `docs/archive/current_capabilities_legacy_20260718/README.md`
- `docs/archive/handoffs_legacy_20260718/README.md`
- `docs/archive/legacy_plans_reports_20260718/README.md`
- `docs/archive/legacy_production_scripts_20260718/README.md`
- `docs/archive/readme_legacy_20260718/README.en-US.md`
- `docs/archive/readme_legacy_20260718/README.md`
- `docs/archive/readme_legacy_20260718/README.zh-CN.md`
- `docs/archive/retired_agent_templates_legacy_20260718/README.md`
- `docs/archive/retired_runtime_adapters_legacy_20260718/README.md`
- `docs/archive/root_agent_guides_legacy_20260718/AGENTS.md`
- `docs/archive/root_agent_guides_legacy_20260718/README.md`
- `docs/archive/root_agent_guides_legacy_20260718/README_PRE_PRUNING.md`
- `docs/archive/skill_usage_legacy_20260718/README.md`
- `projects/README.md`
- `requirements.txt`
- `tests/fixtures/p1_closure/fake_ecc/AGENTS.md`
- `tests/fixtures/p1_closure/fake_repo/pyproject.toml`
- `web_ui/README.md`

## Change History

- `047e1e6 2026-07-19 feat(narrative): establish phase 0 diagnostic baseline`
- `8456bc6 2026-07-18 refactor: prune AgentLab workflow governance`
- `2239ad7 2026-07-18 fix: delay transient background provider retries`
- `faa0a60 2026-07-18 fix: preserve runtime imports in detached jobs`
- `c7c193d 2026-07-18 docs: sanitize archived handoff path`
- `0516cf7 2026-07-18 fix: prune AgentLab execution and durable longform flow`
- `7b4a927 2026-07-14 docs: refresh capability reference handoff`
- `2ee2716 2026-07-14 docs: publish current AgentLab capability reference`
- `b098513 2026-07-14 docs: refresh AgentLab role overhaul handoff`
- `424b983 2026-07-14 feat: govern agent roles and model capacity`
- `a27c0b1 2026-07-13 docs: refresh AgentLab handoff`
- `1b96c93 2026-07-13 fix: constrain Agy quota rotation`
- `0bddbd4 2026-07-13 feat: rotate Agy writer quota model`
- `a39918c 2026-07-13 fix: persist narrative quota resume metadata`
- `6ae8488 2026-07-13 fix: archive rejected narrative attempts on resume`
- `19fc00b 2026-07-13 fix: normalize relationship candidate event scope`
- `6570d25 2026-07-13 fix: keep 250 activation on Agy OAuth`
- `49925d4 2026-07-13 fix: block repeated narrative passages`
- `78f2a8d 2026-07-13 fix: bind narrative audit roles to CLI workers`
- `d8afaa5 2026-07-13 test: consolidate fragmented M2 coverage`

## Current Changes

- `## feature/narrative-production-closure`
- ` M PROJECT_HANDOFF.md`
- ` M acceptance_runs/narrative_efficiency/baseline_metrics.json`
- ` M acceptance_runs/narrative_efficiency/frozen_samples.yml`
- ` D acceptance_runs/narrative_efficiency/live_probe_phase0_20260719/chapter_quality_matrix.yml`
- ` D acceptance_runs/narrative_efficiency/live_probe_phase0_20260719/live_execution_log.yml`
- ` D acceptance_runs/narrative_efficiency/live_probe_phase0_20260719/live_generation_error.yml`
- ` M acceptance_runs/narrative_efficiency/live_probe_phase0_20260719/live_trial_receipt.json`
- ` D acceptance_runs/narrative_efficiency/live_probe_phase0_20260719/longform_eval_report.yml`
- ` D acceptance_runs/narrative_efficiency/live_probe_phase0_20260719/model_execution_chain_writer.yml`
- ` D acceptance_runs/narrative_efficiency/live_probe_phase0_20260719/model_execution_receipt_writer_writer_6b3f6541fe8c.yml`
- ` D acceptance_runs/narrative_efficiency/live_probe_phase0_20260719/narrative_invocations.jsonl`
- ` D acceptance_runs/narrative_efficiency/live_probe_phase0_20260719/outbound_context_manifest_writer.yml`
- ` M acceptance_runs/stabilization/text_integrity_audit.json`
- ` M acceptance_runs/stabilization/text_integrity_audit.md`
- ` M agent_runtime/agent_runner.py`
- ` M agent_runtime/narrative/diagnostics/baseline.py`
- ` M agent_runtime/narrative/diagnostics/telemetry.py`
- ` M docs/narrative/NARRATIVE_CALL_GRAPH.md`
- ` M docs/narrative/NARRATIVE_EFFICIENCY_BASELINE.md`
- ` M docs/narrative/NARRATIVE_PIPELINE_DIAGNOSIS.md`
- ` M tests/test_narrative_efficiency.py`

## Related Repositories

### Remotes

- `250 ssh://10.147.17.250/home/admin/AgentLab (fetch)`
- `250 ssh://10.147.17.250/home/admin/AgentLab (push)`
- `origin github.com:Kidrage/AgentLab.git (fetch)`
- `origin github.com:Kidrage/AgentLab.git (push)`

### Submodules

- None detected.

## Media and Literature Routes

### literature

- `.clinerules/sync-rules.md`
- `AGENTS.md`
- `CLAUDE.md`
- `CLI_ROADMAP.md`
- `CONTEXT.md`
- `DRIVER_PROTOCOL.md`
- `OPERATING_MODEL.md`
- `PROJECT_HANDOFF.md`
- `README.md`
- `USAGE_PLAN.md`
- `_shared/AGENT_HANDOFF.md`
- `_shared/AGENT_PROTOCOL.md`
- `acceptance_runs/agentlab_capability_acceptance/private_live_smoke_approval_handoff.md`
- `acceptance_runs/agentlab_capability_acceptance/role_session_acceptance_handoff.md`
- `acceptance_runs/ccs_migration_safety/CCS_MIGRATION_SAFETY_REPORT.md`
- `acceptance_runs/e2e_minimal_task/final_delivery_report.md`
- `acceptance_runs/e2e_minimal_task/input_task.md`
- `acceptance_runs/e2e_minimal_task/revision_packet.md`
- `acceptance_runs/hotfix_cli_binary_aliases/CLI_COMMAND_INVENTORY.md`
- `acceptance_runs/hotfix_cli_binary_aliases/HOTFIX_CLI_BINARY_ALIASES_REPORT.md`

### image

- None detected.

### audio

- None detected.

### video

- None detected.

### structured_data

- `.github/workflows/ci.yml`
- `acceptance_runs/agentlab_capability_acceptance/acceptance_report_hygiene.yml`
- `acceptance_runs/agentlab_capability_acceptance/agent_role_chain_audit.yml`
- `acceptance_runs/agentlab_capability_acceptance/agy_cli_print_smoke.yml`
- `acceptance_runs/agentlab_capability_acceptance/agy_cli_session_smoke.yml`
- `acceptance_runs/agentlab_capability_acceptance/crown_live_candidate_audit.yml`
- `acceptance_runs/agentlab_capability_acceptance/crown_scale_governance_audit.yml`
- `acceptance_runs/agentlab_capability_acceptance/current.yml`
- `acceptance_runs/agentlab_capability_acceptance/external_acceptance_readiness.yml`
- `acceptance_runs/agentlab_capability_acceptance/external_policy_rejection_writer_20260707.yml`
- `acceptance_runs/agentlab_capability_acceptance/frontdesk_boundary_audit.yml`
- `acceptance_runs/agentlab_capability_acceptance/frontdesk_live_handoff.yml`
- `acceptance_runs/agentlab_capability_acceptance/frontdesk_runtime_private_context_rejection_trusted_runner_20260708.yml`
- `acceptance_runs/agentlab_capability_acceptance/frontdesk_runtime_private_context_rejection_writer_20260707_02.yml`
- `acceptance_runs/agentlab_capability_acceptance/goal_acceptance_scope.yml`
- `acceptance_runs/agentlab_capability_acceptance/goal_completion_audit.yml`
- `acceptance_runs/agentlab_capability_acceptance/grok_cli_session_smoke.yml`
- `acceptance_runs/agentlab_capability_acceptance/grok_media_preflight_current.yml`
- `acceptance_runs/agentlab_capability_acceptance/grok_oauth_cli_smoke.yml`
- `acceptance_runs/agentlab_capability_acceptance/hermes_frontdesk_deepseek_v4_pro_smoke.yml`

## Validation and Risks

- This inventory records paths and metadata, not semantic correctness.
- Binary/media payloads and secrets were not read.
- Validate current branch, tests, and interfaces before modifying files.

## Agent Notes

<!-- AGENT_NOTES_START -->
# Highest-priority plan: narrative production, audit, and delivery closure

- Priority: `P0 / HIGHEST`. This plan supersedes other AgentLab roadmap work until
  it reaches a user-approved pause, a documented stop condition, or completion.
- Owner namespace: `agents/codex/`; implementation may be continued by another
  agent only after reading this entire handoff and the linked Phase 0 reports.
- Branch: `feature/narrative-production-closure`; never push this work to `main`
  without explicit user approval.
- Product boundary: AgentLab is the producer, editorial department, version
  controller, and scheduler. A suitable Writer model creates prose. Do not turn
  every chapter into a fixed Supervisor→Writer→Reviewer→Scribe→Verifier meeting.
- Current execution authorization: finish and harden Phase 0, then pause for an
  explicit Phase 1 decision. Highest priority does not waive approval, external
  disclosure, candidate-only, or Production safety gates.

## Non-negotiable invariants

1. Natural language is compiled once. Persist `job_kind`, `run_mode`,
   `candidate_set_id`, lineage, attempt, lease, and fencing identity; never
   reclassify an existing job from generated prose.
2. `fiction_review=blocked`, continuity blocking, literary blocking, missing or
   stale audits, hash drift, missing independent re-audit, stale approval, or an
   expired lease always veto seal.
3. Investigation and rollout remain `candidate_only: true`; Production is not
   written without a hash-matching user acceptance receipt and atomic promotion.
4. Formal product truth comes from manifests, receipts, approval, promotion, and
   release records. `runs/*` is lineage/evidence, not the workbench database.
5. At most two automatic rewrites. Insufficient verified uplift becomes
   `decision_required / insufficient_revision_uplift`.
6. Crown-specific migration logic stays outside queue, lease, retry, supervisor,
   receipt, promotion, and release cores.
7. Central modules receive thin adapters only. A phase adding more than 150 net
   lines to a central module must stop and justify/extract the logic.
8. Raw project runs and task ledgers stay local. Committed evidence is distilled,
   content-free, path-normalized, attributed, and hash-bound.
9. Tests remain consolidated in the six narrative domain files named in the
   plan; do not weaken assertions or schemas to obtain green tests.
10. No unattended full 200-chapter generation/audit before Gates 1 and 2 pass.

## Phase plan and current status

### Phase 0 — reproducible diagnosis and baseline

Status: `IN_PROGRESS / CLOSING`; implementation and review corrections are local,
but the live three-chapter trial is blocked by external-context approval.

- Freeze Ch25–27, continuous Ch21–30, negative Ch26/Ch30, and user-positive
  samples. Positives remain `missing_user_samples`; never invent them.
- Measure wall/process/orchestration/queue timing, tokens, cost, calls, retries,
  provider rotation, final context size, role file loads, context duplication,
  findings, evidence density, revisions, regressions, and uplift availability.
- Separate provider-process wall time from model-active compute. Model compute is
  currently unavailable; do not relabel CLI/network time as model time.
- Deliver diagnosis, call graph, efficiency report, frozen manifest, and generated
  baseline JSON. Preserve two confirmed defects as red replays; do not fix them in
  Phase 0.
- Canonical evidence:
  `docs/narrative/NARRATIVE_PIPELINE_DIAGNOSIS.md`,
  `docs/narrative/NARRATIVE_CALL_GRAPH.md`,
  `docs/narrative/NARRATIVE_EFFICIENCY_BASELINE.md`, and
  `acceptance_runs/narrative_efficiency/baseline_metrics.json`.
- Current evidence: Crown's 200-chapter job is blocked on batch 1 after 11
  attempts, with zero sealed batches and no completion receipt. The isolated Ch25
  attempt used zero tokens/cost and left Production hashes unchanged, but external
  Ch25–27 execution needs explicit manuscript/canon disclosure approval under the
  existing `$10` cap.

### Phase 1 — durable semantics and fail-closed sealing

Status: `NOT STARTED / USER APPROVAL REQUIRED AFTER PHASE 0`.

- Introduce immutable structured job identity and keep audit, generation, and
  revision state machines distinct.
- Treat audit findings as `completed_with_findings`, not task failure and not an
  implicit rewrite request.
- Centralize the hash-bound seal gate and cover all false-green combinations,
  missing/stale evidence, approval drift, independent re-audit, and expired leases.
- Enforce the two-rewrite ceiling and persist `decision_required`.
- Do not add quality prompts, UI, export, or global queue work in this phase.

### Phase 2 — production and audit efficiency

Status: `NOT STARTED / DEPENDS ON PHASE 0 EVIDENCE AND PHASE 1`.

- Build one immutable shared narrative context bundle; roles append only their
  specific inputs and record source/hash provenance.
- Ordinary chapters use one scene contract, one candidate, deterministic precheck,
  and one literary judge. Only risk triggers enable multiple strategies, A/B, or a
  second judge.
- Move completeness/hash/schema/POV/timeline/repetition/version checks to
  deterministic code.
- Re-audit only changed chapters and calculated impact windows; retry only failed
  nodes. Expired workers cannot overwrite newer attempts.
- Keep an optimization only when the same frozen sample and quality gate show no
  blind-review quality regression.

### Phase 3 — literary quality and verified revision uplift

Status: `NOT STARTED / REQUIRES USER POSITIVE SAMPLES`.

- Add evidence-backed six-dimensional scorecards. Causal reasoning, strategic
  competence, and character agency are veto dimensions, never averaged away.
- Compile findings into scene-level revision contracts with must-preserve/change,
  character knowledge, causality, cost, new information, freedom, and forbidden
  regression boundaries.
- Prefer local scene/paragraph rewrites; use whole-chapter rewrites only for
  structural failure.
- Preserve old/new candidates and run anonymous A/B review with independent
  receipts. A revision replaces nothing unless it wins and introduces no blocking.
- Require at least ten human blind comparisons and at least 70% new-system wins
  before scaling production.

### Phase 4 — immutable Candidate Sets and atomic promotion

Status: `NOT STARTED / DEPENDS ON PHASE 3`.

- Freeze Candidate Set manifests when audit starts; any chapter hash change makes
  related audits stale and creates lineage to a new set.
- Bind correctness, literary audit, cost, model tier, context manifest, user
  acceptance, and promotion receipts to exact candidate hashes.
- Permit first publication when a release slot has no current artifact; enforce
  uniqueness by `release_slot + chapter_id + edition_id`.
- Stage and verify a complete immutable edition, atomically switch the index
  pointer, and leave Production unchanged on every failure.

### Phase 5 — generic background core, workbench, reader, and release package

Status: `NOT STARTED / ONLY AFTER PHASES 0–4 PASS`.

- Separate a generic job registry, global queue, capacity arbitration, leases,
  fencing, deadlines, retry wait, supervisor recovery, idempotent seal, and
  completion receipts from the narrative adapter.
- Make the workbench read only formal manifests/receipts and show execution,
  artifact completeness, correctness, literary pass, user acceptance, and
  promotion as separate states.
- Add Production/Candidate switching, per-chapter A/B, evidence, revision contract,
  scores, impact, lineage, model, and cost views.
- Export real immutable Markdown/TXT/DOCX/EPUB packages with contents, editorial
  report, audit archive, receipts, changelog, and SHA256 manifest. PDF is deferred.

## Rollout gates

- Gate 1: isolated three-chapter quality/efficiency pilot; correct routing,
  candidate-only hashes, complete metrics, verified uplift, and no false-green.
- Gate 2: three consecutive 10-chapter batches; restart, network interruption,
  capacity wait, node recovery, incremental audit, two-rewrite stop, and zero
  Production contamination.
- Gate 3: 200-chapter audit soak only after Gates 1–2; completion receipt, every
  planned batch audited, eligible batches sealed, findings completed correctly,
  provider receipts complete, recomputable manifests, consistent hashes,
  recovery/idempotency green, and complete cost/efficiency report.

## Mandatory construction progress protocol

Every agent that touches this plan must update this section twice per construction
session: once before edits (`in_progress`) and once after validation
(`completed`, `blocked`, or `decision_required`). Append; do not erase prior rows.
Each row must name agent, phase/gate, exact scope, files/modules, tests/evidence,
metric delta when available, commit/branch, blocker, rollback, and next action.
No agent may claim a phase complete from unit tests alone or leave uncommitted work
without a progress row.

| Updated (Asia/Shanghai) | Agent | Phase/Gate | Status | Scope and evidence | Commit / rollback | Blocker / next action |
|---|---|---|---|---|---|---|
| 2026-07-19 | Codex | Phase 0 baseline | completed | Added opt-in invocation telemetry, frozen historical baseline, call graph, diagnosis, deterministic red replays; initial local suite 2,739 passed | `047e1e6` on `feature/narrative-production-closure`; revert commit to roll back | CI exposed one absolute-path integrity failure; review hardening followed |
| 2026-07-19 | Codex | Phase 0 review hardening | completed | Corrected timing semantics, added persisted queue-wait measurement, path normalization, measured safety, attribution, and distilled-only live receipt; focused 133 passed, full 2,741 passed / 2 skipped / 11 warnings; standards and spec verification both clear | dirty worktree after `047e1e6`; revert forthcoming correction commit to roll back | Commit/push feature branch, verify CI, sync Truenas; live Ch25–27 still requires explicit disclosure approval |
| 2026-07-19 | Codex | Phase 0 delivery | in_progress | Root handoff refreshed as highest-priority Phase 0–5 authority; text integrity, Ruff, diff check, and repository hygiene pass | pending correction commit on `feature/narrative-production-closure` | Commit/push feature branch, verify remote hash and CI, sync distilled evidence/session summary to Truenas, then pause |

## Stop conditions and immediate next actions

Stop and report if the baseline cannot be trusted, project state conflicts with
this handoff, Production must change, safety tests must be weakened, non-narrative
work cannot be isolated, central modules would grow materially, two rewrites fail,
or positive samples are missing while someone is about to claim literary uplift.

Immediate sequence: finalize the Phase 0 corrective diff; rerun standards/spec
review; commit and push only the feature branch; verify CI; sync distilled evidence
and session state to Truenas; then stop for (1) explicit Ch25–27 external disclosure
approval, (2) 3–5 user-positive samples, and (3) separate Phase 1 authorization.
<!-- AGENT_NOTES_END -->

## Mandatory Update Rule

Refresh canonical PROJECT_HANDOFF.md after branch, commit, file, directory, schema, interface,
related-repository, or material project-state changes, and before final handoff.
