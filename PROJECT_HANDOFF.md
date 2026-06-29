# AgentLab Project Handoff

Last updated: 2026-06-29
Owner context: Codex local coding agent
Repository: `/Users/saintpeter/Desktop/AgentLab`
Branch: `main`
Current status: active long-running repair and cleanup

## Purpose

This file is the explicit project-root handoff for the current AgentLab repair effort. It is meant to be read first by any human, frontdesk role, brain/planning layer, or non-AgentLab agent that needs to understand what is happening in this repository without reconstructing state from scattered run folders, commits, or agent-to-agent notes.

AgentLab already has several narrower handoff mechanisms:

- repository inventory handoff: `.agentlab/HandOff.md`, `agent_docs/HandOff.md`, `HandOff.md`
- executor/run handoffs: `projects/<Project>/runs/<task_id>/...`
- external-agent handoffs: `external_handoff.md` / `external_handoff.yml`
- Codex/API continuation handoffs: `handoff_packet.yml`

Those are useful, but not direct enough as a project dashboard. This file records the active project direction, progress, decisions, remaining work, validation evidence, and next entry point.

## Current Goal

Original long-running goal:

```text
Complete the domain-aware mission compiler plan, verify with real demos that the system is not broken, ensure generalized tasks execute smoothly, commit to main, and confirm CI.
```

Updated goal change on 2026-06-29:

```text
Remove the shutdown requirement. Before final completion, implement a first-class explicit project-root handoff mechanism for AgentLab projects.
```

The final state is not achieved yet. Do not mark the active goal complete until all remaining requirements below are implemented and verified.

## Latest Product Requirement: Project Root Handoff

Every time AgentLab creates a project or materially changes a project, AgentLab must leave an explicit handoff file in the project root. The handoff must make the project immediately understandable and transferable.

Required readers:

- any non-AgentLab coding agent taking over the repository
- AgentLab frontdesk role
- AgentLab brain/planning layer
- human operator requesting a progress report
- future executor looking for a safe starting point

Required content:

- current project progress
- changes already made
- primary direction and project intent
- persistent memory and important context
- what is being worked on now
- rough remaining work / completion estimate
- pending decisions
- pending files to modify
- plans still needing confirmation
- artifacts still needing acceptance
- validation evidence and CI status
- safe next commands
- known risks and non-goals

Implementation expectation:

- The file should be project-root-visible, not buried only under `.agentlab/` or `projects/<Project>/runs/...`.
- It should preserve a manual notes section across automated refreshes.
- It should be updated after material changes and before final reports.
- It should be deterministic where possible and not leak secrets.
- It should integrate with existing repository handoff policy instead of creating an unrelated one-off mechanism.

Candidate canonical filename:

```text
PROJECT_HANDOFF.md
```

Compatibility discovery should continue to recognize:

```text
HandOff.md
HANDOFF.md
.agentlab/HandOff.md
agent_docs/HandOff.md
```

## Work Completed So Far

Mission compiler and domain-aware routing:

- `4de7dec Add domain-aware creative writing mission routing`
- Added mission contract fields for mission flow, task domain, artifact type, memory contract, quality gates, route decision, and route proposal.
- Added `creative_writing` domain pack and `fiction_chapter_pipeline`.
- Added Writer / Reviewer / Scribe role aliases and templates.
- Added route guardrails so creative writing does not silently fall into generic software/artifact routes.

Cleanup/refactor slices:

- `98a675c Start cleanup with route catalog and config inventory`
- `d8568de Extract role capability CLI commands`
- `166f8e3 Extract protocol CLI commands`
- `8c1e97a Extract external project CLI commands`
- `7b084ec Extract routing CLI commands`
- `9bcc6b9 Extract capability contract CLI commands`
- `0c5ed2e Extract runtime hygiene CLI commands`
- `e3fb07e Extract worker CLI commands`

Current cleanup result:

- `agent_runtime/run_task.py` reduced from roughly 7063 lines to 6169 lines.
- New root CLI command modules live under `agent_runtime/cli/`.
- Each slice was verified with targeted tests, three demo commands, full pytest, push to `main`, and GitHub Actions success.

Latest known CI evidence:

- `Extract worker CLI commands` passed CI: run `28346262894`
- Previous 7 `main` CI runs also passed at the time this handoff was written.

## Current Repository State

Known current worktree state at handoff creation:

```text
git status --short
 M agent_runtime/artifact_contract.py
?? PROJECT_HANDOFF.md
```

`agent_runtime/artifact_contract.py` was already dirty while this handoff was being written. It appears to add a mock manifest fallback in `_check_repo_analysis_evidence`. Do not include or revert that change unless the current task explicitly owns artifact evidence behavior.

Latest local history at handoff creation:

```text
e3fb07e Extract worker CLI commands
0c5ed2e Extract runtime hygiene CLI commands
9bcc6b9 Extract capability contract CLI commands
7b084ec Extract routing CLI commands
8c1e97a Extract external project CLI commands
166f8e3 Extract protocol CLI commands
d8568de Extract role capability CLI commands
98a675c Start cleanup with route catalog and config inventory
4de7dec Add domain-aware creative writing mission routing
```

## Validation Commands Used Repeatedly

Targeted examples:

```bash
python3 -m py_compile agent_runtime/run_task.py agent_runtime/cli/<module>.py
python3 -m pytest -q tests/test_m2_worker_cli.py tests/test_m2_worker_audition.py
python3 -m pytest -q tests/test_s9_capability_fabric.py
python3 -m pytest -q tests/test_m2_role_assignment_router.py tests/test_m2_7_pipeline_observability_smoke.py
```

Demo gates:

```bash
./agentlab.sh eval-generalization --out /private/tmp/<run>
./agentlab.sh m1-demo --out /private/tmp/<run>
./agentlab.sh m2-operator-demo --out /private/tmp/<run> --project AgentLab
```

Full verification:

```bash
python3 -m pytest -q
gh run list --branch main --limit 8
gh run view <run_id> --json status,conclusion,url,headSha
```

Known test side effect:

```text
python3 -m pytest -q modifies config/worker_performance_ledger.yml.
Restore the timestamp/count/comment-only changes before committing unless the task intentionally changes worker performance state.
```

## Remaining Work

Immediate next implementation slice:

1. Implement first-class project-root handoff support.
2. Update `agent_runtime/repository_handoff.py` / policy so project-root `PROJECT_HANDOFF.md` is a canonical write target or explicit project-level companion.
3. Add CLI support such as `project-handoff`, `project-handoff-refresh`, or extend `repository-handoff`.
4. Ensure the writer preserves manual notes.
5. Ensure project creation and material project changes can refresh the file.
6. Add tests for root handoff creation, discovery, update preservation, and required sections.

Continuing cleanup after handoff mechanism:

- Continue splitting remaining `run_task.py` command groups.
- Centralize scattered YAML/config reads through existing config loader/safe IO helpers.
- Consolidate registry/config source-of-truth boundaries.
- Classify tracked runtime artifacts and legacy paths.
- Add cleanup invariants where the system has repeated side effects.
- Run final requirement-by-requirement audit before marking complete.

## Pending Decisions

- Canonical filename: use `PROJECT_HANDOFF.md` or `HandOff.md` for project-root visibility.
  - Current recommendation: `PROJECT_HANDOFF.md`, while continuing discovery compatibility with `HandOff.md` / `HANDOFF.md`.
- Whether AgentLab should update the root handoff automatically on every material project mutation or require explicit refresh plus gate enforcement.
  - Current recommendation: deterministic refresh on project creation, after accepted material changes, and before final report.
- Whether handoff should live in every external project root or only AgentLab-managed project directories.
  - Current recommendation: every AgentLab-managed project root; external repositories get a compatible root handoff only when AgentLab has write permission and user policy allows it.

## Files Likely To Modify Next

Likely:

- `agent_runtime/repository_handoff.py`
- `config/repository_handoff_policy.yml`
- `agent_runtime/cli/protocol.py`
- `agent_runtime/run_task.py` if command registration is needed
- tests around repository handoff / protocol enforcement
- this file: `PROJECT_HANDOFF.md`

Possibly:

- `agent_runtime/protocols/*`
- `agent_runtime/project_workflows/*`
- `agent_runtime/task_index.py`
- `.codex/MAINLINE.md`

## Open Risks

- The existing handoff system is repository-inventory oriented, while the new requirement is project-progress oriented. The implementation should not overload inventory facts with planning/state memory in a way that makes the file noisy or stale.
- Root-level files may conflict with repository hygiene preferences. Policy must be explicit.
- Automatic updates must not erase manual notes.
- A handoff writer must avoid copying secrets, raw prompts with credentials, or large run logs.
- Tests currently mutate `config/worker_performance_ledger.yml`; avoid committing that side effect.

## Suggested Next Steps For A New Agent

1. Run:

```bash
git status --short
git log -5 --oneline
gh run list --branch main --limit 5
```

2. Read:

```text
PROJECT_HANDOFF.md
AGENTS.md
.codex/MAINLINE.md
config/repository_handoff_policy.yml
agent_runtime/repository_handoff.py
agent_runtime/cli/protocol.py
```

3. Implement project-root handoff mechanism as a narrow slice.
4. Run targeted repository handoff tests and protocol tests.
5. Run the three demo gates and full pytest.
6. Restore `config/worker_performance_ledger.yml` if full pytest mutates it.
7. Commit, push, confirm CI.

## Manual Notes

<!-- AGENT_NOTES_START -->

- User explicitly requested this file because existing handoff artifacts are too scattered and not usable enough as a project-level status dashboard.
- Shutdown is no longer part of the final objective.
- This handoff is currently hand-written as the first explicit root handoff. The next implementation should make AgentLab able to generate and refresh equivalent files automatically.

<!-- AGENT_NOTES_END -->
