# S4 Minimal E2E Input Task

## Natural Language Request

Review a tiny local documentation-only task and prove that AgentLab can carry a
request through the local lifecycle without calling external services.

## Constraints

- Use dry-run or mock execution only.
- Do not call external APIs, ECC, AnySearch, CodeGraph, or remote MCP servers.
- Do not read `.env`, `secrets/`, private keys, or credentials.
- Keep all artifact paths repo-relative.

## Expected Closure

The task should produce a plan, dry-run pipeline evidence, P2 closure artifacts,
provider feedback, router feedback, and a final delivery report.
