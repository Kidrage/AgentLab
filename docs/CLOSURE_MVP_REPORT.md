# AgentLab Closure MVP Report

## Summary Verdict

Before: the lifecycle smoke task could reach artifact/lifecycle PASS, but `check --strict` returned exit code 0 even when the self-check status was `fail`. Dry-run pipeline evidence helpers also existed without being wired into node completion, and Codex artifact verification only accepted older full-driver artifact names.

After: AgentLab has a verifiable dry-run lifecycle MVP. A fresh smoke task can initialize, prepare, run the dry-run pipeline, pass lifecycle/artifact checks, pass strict self-check, write a terminal handoff packet, and pass Codex artifact verification without paid model calls.

## What Was Fixed

- `check --strict` now exits nonzero when self-check status is `fail`.
- Strict self-check warnings are recorded as blocking reasons.
- Dry-run lifecycle nodes now record explicit command evidence in `execution_log.yml`.
- Dry-run lifecycle nodes now append explicit zero-cost fake-provider entries to `cost_ledger.yml`.
- Numbered lifecycle artifacts now write compatible alias files such as `implementation_report.md`, `validation_report.md`, and `archive_update.md`.
- Codex artifact validation now accepts lifecycle MVP equivalents:
  - `artifact_manifest.yml` for `codex_driver_manifest.yml`
  - `lifecycle.yml` for `00_preflight_report.md`
  - `05_coder_prompt.md` for `05_codex_prompt.md`
- Completed handoff packets no longer claim a resume agent.
- A root `requirements.txt` was added for local/CI dependency installation.
- Closure smoke run directories are ignored to avoid committing generated task clutter.

## Commands That Prove Closure

```bash
./agentlab.sh init-task --project AgentLab --task-id task_0999_closure-smoke-v2 --request-text "Smoke test AgentLab closed-loop lifecycle: prepare, dry-run pipeline, artifact check, self-check, handoff." --no-auto-slug
./agentlab.sh prepare --project AgentLab --task-id task_0999_closure-smoke-v2 --write-plan
./agentlab.sh run-pipeline --project AgentLab --task-id task_0999_closure-smoke-v2 --dry-run
./agentlab.sh lifecycle-status --project AgentLab --task-id task_0999_closure-smoke-v2
./agentlab.sh artifact-check --project AgentLab --task-id task_0999_closure-smoke-v2
./agentlab.sh check --project AgentLab --task-id task_0999_closure-smoke-v2 --strict
./agentlab.sh codex-handoff --project AgentLab --task-id task_0999_closure-smoke-v2
./agentlab.sh codex-verify-artifacts --project AgentLab --task-id task_0999_closure-smoke-v2
```

## Tests Added Or Updated

- Added strict self-check regression tests.
- Added dry-run closure evidence regression coverage.
- Added Codex artifact validator equivalent-name coverage.
- Added terminal handoff semantics coverage.

## Validation Results

```bash
python3 -m pytest -q
# 118 passed in 32.03s

bash -n agentlab.sh
# pass

./agentlab.sh doctor --project AgentLab
# All checks passed.

./agentlab.sh run-pipeline --project AgentLab --task-id task_0999_closure-smoke-v2 --dry-run
# Final status: completed
# Artifact pass_rate: 1.0 (15/15)

./agentlab.sh check --project AgentLab --task-id task_0999_closure-smoke-v2 --strict
# Self-Check: PASS

./agentlab.sh codex-verify-artifacts --project AgentLab --task-id task_0999_closure-smoke-v2
# Result: pass
```

## Known Limitations

- This is a verifiable dry-run lifecycle MVP, not proof of real autonomous API execution.
- Dry-run token and cost values are explicit zero-cost fake-provider records.
- The smoke request routed as a small task in `workflow_plan.yml`; the lifecycle runner still produced RepoScout and Archivist artifacts as part of the configured lifecycle. For forced medium-task routing, update routing policy or use a larger request.
- The handoff packet still reports `last_completed_agent: null` for lifecycle-completed dry-run tasks because lifecycle completion does not currently populate `state.completed_agents`.
- GitHub Actions workflow creation was not included in the pushed commit because the available GitHub OAuth credential lacks `workflow` scope.

## Next Recommended Improvements

- Sync lifecycle node completion into `state.completed_agents`.
- Add a medium-route fixture that explicitly exercises Researcher, InterfaceMapper, and Verifier.
- Move Codex full-driver wrapper inline Python into first-class Typer commands.
- Add GitHub Actions CI once the pushing credential has `workflow` scope.
- Expand CI to run a deterministic smoke pipeline in a temporary project.
