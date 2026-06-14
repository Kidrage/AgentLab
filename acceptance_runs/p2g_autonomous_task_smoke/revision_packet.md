# P2 Revision Packet

## Task
- task_id: task_p2g_smoke
- delivery_id: fake_repo
- original_provider: mock_executor
- original_executor: mock

## Verdict
rejected

## Why this failed
- HIGH evidence: Required artifact is missing: external_handoff.md
- HIGH evidence: Required artifact is missing: skill_usage_ledger.yml
- MEDIUM evidence: Required report section is missing: Summary
- MEDIUM evidence: Required report section is missing: Tests Run
- MEDIUM evidence: Required report section is missing: Safety Evidence
- MEDIUM evidence: Required report section is missing: Known Limitations
- MEDIUM evidence: Required report section is missing: Verdict
- MEDIUM tests: No claimed tests were found in the delivery evidence.

### Missing Evidence
- external_handoff.md
- skill_usage_ledger.yml

## Required Fixes
1. HIGH evidence: Required artifact is missing: external_handoff.md
2. HIGH evidence: Required artifact is missing: skill_usage_ledger.yml
3. MEDIUM evidence: Required report section is missing: Summary
4. MEDIUM evidence: Required report section is missing: Tests Run
5. MEDIUM evidence: Required report section is missing: Safety Evidence
6. MEDIUM evidence: Required report section is missing: Known Limitations
7. MEDIUM evidence: Required report section is missing: Verdict
8. MEDIUM tests: No claimed tests were found in the delivery evidence.

## Files / Artifacts to inspect
- None specified

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
