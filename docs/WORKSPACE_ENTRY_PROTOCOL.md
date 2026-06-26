# AgentLab Workspace Entry Protocol

Authority: `_shared/AGENT_PROTOCOL.md`

This protocol is the enforced entry point for any AgentLab-managed CLI agent
session. It prevents new sessions from rediscovering the repository and guessing
what AgentLab is or which task is active.

## Required Entry

Every managed agent session starts with:

```bash
./agentlab.sh workspace-entry --agent <agent_id>
```

Optional task grounding:

```bash
./agentlab.sh workspace-entry --agent <agent_id> --project <Project> --task-id <task_id>
```

## Packet Contract

The packet must include:

- workspace root
- Git branch/head and detached status
- agent id
- allowed profiles: frontdesk and/or worker roles
- known projects
- recent task state
- source artifacts used for grounding
- forbidden actions

## Strong Rules

- Do not reread the full repository before loading this packet.
- Do not infer AgentLab purpose from a raw repository scan.
- Do not ignore existing task state artifacts.
- Do not bypass frontdesk or role session contracts.

## Verification

Run:

```bash
./agentlab.sh protocol-doctor
```
