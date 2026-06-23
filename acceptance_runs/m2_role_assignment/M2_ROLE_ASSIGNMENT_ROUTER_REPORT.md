# M2-4 Role Activation + Assignment Router v2

## Result

PASS. AgentLab now assigns workers to all nine roles using capability fit,
availability, assignment mode, tier, cost, risk, approval state, fallback
policy, and the M2-3 performance ledger.

## Delivered

- Explainable `route_decision` schema with selection, rejection, activation,
  approval, cost, constraints, fallback, and evidence fields.
- Role assignment engine with deterministic-tool preferences and measured
  performance weighting.
- Coder fallback chain: Claude Code -> Codex -> Aider.
- Mode/tier policies for single CLI, hybrid local, cost-saving, max-quality,
  and front-desk operation.
- High-risk worker and capability approval gate.
- Task-packet routing with task-scoped evidence under
  `projects/<project>/runs/<task>/routing/`.
- CLI commands: `assign-role`, `route-task`, and `route-explain`.
- Restored the conservative executor-router contract (`dry_run`, external API
  providers disabled), repairing a pre-existing M2-2 regression.

## Acceptance Evidence

- Coder selects Claude Code when eligible and falls back to Codex/Aider when
  Claude Code is unavailable.
- RepoScout selects `rg`.
- InterfaceMapper selects `ast_grep`/`sg`.
- TesterAuditor selects `pytest`.
- Verifier selects `ruff`.
- Archivist selects `git`.
- High-risk coding workers emit `activation_decision: require_approval` unless
  explicitly approved.
- Every saved decision includes selection reasons, rejected worker reasons,
  fallback workers, and its evidence path.

## Verification

```text
/usr/bin/python3.11 -m compileall -q agent_runtime agentlab_app.py
PASS

uv run --python 3.11 --with-requirements requirements.txt python -m pytest -q
1470 passed, 2 skipped

uv run --python 3.11 --with-requirements requirements.txt \
  python scripts/audit_text_integrity.py --fail-on-suspicious
933 files scanned, 0 suspicious

./agentlab.sh assign-role --help
./agentlab.sh route-task --help
./agentlab.sh route-explain --help
PASS

/usr/bin/python3.11 scripts/check_remote_raw_integrity.py \
  --repo Kidrage/AgentLab --ref main --fail-on-suspicious
72 remote files checked, 0 suspicious
```
