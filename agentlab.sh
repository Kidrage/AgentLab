#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" == "bootstrap" ]]; then
  shift
  exec bash "$ROOT/scripts/bootstrap.sh" "$@"
fi

PYTHON_BIN="$ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" && -x "$ROOT/.venv/bin/python3" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python3"
elif [[ ! -x "$PYTHON_BIN" && -x "$ROOT/agent_runtime/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/agent_runtime/.venv/bin/python"
elif [[ ! -x "$PYTHON_BIN" && -x "$ROOT/agent_runtime/.venv/bin/python3" ]]; then
  PYTHON_BIN="$ROOT/agent_runtime/.venv/bin/python3"
fi

_python_has_runtime_deps() {
  "$1" - <<'PY' >/dev/null 2>&1
import typer
import yaml
import dotenv
import pydantic
import rich
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

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  cat >&2 <<EOF
AgentLab bootstrap error [blocking]: Python was not found at '$PYTHON_BIN'.
Install Python 3.11-3.13, or set PYTHON to a compatible interpreter.
EOF
  exit 2
fi

if ! _python_has_runtime_deps "$PYTHON_BIN"; then
  cat >&2 <<'EOF'
AgentLab bootstrap error [blocking]: runtime dependencies are not installed.
Run the deterministic project bootstrap first:

  ./agentlab.sh bootstrap

Then retry the requested command. See README.md for supported Python versions.
EOF
  exit 2
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
