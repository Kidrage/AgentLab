# AgentLab M2-3 — Worker Audition / Performance Ledger Report

## Verdict
PASS

## Baseline
- **branch**: `main`
- **before commit**: `40eb6a7` (feat(runtime): implement M2-2 capability schema and 9-role requirement matrix)
- **current staging status**: Staging and committing deferred to user preference.
- **remote**: `https://github.com/Kidrage/AgentLab.git`
- **CI**: Passing locally (`pytest tests/test_m2_audition_*` + `pytest tests/test_m2_worker_*` all green)

## Summary
Introduced worker audition capabilities and a performance ledger to evaluate worker performance dynamically instead of trusting static defaults.
- Audition runner sets up a temporary `AuditionSandbox` environment using mock files to prevent mutating user repositories.
- Mock worker execution is the default mode (opt-in for real CLI execution via `--real` flag to satisfy safety constraints).
- Scorer evaluates worker runs based on 8 dimensions: `success_rate`, `cost_score`, `latency_score`, `safety_score`, `diff_minimality_score`, `evidence_quality_score`, `operator_friction_score`, and `role_fit_score`.
- Audition runs produce structured scorecards and save metrics to the `config/worker_performance_ledger.yml` file.
- The performance ledger supports sorting/querying compatible workers for a role based on historical fit scores, which will influence route assignment in subsequent stages.

## Changed Files
- `agent_runtime/workers/__init__.py`: Exported worker audition module public functions.
- `agent_runtime/run_task.py`: Registered `worker-audition` and `worker-scorecard` commands.

## New Runtime Modules
- `agent_runtime/workers/performance_ledger.py`: Handles serialization and loading of worker performance ledger data.
- `agent_runtime/workers/sandbox.py`: Isolates test execution contexts within temporary repository scopes.
- `agent_runtime/workers/audition_tasks.py`: Encapsulates role-specific audition tasks and expectation specifications.
- `agent_runtime/workers/audition_scorer.py`: Calculates multi-dimensional performance scores.
- `agent_runtime/workers/audition_runner.py`: Orchestrates mock and sandbox executions.
- `agent_runtime/workers/audition.py`: High-level worker evaluation runner and report manager.

## New Configs
- `config/worker_performance_ledger.yml`: Main ledger file persisting worker execution stats (automatically created on first audition).

## New CLI
- `./agentlab.sh worker-audition --all --level quick`: Audition all discovered workers on compatible roles.
- `./agentlab.sh worker-audition --worker <id> --role <RoleName> --level standard`: Run a specific audition task for a worker.
- `./agentlab.sh worker-scorecard`: Consolidate and render scorecard results for all audited workers.

## Artifacts Produced
- `acceptance_runs/m2_worker_audition/M2_WORKER_AUDITION_REPORT.md` (this file)

## Tests Added
- `tests/test_m2_audition_scorer.py`: Validates calculation of fit, cost, latency, safety, and other metrics.
- `tests/test_m2_worker_performance_ledger.py`: Validates ledger load/save persistence and best worker selection query.
- `tests/test_m2_worker_audition.py`: Verifies sandbox isolation setup, mock run success, and Typer CLI commands execution.

## Tests Run
```bash
agent_runtime/.venv/bin/python -m pytest tests/test_m2_audition_scorer.py tests/test_m2_worker_performance_ledger.py tests/test_m2_worker_audition.py
```
Output:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.13, pytest-8.4.2, pluggy-1.6.0
rootdir: <CLOUD_WORKSPACE>
configfile: pytest.ini
plugins: langsmith-0.8.18, anyio-4.14.0
collecting ... collected 7 items                                                              

tests/test_m2_audition_scorer.py ..                                      [ 28%]
tests/test_m2_worker_performance_ledger.py ..                            [ 57%]
tests/test_m2_worker_audition.py ...                                     [100%]

============================== 7 passed in 13.56s ==============================
```


## Safety Notes
- Sandbox environments copy mock configurations to temporary folders, guaranteeing zero user repository mutation.
- Real external CLI execution is strictly opt-in, defaulting to safe mock simulations.

## Known Limitations
- Ledger results are compiled locally. Centralized sync of scores between offices remains for later mainline integrations.

## Next Recommended Stage
- **M2-4 — Role Activation + Assignment Router v2**: Adapt the task-budget and agent-router lifecycle to automatically select workers based on capabilities and ledger performance scores.
