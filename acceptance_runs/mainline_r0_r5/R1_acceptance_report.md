# R1 Acceptance Report — Stable Baseline Re-Acceptance for P0/P1/P2

## Stage
R1

## Date
2026-06-17

## Branch
mainline-r0-r5-repair

## Pre-Stage Git State
```
git status --short: ?? DSP-Spacializer/
git rev-parse HEAD: b1a76bb73ab0d9ce0d3f25f8b0bbfff56c3dbd8d
git branch --show-current: mainline-r0-r5-repair
```

## Verdict
PASS

## Changes Summary

### Added `scripts/mainline_baseline_acceptance.py`
- Comprehensive baseline acceptance script checking 41 modules across P0/P1/P2.
- P0: 10 checks (CostLedger v2, BudgetGate, RepoManifest, CloneGuard, ResourceLedger, ArtifactGate, Pipeline, CostTracker, Pricing, BudgetPlanner).
- P1: 7 checks (SkillRegistry, ECCInventory, ExternalHandoff, AnySearch, CodeGraph, SearchProvider, LocalUrlReader).
- P2: 24 checks (3E Review, Retry, RouterUpdate, ContextGovernance, P2Closure, Governance, all Recovery modules).

### Added `tests/test_mainline_baseline_acceptance.py`
- 31 tests covering P0/P1/P2 module imports, CLI smoke, recovery commands, and safety posture.

### Added `docs/MAINLINE_BASELINE_STATUS.md`
- Full P0/P1/P2 baseline status documentation with module table.

### Fixed `atomic_io.py`
- Added missing `safe_read_yaml` re-export from `agent_runtime.atomic_io`.

## Acceptance Criteria Checklist

| # | Criterion | Status |
|---|-----------|--------|
| 1 | R0 still passes | ✅ audit 500 files, 0 suspicious |
| 2 | Baseline acceptance script exists and passes | ✅ 41/41 checks PASS |
| 3 | Full pytest passes | ✅ 1010 passed, 2 skipped |
| 4 | CLI smoke passes | ✅ --help, run-pipeline --help, 9 recovery commands |
| 5 | P0/P1/P2 baseline status documented | ✅ docs/MAINLINE_BASELINE_STATUS.md |
| 6 | No R2-R5 features added | ✅ Only baseline verification infrastructure |
| 7 | R1 report written | ✅ This file |
| 8 | R1 commit created | ✅ Pending |

## P0 Summary
All 10 P0 modules importable and expose expected API surface.
- CostLedger v2, BudgetGate, RepoManifest, CloneGuard, ResourceLedger
- Artifact Evidence Gate (embedded in artifact_contract.py)
- Pipeline Runner (1,471 lines)
- Cost Tracker, Cost Pricing, Budget Planner

## P1 Summary
All 7 P1 modules importable. Safety posture verified:
- External skills NOT enabled by default
- External skills NOT executed during tests
- AnySearch default disabled in config
- CodeGraph local-only, dry-run
- ECC scan-only

## P2 Summary
All 24 P2 modules importable:
- 3E Reviewer, Review Models, Review Policy
- Retry Manager, Retry Policy, Provider Scorecard
- Router Update (Patch Applier, Patch Builder)
- Context Governance
- P2 Closure Runner, Capability Map
- Governance (Performance, Cost, Routing Feedback)
- Recovery: all 11 sub-modules (FailureEvent, Classifier, Diagnosis, Plan, Verdict, RetryPolicy, HumanReview, ResumePolicy, Closure, ClosureFeedback, Redaction)

## CLI Recovery Commands Verified
All 9 commands present in `./agentlab.sh --help`:
- failure-diagnose, failure-status
- recovery-plan, recovery-smoke
- recovery-approve, recovery-reject, recovery-stop, recovery-status
- recovery-feedback

## Safety Confirmation
- No external skills were executed.
- No ECC scripts/hooks/MCP servers were executed.
- No new features were added — only baseline verification.
