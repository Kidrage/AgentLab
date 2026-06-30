# Project Handoff

> Deterministically generated repository/project memory for cross-agent handoff.
> Update after every material project change and before final reporting.

## Repository Identity

- Repository ID: `AgentLab-de62d90289e0`
- Working root: `/Users/saintpeter/Desktop/AgentLab`
- Git repository: `true`
- Generated at: `2026-06-30T06:38:57.381420+00:00`

## Current State

- Branch: `main`
- HEAD: `86a0625`
- Indexed paths: 1461
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
- Fast reporting source: this root file plus the shared `memory/repositories/` mirror.

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
| `agent_runtime` | 454 |
| `tests` | 391 |
| `docs` | 203 |
| `acceptance_runs` | 176 |
| `config` | 137 |
| `docs/archive` | 126 |
| `tests/fixtures` | 94 |
| `agent_templates` | 25 |
| `scripts` | 22 |
| `agent_runtime/program_manager` | 21 |
| `agent_runtime/recovery` | 21 |
| `agent_runtime/workers` | 21 |
| `acceptance_runs/mainline_r0_r5` | 20 |
| `agent_runtime/context_governance` | 20 |
| `.` | 17 |
| `agent_runtime/executors` | 17 |
| `acceptance_runs/m2_operator_demo` | 16 |
| `agent_runtime/capabilities` | 15 |
| `agent_runtime/ingestion` | 15 |
| `acceptance_runs/p2_closure` | 12 |
| `acceptance_runs/s10_generalization_eval` | 12 |
| `agent_runtime/execution_economy` | 12 |
| `agent_runtime/goals` | 12 |
| `agent_runtime/brain` | 11 |
| `agent_runtime/capability_broker` | 11 |
| `agent_runtime/costs` | 11 |
| `agent_runtime/skills` | 11 |
| `acceptance_runs/e2e_minimal_task` | 10 |
| `acceptance_runs/p2_provider_governance` | 10 |
| `acceptance_runs/s0_remote_raw_repair` | 10 |
| `agent_runtime/config_center` | 10 |
| `agent_runtime/intelligence` | 10 |
| `agent_runtime/router_update` | 10 |
| `agent_templates/codex_full_driver` | 10 |
| `acceptance_runs/s12_productization` | 9 |
| `agent_runtime/control_panel` | 9 |
| `agent_runtime/routing` | 9 |
| `examples` | 9 |
| `acceptance_runs/p1_closure` | 8 |
| `agent_runtime/assistant` | 8 |

## Data and File Structure

### Categories

- code: 792 files, 4353968 bytes
- literature: 299 files, 1200327 bytes
- other: 10 files, 74969 bytes
- structured_data: 360 files, 1223294 bytes

### Common Extensions

- `.py`: 786
- `.yml`: 344
- `.md`: 260
- `.txt`: 39
- `.json`: 13
- `[no extension]`: 5
- `.sh`: 5
- `.diff`: 1
- `.ini`: 1
- `.jsonl`: 1
- `.log`: 1
- `.csv`: 1
- `.toml`: 1
- `.js`: 1
- `.html`: 1
- `.css`: 1

### Schema / Model / Interface Candidates

- `OPERATING_MODEL.md`
- `acceptance_runs/ccs_migration_safety/CCS_MIGRATION_SAFETY_REPORT.md`
- `acceptance_runs/hotfix_cli_schema_v4_routing/HOTFIX_CLI_SCHEMA_V4_ROUTING_REPORT.md`
- `acceptance_runs/m2_operator_demo/migration_doctor_summary.yml`
- `acceptance_runs/m2_worker_invocation_contracts/classified_cli_failures.yml`
- `acceptance_runs/m2_worker_invocation_contracts/invalid_templates.yml`
- `acceptance_runs/m2_worker_invocation_contracts/worker_invocation_contract_report.md`
- `acceptance_runs/m2_worker_invocation_contracts/worker_invocation_contract_report.yml`
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
- `agent_runtime/config_center/schema.py`
- `agent_runtime/context_governance/schemas.py`
- `agent_runtime/costs/model_cost_profile.py`
- `agent_runtime/executors/connector_contract.py`
- `agent_runtime/executors/models.py`
- `agent_runtime/external_projects/adapter_contract.py`
- `agent_runtime/external_projects/models.py`
- `agent_runtime/goals/action_schema.py`
- `agent_runtime/goals/models.py`
- `agent_runtime/governance/models.py`
- `agent_runtime/ingestion/ingestion_contract.py`
- `agent_runtime/langgraph_schema.py`
- `agent_runtime/migration_doctor.py`
- `agent_runtime/model_resolver.py`
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
- `agent_templates/codex_full_driver/04_INTERFACE_MAPPER.md`
- `agent_templates/interface_mapper.md`
- `agentlab_tui/models.py`
- `config/agent_model_profiles.yml`
- `config/capability_schema.yml`
- `config/config_ui_schema.yml`
- `config/hermes_brain_model_groups.yml`
- `config/migration_profile.yml`
- `config/model_catalog.yml`
- `config/model_cost_profiles.yml`
- `config/model_pricing.yml`
- `config/model_providers.yml`
- `config/project_artifact_contracts.yml`
- `config/worker_invocation_contracts.yml`
- `docs/AGENTLAB_COMPANY_MODEL.md`
- `docs/AGENT_PACKET_CONTRACT.md`
- `docs/CLI_AGENT_ROUTING_SCHEMA_V4.md`
- `docs/S9_VISION_AUDIO_DOCUMENT_CONTRACTS.md`
- `docs/SERVICE_FACTORY_MODEL.md`
- `scripts/check_cli_schema_v4_routing.py`
- `tests/test_cli_contract.py`
- `tests/test_m1_ingestion_contracts.py`
- `tests/test_m2_10_tui_models.py`
- `tests/test_m2_12_operator_demo_migration_classification.py`
- `tests/test_m2_9_assistant_models.py`
- `tests/test_m2_capability_schema.py`
- `tests/test_m2_route_decision_schema.py`
- `tests/test_m2_worker_card_schema.py`
- `tests/test_m2_worker_invocation_contract.py`
- `tests/test_mcp_server_contract.py`
- `tests/test_migration_backup.py`
- `tests/test_skill_vault_migration.py`

## Key Entrypoints and Guides

- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- `agent_runtime/README.md`
- `agent_runtime/requirements.txt`
- `config/README.md`
- `docs/README.en-US.md`
- `docs/README.zh-CN.md`
- `projects/README.md`
- `requirements.txt`
- `tests/fixtures/p1_closure/fake_ecc/AGENTS.md`
- `tests/fixtures/p1_closure/fake_repo/pyproject.toml`
- `web_ui/README.md`

## Change History

- `86a0625 2026-06-30 Fix README public doc gates`
- `0a8c298 2026-06-30 Add project fact state machine`
- `7367a9a 2026-06-29 Refresh bilingual README for M-series baseline and Jun 29 state`
- `9c65d95 2026-06-29 Add media generation routing layer`
- `2e8ff83 2026-06-29 Add root project handoff generation`
- `d8b958b 2026-06-29 Add project handoff for AgentLab repair`
- `e3fb07e 2026-06-29 Extract worker CLI commands`
- `0c5ed2e 2026-06-29 Extract runtime hygiene CLI commands`
- `9bcc6b9 2026-06-29 Extract capability contract CLI commands`
- `7b084ec 2026-06-29 Extract routing CLI commands`
- `8c1e97a 2026-06-29 Extract external project CLI commands`
- `166f8e3 2026-06-29 Extract protocol CLI commands`
- `d8568de 2026-06-29 Extract role capability CLI commands`
- `98a675c 2026-06-29 Start cleanup with route catalog and config inventory`
- `4de7dec 2026-06-29 Add domain-aware creative writing mission routing`
- `14e6168 2026-06-28 Allow agy Coder role in protocol doctor enforcement check`
- `3fa3434 2026-06-28 Register agy capabilities and Coder role in shared agent directory`
- `331ab6f 2026-06-28 Sync role-assignment and fallback tests to new Coder bindings`
- `0cfa8e0 2026-06-28 Fix hardcoded absolute paths in Crown of Ash scripts`
- `e1d5172 2026-06-28 Reassign role bindings: agy as Coder, expand Hermes model groups, update worker contracts`

## Current Changes

- `## main...origin/main`
- ` M .gitignore`
- ` M AGENTS.md`
- `D  "_shared/novel-moon-in-seal/audio-drama/001-\347\254\254\344\270\200\347\253\240-\344\270\200\346\236\232\345\201\217\347\203\253\347\232\204\346\227\247\347\216\211.mp3"`
- `D  _shared/novel-moon-in-seal/project_brain/acceptance_history.yml`
- `D  _shared/novel-moon-in-seal/project_brain/architecture_state.yml`
- `D  _shared/novel-moon-in-seal/project_brain/decision_log.yml`
- `D  _shared/novel-moon-in-seal/project_brain/known_risks.yml`
- `D  _shared/novel-moon-in-seal/project_brain/memory_index.yml`
- `D  _shared/novel-moon-in-seal/project_brain/next_actions.yml`
- `D  _shared/novel-moon-in-seal/project_brain/product_vision.md`
- `D  _shared/novel-moon-in-seal/project_brain/roadmap.yml`
- `D  _shared/novel-moon-in-seal/project_brain/unresolved_questions.yml`
- `D  "_shared/novel-moon-in-seal/project_brain/\345\217\221\345\261\225\350\267\257\347\272\277.md"`
- ` M agent_runtime/context_governance/packers/narrative_packer.py`
- ` M agent_runtime/program_manager/phase_planner.py`
- ` M agent_runtime/project_artifact_steward.py`
- ` M agent_runtime/protocols/enforcement.py`
- ` M config/long_project_governance.yml`
- `D  config/worker_performance_ledger.yml`
- ` M projects/README.md`
- ` M tests/test_long_project_governance.py`
- ` M tests/test_p2g_context_packers.py`
- ` M tests/test_project_artifact_steward.py`
- ` M tests/test_protocol_enforcement.py`
- `?? config/content_project_governance.yml`

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
- `AGENTLAB_M_SERIES_MAINLINE_HANDOFF_CACHE_AWARE.md`
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
- `acceptance_runs/ccs_migration_safety/CCS_MIGRATION_SAFETY_REPORT.md`
- `acceptance_runs/e2e_minimal_task/final_delivery_report.md`
- `acceptance_runs/e2e_minimal_task/input_task.md`
- `acceptance_runs/e2e_minimal_task/revision_packet.md`
- `acceptance_runs/hotfix_cli_binary_aliases/CLI_COMMAND_INVENTORY.md`
- `acceptance_runs/hotfix_cli_binary_aliases/HOTFIX_CLI_BINARY_ALIASES_REPORT.md`
- `acceptance_runs/hotfix_cli_schema_v4_routing/HOTFIX_CLI_SCHEMA_V4_ROUTING_REPORT.md`

### image

- None detected.

### audio

- None detected.

### video

- None detected.

### structured_data

- `.github/workflows/ci.yml`
- `acceptance_runs/e2e_minimal_task/check.yml`
- `acceptance_runs/e2e_minimal_task/init_task.yml`
- `acceptance_runs/e2e_minimal_task/provider_feedback.yml`
- `acceptance_runs/e2e_minimal_task/review_verdict.yml`
- `acceptance_runs/e2e_minimal_task/router_feedback.yml`
- `acceptance_runs/e2e_minimal_task/run_pipeline_dry_run.yml`
- `acceptance_runs/e2e_minimal_task/task_plan.yml`
- `acceptance_runs/m1_external_projects/external_project_risk_report.yml`
- `acceptance_runs/m1_generalization_demo/m1_demo_results.yml`
- `acceptance_runs/m2_operator_demo/approval_decision_card.yml`
- `acceptance_runs/m2_operator_demo/cost_estimate_and_ledger.yml`
- `acceptance_runs/m2_operator_demo/m2_operator_demo_summary.yml`
- `acceptance_runs/m2_operator_demo/migration_doctor_summary.yml`
- `acceptance_runs/m2_operator_demo/mock_executor_result.yml`
- `acceptance_runs/m2_operator_demo/phase_acceptance.yml`
- `acceptance_runs/m2_operator_demo/role_requirement_matrix_summary.yml`
- `acceptance_runs/m2_operator_demo/route_decision.yml`
- `acceptance_runs/m2_operator_demo/runtime_hygiene_summary.yml`
- `acceptance_runs/m2_operator_demo/timeline_excerpt.yml`

## Validation and Risks

- This inventory records paths and metadata, not semantic correctness.
- Binary/media payloads and secrets were not read.
- Validate current branch, tests, and interfaces before modifying files.

## Agent Notes

<!-- AGENT_NOTES_START -->
- User explicitly requested this file because existing handoff artifacts are too scattered and not usable enough as a project-level status dashboard.
- Shutdown is no longer part of the final objective.
- This handoff started as a hand-written root handoff and is now generated by `./agentlab.sh repository-handoff --repo <path> --write`.
- Implemented slice: `repository_handoff` treats `PROJECT_HANDOFF.md` as the root-visible canonical handoff and still writes `.agentlab/HandOff.md`, `agent_docs/HandOff.md`, and shared `memory/repositories/{repository_id}/HandOff.md`.
- Protocol/config/context updates are implemented: repository handoff policy, shared agent directory, agent collaboration config, workspace entry policy, shared protocol, driver protocol, agent runner context, CLI executor packets, and external task packets now point at the root-visible handoff.
- Verification passed for this slice: handoff/protocol tests, executor packet tests, CLI executor tests, three demo gates, and full pytest (`1906 passed, 2 skipped`).
- Pre-existing dirty file `agent_runtime/artifact_contract.py` broke full pytest by suppressing missing `repo_manifest.json` evidence. It was adjusted to preserve the fallback structure while still enforcing missing-manifest errors.
- Remaining before final completion: commit/push and GitHub Actions confirmation. No shutdown.
<!-- AGENT_NOTES_END -->

## Mandatory Update Rule

Refresh this Project Handoff after branch, commit, file, directory, schema, interface,
related-repository, or material project-state changes, and before final handoff.
