# S4 Skill Trust / Promotion

S4 consumes S3 skill plans and local skill packages, then decides whether a
skill is eligible for promotion or active dispatch.

## Inputs

- local skill package directory or `SKILL.md`
- `config/skill_trust_policy.yml`
- `config/skill_permission_policy.yml`
- `config/skill_sandbox_policy.yml`
- `config/skill_promotion_policy.yml`

## Reports

`./agentlab.sh skill-trust-validate --package-path <path> --out <dir>` writes:

- `parsed_package.yml`
- `trust_report.yml`
- `permission_report.yml`
- `sandbox_report.yml`
- `promotion_eligibility.yml`
- `s4_validation_summary.yml`

## Safety

S4 is still local-first:

- no third-party code execution;
- no network calls;
- no automatic promotion;
- no automatic active dispatch.

Missing permission, risk, source, or license metadata blocks dispatch until
fixed and approved.

## Boundary

Existing lifecycle commands (`skill-stage`, `skill-validate`, `skill-promote`)
remain available. S4 adds a stricter report-based eligibility gate that later
pipeline stages should check before dispatching active skills.
