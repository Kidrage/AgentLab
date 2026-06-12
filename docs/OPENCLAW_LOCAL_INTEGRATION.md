# OpenClaw Local Integration

AgentLab is a local-first AgentOps kernel. In cloud self-hosting, it should run
beside OpenClaw on the same machine, private Docker network, or equivalent local
runtime. OpenClaw is the public chat entry point; AgentLab is the local task
factory.

## Deployment Principles

- Only OpenClaw should be exposed publicly.
- AgentLab stays local to the same machine / Docker network.
- AgentLab should be invoked by OpenClaw through CLI or MCP stdio.
- AgentLab should send feedback to OpenClaw through localhost webhook or local event queue.
- AgentLab should not expose a public HTTP API.
- AgentLab workspace, skills, reports, tokens, and artifacts remain local.

## Recommended Layout

Same-host layout:

```text
~/agent-stack/
  openclaw/
    .env
    logs/
  agentlab/
    agentlab.sh
    projects/
    skills/
    config/
    artifacts/
  shared/
    agentlab_events/
    handoff/
```

Docker layout:

```text
agent-stack-network:
  openclaw
  agentlab
```

AgentLab does not need a public port in either layout. If feedback uses HTTP,
target `localhost` or a private Docker service name only. If feedback uses the
queue fallback, OpenClaw can poll `shared/agentlab_events/`.

## AgentLab CLI Calls

These examples use the current CLI contract:

```bash
./agentlab.sh init-task --project AgentLab --task-id task_0001 --request-text "..."
./agentlab.sh prepare --project AgentLab --task-id task_0001
./agentlab.sh status --project AgentLab --task-id task_0001
./agentlab.sh feedback-status --project AgentLab --task-id task_0001
./agentlab.sh decision-list --project AgentLab --task-id task_0001
./agentlab.sh decision-approve decision_xxxx --project AgentLab --task-id task_0001 --option approve_write
./agentlab.sh decision-reject decision_xxxx --project AgentLab --task-id task_0001 --option stop_task
./agentlab.sh decision-resume task_0001 --project AgentLab
./agentlab.sh task-artifacts --project AgentLab --task-id task_0001
./agentlab.sh daemon --project AgentLab --once
```

The current CLI exposes reports through `status`, `task-artifacts`, and the run
directory report files; there is no separate `report` command yet. The current
daemon MVP runs one scan cycle per invocation. A scheduler, process manager, or
OpenClaw side loop can call `daemon --once` every 30 seconds until a future
long-running interval mode exists.

## Feedback Events

OpenClaw should be prepared to display these local feedback events:

```text
ACTION_REQUIRED
BLOCKED
STALE_RUNNING
FAILED_RECOVERABLE
COMPLETED
SKILL_REQUEST_PENDING
SKILL_CANDIDATE_READY
SKILL_PROMOTED
```

## User Reply Mapping

Suggested chat mapping:

```text
A / approve / 批准 / 同意 -> selected decision option
B / reject / 拒绝 -> reject decision
C / stop / 停止 -> stop task
继续 / resume -> decision-resume
跳过 / skip -> skip_skill or skip_action
```

`agent_runtime/openclaw_local_adapter.py` provides a testable parser for this
mapping without executing the CLI.

## Security Notes

- Do not expose AgentLab directly to the public internet.
- Do not put API keys in webhook payloads.
- Use localhost or private Docker network for AgentLab feedback.
- Use OpenClaw as the only public user-facing service.
- Prefer CLI/MCP stdio over public HTTP for local same-host integration.
