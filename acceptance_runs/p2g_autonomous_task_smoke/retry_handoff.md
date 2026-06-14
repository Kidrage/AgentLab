# Retry Handoff

## Why this failed
- missing-artifact-external_handoff.md (high/evidence): Required artifact is missing: external_handoff.md
- missing-artifact-skill_usage_ledger.yml (high/evidence): Required artifact is missing: skill_usage_ledger.yml
- missing-report-section-summary (medium/evidence): Required report section is missing: Summary
- missing-report-section-tests-run (medium/evidence): Required report section is missing: Tests Run
- missing-report-section-safety-evidence (medium/evidence): Required report section is missing: Safety Evidence
- missing-report-section-known-limitations (medium/evidence): Required report section is missing: Known Limitations
- missing-report-section-verdict (medium/evidence): Required report section is missing: Verdict
- claimed-tests-empty (medium/tests): No claimed tests were found in the delivery evidence.

## Required Fixes
- Regenerate the delivery with all required review artifacts.
- Add the missing report section with concrete evidence.
- List the validation commands and results in the report.

## Scope Limits
- Do not add new features, expand scope, or modify unrelated modules.

## Reproduction Commands
- `python -m compileall agent_runtime agentlab_app.py`
- `python -m pytest -q`
- `python scripts/p2_review_check.py --target /Users/saintpeter/Desktop/AgentLab/tests/fixtures/p2g_smoke_task/fake_repo`

## Acceptance Criteria
- All required artifacts are present.
- All required report sections include concrete evidence.
- Safety evidence contains no forbidden actions, private/local/file URL access, or secret-like values.
- Changed files avoid forbidden paths and explain high-risk path changes.
- The next 3E review verdict is PASS or PASS_WITH_WARNINGS.

## Safety Constraints
- Do not execute external scripts.
- Do not start MCP servers.
- Do not clone remote repositories.
- Do not access private, local, or file URLs.
- Do not expose secrets.
- Do not copy third-party source code.
