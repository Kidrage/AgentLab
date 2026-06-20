# Text Integrity Audit Report

## Summary

- Total files scanned: 796
- Suspicious files: 12
- Suspicious Python files: 0
- Suspicious YAML files: 0

## Suspicious Files

| Path | Lines | Max Line | Size | AST/YAML | Issues |
|------|-------|----------|------|----------|--------|
| docs/archive/historical_runs/executor_runs/p2_router_demo/external_execution_handoff.md | 59 | 218 | 1686 |  | contains local absolute /Users path |
| docs/archive/historical_runs/executor_runs/p2_router_handoff/external_execution_handoff.md | 59 | 218 | 1689 |  | contains local absolute /Users path |
| docs/archive/historical_runs/executor_runs/p2_router_mock/review/review_report.md | 36 | 122 | 1142 |  | contains local absolute /Users path |
| docs/archive/historical_runs/retry_runs/p2_retry_fail_then_pass/attempt_001/review/retry_handoff.md | 30 | 141 | 1131 |  | contains local absolute /Users path |
| docs/archive/historical_runs/retry_runs/p2_retry_fail_then_pass/attempt_001/review/review_report.md | 36 | 108 | 1258 |  | contains local absolute /Users path |
| docs/archive/historical_runs/retry_runs/p2_retry_fail_then_pass/attempt_002/review/review_report.md | 36 | 108 | 1031 |  | contains local absolute /Users path |
| docs/archive/historical_runs/retry_runs/p2_retry_fail_until_max/attempt_001/review/retry_handoff.md | 30 | 141 | 1131 |  | contains local absolute /Users path |
| docs/archive/historical_runs/retry_runs/p2_retry_fail_until_max/attempt_001/review/review_report.md | 36 | 108 | 1258 |  | contains local absolute /Users path |
| docs/archive/historical_runs/retry_runs/p2_retry_fail_until_max/attempt_002/review/retry_handoff.md | 30 | 141 | 1131 |  | contains local absolute /Users path |
| docs/archive/historical_runs/retry_runs/p2_retry_fail_until_max/attempt_002/review/review_report.md | 36 | 108 | 1258 |  | contains local absolute /Users path |
| docs/archive/historical_runs/retry_runs/p2_retry_pass_first/attempt_001/review/review_report.md | 36 | 104 | 1023 |  | contains local absolute /Users path |
| docs/archive/historical_runs/review_runs/p2_review_p1_closure/review_report.md | 36 | 90 | 1008 |  | contains local absolute /Users path |

## Top 30 Files by Max Line Length

| Path | Lines | Max Line | Size | Status |
|------|-------|----------|------|--------|
| README.md | 700 | 781 | 37132 | OK |
| agent_runtime/context_governance/packers/history_packer.py | 11 | 533 | 1186 | OK |
| agent_runtime/context_governance/packers/tool_output_packer.py | 11 | 466 | 1109 | OK |
| acceptance_runs/m1_project_brain/M1_4_ACCEPTANCE_REPORT.md | 38 | 460 | 2369 | OK |
| acceptance_runs/m1_recovery/M1_RECOVERY_REPORT.md | 56 | 428 | 2539 | OK |
| agent_runtime/context_governance/packers/data_context_packer.py | 11 | 421 | 1074 | OK |
| agent_runtime/context_governance/packers/crawl_context_packer.py | 11 | 418 | 1132 | OK |
| agent_runtime/context_governance/packers/log_context_packer.py | 11 | 398 | 1042 | OK |
| agent_runtime/context_governance/packers/abstract_reasoning_packer.py | 11 | 396 | 954 | OK |
| acceptance_runs/m1_executor_connector_loop/M1_5_ACCEPTANCE_REPORT.md | 34 | 390 | 2514 | OK |
| agent_runtime/context_governance/packers/web_context_packer.py | 11 | 389 | 1023 | OK |
| agent_runtime/context_governance/packers/image_context_packer.py | 11 | 367 | 1084 | OK |
| docs/AGENTLAB_CODEX_FULL_DRIVER_OPERATION_CHAIN_SPEC.md | 1397 | 365 | 29633 | OK |
| agent_runtime/run_task.py | 5625 | 361 | 245837 | OK |
| acceptance_runs/stabilization/S0_STABILIZATION_REPORT.md | 134 | 338 | 5803 | OK |
| docs/README.en-US.md | 314 | 330 | 14171 | OK |
| acceptance_runs/p2_closure/P2_F_CLOSURE_REPORT.md | 212 | 329 | 8302 | OK |
| agent_runtime/capabilities/registry.py | 80 | 325 | 6618 | OK |
| docs/CLOSURE_MVP_REPORT.md | 81 | 324 | 4442 | OK |
| acceptance_runs/s0_remote_raw_repair/report.md | 140 | 319 | 6083 | OK |
| docs/SKILL_DISTILLATION.md | 32 | 302 | 1262 | OK |
| agent_runtime/artifact_contract.py | 701 | 300 | 28249 | OK |
| tests/test_external_skill_artifact_paths.py | 42 | 300 | 1977 | OK |
| acceptance_runs/m0_preflight/M0_PREFLIGHT_REPORT.md | 74 | 299 | 2995 | OK |
| docs/S11_OPS_CONSOLE.md | 54 | 296 | 1497 | OK |
| docs/EXTERNAL_AGENT_HANDOFF.md | 134 | 293 | 4842 | OK |
| docs/SKILL_VAULT.md | 116 | 290 | 4011 | OK |
| docs/S9_VISION_AUDIO_DOCUMENT_CONTRACTS.md | 75 | 288 | 1528 | OK |
| agent_runtime/mcp_server.py | 493 | 284 | 27787 | OK |
| scripts/p2_router_update_check.py | 113 | 283 | 4420 | OK |
