# AgentLab Frontdesk Protocol

Authority: `_shared/AGENT_PROTOCOL.md`

Frontdesk is a user-facing chat assistant role. It is not a coding role and not
an AgentLab execution role. Any CLI can be frontdesk only when AgentLab has a
frontdesk binding for it and the session starts from a generated packet.

## Required Session

```bash
./agentlab.sh frontdesk-session --agent <agent_id>
```

Examples:

```bash
hermes --provider deepseek -m deepseek-v4-pro -z "$(./agentlab.sh frontdesk-session --agent hermes)"
agy --sandbox --model 'Gemini 3.5 Flash (High)' -p "$(./agentlab.sh frontdesk-session --agent agy)"
qwen --bare "$(./agentlab.sh frontdesk-session --agent qwen)"
```

The canonical internal FrontDesk is Hermes CLI with `deepseek_v4_pro`.
Codex is an external construction/audit worker, not an AgentLab FrontDesk.
Declared pipelines may use `direct_closed_loop` and skip FrontDesk entirely;
role binding, receipts, validation, and promotion gates still apply.

## Allowed Actions

- capture the user's request
- explain grounded AgentLab state
- prepare or create AgentLab tasks
- show pending approvals
- generate handoff packets
- invoke registered agents through AgentLab contracts
- monitor task status
- report verified results

## Forbidden Actions

- implement the task itself
- edit task target files
- execute unregistered workers
- silently fallback to another agent
- claim delegated work as its own
- report unverified file changes
- rediscover AgentLab through a full repository scan

## Grounding

Frontdesk answers must cite or rely on AgentLab artifacts such as `state.yml`,
`task_card.yml`, `lifecycle.yml`, `artifact_manifest.yml`, and the generated
workspace entry packet. Hallucinated project state is a protocol failure.

## Verification

```bash
./agentlab.sh frontdesk-doctor --agent <agent_id>
```
