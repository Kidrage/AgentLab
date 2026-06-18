# S3 Skill OS Discovery Report

## Scope

This stage completes the S1/S2/S3 planning chain by adding metadata-only Skill
OS discovery planning. It does not install, promote, download, or execute
skills.

## Added

- `agent_runtime/skills/source_registry.py`
  - safe source registry loader and validator;
  - network sources disabled unless policy enables them.
- `agent_runtime/skills/package_parser.py`
  - local `SKILL.md` / `skill.yml` / `manifest.yml` metadata parser;
  - reports missing capability, permission, risk, and source declarations.
- `agent_runtime/skills/skill_search_plan.py`
  - builds `skill_search_plan.yml` from `mission_contract.yml` and
    `workflow_plan.yml`.
- `./agentlab.sh skill-search-plan`
  - writes the S3 plan artifact without executing tools.
- `config/skill_source_registry.yml`
- `config/skill_package_schema.yml`
- `docs/S1_S2_S3_REPAIR_PATH.md`

## Acceptance

- Skill search plans include required capabilities, candidate sources, search
  terms, risk policy, and approval status.
- Network and auto-promotion stay disabled by default.
- Local fixture skill packages parse without executing code.
- Missing metadata is surfaced as validation errors, not ignored.

## Remaining Boundary

S4 should consume S3 plans for trust scanning, permission validation, sandbox
checks, promotion, and active dispatch.
