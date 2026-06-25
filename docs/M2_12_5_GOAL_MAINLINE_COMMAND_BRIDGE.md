# M2-12.5 Goal / Mainline Command Bridge

## Purpose
Completes the M2 Operator OS control loop by adding a deterministic `/goal` command bridge. It acts as a local-first project goal compiler, transforming rough human requirements into a deterministic set of governance artifacts.

## Command Grammar
- `/goal <text>`
- `/goal set <text>`
- `/goal set --text "<text>"`
- `/goal set --prompt-file path/to/prompt.md`
- `/goal plan`
- `/goal status`
- `/goal progress`
- `/goal validate`
- `/goal report`
- `/goal pause`
- `/goal resume`
- `/goal close`

## Chinese Aliases
- `/目标 <text>`
- `/目标 设置 <text>`
- `/目标 计划`
- `/目标 状态`
- `/目标 进度`
- `/目标 验收`
- `/目标 报告`
- `/目标 暂停`
- `/目标 恢复`
- `/目标 关闭`
- Short aliases: `/计划`, `/进度`, `/验收`, `/报告`

## Artifact Flow
1. **set**: `goal_contract.yml`, `decision_log.yml`, `next_actions.yml`
2. **plan**: `mission_contract.yml`, `workflow_plan.yml`, `mainline_program.yml`, `mainline_acceptance_contract.yml`, `scenario_validation_plan.yml`, `mainline_progress.yml`
3. **report**: `mainline_completion_report.md`

## Project Brain Integration
Artifacts are stored in `projects/<project>/project_brain/`. 
Updates are deterministically applied.

## Template Selection Rules
Uses keyword matching to select deterministic templates:
- `agentlab`, `self repair`, `m-series` -> `agentlab_self_repair`
- `novel`, `story`, `writing` -> `longform_creation`
- `codebase`, `app` -> `codebase_build`
- ...and others. Defaults to `unknown_large_project`.

## Acceptance Behavior
A mainline stage requires all `required_artifacts` and `required_evidence` to be present. Scenario validation is deterministic mock for M2-12.5. Future M3 reserved stages (`future_reserved`) explicitly do not block M2 closure.

## Non-Goals
- No business contract engine
- No LLM calls
- No unsafe shell execution
- No external agent dispatch
- No automatic skill installation

## Safety Guarantees
The parser and compiler run 100% locally and deterministically. They do not execute external processes, models, or network requests.

## CLI Examples
```bash
./agentlab.sh goal set --project AgentLab --text "Repair AgentLab M2 mainline"
./agentlab.sh goal plan --project AgentLab
./agentlab.sh goal report --project AgentLab
```

## Control-Surface Integration Summary
All surfaces (CLI, Assistant, TUI, WebUI, MCP/Frontdesk) route to a single shared `GoalActionSchema` to guarantee uniform deterministic behavior without bypassing Operator OS governance.
