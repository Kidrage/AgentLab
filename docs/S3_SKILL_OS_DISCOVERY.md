# S3 Skill OS Discovery

S3 turns S1/S2 planning output into a reviewable skill search plan.

## Inputs

- `mission_contract.yml`
- `workflow_plan.yml`
- `config/skill_source_registry.yml`
- `config/skill_discovery.yml`

## Output

- `skill_search_plan.yml`

The plan records:

- `required_capabilities`
- `recommended_skills`
- `candidate_sources`
- `search_terms`
- `risk_policy`
- `approval_required`

## CLI

```bash
./agentlab.sh skill-search-plan \
  --mission-contract examples/mission_contracts/coding_bug.yml \
  --workflow-plan /tmp/workflow_plan.yml \
  --out /tmp/skill_plan
```

## Safety

S3 is metadata-only:

- no skill execution;
- no auto-install;
- no auto-promotion;
- no unknown repo download;
- no third-party source copying.

Network-capable sources remain disabled unless a later approved stage changes
policy.

## Package Parsing

`agent_runtime/skills/package_parser.py` parses local packages containing:

- `SKILL.md`
- `skill.yml`
- `manifest.yml`
- `README.md`
- `examples/`
- `tests/`

Missing capabilities, permissions, risk, or source metadata are surfaced as
validation errors. Parsed packages are not dispatchable by default.
