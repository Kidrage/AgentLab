# M2-11 WebUI Dashboard

## Overview
M2-11 implements a local-only, read-only, JSON-first WebUI dashboard skeleton.

It is not yet a styled production web frontend.
It does not expose remote binding.
It does not implement authentication because it binds only to localhost.
It does not mutate project state.
It does not approve/reject actions.
It does not execute external agents.
It does not require FastAPI, Flask, React, Node, or frontend build tools.

## Key Features
- **Localhost Binding**: Binds exclusively to `127.0.0.1` or `localhost`.
- **Data Redaction**: Intercepts outgoing JSON to automatically mask secrets and API keys using `[REDACTED]`.
- **Stateless Read-Only Shell**: Serves drill-down insights (costs, workers, phases, timelines, approvals) without mutating the underlying project state.

## Usage
Start the server using the unified CLI:
```bash
./agentlab.sh webui --host 127.0.0.1 --port 8765
```

## Known Limitations
- HTML templates / styled frontend are deferred.
- Authentication is deferred because M2-11 is local-only.
- Write operations / approvals / mutations are not exposed.
- Remote binding is intentionally rejected.
- This is a control-plane visibility skeleton, not the final Operator OS UI.
