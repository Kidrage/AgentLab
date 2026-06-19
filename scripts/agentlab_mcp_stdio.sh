#!/usr/bin/env bash
set -euo pipefail

ROOT="${AGENTLAB_ROOT:-}"
if [ -z "$ROOT" ]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

cd "$ROOT"
PYTHON_BIN="$ROOT/agent_runtime/.venv/bin/python"

_python_has_runtime_deps() {
  "$1" - <<'PY' >/dev/null 2>&1
import typer
import yaml
PY
}

# Prefer the project-local runtime when it exists, then an explicit PYTHON,
# then the CI/setup-python interpreter exposed as `python`, and finally
# `python3`. This keeps subprocess CLI tests on the same dependency-bearing
# interpreter as the GitHub Actions install step.
if [[ ! -x "$PYTHON_BIN" ]]; then
  if [[ -n "${PYTHON:-}" ]]; then
    PYTHON_BIN="$PYTHON"
  elif command -v python >/dev/null 2>&1 && _python_has_runtime_deps "$(command -v python)"; then
    PYTHON_BIN="$(command -v python)"
  elif command -v python3 >/dev/null 2>&1 && _python_has_runtime_deps "$(command -v python3)"; then
    PYTHON_BIN="$(command -v python3)"
  else
    PYTHON_BIN="python3"
  fi
fi
exec "$PYTHON_BIN" -m agent_runtime.mcp_server --serve
