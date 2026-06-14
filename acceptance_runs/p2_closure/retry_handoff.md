# Retry Handoff

## Why this failed
- missing-artifact-skill_usage_ledger.yml (high/evidence): Required artifact is missing: skill_usage_ledger.yml

## Required Fixes
- Regenerate the delivery with all required review artifacts.

## Scope Limits
- Do not add new features, expand scope, or modify unrelated modules.

## Reproduction Commands
- `python -m compileall agent_runtime agentlab_app.py`
- `python -m pytest -q`
- `python scripts/p2_review_check.py --target tests/fixtures/p2_closure/needs_revision_delivery`

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
