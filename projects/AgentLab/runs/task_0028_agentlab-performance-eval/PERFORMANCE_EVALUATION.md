# AgentLab Performance Evaluation

## Summary

- Score: **100.0/100 (A)**
- Route: `evaluation_task`
- Model tokens: `0`
- Artifact pass rate: `1.0`

## Component Scores

| Component | Points |
|---|---:|
| routing | 30.0 |
| configuration | 20.0 |
| lifecycle | 20.0 |
| analysis_skip | 10.0 |
| commands | 20.0 |

## Routing Cases

| Case | Expected | Actual | Pass |
|---|---|---|---|
| comprehensive_evaluation | evaluation_task | evaluation_task | True |
| small_fix | small_task | small_task | True |
| interface_change | large_or_risky_task | large_or_risky_task | True |
| external_research | research_sensitive_task | research_sensitive_task | True |
| large_architecture | large_or_risky_task | large_or_risky_task | True |
| performance_eval | evaluation_task | evaluation_task | True |

## Command Timings

| Command | Pass | Time ms |
|---|---:|---:|
| `python3 -m py_compile agent_runtime/task_router.py agent_runtime/lifecycle_graph.py` | True | 83.3 |
| `./agentlab.sh policy-status --project AgentLab` | True | 817.8 |

## Configuration

- Route issues: 0
- Profile issues: 0

## Interpretation

The optimized AgentLab now routes evaluation/performance requests to an analysis-only L3 path, skips Coder for pure assessment work, and leaves a complete auditable task record.
