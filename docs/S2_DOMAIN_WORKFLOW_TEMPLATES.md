# AgentLab S2 Domain Workflow Templates

## 1. S2 position in the mainline

S2 sits after the S1 Mission Contract compiler and domain classifier. S1 answers
what the user wants: task type, artifacts, acceptance gates, assumptions, risks,
and approval needs. S2 answers how AgentLab should produce the work for that
domain.

S2 does not start Skill OS, Capability Registry, Web Intelligence, Recovery Brain,
Long Project Orchestrator, Coding Agent Connector, Multimodal runtime, Eval Suite,
or Dashboard work. It only introduces deterministic workflow planning.

## 2. Mission Contract versus Workflow Plan

A `mission_contract.yml` is the compiled task intent. It records the user's goal,
constraints, required capabilities, required artifacts, acceptance gates, risks,
and approval policy.

A `workflow_plan.yml` is the domain-aware production method. It records the chosen
workflow template, phases, recommended agents, recommended skills, expected phase
artifacts, phase gates, human decision points, route preferences, warnings, and
capability gaps.

## 3. Why domain workflows improve generalization

AgentLab should not rely on one universal prompt for every task. Different domains
need different production methods:

- coding needs repo inspection, patch planning, tests, text-integrity audit, and
  rollback notes;
- research needs source policy, source quality review, citations, and uncertainty;
- creative longform needs constitution, bible, outline, cards, draft, continuity,
  and style revision;
- local operations need scope, permission checks, dry-runs, approvals, verification,
  and rollback.

S2 captures those production methods as YAML templates and a deterministic planner.

## 4. Built-in domains

The S2 catalog includes twelve generalized templates:

1. `coding_software_engineering`
2. `research_investigation`
3. `creative_longform`
4. `business_strategy`
5. `product_design`
6. `data_analysis`
7. `document_processing`
8. `multimodal_vision`
9. `audio_music`
10. `local_ops_automation`
11. `education_tutoring`
12. `unknown_exploratory`

`unknown_exploratory` is the safe fallback and must not execute work.

## 5. Template schema

Templates live in `config/domain_workflow_templates.yml`. Each template includes:

```yaml
template_id: coding_software_engineering
display_name: Coding / Software Engineering
description: ...
trigger_task_types:
  - coding
trigger_signals:
  - bug
required_capabilities:
  - file_read
recommended_agents:
  - repo_scout
recommended_skills:
  - safe_patch_planning
phase_plan:
  - phase_id: compile_mission
    title: Compile mission
    goal: Normalize the mission contract and preserve constraints.
    required_inputs:
      - mission_contract
    expected_artifacts:
      - scope_summary
    acceptance_gates:
      - scope_is_bounded
    recommended_agents:
      - repo_scout
    recommended_skills:
      - safe_patch_planning
    required_capabilities:
      - file_read
    human_decision_point: false
    failure_recovery:
      missing_evidence: request_more_context
failure_recovery:
  missing_evidence: request_more_context
human_decision_points:
  - approve_large_patch
route_preferences:
  default_route: coding
  allowed_routes:
    - coding
risk_notes:
  - Do not modify unrelated files.
```

Compatibility keys such as `task_types`, `required_artifacts`, `acceptance_gates`,
`risk_defaults`, and `human_approval` remain present so S1 compiler tests and older
builders continue to read the catalog.

## 6. Matching rules

`agent_runtime/domain_workflows/matcher.py` selects a template deterministically:

1. Prefer exact `task_type`, `domain`, or `domain_workflow_template:` note match.
2. Match `task_type` / `domain` against `trigger_task_types`.
3. Score `trigger_signals` against `user_goal`, `intent_summary`, unknowns, and
   notes.
4. Fall back to `unknown_exploratory`.

There is no LLM call, network call, provider call, shell execution, or repository
inspection during matching.

## 7. CLI usage

The safe CLI command is:

```bash
./agentlab.sh workflow-plan \
  --mission-contract examples/mission_contracts/coding_bug.yml \
  --out /tmp/agentlab_s2_workflow_demo
```

It writes:

```text
workflow_plan.yml
workflow_plan.md
```

The command only loads YAML and writes plan artifacts. It does not execute phases.

## 8. Safety limits

S2 explicitly does not perform:

- workflow execution;
- shell command execution;
- web crawling;
- AnySearch calls;
- external provider calls;
- skill discovery or installation;
- external skill package parsing;
- sandbox execution;
- vision model calls;
- audio model calls;
- dashboard work.

Capability gaps are represented as warnings and decision points.

## 9. How S2 prepares later stages

S2 gives later systems a stable planning target:

- S3 Skill OS can map `recommended_skills` to discovered or installed skill
  packages.
- S4 Capability Registry can replace contract-only capability availability with a
  real registry.
- S5 Web Intelligence can satisfy research source collection requests.
- S7 Long Project Orchestrator can expand workflow phases into staged long-running
  plans.
- S8 Coding Agent Connector can execute only the coding workflow phases after
  approval.

The boundary is deliberate: S2 plans production; later stages execute, route,
recover, and evaluate it.
