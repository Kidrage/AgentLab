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

The canonical routed Frontdesk is OpenClaw. On the 250 runtime its configured
backend is DeepSeek V4 Flash. Hermes remains an optional operator shell, not the
default public Frontdesk. Codex is an external construction/audit worker, not an
AgentLab Frontdesk.
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

Each turn has exactly one phase: `INTAKE`, `CLARIFY`, `ROUTE`, `MONITOR`, or
`REPORT`. The original request is passed verbatim through `frontdesk route`.
Repository claims use literal tracked-file evidence from `frontdesk search`;
completion and validation claims use `frontdesk report`. If those tools have no
evidence, the only valid value is `UNKNOWN`.

```bash
./agentlab.sh frontdesk route --adapter openclaw --request "<verbatim>" --explain
./agentlab.sh frontdesk search --query "<literal>" --path agent_runtime
./agentlab.sh frontdesk report --project <Project> --task-id <task_id>
```

## Verification

```bash
./agentlab.sh frontdesk-doctor --agent <agent_id>
```
