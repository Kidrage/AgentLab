# AgentLab Web UI

This is a dependency-free static dashboard shell for AgentLab status.

Open `index.html` directly in a browser. When served from a local web server, the
page attempts to load `agent_status.sample.json`; otherwise it falls back to the
embedded snapshot in `app.js`.

Current scope:

- Show all configured agents.
- Show task route, status, provider, ownership, edit rights, and token usage.
- Keep the data shape compatible with a future local AgentLab status endpoint.

Future integration points:

- Replace `agent_status.sample.json` with a generated run snapshot.
- Add a tiny local server command in `agent_runtime/run_task.py`.
- Stream state changes from task reports and ledgers.
