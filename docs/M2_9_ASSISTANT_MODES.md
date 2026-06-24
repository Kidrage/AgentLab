# M2-9 AgentLab Assistant Modes

## Overview
The Assistant Modes module implements a grounded, read-only explainer for AgentLab's runtime state. It introduces four core modes:
1. **Operator**: Explains project status, blockers, and costs.
2. **Planner**: Explains roadmaps and phases.
3. **Reviewer**: Explains acceptance and failure gates.
4. **Teacher**: Explains routing decisions and worker choices.

## Contract
The assistant is **strictly forbidden** from hallucinating project states or executing actions. It relies entirely on `projects/<id>/*.yml` files for grounding.

## CLI Usage
Commands are namespaced under `./agentlab.sh assistant`:
- `ask --project <id> --mode operator "..."`
- `explain-phase --project <id> --phase <phase_id>`
- `explain-cost --project <id>`
- `explain-route --decision path/to.yml`
- `explain-worker --worker <id>`
