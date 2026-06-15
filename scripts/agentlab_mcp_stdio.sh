#!/usr/bin/env bash
set -euo pipefail

ROOT="${AGENTLAB_ROOT:-}"
if [ -z "$ROOT" ]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

cd "$ROOT"
PYTHON_BIN="$ROOT/agent_runtime/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="${PYTHON:-python3}"
fi
exec "$PYTHON_BIN" -m agent_runtime.mcp_server --serve
