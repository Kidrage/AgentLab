# AgentLab Current Bug, Risk, and Performance Audit

Generated: 2026-06-07
Auditor: Codex local review
Repository: `/Users/saintpeter/Desktop/AgentLab`

## Scope

This audit reviewed the current dirty working tree of AgentLab, including source
code, config, project memory, recent task runs, known bug reports, and local
CLI behavior. It did not call external model APIs and did not modify source
code. It did create this report, a local performance-eval run under
`task_0033_codex_current_audit_perf`, and a budget matrix under
`task_0032_self_audit`. Running `task-open` also refreshed generated task index
artifacts (`task_snapshot.yml`, `artifact_manifest.yml`, `task_card.yml`) across
older run directories.

## Validation Commands Run

- `python3 -m pytest -q`: PASS, 18 tests passed in 1.27s.
- `python3 -B -m compileall -q agent_runtime tests`: PASS.
- `./agentlab.sh doctor --project AgentLab --json-output`: PASS.
- `./agentlab.sh model-doctor --project AgentLab`: PASS, 0 model wiring issues.
- `./agentlab.sh performance-eval --project AgentLab --task-id task_0033_codex_current_audit_perf`: PASS score 100/100, but local deterministic only.
- `./agentlab.sh budget-eval --project AgentLab --task-id task_0032_self_audit`: wrote budget matrix.
- `./agentlab.sh lifecycle-status --project AgentLab --task-id task_0032_self_audit`: validation FAIL, 5/14 completed, 1 skipped.
- `./agentlab.sh artifact-check --project AgentLab --task-id task_0032_self_audit`: FAIL, pass rate 0.79.
- `./agentlab.sh migration-doctor --project AgentLab --json-output --no-write-probe`: FAIL due missing GitHub token, missing Web UI token, missing TrueNAS mount.
- `./agentlab.sh truenas-status --project AgentLab --json-output --no-write-probe`: FAIL, mount path missing.
- `./agentlab.sh backup-status --project AgentLab --json-output`: WARN.
- `./agentlab.sh guard-status --project AgentLab --task-id task_0032_self_audit`: FAIL, command does not exist.
- `./agentlab.sh recover --scan`: FAIL, command does not exist.

## Executive Summary

AgentLab's local CLI/runtime core is healthy enough for local L1/L2 tasks:
syntax, tests, config parsing, and model registry wiring all pass. The current
implementation is not yet reliable for unattended L3 multi-agent execution.

The main unresolved problems are not import crashes or basic CLI failures. They
are closure problems:

- state, progress, lifecycle, snapshot, and UI views can disagree;
- artifact gates catch some bad reports but do not always update all status
  stores;
- Archivist memory write-back prompt/format does not match the parser contract;
- budget thresholds are visible after the fact but not enforced before expensive
  calls;
- Web UI execution endpoints are not broadly protected by auth despite binding
  to `0.0.0.0`;
- docs mention recovery commands that are absent from the CLI.

## P0 / High Severity Findings

### 1. Web UI has unauthenticated execution endpoints

`web_ui/server.py` binds to `0.0.0.0` and sets CORS to `*`. Only TrueNAS execute
sync uses `_web_execute_authorized`; endpoints such as `/api/decision`,
`/api/agent/action`, `/api/task/create`, `/api/task/nl`, and
`/api/task/run-next` execute local AgentLab commands without token enforcement.

Risk: if the server is reachable on LAN, another machine can trigger model API
calls or local task operations.

Evidence:
- `web_ui/server.py:1004-1007` sends permissive CORS headers.
- `web_ui/server.py:1153-1188` routes POST execution endpoints without auth,
  except `/api/backup/truenas-sync`.
- `web_ui/server.py:1198-1200` binds `HTTPServer(("0.0.0.0", port), ...)`.
- `config/migration_profile.yml:39-44` also describes Web UI as host `0.0.0.0`
  with auth required.

Recommended fix: require `AGENTLAB_WEB_UI_TOKEN` for all POST endpoints and any
artifact/config endpoint that returns local project content. Default bind host
should be `127.0.0.1`; `0.0.0.0` should require an explicit env flag.

### 2. Pipeline block paths leave progress.yml stale

When artifact gate blocks a node, `_block_on_artifact_gate` updates lifecycle and
state, but not `progress.yml`. In `task_0032_self_audit`, this produced:

- `state.yml`: `status: blocked`
- `lifecycle.yml`: `REPO_CONTEXT: failed`, `VALIDATION: failed`, `AUDIT/VERIFY: running`
- `progress.yml`: `status: running`, `last_event: Archivist completed`
- `task_snapshot.yml`: drift includes `status_mismatch`

Evidence:
- `agent_runtime/pipeline_runner.py:342-385` writes block files and state but
  never updates progress.
- `projects/AgentLab/runs/task_0032_self_audit/task_snapshot.yml` records
  `state: blocked`, `progress: running`, `lifecycle: blocked`.
- `./agentlab.sh progress --project AgentLab --task-id task_0032_self_audit`
  reports running at 61% even though task status is blocked.

Recommended fix: all terminal or paused transitions should go through one
central state transition helper that updates state, lifecycle, progress, and
snapshot together.

### 3. Archivist memory write-back contract is mismatched

`memory_writer` only parses `<<<AGENTLAB_EDIT path ... >>>` search/replace
blocks. The Archivist report in `task_0032_self_audit` used HTML comment style:
`<!-- AGENTLAB_EDIT: agent_docs/02_TASK_LEDGER.yml -->`. The parser finds zero
blocks, so durable memory is not updated.

Evidence:
- `agent_runtime/patch_applicator.py:43-50` defines the only accepted edit block
  grammar.
- `agent_runtime/memory_writer.py:152-157` delegates to that parser and falls
  back when no blocks are found.
- `agent_runtime/agent_runner.py:113-121` tells Archivist to include edit blocks
  but does not show the exact syntax.
- `projects/AgentLab/runs/task_0032_self_audit/USER_DECISION_REQUIRED.md`
  contains an HTML-style edit block and then says structured edit blocks found: 0.

Recommended fix: put the exact `<<<AGENTLAB_EDIT ... >>>` syntax into the
Archivist template and agent_runner system prompt, or extend the parser to
accept the HTML comment syntax. Add a regression test using the real
`task_0032` Archivist output shape.

### 4. Budget thresholds are advisory, not enforced

`task_0032_self_audit` was estimated at 60,000 tokens in balanced L3 mode, but
the task consumed 119,459 tokens before blocking. Several agents exceeded their
stop thresholds, and `brain-status` only reports `ask_user` after the spending
already happened.

Evidence:
- `projects/AgentLab/runs/task_0032_self_audit/cost_ledger.yml` totals:
  Supervisor 24,094, Researcher 23,141, InterfaceMapper 23,462,
  TesterAuditor 23,516, Archivist 25,246.
- `./agentlab.sh budget-eval` estimates balanced L3 at 60,000 tokens.
- `agent_runtime/brain_governor.py:99-127` computes token status.
- `agent_runtime/brain_governor.py:300-359` uses the token status only during
  traversal decisions, not before every model call.

Recommended fix: before `generate_text`, check the agent's predicted input
against remaining budget; require user decision before the call that would pass
the stop threshold.

## P1 / Medium Severity Findings

### 5. Performance evaluator score is inflated for closure reliability

The local performance evaluator scored 100/100, but it does not call models, does
not validate real provider failover, and programmatically marks lifecycle nodes
complete. It is a smoke test, not an end-to-end stability benchmark.

Evidence:
- `agent_runtime/performance_evaluator.py:1-6` says it is local-only.
- `agent_runtime/performance_evaluator.py:161-177` changes waiting lifecycle
  nodes to completed.
- Current run reports only two timed commands: py_compile 71.6 ms and
  policy-status 650.7 ms.

Recommended fix: rename score interpretation to "local smoke score" or add a
separate end-to-end score that includes fake-provider semantic failures,
progress drift, memory write-back, and resume behavior.

### 6. progress.yml schema is inconsistent

The normal progress schema uses `percent_complete` and an `agents` mapping. The
performance evaluator writes `percent` and an `agents` list. The `progress` CLI
therefore prints `completed` with `Progress: 0%` for
`task_0033_codex_current_audit_perf`.

Evidence:
- `agent_runtime/progress_tracker.py:187-209` reads `percent_complete`.
- `agent_runtime/performance_evaluator.py:299-311` writes `percent: 100` and
  `agents` as a list.
- `./agentlab.sh progress --project AgentLab --task-id task_0033_codex_current_audit_perf`
  prints completed / 0%.

Recommended fix: make all writers use `create_progress`/`save_progress`, or make
`progress_summary` accept both schemas consistently.

### 7. Snapshot drift is detected but artifact-check does not fail it

`task_snapshot.yml` can record `status_mismatch`, but `artifact-check` still
passes or only checks file presence/content placeholders. That means a task can
have inconsistent authoritative state but still appear artifact-valid.

Evidence:
- `agent_runtime/task_snapshot.py:232-245` detects drift.
- `agent_runtime/artifact_contract.py:119-198` does not inspect snapshot drift.
- `task_0032_self_audit` has drift but artifact-check reports only report
  placeholder/missing finalization artifacts.
- `task_0033_codex_current_audit_perf` artifact-check passes despite stale
  snapshot source statuses (`state: unknown`, `progress: unknown`) generated
  before state/progress were written.

Recommended fix: artifact contract should fail when `task_snapshot.yml` has
non-empty drift or unknown source statuses for finalized tasks.

### 8. README and generated docs reference missing recovery commands

README says `./agentlab.sh guard-status` exists, and run-agent lock conflict
message tells the user to run `./agentlab.sh recover --scan`. Neither command is
available.

Evidence:
- `README.md` references `guard-status`.
- `agent_runtime/run_task.py:884-888` prints `recover --scan` on lock conflict.
- Both commands fail in current CLI.

Recommended fix: add `guard-status` and `recover` commands around `guard.py`, or
remove/update the docs and error messages.

### 9. Web UI status display uses stale/hard-coded provider assumptions

Web UI status hard-codes provider/model labels and checks `QWEN_API_KEY`, while
the current config uses `DASHSCOPE_API_KEY`. Blocked events are shown as
"DeepSeek API timeout" regardless of actual provider or blocker reason.

Evidence:
- `web_ui/server.py:406-416` hard-codes DeepSeek for non-Coder and Codex Plus
  for Coder.
- `web_ui/server.py:453-460` hard-codes the blocked event text.
- `web_ui/server.py:500-504` checks `QWEN_API_KEY` instead of the current
  DashScope env key.

Recommended fix: derive provider/model/status from `progress.yml`,
`model_profiles`, and `provider_incidents.yml`.

### 10. Backup and migration configuration conflict

Global backup policy has GitHub enabled, while the AgentLab project config has
GitHub backup disabled. `migration-doctor` treats `GITHUB_TOKEN` as required and
fails; `backup-status` says GitHub enabled is false.

Evidence:
- `config/backup_policy.yml:9-20` has GitHub target enabled.
- `projects/AgentLab/project_config.yml:10-17` has `github.backup.enabled: false`.
- `migration-doctor` fails on missing `GITHUB_TOKEN`.
- `backup-status` reports GitHub enabled false.

Recommended fix: make migration-doctor honor project-level backup disabled, or
make project config enable backup when migration profile requires it.

## P2 / Lower Severity Findings

### 11. Guard locking is not a true exclusive create

`guard.acquire_lock` checks whether a lock file exists and then writes it. Two
processes racing at the same time can both observe no lock and write. This is a
classic check-then-write race.

Evidence:
- `agent_runtime/guard.py:70-93` uses exists/read/write, not `O_EXCL` or atomic
  create.

Recommended fix: use `os.open(..., O_CREAT | O_EXCL)` or a platform file lock.

### 12. Several ledger/report writes are non-atomic

Core state/lifecycle/progress use atomic helpers, but cost ledger, brain
decisions, some manifests, and performance reports use direct `write_text`.
Concurrent or interrupted writes can corrupt those files.

Evidence:
- `agent_runtime/cost_tracker.py:13-21` appends via read/modify/direct write.
- `agent_runtime/brain_governor.py:22-27` appends decisions via direct write.
- `agent_runtime/artifact_contract.py:306-318` writes manifest via direct write.
- `agent_runtime/performance_evaluator.py` uses direct writes for many artifacts.

Recommended fix: standardize these through `atomic_write_yaml` /
`atomic_write_text` and add append-locking for ledgers.

### 13. Artifact manifest marks route-irrelevant implementation/handoff as important

`task-open` shows `06_implementation_report.md` and `handoff_packet.yml` as
important even when the route intentionally skips Coder. This creates false
negative/misleading UI for analysis-only tasks.

Evidence:
- `agent_runtime/task_index.py:176-189` marks implementation and handoff as
  important unconditionally.
- `task_0033_codex_current_audit_perf` is completed but `task-open` shows
  missing implementation/handoff.

Recommended fix: make importance route-aware.

## Current Performance Assessment

### Local CLI performance

The CLI is fast enough for local use:

- pytest: 18 tests in 1.27s.
- compileall: completed without output.
- performance-eval command timing:
  - `python3 -m py_compile agent_runtime/task_router.py agent_runtime/lifecycle_graph.py`: 71.6 ms.
  - `./agentlab.sh policy-status --project AgentLab`: 650.7 ms.
- `doctor` completed in about 4 seconds and passed.

### Model/API workflow performance

Current L3 API-agent workflow is costly and brittle:

- `task_0032_self_audit` consumed 119,459 model tokens and still blocked.
- Balanced L3 estimate for that task was 60,000 tokens.
- The task did not complete artifact closure; artifact pass rate is 0.79.
- One provider failure caused RepoScout to block, yet later nodes still ran,
  leaving lifecycle inconsistent.

### Benchmark caveat

The 100/100 performance score is not a production readiness score. It verifies
routing/config/lifecycle smoke behavior in a controlled local mode. The older
evaluation summary is still more realistic for readiness: 65/100, MVP ready,
with lifecycle and artifact completeness as blocking P0 areas.

## Recommended Repair Order

1. Lock down Web UI: token-check all POST endpoints, validate artifact paths,
   bind localhost by default.
2. Introduce a single task transition API that updates lifecycle, state,
   progress, and snapshot together.
3. Fix Archivist edit-block prompt/parser mismatch and add real memory write
   tests based on `task_0032_self_audit`.
4. Enforce token budgets before model calls.
5. Make artifact-check fail on snapshot drift and unknown source statuses.
6. Normalize progress schema everywhere.
7. Add or remove missing `guard-status` / `recover --scan` CLI docs.
8. Make performance-eval score names honest: local smoke score vs end-to-end
   reliability score.
9. Align backup/migration policy with project-level GitHub backup settings.
10. Make guard locks and ledger writes atomic.

## Bottom Line

AgentLab is currently usable as a local-first task ledger, routing planner, CLI
wrapper, and smoke-tested agent workflow scaffold. It is not yet safe for
unattended high-cost or production-critical multi-agent execution. The biggest
risk is not that it cannot run; it can. The risk is that it can spend tokens,
write plausible-looking reports, and leave the task half-blocked while different
status surfaces disagree about what happened.
