#\!/usr/bin/env bash
# Wrapper for check_forbidden_tracked_files.py — matches CI expectations.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "${SCRIPT_DIR}/check_forbidden_tracked_files.py" "$@"
