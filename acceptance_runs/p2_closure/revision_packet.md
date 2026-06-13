# P2 Revision Packet

## Task
- task_id: task_p2_closure_demo
- delivery_id: needs_revision_delivery
- original_provider: deepseek-v4-pro
- original_executor: deepseek

## Verdict
rejected

## Why this failed
- HIGH evidence: Required artifact is missing: skill_usage_ledger.yml

### Missing Evidence
- skill_usage_ledger.yml

## Required Fixes
1. HIGH evidence: Required artifact is missing: skill_usage_ledger.yml

## Files / Artifacts to inspect
- agent_runtime/p2_closure/models.py

## Acceptance Criteria for Revision
- All required artifacts are present.
- All required report sections include concrete evidence.
- No safety findings in the delivery.
- The next 3E review verdict is accepted.

## Safety Constraints
- Do not expose secrets.
- Do not run external hooks/scripts.
- Do not enable external tools by default.
- Do not modify router config without approval.
- Keep all changes deterministic and testable.

## Suggested Executor
deepseek

## Evidence Required on Return
- tests run
- files changed
- artifact manifest
- review notes
