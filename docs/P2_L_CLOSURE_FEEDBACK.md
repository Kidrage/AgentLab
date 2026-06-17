# P2-L: Recovery History → Closure Quality Feedback

## What P2-L Does

P2-L converts recovery history into **structured closure quality feedback**.
It reads recovery artifacts produced during task execution (failure events,
diagnoses, verdicts, human review decisions, retry attempts) and generates:

- `closure_quality_feedback.json` — machine-readable feedback
- `closure_quality_feedback.md` — human-readable report

The feedback is **passive**: it does not modify live router policy, provider
routing, or execution paths. It writes artifacts that can be consumed later by
governance modules, reviewer policy, or skill incubation.

## Artifacts Read

P2-L discovers and reads these artifact paths (if present) from
`projects/<Project>/runs/<task_id>/recovery/`:

| Artifact | Path |
|----------|------|
| Failure event | `recovery/failure_event.json` |
| Failure diagnosis | `recovery/failure_diagnosis.json` |
| Recovery plan | `recovery/recovery_plan.md` |
| Recovery verdict | `recovery/recovery_verdict.json` |
| Human review decision | `recovery/human_review_decision.json` |
| Indexed human reviews | `recovery/human_reviews/human_review_*.json` |
| Retry attempts | `recovery/retry_attempts.json` |
| Indexed failures | `recovery/failures/failure_event_*.json` |
| Indexed diagnoses | `recovery/failures/failure_diagnosis_*.json` |
| Indexed verdicts | `recovery/failures/recovery_verdict_*.json` |

Missing or corrupt artifacts produce warnings but do not crash.

## Artifacts Written

Output goes to the task run directory (or a custom `--output-dir`):

| Artifact | Format | Description |
|----------|--------|-------------|
| `closure_quality_feedback.json` | JSON | Structured feedback with task_id, verdict, quality_score, lessons, recommended_actions |
| `closure_quality_feedback.md` | Markdown | Human-readable report with all fields plus quality score heuristic documentation |

## Deterministic Quality Score

The quality score is a **deterministic heuristic**, not a business-grade metric:

| Starting point | Condition |
|---------------|-----------|
| 1.0 | Closure verdict passed/accepted |
| 0.5 | Closure verdict unknown |
| 0.0 | Closure verdict failed/blocked/rejected |

**Adjustments:**

- Subtract 0.05 per retry (floor at 0.0)
- Subtract 0.10 if human review was required
- Add 0.10 if recovery succeeded after initial failure (cap at 1.0)

## Feedback Fields

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | Task identifier |
| `verdict` | string | `passed`, `failed`, `unknown`, `retry`, `exhausted` |
| `quality_score` | float\|null | Heuristic score |
| `recovery_used` | bool | Whether any recovery action occurred |
| `recovery_successful` | bool\|null | Whether recovery led to successful closure |
| `failure_categories` | list[string] | Unique failure categories observed |
| `retry_count` | int | Number of retry/resume events |
| `human_review_required` | bool | Whether human review was triggered |
| `blocked_reason` | string\|null | Why closure was blocked (if applicable) |
| `lessons` | list[string] | Deterministic lesson templates |
| `recommended_actions` | list[string] | Action tags for governance consumption |
| `evidence_artifacts` | list[string] | Paths to supporting artifacts |

## Recommended Actions

Action tags that may appear:

- `keep_recovery_gate_enabled` — human review was needed; keep gates
- `increase_test_evidence_requirement` — recovery worked; strengthen evidence
- `prefer_smaller_task_split` — repeated retries; split tasks smaller
- `route_similar_failures_to_human_review` — recovery failed; escalate
- `no_action` — nothing actionable detected

## CLI Usage

### Via agentlab.sh

```bash
./agentlab.sh recovery-feedback --task-id <task_id> --project <project>
./agentlab.sh recovery-feedback --task-id <task_id> --project <project> --output-dir <path>
```

### Via Python module

```bash
python -m agent_runtime.recovery.closure_feedback --task-run-dir <path>
python -m agent_runtime.recovery.closure_feedback --task-id <id> --project <name>
```

## Known Limitations

1. **Passive feedback only** — does not mutate live router or provider policy.
2. **Heuristic quality score** — not calibrated against production data.
3. **No dashboard or web UI** — artifacts are file-based only.
4. **Deterministic lesson templates** — no LLM-generated prose.
5. **No automatic policy mutation** — feedback is for human/automated review consumption, not automatic execution.
6. **Requires existing recovery artifacts** — if no recovery directory exists, feedback is limited to "no_recovery_history".

## Why Passive Only

P2-L is designed as a **read-and-write-files** layer. It does not:

- Call external APIs
- Mutate provider routing tables
- Quarantine executors
- Change live execution paths
- Require a database

This keeps the feedback layer safe to run at any time — during a task, after
closure, or as a retrospective analysis — without risk of disrupting active
work. Future rounds (P3+) can build active governance responses on top of these
passive artifacts.
