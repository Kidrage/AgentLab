# Agent Collaboration Observability

AgentLab should not be a black box. Each agent should leave a compact, structured record of its contribution.

## Contribution Ledger

A task-level contribution ledger records:

- `agent_id`
- role
- status
- inputs read
- artifacts created
- findings
- decisions
- estimated token/cost information
- supervisor acceptance state

## Lightweight Agent Packets

Agents should pass small packets that point to artifacts instead of embedding long raw histories. The packet contract includes:

- sender and receiver
- purpose
- max context budget
- must-read artifacts
- summary
- requested action
- forbidden actions

This keeps collaboration auditable while reducing repeated token spend.
