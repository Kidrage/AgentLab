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

For Cline, use the local STDIO wrapper and manual config examples documented in
`docs/CLINE_MCP_SETUP.md`.

## MCP vs Webhook

Webhook is push: AgentLab notifies a chat gateway when action is required.

MCP is pull/control: an external agent calls tools to inspect state, approve
decisions, resume tasks, and request skill learning.

OpenClaw can either:

1. call AgentLab CLI directly, or
2. call AgentLab MCP stdio tools if OpenClaw supports MCP.

## Policy

`config/mcp_policy.yml` supports safety profiles:

```yaml
schema_version: 1
enabled: true
default_profile: local_cline_safe
profiles:
  readonly:
    allow_task_creation: false
    allow_decision_approval: false
    allow_skill_approval: false
    allow_stop_task: false
  local_cline_safe:
    allow_task_creation: true
    allow_decision_approval: true
    allow_skill_approval: true
    allow_stop_task: false
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

Cline wrapper:

```bash
scripts/agentlab_mcp_stdio.sh
```

Example request line:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}
```

Example Cline config files:

- `examples/cline/mcp_agentlab_stdio.macos-linux.json`
- `examples/cline/mcp_agentlab_stdio.wsl.json`

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

- Enable MCP only for trusted local STDIO clients and keep it off any public
  HTTP/SSE surface.
- Do not pass local secrets through tool arguments.
- Recommended transport for local OpenClaw integration: stdio or local process.
- Do not expose MCP over public HTTP unless a separate authenticated gateway exists.
- For Cline `autoApprove`, use read-only tools only:
  `agentlab_get_task_status`, `agentlab_get_task_events`,
  `agentlab_get_task_report`, `agentlab_list_decisions`,
  `agentlab_list_active_skills`, `agentlab_get_skill_usage`, and
  `agentlab_webhook_status`.
- Do not auto-approve state-changing tools such as task creation, decision
  approval/rejection, task control, skill request/approval, or watchdog scans.
- Stop-task, skill approval, and decision approval are controlled by
  `config/mcp_policy.yml`.
- Tools return structured JSON and avoid exposing raw filesystem paths except
  for local smoke metadata where existing runtime APIs already produce them.

## Cline Compatibility Status

Implemented:

- local STDIO MCP-style server
- Cline manual config examples
- wrapper script
- read-only autoApprove recommendation
- compatibility tests

Not implemented:

- Cline Marketplace packaging
- remote HTTP/SSE hosted MCP
- production MCP SDK certification
- public AgentLab MCP gateway

Future work:

- Validate with official MCP Inspector.
- Optionally migrate to official MCP Python SDK / FastMCP if Cline compatibility issues appear.
- Add Marketplace packaging metadata after stable release.
