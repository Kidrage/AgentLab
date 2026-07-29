#!/usr/bin/env bash
set -euo pipefail

agentlab_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
evidence_root="${AGENTLAB_RADAR_EVIDENCE_ROOT:-${HOME}/.agentlab_runtime/capability_radar}"
run_id="$(date -u +%Y%m%dT%H%M%SZ)"
run_root="${evidence_root}/${run_id}"

mkdir -p "${run_root}"

for profile in code agents narrative media research; do
  "${agentlab_root}/agentlab.sh" capability radar \
    --profile "${profile}" \
    --source all \
    --record-vault \
    --output "${run_root}/${profile}.yml"
done
