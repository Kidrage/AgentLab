#!/usr/bin/env bash
# AgentLab auto-push hook
# After each commit, push to origin main if we have the remote.
set -euo pipefail

REMOTE=$(git remote get-url origin 2>/dev/null || true)
if [[ -z "$REMOTE" ]]; then
  echo "[agentlab] No remote configured, skipping auto-push."
  exit 0
fi

BRANCH=$(git branch --show-current)
echo "[agentlab] Auto-pushing $BRANCH -> $REMOTE ..."
git push origin "$BRANCH" 2>&1 || echo "[agentlab] Push failed (network may be unavailable). Use 'git push' manually."
