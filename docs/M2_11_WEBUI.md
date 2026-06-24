# M2-11 WebUI Dashboard

## Overview
The M2-11 WebUI provides a strict, locally-bound HTTP dashboard for AgentLab. Built entirely on standard Python libraries without external heavyweight web frameworks, it guarantees zero installation friction.

## Key Features
- **Localhost Binding**: Binds exclusively to `127.0.0.1:8765`.
- **Data Redaction**: Intercepts outgoing JSON to automatically mask secrets and API keys using `[REDACTED]`.
- **Stateless Read-Only Shell**: Serves drill-down insights (costs, workers, phases, timelines, approvals) without mutating the underlying project state.

## Usage
Start the server using the unified CLI:
```bash
./agentlab.sh webui --host 127.0.0.1 --port 8765
```
