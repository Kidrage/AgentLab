# Cline MCP STDIO Setup

AgentLab supports local STDIO MCP-style integration for manual Cline MCP Server
configuration. This is local-first: do not expose AgentLab as a public HTTP/SSE
MCP server.

## Manual Configuration Steps

Open Cline and edit the MCP settings JSON:

```text
Cline -> MCP Servers icon -> Configure -> Configure MCP Servers -> edit mcpServers JSON
```

Depending on your Cline version, the settings may be edited in one of these
places:

```text
IDE extension: Cline opened MCP settings JSON
CLI: ~/.cline/mcp.json
Global settings may also live under ~/.cline/data/settings/cline_mcp_settings.json depending on Cline version
```

Use absolute paths for both the wrapper script and `AGENTLAB_ROOT`.

## Recommended STDIO Config

macOS/Linux:

```json
{
  "mcpServers": {
    "agentlab": {
      "command": "/bin/bash",
      "args": ["/ABSOLUTE/PATH/TO/AgentLab/scripts/agentlab_mcp_stdio.sh"],
      "env": {
        "AGENTLAB_ROOT": "/ABSOLUTE/PATH/TO/AgentLab"
      },
      "disabled": false,
      "autoApprove": [
        "agentlab_get_task_status",
        "agentlab_get_task_events",
        "agentlab_get_task_report",
        "agentlab_list_decisions",
        "agentlab_list_active_skills",
        "agentlab_get_skill_usage",
        "agentlab_webhook_status"
      ]
    }
  }
}
```

Windows with WSL:

```json
{
  "mcpServers": {
    "agentlab": {
      "command": "wsl",
      "args": ["bash", "/home/<user>/AgentLab/scripts/agentlab_mcp_stdio.sh"],
      "env": {
        "AGENTLAB_ROOT": "/home/<user>/AgentLab"
      },
      "disabled": false,
      "autoApprove": [
        "agentlab_get_task_status",
        "agentlab_get_task_events",
        "agentlab_get_task_report",
        "agentlab_list_decisions",
        "agentlab_list_active_skills",
        "agentlab_get_skill_usage",
        "agentlab_webhook_status"
      ]
    }
  }
}
```

Copyable examples:

- `examples/cline/mcp_agentlab_stdio.macos-linux.json`
- `examples/cline/mcp_agentlab_stdio.wsl.json`

## AutoApprove Safety

Recommended read-only tools for `autoApprove`:

```text
agentlab_get_task_status
agentlab_get_task_events
agentlab_get_task_report
agentlab_list_decisions
agentlab_list_active_skills
agentlab_get_skill_usage
agentlab_webhook_status
```

Do not auto-approve state-changing or scanning tools:

```text
agentlab_create_task
agentlab_approve_decision
agentlab_reject_decision
agentlab_resume_task
agentlab_pause_task
agentlab_stop_task
agentlab_request_skill_learning
agentlab_approve_skill_request
agentlab_reject_skill_request
agentlab_watchdog_scan
```

`config/mcp_policy.yml` includes safety profiles. The default
`local_cline_safe` profile allows normal local Cline control but keeps
`allow_stop_task: false`.

## Smoke Tests

List tools:

```bash
cd /ABSOLUTE/PATH/TO/AgentLab
python3 -m agent_runtime.mcp_server --list-tools
```

STDIO JSON-RPC smoke:

```bash
printf '%s\n' \
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"manual-smoke","version":"0.1"}}}' \
'{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
| scripts/agentlab_mcp_stdio.sh
```

The wrapper and server must emit only JSON-RPC responses on stdout. Any debug
logging must go to stderr.

## Troubleshooting

- Cline cannot see tools: run `python3 -m agent_runtime.mcp_server --list-tools`, then check the wrapper path.
- Server will not connect: confirm `command` and `args` use absolute paths.
- stdout is polluted: the wrapper/server must not print banners or logs to stdout.
- Permission error: run `chmod +x scripts/agentlab_mcp_stdio.sh`.
- Windows: prefer WSL and use Linux paths inside `AGENTLAB_ROOT`.
- Do not expose AgentLab as a public HTTP MCP server.

## Implemented

- Local STDIO MCP-style server.
- Cline manual config examples.
- Wrapper script.
- Read-only `autoApprove` recommendation.
- Compatibility tests.

## Not Implemented

- Cline Marketplace packaging.
- Remote HTTP/SSE hosted MCP.
- Production MCP SDK certification.
- Public AgentLab MCP gateway.

## Future Work

- Validate with official MCP Inspector.
- Optionally migrate to official MCP Python SDK / FastMCP if Cline compatibility issues appear.
- Add Marketplace packaging metadata after stable release.
