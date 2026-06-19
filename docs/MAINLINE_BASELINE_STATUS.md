# Mainline Baseline Status

Last verified: 2026-06-17 (R1 stage of mainline-r0-r5-repair)

## P0 — Core Infrastructure

| Module | Status | Key File(s) |
|--------|--------|-------------|
| CostLedger v2 | ✅ Active | `agent_runtime/costing/ledger.py` |
| Cost Pricing | ✅ Active | `agent_runtime/costing/pricing.py` |
| BudgetGate | ✅ Active | `agent_runtime/costing/budget.py` |
| Budget Planner | ✅ Active | `agent_runtime/budget_planner.py` |
| RepoManifest | ✅ Active | `agent_runtime/ingestion/repo_manifest.py` |
| CloneGuard | ✅ Active | `agent_runtime/ingestion/clone_guard.py` |
| ResourceLedger | ✅ Active | `agent_runtime/ingestion/resource_ledger.py` |
| Artifact Evidence Gate | ✅ Active | `agent_runtime/artifact_contract.py` |
| Pipeline Runner | ✅ Active | `agent_runtime/pipeline_runner.py` |
| Cost Tracker | ✅ Active | `agent_runtime/cost_tracker.py` |

## P1 — External Integration

| Module | Status | Key File(s) | Safety |
|--------|--------|-------------|--------|
| External Skill Registry | ✅ Active | `agent_runtime/skills/registry.py` | Disabled by default |
| ECC Inventory | ✅ Active | `agent_runtime/external_agents/ecc_inventory.py` | Scan-only |
| External Agent Handoff | ✅ Active | `agent_runtime/external_agents/handoff.py` | Approval-gated |
| AnySearch Adapter | ✅ Active | `agent_runtime/search/anysearch_adapter.py` | Default disabled |
| CodeGraph Adapter | ✅ Active | `agent_runtime/ingestion/repo_indexers/codegraph_adapter.py` | Local/dry-run only |
| Search Provider Base | ✅ Active | `agent_runtime/search/provider.py` | Abstract |
| Local URL Reader | ✅ Active | `agent_runtime/search/local_url_reader.py` | Local-only |

**P1 Safety Posture:**
- External skills are NOT enabled by default.
- External skills are NOT executed during tests.
- AnySearch defaults to disabled in config.
- CodeGraph is local-only, dry-run, approval-gated.
- ECC inventory is scan-only (no script execution).

## P2 — Review, Retry, Governance, Recovery

### P2-B: Review
| Module | Status | Key File(s) |
|--------|--------|-------------|
| 3E Reviewer | ✅ Active | `agent_runtime/review/three_e_reviewer.py` |
| Review Models | ✅ Active | `agent_runtime/review/models.py` |
| Review Policy | ✅ Active | `agent_runtime/review/policy.py` |

### P2-C: Retry
| Module | Status | Key File(s) |
|--------|--------|-------------|
| Retry Manager | ✅ Active | `agent_runtime/retry/retry_manager.py` |
| Retry Policy | ✅ Active | `agent_runtime/retry/policy.py` |
| Provider Scorecard | ✅ Active | `agent_runtime/retry/scorecard.py` |

### P2-D: Router Update
| Module | Status | Key File(s) |
|--------|--------|-------------|
| Patch Applier | ✅ Active | `agent_runtime/router_update/patch_applier.py` |
| Patch Builder | ✅ Active | `agent_runtime/router_update/patch_builder.py` |

### P2-G: Context Governance
| Module | Status | Key File(s) |
|--------|--------|-------------|
| Context Pack | ✅ Active | `agent_runtime/context_governance/context_pack.py` |

### P2-F: P2 Closure
| Module | Status | Key File(s) |
|--------|--------|-------------|
| Closure Runner | ✅ Active | `agent_runtime/p2_closure/closure_runner.py` |
| Capability Map | ✅ Active | `agent_runtime/p2_closure/capability_map.py` |

### P2 Shared: Governance
| Module | Status | Key File(s) |
|--------|--------|-------------|
| Performance | ✅ Active | `agent_runtime/governance/performance.py` |
| Cost | ✅ Active | `agent_runtime/governance/cost.py` |
| Routing Feedback | ✅ Active | `agent_runtime/governance/routing_feedback.py` |

### P2-I/K: Failure Recovery
| Module | Status | Key File(s) |
|--------|--------|-------------|
| Failure Event | ✅ Active | `agent_runtime/recovery/failure_event.py` |
| Failure Classifier | ✅ Active | `agent_runtime/recovery/failure_classifier.py` |
| Diagnosis | ✅ Active | `agent_runtime/recovery/diagnosis.py` |
| Recovery Plan | ✅ Active | `agent_runtime/recovery/recovery_plan.py` |
| Recovery Verdict | ✅ Active | `agent_runtime/recovery/verdict.py` |
| Retry Policy | ✅ Active | `agent_runtime/recovery/retry_policy.py` |
| Human Review | ✅ Active | `agent_runtime/recovery/human_review.py` |
| Resume Policy | ✅ Active | `agent_runtime/recovery/resume_policy.py` |
| Closure | ✅ Active | `agent_runtime/recovery/closure.py` |
| Closure Feedback | ✅ Active | `agent_runtime/recovery/closure_feedback.py` |
| Context Redaction | ✅ Active | `agent_runtime/recovery/redaction.py` |

## CLI Recovery Commands

All 9 P2 recovery commands are registered and accessible:

- `failure-diagnose`
- `failure-status`
- `recovery-plan`
- `recovery-smoke`
- `recovery-approve`
- `recovery-reject`
- `recovery-stop`
- `recovery-status`
- `recovery-feedback`


## S7-S8 — Long Project Orchestrator and Executor Connector Loop

Last verified: 2026-06-19 (S7/S8 local repair)

| Stage | Status | Key File(s) | Acceptance |
|-------|--------|-------------|------------|
| S7 Long Project Orchestrator | ✅ Active | `agent_runtime/program_manager/*` | `acceptance_runs/s7_long_project_orchestrator/S7_LONG_PROJECT_ORCHESTRATOR_REPORT.md` |
| S8 Executor Connector Loop | ✅ Active | `agent_runtime/executors/task_packet.py`, `agent_runtime/executors/phase_connector.py` | `acceptance_runs/s8_executor_connector/S8_EXECUTOR_CONNECTOR_REPORT.md` |

**S7/S8 Safety Posture:**
- S7 is deterministic and planning-only: no LLM calls, no network access, no external executor dispatch.
- S7 project brain writes roadmap, milestone graph, phase plans, phase summaries, snapshots, acceptance history, and next actions.
- S8 converts S7 phase plans into task packets and connector contracts.
- S8 executor results are evidence only until S7 phase acceptance passes.
- External executors remain approval-gated and are not auto-dispatched.
- Verification: `62 passed`; text integrity suspicious files: `0`; S7→S8 CLI smoke produced project brain, task packet, ingested evidence, and phase acceptance artifacts.

## M-Series — Product Mainline Repair

Last verified: 2026-06-20 (M0/M1-1 local repair)

| Stage | Status | Key File(s) | Acceptance |
|-------|--------|-------------|------------|
| M0 Preflight / Baseline Lock | ✅ Active | `docs/M_SERIES_SCOPE.md` | `acceptance_runs/m0_preflight/M0_PREFLIGHT_REPORT.md` |
| M1-1 External Project Registry + Capability Mapping | ✅ Active | `agent_runtime/external_projects/*`, `config/external_project_*.yml` | `acceptance_runs/m1_external_projects/M1_EXTERNAL_PROJECT_REGISTRY_REPORT.md` |

**M-Series Safety Posture:**
- Pre-M-series backup is tagged as `m-series-pre-m0-backup`.
- M0 freezes scope: M1 is governance, M2 is operator control, M3 is business/asset/revenue loops.
- M1-1 is registry-only: no clone, vendor, install, import, launch, or execution of external project code.
- All external projects are disabled by default and require approval before any future adapter work.
- Network and shell permissions are false in M1-1 registry records.

**Next recommended M-series stage:**
- M1-2 Mission Compiler v2.
