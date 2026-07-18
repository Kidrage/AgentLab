# Project Handoff

> Deterministically generated repository/project memory for cross-agent handoff.
> Update after every material project change and before final reporting.

## Repository Identity

- Repository ID: `AgentLab-de62d90289e0`
- Working root: `.`
- Repository name: `AgentLab`
- Git repository: `true`
- Generated at: `2026-07-18T13:07:22.096155+00:00`

## Current State

- Branch: `feature/agent-role-capacity-overhaul`
- HEAD: `2239ad7`
- Indexed paths: 1821
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
| `agent_runtime` | 519 |
| `tests` | 440 |
| `docs` | 307 |
| `acceptance_runs` | 297 |
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

- code: 899 files, 7217257 bytes
- literature: 391 files, 2090177 bytes
- other: 12 files, 74102 bytes
- structured_data: 519 files, 2090294 bytes

### Common Extensions

- `.py`: 886
- `.yml`: 499
- `.md`: 352
- `.txt`: 39
- `.json`: 15
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
- `715546c 2026-07-13 fix: close narrative heavy audit workflow`
- `2c0c7cc 2026-07-13 fix: stop retrying exhausted Agy quota`

## Current Changes

- `## feature/agent-role-capacity-overhaul`
- ` M AGENTS.md`
- ` M CLAUDE.md`
- ` M CLI_ROADMAP.md`
- ` M CONTEXT.md`
- ` M DRIVER_PROTOCOL.md`
- ` M OPERATING_MODEL.md`
- ` M PROJECT_HANDOFF.md`
- ` M README.md`
- ` M USAGE_PLAN.md`
- ` M _shared/AGENT_HANDOFF.md`
- ` M _shared/AGENT_PROTOCOL.md`
- ` M acceptance_runs/agentlab_capability_acceptance/current.yml`
- ` M acceptance_runs/agentlab_capability_acceptance/goal_completion_audit.yml`
- ` M acceptance_runs/agentlab_capability_acceptance/objective_requirement_audit.yml`
- ` M acceptance_runs/stabilization/text_integrity_audit.json`
- ` M acceptance_runs/stabilization/text_integrity_audit.md`
- ` D agent_runtime/AIDER_ADAPTER.md`
- ` M agent_runtime/README.md`
- ` M agent_runtime/agent_runner.py`
- ` D agent_runtime/agents_def.py`
- ` D agent_runtime/aider_adapter.py`
- ` M agent_runtime/api_continuation.py`
- ` M agent_runtime/artifact_contract.py`
- ` M agent_runtime/atomic_io.py`
- ` M agent_runtime/brain/media_generation_router.py`
- ` M agent_runtime/brain/mission_contract.py`
- ` M agent_runtime/brain_governor.py`
- ` M agent_runtime/capability_acceptance.py`
- ` M agent_runtime/cli/protocol.py`
- ` M agent_runtime/cli/routing.py`
- ` M agent_runtime/cli_executor.py`
- ` M agent_runtime/codex_artifact_validator.py`
- ` M agent_runtime/config_inventory.py`
- ` M agent_runtime/config_loader.py`
- ` M agent_runtime/daemon.py`
- ` M agent_runtime/execution_economy/__init__.py`
- ` M agent_runtime/execution_economy/activation_plan.py`
- ` M agent_runtime/execution_economy/marginal_utility_gate.py`
- ` M agent_runtime/execution_economy/renderer.py`
- ` D agent_runtime/execution_economy/role_coalescing.py`
- ` M agent_runtime/executors/task_packet.py`
- ` M agent_runtime/external_skills_cli.py`
- ` M agent_runtime/handoff_builder.py`
- ` M agent_runtime/lifecycle_graph.py`
- ` M agent_runtime/llm_provider.py`
- ` M agent_runtime/mcp_server.py`
- ` M agent_runtime/media_series_scaffold_audit.py`
- ` M agent_runtime/memory_writer.py`
- ` M agent_runtime/migration_doctor.py`
- ` M agent_runtime/narrative_eval.py`
- ` M agent_runtime/p2_closure/evidence.py`
- ` M agent_runtime/performance_evaluator.py`
- ` M agent_runtime/pipeline_runner.py`
- ` M agent_runtime/production_chain_audit.py`
- ` M agent_runtime/production_pack_registry.py`
- ` M agent_runtime/production_pack_role_session_request.py`
- ` M agent_runtime/production_packs.py`
- ` M agent_runtime/project_artifact_steward.py`
- ` M agent_runtime/project_ops/project_router.py`
- ` M agent_runtime/project_ops/repo_hygiene.py`
- ` M agent_runtime/repo_index_cli.py`
- ` M agent_runtime/repository_handoff.py`
- ` M agent_runtime/routing/route_catalog.py`
- ` M agent_runtime/routing/worker_router.py`
- ` M agent_runtime/run_task.py`
- ` M agent_runtime/schemas.py`
- ` M agent_runtime/search/policy.py`
- ` M agent_runtime/skill_evolution.py`
- ` M agent_runtime/skill_injector.py`
- ` M agent_runtime/skill_retriever.py`
- ` M agent_runtime/skill_usage.py`
- ` M agent_runtime/task_purge.py`
- ` M agent_runtime/ui_candidate_smoke.py`
- ` M agent_runtime/watchdog.py`
- ` M agent_runtime/workflow_plan.py`
- ` M agent_runtime/workspace_scanner.py`
- ` M agent_templates/archivist.md`
- ` D agent_templates/codex_full_driver/00_PRE_FLIGHT.md`
- ` D agent_templates/codex_full_driver/01_SUPERVISOR.md`
- ` D agent_templates/codex_full_driver/02_REPOSCOUT.md`
- ` D agent_templates/codex_full_driver/03_RESEARCHER.md`
- ` D agent_templates/codex_full_driver/04_INTERFACE_MAPPER.md`
- ` D agent_templates/codex_full_driver/05_CODEX_PROMPT_GENERATOR.md`
- ` D agent_templates/codex_full_driver/06_CODER.md`
- ` D agent_templates/codex_full_driver/07_TESTER_AUDITOR.md`
- ` D agent_templates/codex_full_driver/08_ARCHIVIST.md`
- ` D agent_templates/codex_full_driver/09_HANDOFF.md`
- ` D agent_templates/doc_manager.md`
- ` D agent_templates/skill_distiller.md`
- ` M agent_templates/tester_auditor.md`
- ` M config/README.md`
- ` M config/agent_collaboration.yml`
- ` M config/agent_registry.yml`
- ` M config/domain_route_packs.yml`
- ` M config/execution_modes.yml`
- ` M config/harness_policy.yml`
- ` M config/media_generation_backends.yml`
- ` M config/memory_policy.yml`
- ` M config/model_pricing.yml`
- ` M config/model_providers.yml`
- ` M config/production_packs.yml`
- ` M config/repository_handoff_policy.yml`
- ` M config/repository_hygiene.yml`
- ` M config/routing_rules.yml`
- ` M config/shared_agent_directory.yml`
- ` M config/skill_injection_policy.yml`
- ` M config/workspace_entry_policy.yml`
- ` D docs/AGENTLAB_250_GEMINI_ROUGH_WORKER_PLAN.md`
- ` M docs/AGENTLAB_CAPABILITY_ACCEPTANCE_MATRIX.md`
- ` D docs/AGENTLAB_CODEX_FULL_DRIVER_OPERATION_CHAIN_SPEC.md`
- ` M docs/AGENTLAB_CORP_AND_COLLABORATION_PROTOCOL.md`
- ` M docs/AGENTLAB_OPERATING_LOGIC.zh-CN.md`
- ` M docs/AGENTLAB_PRUNING_REPORT_20260718.md`
- ` M docs/AGENTLAB_SKILL_FEEDBACK_ROADMAP.md`
- ` M docs/ANYSEARCH_INTEGRATION.md`
- ` D docs/CLOSURE_MVP_REPORT.md`
- ` M docs/CODEGRAPH_INTEGRATION.md`
- ` M docs/CURRENT_VERSION_CAPABILITIES.en-US.md`
- ` M docs/CURRENT_VERSION_CAPABILITIES.zh-CN.md`
- ` D docs/M2_REPAIR_PHASE_SUMMARY.md`
- ` M docs/PROJECT_ARTIFACT_STEWARD.md`
- ` M docs/README.en-US.md`
- ` M docs/README.zh-CN.md`
- ` M docs/REPOSITORY_DIRECTORY_CONSTITUTION.md`
- ` D docs/V1_STABLE_INTERNAL_CLOSED_LOOP_PLAN.md`
- `RM skills/active/skill_agentlab_narrative_chapter_writer_lite/usage_ledger.yml -> docs/archive/skill_usage_legacy_20260718/narrative-chapter-writer-lite_usage_ledger.yml`
- `R  skills/active/skill_20260703174334298047_story-long-write/usage_ledger.yml -> docs/archive/skill_usage_legacy_20260718/story-long-write_usage_ledger.yml`
- ` M pytest.ini`
- ` D scripts/reader_server.py`
- ` D scripts/write_chapters.py`
- ` M tests/test_acceptance_docs_consistency.py`
- ` M tests/test_agent_role_chain_audit.py`
- ` M tests/test_agent_runner_cli_integration.py`
- ` M tests/test_artifact_task_protocol.py`
- ` M tests/test_capability_acceptance.py`
- ` M tests/test_cleanup_refactor_invariants.py`
- ` M tests/test_daemon_mvp.py`
- ` M tests/test_execution_config_consolidation.py`
- ` M tests/test_external_skill_artifact_paths.py`
- ` M tests/test_external_skill_cli.py`
- ` M tests/test_external_skill_full_closure.py`
- ` M tests/test_external_skill_importer_live.py`
- ` M tests/test_external_skill_mcp_readonly.py`
- ` M tests/test_feedback_realtime_watchdog.py`
- ` M tests/test_handoff_builder.py`
- ` M tests/test_high_risk_skill_approval.py`
- ` M tests/test_m1_mission_compiler_v2.py`
- ` M tests/test_m1_project_init_cli.py`
- ` M tests/test_m2_activation_plan_cli.py`
- ` M tests/test_m2_role_assignment_router.py`
- ` M tests/test_m2_worker_governance.py`
- ` M tests/test_observer_lifecycle.py`
- ` M tests/test_production_chain_audit.py`
- ` M tests/test_production_pack_registry.py`
- ` M tests/test_production_pack_role_session_request.py`
- ` M tests/test_project_artifact_steward.py`
- ` M tests/test_protocol_enforcement.py`
- ` M tests/test_repo_hygiene.py`
- ` M tests/test_repository_handoff.py`
- ` M tests/test_shared_agent_protocol.py`
- ` M tests/test_skill_lifecycle.py`
- ` M tests/test_skill_retrieval_injection.py`
- ` M tests/test_task1_6_full_system_closure.py`
- ` M tests/test_ui_candidate_smoke.py`
- ` M tests/test_visual_acceptance_workflow.py`
- ` M tests/test_workflow_plan_routing.py`
- ` M web_ui/agent_status.sample.json`
- ` M web_ui/app.js`
- ` M web_ui/index.html`
- ` M web_ui/server.py`
- `?? docs/TEST_SUITE_GOVERNANCE.md`
- `?? docs/archive/acceptance_docs_legacy_20260718/`
- `?? docs/archive/codex_full_driver_legacy_20260718/`
- `?? docs/archive/current_capabilities_legacy_20260718/`
- `?? docs/archive/legacy_plans_reports_20260718/`
- `?? docs/archive/legacy_production_scripts_20260718/`
- `?? docs/archive/readme_legacy_20260718/`
- `?? docs/archive/retired_agent_templates_legacy_20260718/`
- `?? docs/archive/retired_runtime_adapters_legacy_20260718/`
- `?? docs/archive/root_agent_guides_legacy_20260718/`
- `?? docs/archive/skill_usage_legacy_20260718/README.md`

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
# AgentLab pruning closure

- Date: `2026-07-18`
- Branch: `feature/agent-role-capacity-overhaul`
- Scope: route/model/shell authority consolidation, artifact and handoff placement, legacy absorption, test governance, and performance repair.
- Canonical report: `docs/AGENTLAB_PRUNING_REPORT_20260718.md`.
- Full local regression: `2736 passed, 2 skipped, 11 warnings in 208.35s`.
- Model registry doctor: 135 profiles, 0 issues.
- Protocol doctor: 108 checks, 0 failed.
- Repository hygiene: 0 hard violations, 0 warnings; text integrity: 1425 files, 0 suspicious.
- Full CLI native capabilities may be used inside one bounded AgentLab role-session. Cross-lifecycle role coalescing remains forbidden.
- Retired coalescing, full-driver, project-specific production scripts, old prompts, and stale reports are archive-only evidence under `docs/archive/`.
- All AgentLab production is paused/stopped. No local AgentLab production controller, Writer, heavy-audit, narrative-eval, or trusted-runner process was active at final inspection.
- Historical Crown job state and candidate artifacts remain durable but are not active execution authority. Resumption requires a new explicit instruction and a fresh status/preflight check.
- The 250 workspace was intentionally skipped; no remote configuration or production sync was performed.
<!-- AGENT_NOTES_END -->

## Mandatory Update Rule

Refresh canonical PROJECT_HANDOFF.md after branch, commit, file, directory, schema, interface,
related-repository, or material project-state changes, and before final handoff.
