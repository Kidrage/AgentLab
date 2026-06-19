#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

# Load optional local environment overrides without requiring them.
if [[ -f "$ROOT/agent_runtime/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/agent_runtime/.env"
  set +a
fi

PROJECT_OPS_COMMANDS=(
  repo-hygiene-check
  project-route
  project-init
  project-status
  task-compact
  agent-contributions
)

if [[ $# -gt 0 ]]; then
  for cmd in "${PROJECT_OPS_COMMANDS[@]}"; do
    if [[ "$1" == "$cmd" ]]; then
      cd "$ROOT"
      exec "$PYTHON_BIN" -m agent_runtime.project_ops.cli "$@"
    fi
  done
fi

exec "$PYTHON_BIN" "$ROOT/agent_runtime/run_task.py" "$@"
