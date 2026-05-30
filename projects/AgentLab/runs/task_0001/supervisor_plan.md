# Supervisor Plan

## Route

Selected route: `interface_sensitive_task`.

Agents:

- Supervisor
- RepoScout
- InterfaceMapper
- Coder
- TesterAuditor
- Archivist

Skipped agents:

- Researcher: no external facts were needed.
- CodexPromptGenerator: the task was small enough for direct Codex Coder execution.

## Scope

Create a simple, dependency-free web UI framework for AgentLab that shows the
status of every configured agent. Keep it local-first and static for this task.

## Token Budget

| Phase | Estimate | Warning | Stop |
| --- | ---: | ---: | ---: |
| Intake and routing | 3700 | 3330 | 4255 |
| RepoScout repository scan | 7800 | 7020 | 8970 |
| Interface mapping | 6400 | 5760 | 7359 |
| Coder implementation | 9800 | 8820 | 11270 |
| Tester/Auditor validation | 6800 | 6120 | 7819 |
| Archivist update | 3800 | 3420 | 4370 |

## Editable Files

Approved editable paths:

- `web_ui/`
- `README.md`
- `projects/AgentLab/`

## Stop Rules

- Do not install dependencies.
- Do not touch unrelated repositories.
- Stop for user approval before destructive changes or package installation.
- Report failed or unavailable validation commands clearly.
