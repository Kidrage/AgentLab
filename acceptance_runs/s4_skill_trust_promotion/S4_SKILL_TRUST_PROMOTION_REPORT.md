# S4 Skill Trust / Promotion Report

## Scope

S4 adds a metadata-only trust and promotion gate for local skill packages. It
does not execute skills, call the network, or automatically promote anything.

## Added

- `agent_runtime/skills/trust_scanner.py`
- `agent_runtime/skills/permission_manifest.py`
- `agent_runtime/skills/sandbox_runner.py`
- `agent_runtime/skills/promotion.py`
- `agent_runtime/skills/validation.py`
- `config/skill_trust_policy.yml`
- `config/skill_permission_policy.yml`
- `config/skill_sandbox_policy.yml`
- `config/skill_promotion_policy.yml`
- `./agentlab.sh skill-trust-validate`

## Acceptance

- Safe local package passes trust, permission, and mock sandbox checks.
- Safe package is not dispatch eligible without human approval.
- Approved safe package becomes promotion/dispatch eligible.
- Risky shell/network/secret package is blocked.
- Existing fixture with missing permissions/risk/source is blocked.
- S4 validation does not call network, subprocess, or execute skill code.

## Boundary

S4 produces eligibility reports. Later phases should wire these reports into
active skill dispatch enforcement and broader task execution.
