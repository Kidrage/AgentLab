#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SOURCE_REQUEST="$ROOT/projects/AgentLab/runs/task_production_pack_role_session_live_20260710/user_request.md"
TARGET_RUN="$ROOT/projects/AgentLab/runs/task_production_pack_role_session_governed_20260710_01"
AUDIT_OUT="$ROOT/acceptance_runs/agentlab_capability_acceptance/production_pack_role_session_request_audit.yml"

if [[ "${AGENTLAB_PRODUCTION_PACK_CONTEXT_APPROVED:-}" != "1" ]]; then
  echo "blocked: set AGENTLAB_PRODUCTION_PACK_CONTEXT_APPROVED=1 only after explicit informed approval" >&2
  exit 2
fi
if [[ -e "$TARGET_RUN" ]]; then
  echo "blocked: target run already exists: $TARGET_RUN" >&2
  exit 3
fi

cd "$ROOT"
export AGENTLAB_MODE=full_cli

./agentlab.sh init-task   --project AgentLab   --task-id task_production_pack_role_session_governed_20260710_01   --request-file "$SOURCE_REQUEST"   --no-auto-slug

./agentlab.sh prepare   --project AgentLab   --task-id task_production_pack_role_session_governed_20260710_01   --budget max-quality   --write-plan

test -s "$TARGET_RUN/mission_contract.yml"
test -s "$TARGET_RUN/workflow_plan.yml"

./agentlab.sh run-pipeline   --project AgentLab   --task-id task_production_pack_role_session_governed_20260710_01   --budget max-quality   --execute

./agentlab.sh production-pack-role-session-audit   --project AgentLab   --task-id task_production_pack_role_session_governed_20260710_01   --out "$AUDIT_OUT"   --require-pass
