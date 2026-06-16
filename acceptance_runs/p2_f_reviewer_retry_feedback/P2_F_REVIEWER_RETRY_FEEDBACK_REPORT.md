# AgentLab P2-F Reviewer / Retry / Provider / Router Feedback Closure Report

## Summary

P2-F completes the review → verdict → revision → governance → router feedback closure loop.
All 55 new tests pass, bringing total suite to 750 passed, 2 skipped, 0 failures.
No P2-G, P2-H, TUI, WebUI, or real external API calls were introduced.
All P1-A/B/C/D safety boundaries remain intact.

## Branch / Commit

- branch: fix/s0-remote-raw-integrity
- commit: 9558e0e68e005c85d3984337fe1b1c906e9675bd
- remote HEAD (main): f9efd07ad8167fea8f10b9f1cf5f53c9134cff64

## Changed Files

| File | Reason |
|------|--------|
| `config/reviewer_policy.yml` | NEW: Deterministic reviewer policy (artifact requirements, safety checks, cost checks, verdict mapping) |
| `config/router_feedback_policy.yml` | NEW: Router feedback policy (safety thresholds, recommendation actions, ledger config) |
| `tests/test_p2f_reviewer.py` | NEW: 14 tests for deterministic reviewer (pass, missing artifacts, secrets, forbidden paths, cost) |
| `tests/test_p2f_retry_plan.py` | NEW: 13 tests for retry plan (fail→retry, safety→block, max attempts, evidence gap) |
| `tests/test_p2f_provider_feedback.py` | NEW: 10 tests for provider feedback (pass→prefer, fail→watchlist, unknown provider, ledger) |
| `tests/test_p2f_router_feedback.py` | NEW: 10 tests for router feedback (success→prefer, fail→quarantine, dry-run safety) |
| `tests/test_p2f_pipeline_integration.py` | NEW: 8 tests for pipeline integration (CLI smoke, artifact production, P1 safety) |

## New Artifacts

The P2-F closure pipeline produces the following artifacts per task:

| Artifact | Description |
|----------|-------------|
| `review_verdict.yml` | Unified 3E review verdict with scores, findings, and required actions |
| `revision_packet.md` | Structured revision packet for needs_revision/rejected/unsafe verdicts |
| `provider_feedback.yml` | Provider/executor performance record with governance recommendation |
| `router_feedback.yml` | Router recommendation (prefer/keep/watchlist/quarantine) with confidence |
| `router_update_dry_run.yml` | Dry-run router update record (never modifies production config) |
| `p2_closure_report.md` | Summary report of the full closure pipeline |

## Reviewer

The deterministic reviewer (3E: Explore → Examine → Enhance) checks:

1. **Artifact completeness**: Required artifacts (`external_handoff.md`, `skill_usage_ledger.yml`) present
2. **Optional artifacts**: `task_card.yml`, `workflow_plan.yml`, test results
3. **Safety**: Secret patterns (API keys, tokens), forbidden paths (`.env`, `.git/`, `secrets/`)
4. **Scope**: Changed files against forbidden/high-risk path lists
5. **Evidence**: Report sections (Summary, Tests Run, Safety Evidence, Known Limitations, Verdict)
6. **Test coverage**: Claimed tests vs. detected tests
7. **Verdict mapping**: critical→BLOCKED, high→FAIL, medium→NEEDS_REVISION, low→PASS_WITH_WARNINGS

## Retry Policy

- **Max attempts**: 3 per task (configurable in `config/retry_policy.yml`)
- **Stop conditions**: BLOCKED verdict, max attempts exceeded, budget exceeded, repeated same failure
- **Safety violation**: Immediately stops retry, escalates to human review
- **Evidence gap**: Retry focuses on regenerating evidence, not blind rerun
- **Provider routing**: Same provider allowed; different provider preferred after failure
- **External providers**: Require manual approval before retry

## Provider Feedback

- Records provider/executor performance per task
- Governance recommendation mapping:
  - `unsafe`/`BLOCKED` → quarantine
  - `needs_revision` + low score → watchlist
  - `accepted` + high score → prefer
  - `accepted` + medium score → neutral
- Tracks quality score, artifact completeness, test confidence, safety confidence
- Written to `provider_feedback.yml` per task and optionally to project-level ledger

## Router Feedback

- Generates recommendation based on review verdict and provider feedback
- Default: **dry-run only**, never modifies production config
- Actions: prefer, keep, watchlist, quarantine, avoid
- Confidence based on number of failure reasons
- `apply_allowed` is always False in feedback; requires explicit approval flow
- Router update system has separate approval gate (`router_update_policy.yml`)

## Pipeline Integration

P2-F stages are available via:

```bash
./agentlab.sh p2-closure --task-id <task_id> --delivery-path <path> --dry-run
```

The full closure pipeline:
1. **Capability Map**: Scans P2 module status
2. **3E Review**: Explore → Examine → Enhance
3. **Verdict**: Unified review verdict with scores
4. **Revision Packet**: Generated for non-accepted verdicts
5. **Provider Feedback**: Records provider performance
6. **Router Feedback**: Generates routing recommendation
7. **Router Dry-Run**: Safe dry-run update (never modifies production)
8. **Closure Report**: Summary of all stages

`run-pipeline --dry-run` runs the full lifecycle and remains unchanged; P2-F closure is a separate command that can be chained after pipeline completion.

## CLI

Existing commands used:
- `./agentlab.sh p2-closure` — Full P2-F closure pipeline
- `./agentlab.sh p2-capability-map` — Scan P2 module capabilities
- `./agentlab.sh run-pipeline` — Full lifecycle pipeline (unchanged)

## Tests Added

| File | Tests | Coverage |
|------|-------|----------|
| `test_p2f_reviewer.py` | 14 | Complete artifact pass, missing handoff, missing evidence, secrets, forbidden paths, cost |
| `test_p2f_retry_plan.py` | 13 | Fail→retry, safety→block, max attempts, pass→no-retry, policy loading |
| `test_p2f_provider_feedback.py` | 10 | Pass→prefer, fail→watchlist, unsafe→quarantine, unknown provider, ledger schema |
| `test_p2f_router_feedback.py` | 10 | Success→prefer, fail→quarantine, dry-run safety, schema compliance |
| `test_p2f_pipeline_integration.py` | 8 | CLI smoke, artifact production, P1 safety, compilation |

**Total new tests: 55**

## Tests Run

```bash
python -m compileall agent_runtime agentlab_app.py scripts tests
# PASS (no errors)

python -m pytest -q --tb=line
# 750 passed, 2 skipped in 135.32s

bash -n agentlab.sh
# OK

./agentlab.sh --help
# OK

./agentlab.sh run-pipeline --help
# OK

python scripts/audit_text_integrity.py --fail-on-suspicious
# Total files scanned: 435, Suspicious files: 0, PASS

python scripts/check_remote_raw_integrity.py --repo Kidrage/AgentLab --branch main --fail-on-suspicious
# Checked 24 files; suspicious=0
```

## Safety Regression

- ✅ No automatic external skill execution
- ✅ No real external provider calls
- ✅ ECC/AnySearch/CodeGraph safety boundaries not modified
- ✅ No automatic production router policy modification
- ✅ Retry has hard max_attempts limit (3 by default)
- ✅ Safety violation blocks retry, escalates to human review
- ✅ All router updates are dry-run by default
- ✅ No new external dependencies introduced
- ✅ No database/Redis/Postgres introduced

## Known Limitations

- P2-G Context Governance not implemented
- P2-H Skill Governance not implemented
- TUI/WebUI not implemented
- Real external executor calls not implemented
- LLM-based reviewer not implemented (deterministic only)
- Provider feedback ledger not yet aggregated across tasks
- Router feedback does not auto-update routing policy

## Verdict

**PASS**

All Final Acceptance Criteria met:
1. ✅ Full pytest passes (750 passed, 2 skipped, 0 failed)
2. ✅ compileall passes
3. ✅ agentlab.sh bash -n passes
4. ✅ Text integrity audit passes
5. ✅ Remote raw integrity check passes
6. ✅ Reviewer generates `review_verdict.yml`
7. ✅ Fail/needs_retry generates `revision_packet.md`
8. ✅ Provider feedback enters `provider_feedback.yml`
9. ✅ Router recommendation generates `router_feedback.yml`
10. ✅ P2 closure dry-run produces all artifacts
11. ✅ Retry has max_attempts limit
12. ✅ Safety violation blocks retry
13. ✅ No real external provider calls
14. ✅ No production router policy modification
15. ✅ P1-A/B/C/D safety boundaries intact
16. ✅ P2-F acceptance report generated
