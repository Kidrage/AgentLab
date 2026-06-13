# P2-F Closure Workflow

## What P2-F Is

P2-F closes the loop between external/self task delivery, 3E review, retry/revision planning, provider governance feedback, and router update recommendations.

After a task delivery is submitted, P2-F orchestrates:

```
task delivery
  ↓
3E Review (Explore / Examine / Enhance)
  ↓
Review Verdict: accepted | needs_revision | rejected | unsafe
  ↓
(if not accepted) → Revision Packet with fix list and acceptance criteria
  ↓
Provider Governance Feedback: quality scores, retry recommendation, governance classification
  ↓
Router Feedback: routing recommendation (prefer/neutral/watchlist/quarantine)
  ↓
Router Update Safety: dry-run by default, approval required for apply, rollback mandatory
  ↓
P2 Closure Report: complete evidence package
```

## What P2-F Is Not

- Not a real external executor (Codex/Cline/ECC).
- Not an automatic API caller.
- Not a production router auto-mutator.
- Not P3.
- Not multimodal.
- Not LiteLLM.

## Usage

### Via Script

```bash
python scripts/p2_closure_check.py \
  --task-id task_p2_closure_demo \
  --delivery-path tests/fixtures/p2_closure/needs_revision_delivery \
  --output-dir acceptance_runs/p2_closure \
  --provider-id deepseek-v4-pro \
  --executor deepseek \
  --dry-run
```

### Via Python API

```python
from agent_runtime.p2_closure import run_p2_closure
from pathlib import Path

result = run_p2_closure(
    task_id="my_task",
    delivery_path=Path("path/to/delivery"),
    output_dir=Path("acceptance_runs/p2_closure"),
    provider_id="deepseek-v4-pro",
    executor="deepseek",
    dry_run=True,
)

print(f"Verdict: {result.verdict_status}")
print(f"Revision required: {result.revision_required}")
print(f"Provider feedback: {result.provider_feedback}")
print(f"Router feedback: {result.router_feedback}")
```

## Output Artifacts

| File | Description |
|------|-------------|
| `p2_capability_map.yml` | P2 module discovery report |
| `review_verdict.yml` | Unified review verdict with scores |
| `revision_packet.md` | Revision task card (if not accepted) |
| `provider_feedback.yml` | Provider governance feedback |
| `router_feedback.yml` | Router update recommendation |
| `router_update_dry_run.yml` | Dry-run router update artifact |
| `router_update_apply_result.yml` | Apply result (if allowed) |
| `router_update_rollback_plan.yml` | Rollback plan (if applied) |
| `p2_closure_report.md` | Summary closure report |

## Safety Principles

- **dry-run by default**: No config is modified unless explicitly allowed.
- **approval required for router apply**: A file-token approval artifact must exist.
- **rollback required for apply**: Every apply generates a rollback plan.
- **evidence-first**: All decisions are written as deterministic artifacts.
- **no secrets**: No credentials are read or exposed.
- **no external scripts**: Nothing is executed outside the local Python process.
- **no network tests**: No HTTP calls are made.
- **local-first**: All operations are deterministic and work with fixtures.

## Test Fixtures

| Fixture | Purpose |
|---------|---------|
| `accepted_delivery` | Complete delivery → verdict accepted |
| `needs_revision_delivery` | Missing tests → verdict needs_revision/rejected |
| `unsafe_delivery` | Secret leak patterns → verdict unsafe |
| `missing_artifacts_delivery` | Missing required files → verdict not accepted |
| `router_apply_approval_granted` | Valid approval token for router apply test |
| `router_apply_approval_missing` | Empty dir for missing approval test |

## Architecture

```
p2_closure/
├── __init__.py          # Package exports
├── models.py            # P2ClosureResult, ProviderFeedback, RouterFeedback
├── capability_map.py    # P2 module scanner
├── closure_runner.py    # Main orchestration
├── evidence.py          # Verdict, feedback, revision packet writers
└── report_writer.py     # Closure report writer
```

All components reuse existing P2 modules:
- `agent_runtime/review/` for 3E review
- `agent_runtime/governance/` for provider governance patterns
- `agent_runtime/router_update/` for router update safety
