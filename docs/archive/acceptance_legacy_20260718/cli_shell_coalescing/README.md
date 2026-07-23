# Retired Synthetic CLI Coalescing Acceptance

These files preserve the July 2026 synthetic Claude inline-agent and Hermes
kanban acceptance evidence. They are historical records, not current runtime
contracts.

The experiment grouped roles from the full CLI matrix without respecting
AgentLab lifecycle dependencies. It was never called by `run-pipeline` and did
not reduce production shell invocations. The current rule is defined in
`config/cli_workflow_shells.yml`: a CLI may use native subagents or boards
inside one bounded AgentLab role-session, while dependent AgentLab roles remain
separate until the earlier role receipt passes.
