# S1/S2/S3 Repair Path

## Goal

Complete the local-first planning chain without expanding into execution:

```text
raw prompt
→ mission_contract.yml
→ workflow_plan.yml / workflow_plan.md
→ skill_search_plan.yml
→ reviewed skill candidates only
```

## S1 Mission Compiler

Done when:

- prompts compile into valid `MissionContract` data;
- domain, capabilities, artifacts, acceptance gates, risks, unknowns, and human
  approval are explicit;
- `execution_profile` describes task size, risk, budget hint, route hint, and
  recovery boundaries;
- compilation performs no network, shell, provider, or skill execution.

## S2 Domain Workflow

Done when:

- 12 domain templates load deterministically;
- mission contracts map to workflow plans with phases, gates, artifacts, and
  human decision points;
- `route_controls` expose mock-first, approval-first, skipped-agent reasons,
  and blocked-task recovery artifacts;
- workflow planning performs no external execution.

## S3 Skill OS Discovery

Done when:

- source registry defaults are safe: network off, auto install off, review on;
- local skill packages can be parsed as metadata;
- `mission_contract + workflow_plan` produces `skill_search_plan.yml`;
- search plans contain required capabilities, candidate sources, terms, risk
  policy, and approval status;
- no skill code is executed, downloaded, promoted, or copied.

## Boundary

S1/S2/S3 end at reviewable planning artifacts. S4 owns trust scanning,
permission validation, sandbox checks, promotion, and active dispatch.
