#!/usr/bin/env bash
set -euo pipefail

ROOT="${AGENTLAB_ROOT:-}"
if [ -z "$ROOT" ]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

cd "$ROOT"
exec python3 -m agent_runtime.mcp_server --serve
