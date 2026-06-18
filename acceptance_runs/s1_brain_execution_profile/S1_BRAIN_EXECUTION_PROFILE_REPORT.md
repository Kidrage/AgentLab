# S1 Brain Execution Profile Report

## Scope

This stage adds a lightweight brain-layer execution profile to the deterministic
Task Compiler and wires it into the legacy workflow planner route selection.

The goal is to keep agent work lightweight and efficient while preventing
network, permission, or capability-gap issues from cascading into whole-pipeline
failure.

## What Changed

- `agent_runtime/brain/task_compiler.py` now emits `execution_profile` with:
  - task size;
  - risk level;
  - budget suggestion;
  - route key hint;
  - plan-first and recovery boundaries.
- `agent_runtime/task_router.py` now accepts a brain profile and uses it before
  falling back to legacy keyword routing.
- `agent_runtime/workflow_plan.py` softly compiles the profile during planning.
  Compiler errors are recorded as notes and fall back to keyword routing.
- `agent_runtime/schemas.py` records the profile on `WorkflowPlan`.
- `workflow_plan.yml` now includes `route_controls` with recovery boundaries,
  mock/approval-first flags, skipped-agent reasons, and blocked-task recovery
  artifact expectations.
- `task_snapshot.yml` exposes `route_controls` for status/UI consumers.
- `scripts/compile_mission_contract.py` includes the profile in CLI summary.
- `docs/TASK_COMPILER.md` documents the profile contract.

## Acceptance

- Small code repair prompts that mention network or permission failures stay on
  the lightweight route and record recovery boundaries.
- Large architecture/orchestration prompts are marked large, but the rationale
  requires phase splitting instead of blind route expansion.
- Workflow planning consumes the brain profile before legacy keyword routing.
- Task snapshots carry route controls without reparsing notes.
- No networking, shell execution, provider calls, or repository mutation occurs
  during compilation.

## Remaining Work

- Calibrate profile heuristics with real task history.
- Add recovery planner integration so failure boundaries produce concrete retry
  packets.
