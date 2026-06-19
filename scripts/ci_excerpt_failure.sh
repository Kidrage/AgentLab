#!/usr/bin/env bash
# Diagnostic: emit a GitHub Actions ::error annotation with pytest failure summary.
# Reads pytest-output.txt (produced by `pytest ... 2>&1 | tee pytest-output.txt`).
set -euo pipefail

marker_lines=$(grep -n -E "^(FAILURES|short test summary info|ERRORS)" pytest-output.txt 2>/dev/null || true)

if [ -z "$marker_lines" ]; then
  echo "::error title=pytest failure excerpt::(pytest failed but no standard markers found — last lines) $(tail -30 pytest-output.txt | sed 's/%/%25/g; s/\r/%0D/g; s/\n/%0A/g')"
  exit 0
fi

first_line=$(echo "$marker_lines" | head -1 | cut -d: -f1)
excerpt=$(tail -n +"$first_line" pytest-output.txt | tail -50)

# Escape for GitHub workflow command
excerpt="${excerpt//%/\%25}"
excerpt="${excerpt//$'\r'/\%0D}"
excerpt="${excerpt//$'\n'/\%0A}"

echo "::error title=pytest failure excerpt::${excerpt}"
