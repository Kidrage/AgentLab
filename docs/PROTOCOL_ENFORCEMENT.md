# AgentLab Protocol Enforcement

Authority: `_shared/AGENT_PROTOCOL.md`

AgentLab protocol strength is defined as:

1. normative protocol text
2. policy YAML
3. runtime packet generation
4. doctor gates
5. tests

Rules that exist only in prose are not considered fully enforced.

## Enforced Areas

- workspace entry
- frontdesk session
- role session
- role-worker binding
- explicit delegation relay-only behavior
- repository handoff gate
- Git and validation evidence discipline

## Runtime Gates

```bash
./agentlab.sh protocol-doctor
./agentlab.sh frontdesk-doctor --agent <agent_id>
./agentlab.sh role-doctor --role <Role> --worker <worker>
```

`protocol-doctor` fails when required docs/configs are missing, frontdesk-only
workers are configured as task-packet executors, or a role has unbound workers.

## Boundary

AgentLab cannot prevent a human from manually launching an external binary with
a raw prompt. The strong guarantee applies to AgentLab-managed sessions,
generated packets, routing, and invocation contracts.
