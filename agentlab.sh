#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$ROOT/agent_runtime/.venv/bin/python"

# Prefer the project-local runtime when it exists.
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON:-python3}"
fi

# Load optional local environment overrides without requiring them.
if [[ -f "$ROOT/agent_runtime/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/agent_runtime/.env"
  set +a
fi

exec "$PYTHON_BIN" "$ROOT/agent_runtime/run_task.py" "$@"
