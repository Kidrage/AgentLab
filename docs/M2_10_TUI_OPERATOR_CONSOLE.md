# M2-10 TUI Operator Console Skeleton

## Overview
The M2-10 TUI provides a terminal control-plane skeleton for project, worker, cost, and approval views. It establishes strict mutation contracts.

## Key Features
- **Headless Snapshot Renderer**: Outputs text-based snapshots for CI and automated testing without requiring interactive terminal libraries.
- **Strict Command Handlers**: All mutation requests (approve, reject, pause) return structured `TUICommandResult` objects demanding explicit `actor` and `reason` signatures.
- **Graceful Fallback**: Safely falls back to headless rendering if optional libraries (`rich`, `textual`) are not installed.

## CLI Usage
- `./agentlab.sh tui --headless --view overview --project <id>`
- `./agentlab.sh tui --headless --view workers`
