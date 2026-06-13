# P2 Review → Retry → Governance → Router Loop

## Overview

This document describes how the P2 modules form a complete feedback loop for task delivery validation.

## The Loop

```
┌──────────────────────────────────────────────────────────────────┐
│                     Task Delivery                                │
│  (external handoff result, self-delivery, artifact directory)    │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  3E Review                                                       │
│  Explore:   discover artifacts, tests, changed files             │
│  Examine:   check safety, scope, evidence, requirements          │
│  Enhance:   generate retry handoff / revision recommendations    │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Review Verdict                                                  │
│  accepted      → delivery passes                                 │
│  needs_revision → minor fixes needed                             │
│  rejected      → major issues                                    │
│  unsafe        → security violation                              │
└──────────────────────┬───────────────────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          │ needs_revision/rejected │
          │ /unsafe                 │
          ▼                         │
┌───────────────────┐               │ (accepted → skip)
│ Revision Packet   │               │
│ - failed checks   │               │
│ - missing evidence│               │
│ - safety findings │               │
│ - required fixes  │               │
│ - acceptance crit │               │
│ - suggested exec  │               │
└───────────────────┘               │
          │                         │
          ▼                         │
┌──────────────────────────────────────────────────────────────────┐
│  Provider Governance Feedback                                    │
│  - quality score                                                 │
│  - artifact completeness                                         │
│  - test confidence                                               │
│  - safety confidence                                             │
│  - retry recommended?                                            │
│  - governance recommendation (prefer/neutral/watchlist/quarantine)│
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Router Feedback                                                 │
│  - routing recommendation                                        │
│  - confidence level                                              │
│  - dry-run: true (always by default)                             │
│  - apply_allowed: false (default)                                │
│  - approval_required: true                                       │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Router Update Safety                                            │
│  dry-run:      always written                                    │
│  apply:        only with approval artifact                       │
│  rollback:     always generated if apply succeeds                │
│  validation:   safety invariants enforced                        │
└──────────────────────────────────────────────────────────────────┘
```

## Verdict Priority

When multiple conditions apply, the verdict is determined by the most severe:

1. **unsafe** (highest): secret patterns, forbidden file access, affirmed private URLs
2. **rejected**: high-severity findings, missing required artifacts
3. **needs_revision**: medium-severity findings, incomplete evidence
4. **accepted** (lowest): all checks pass

## Provider Governance Recommendations

| Recommendation | Meaning |
|---------------|---------|
| `prefer` | High quality, consistent success |
| `neutral` | Acceptable performance |
| `watchlist` | Elevated retry rate or declining quality |
| `quarantine` | Repeated failures, safety violations |
| `insufficient_data` | Too few attempts to evaluate |

## Router Update Safety

Router updates follow these invariants:

1. **Production config is never modified** by staging or dry-run.
2. **Approval is always required** for any config change.
3. **Rollback is always available** after a successful apply.
4. **Validation enforces safety**: no enabling disabled external providers, no enabling auto-execution.
5. **All operations are logged** to the router update ledger.

## Evidence Chain

Every step produces a deterministic artifact:

```
review_verdict.yml          → verdict, scores, findings
revision_packet.md          → fix list, acceptance criteria
provider_feedback.yml       → provider performance data
router_feedback.yml         → routing recommendation
router_update_dry_run.yml   → dry-run result
router_update_apply_result.yml → apply result (if applicable)
rollback_plan.yml           → rollback instructions (if applied)
p2_closure_report.md        → summary report
```

These artifacts can be ingested by:
- `agent_runtime/governance/ledger_reader.py` for provider performance analysis
- `agent_runtime/router_update/recommendation_loader.py` for router update planning
- External audit or human review processes
