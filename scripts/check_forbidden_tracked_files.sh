#!/usr/bin/env bash
# AgentLab forbidden tracked files checker
# Exits 0 if clean, exits 1 if forbidden files are tracked.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FORBIDDEN_PATTERNS=(
  "projects/*/agent_docs/*"
  "projects/*/runs/*"
  "projects/*/repo/*"
  "projects/*/evaluation_runs/*"
  "*.local.bak"
  ".env"
  "*.pem"
  "*.key"
)

echo "=== AgentLab Forbidden Tracked Files Check ==="
echo ""

VIOLATIONS=()

for pattern in "${FORBIDDEN_PATTERNS[@]}"; do
  # Use git grep from HEAD to check tracked files
  if git ls-files -- "$pattern" 2>/dev/null | grep -q .; then
    FILES=$(git ls-files -- "$pattern" 2>/dev/null)
    VIOLATIONS+=("$pattern")
    echo "FORBIDDEN: $pattern"
    echo "$FILES" | while read -r f; do echo "  -> $f"; done
    echo ""
  fi
done

echo "Checked ${#FORBIDDEN_PATTERNS[@]} patterns."

if [ ${#VIOLATIONS[@]} -gt 0 ]; then
  echo ""
  echo "FAIL: ${#VIOLATIONS[@]} forbidden pattern(s) found in tracked files."
  echo "These files must be removed from Git tracking (git rm --cached)."
  echo "They will then be ignored by .gitignore."
  exit 1
else
  echo ""
  echo "PASS: No forbidden tracked files detected."
  exit 0
fi