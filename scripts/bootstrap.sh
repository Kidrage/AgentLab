#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="${AGENTLAB_VENV_PATH:-$ROOT/.venv}"
BOOTSTRAP_PYTHON="${AGENTLAB_BOOTSTRAP_PYTHON:-}"

usage() {
  cat <<'EOF'
Usage: ./agentlab.sh bootstrap

Create the project-local virtual environment and install the hash-locked
AgentLab dependencies. Supported Python versions: 3.11, 3.12, and 3.13.

Optional environment variables:
  AGENTLAB_BOOTSTRAP_PYTHON  Python interpreter used to create the venv
  AGENTLAB_VENV_PATH         Virtual environment path (default: .venv)
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 0 ]]; then
  usage >&2
  exit 2
fi

if [[ -z "$BOOTSTRAP_PYTHON" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    BOOTSTRAP_PYTHON="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    BOOTSTRAP_PYTHON="$(command -v python)"
  else
    echo "AgentLab bootstrap error [blocking]: Python 3.11-3.13 was not found." >&2
    exit 2
  fi
fi

if ! command -v "$BOOTSTRAP_PYTHON" >/dev/null 2>&1; then
  echo "AgentLab bootstrap error [blocking]: '$BOOTSTRAP_PYTHON' is not executable." >&2
  exit 2
fi

if ! "$BOOTSTRAP_PYTHON" - <<'PY'
import sys

if not ((3, 11) <= sys.version_info[:2] < (3, 14)):
    raise SystemExit(1)
PY
then
  echo "AgentLab bootstrap error [blocking]: supported Python versions are 3.11-3.13." >&2
  exit 2
fi

if [[ ! -x "$VENV_PATH/bin/python" ]]; then
  "$BOOTSTRAP_PYTHON" -m venv "$VENV_PATH"
fi

LOCK_FILE="$ROOT/requirements.lock"
if [[ ! -f "$LOCK_FILE" ]]; then
  echo "AgentLab bootstrap error [blocking]: requirements.lock is missing." >&2
  exit 2
fi

"$VENV_PATH/bin/python" -m pip install --require-hashes -r "$LOCK_FILE"

cat <<EOF
AgentLab bootstrap complete.
Python: $VENV_PATH/bin/python
Next:   ./agentlab.sh repository-handoff --repo .
EOF
