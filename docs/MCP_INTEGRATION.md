# AgentLab MCP Integration

AgentLab exposes a thin MCP-style stdio tool server for external agents running
in the same environment that need structured task, decision, skill, webhook, and
watchdog operations.

The MVP intentionally has no mandatory MCP SDK dependency. `agent_runtime/mcp_server.py`
provides tool schemas, resource readers, structured handlers, and a minimal
stdio JSON-RPC loop compatible with local smoke testing.

For local OpenClaw integration, the recommended transport is stdio or a local
process invocation. Do not expose MCP over public HTTP unless a separate
authenticated gateway exists.

## MCP vs Webhook

Webhook is push: AgentLab notifies a chat gateway when action is required.

MCP is pull/control: an external agent calls tools to inspect state, approve
decisions, resume tasks, and request skill learning.

OpenClaw can either:

1. call AgentLab CLI directly, or
2. call AgentLab MCP stdio tools if OpenClaw supports MCP.

## Policy

`config/mcp_policy.yml`:

```yaml
enabled: false
allow_task_creation: true
allow_decision_approval: true
allow_skill_approval: true
allow_stop_task: true
```

High-impact actions should continue to use existing decision and skill approval
gates. The server does not return secret values.

## Tools

Task tools:

- `agentlab_create_task`
- `agentlab_get_task_status`
- `agentlab_get_task_events`
- `agentlab_get_task_report`
- `agentlab_list_decisions`
- `agentlab_approve_decision`
- `agentlab_reject_decision`
- `agentlab_resume_task`
- `agentlab_pause_task`
- `agentlab_stop_task`

Skill tools:

- `agentlab_list_skill_requests`
- `agentlab_request_skill_learning`
- `agentlab_approve_skill_request`
- `agentlab_reject_skill_request`
- `agentlab_list_active_skills`
- `agentlab_get_skill_usage`

Webhook/watchdog tools:

- `agentlab_webhook_status`
- `agentlab_watchdog_scan`

## Resources

- `agentlab://tasks/<project>/<task_id>/status`
- `agentlab://tasks/<project>/<task_id>/events`
- `agentlab://tasks/<project>/<task_id>/report`
- `agentlab://skills/active`

## Local Smoke Commands

```bash
python -m agent_runtime.mcp_server --list-tools
python -m agent_runtime.mcp_server --list-resources
python -m agent_runtime.mcp_server --call-tool agentlab_get_task_status --args-json '{"project":"AgentLab","task_id":"task_0001"}'
```

## Stdio JSON-RPC

Start:

```bash
python -m agent_runtime.mcp_server --serve
```

Example request line:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}
```

Example Claude Desktop-style local config:

```json
{
  "mcpServers": {
    "agentlab": {
      "command": "python",
      "args": ["-m", "agent_runtime.mcp_server", "--serve"],
      "cwd": "/Users/saintpeter/Desktop/AgentLab"
    }
  }
}
```

## Security Notes

- Keep `enabled: false` unless you intentionally enable local tool access.
- Do not pass local secrets through tool arguments.
- Recommended transport for local OpenClaw integration: stdio or local process.
- Do not expose MCP over public HTTP unless a separate authenticated gateway exists.
- Stop-task, skill approval, and decision approval are controlled by
  `config/mcp_policy.yml`.
- Tools return structured JSON and avoid exposing raw filesystem paths except
  for local smoke metadata where existing runtime APIs already produce them.
