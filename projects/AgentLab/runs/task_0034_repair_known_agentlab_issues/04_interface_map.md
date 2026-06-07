# Interface Mapper Report

## Task
- Task id: task_0034_repair_known_agentlab_issues
- User request: Repair known AgentLab defects from Codex audit. Priority scope: (1) secure Web UI execution endpoints with AGENTLAB_WEB_UI_TOKEN and safer localhost default, (2) keep state.yml/progress.yml/lifecycle.yml/task_snapshot.yml consistent when artifact gates/provider/user-decision blocks occur, (3) fix Archivist AGENTLAB_EDIT prompt/parser contract so durable memory write-back works, (4) enforce token budget stop thresholds before real model calls, (5) make artifact-check fail on task_snapshot drift, (6) add or correct guard-status/recover CLI commands. Use smallest safe implementation, preserve unrelated dirty worktree changes, add focused regression tests, and validate with pytest/doctor/artifact-check. If the full scope is too large, stop after producing a split plan and USER_DECISION_REQUIRED.md.
- Assigned scope: Interface boundary analysis, contract mapping, and compatibility review for the 6 priority defect areas.

## Work Performed
- Files read: `agent_runtime/run_task.py`, `agent_runtime/brain_governor.py`, `agent_runtime/agent_runner.py`, `web_ui/app.js`, `config/execution_policy.yml`, `config/brain_governance.yml`, `agent_templates/archivist.md`, `agent_docs/04_INTERFACE_REGISTRY.md` (contextual).
- Commands run: None (read-only inspection phase per shell_policy).
- Key observations: The task spans HTTP/auth, YAML state persistence, LLM prompt/response parsing, token governance, CLI routing, and validation gates. Cross-layer boundaries require explicit contract definitions to prevent regression.

## Findings
- Summary:
  - **Web UI Security**: New `AGENTLAB_WEB_UI_TOKEN` env var must be injected into `web_ui/app.js` and any local server. Localhost binding (`127.0.0.1`) must be enforced by default.
  - **State Consistency**: `state.yml`, `progress.yml`, `lifecycle.yml`, `task_snapshot.yml` currently lack a unified write contract. Block states (artifact gates, provider errors, user decisions) cause drift. A synchronized `write_state()` wrapper with atomic fallback is required.
  - **Archivist Contract**: `AGENTLAB_EDIT` prompt format and parser in `agent_runner.py`/`patch_applicator` are misaligned. Strict JSON/YAML schema validation must precede memory write-back.
  - **Token Budget**: `brain_governor.py` must evaluate `stop_threshold_tokens` *before* LLM dispatch. Current flow risks over-budget calls.
  - **Artifact Check**: Validation gate must explicitly compare `task_snapshot.yml` against expected schema. Drift must trigger hard failure.
  - **CLI Commands**: `guard-status` and `recover` require defined CLI flags, structured output (JSON/YAML), and direct hooks into `brain_governor.py` and state readers.
- Risks:
  - High coupling between YAML state files; unsynchronized writes will cause race conditions.
  - `AGENTLAB_WEB_UI_TOKEN` may break legacy static UI deployments if not backward-compatible (dev-mode bypass needed).
  - Archivist parser strictness could reject valid legacy `AGENTLAB_EDIT` blocks.
  - Token budget pre-check must allow controlled retries without bypassing stop thresholds.
- Blockers: None. Requires Supervisor sign-off on state synchronization strategy and Archivist schema versioning before Coder implementation.

## Outputs
- Deliverables:
  - Interface mapping notes for the active run.
  - Proposed updates to `agent_docs/04_INTERFACE_REGISTRY.md`.
  - Risks, compatibility notes, and validation targets.
- Recommended next steps:
  1. Coder implements unified state writer, token budget pre-check, and Archivist parser schema.
  2. TesterAuditor validates state consistency under simulated block conditions and token budget enforcement.
  3. Update `agent_docs/04_INTERFACE_REGISTRY.md` with new contracts (see below).

### Proposed Updates to `agent_docs/04_INTERFACE_REGISTRY.md`
```yaml
# Additions/Updates for task_0034
interfaces:
  - name: WebUI_Auth
    type: HTTP/Env
    inputs: AGENTLAB_WEB_UI_TOKEN (env), localhost binding (config)
    outputs: Authenticated UI session, 401/403 on mismatch
    side_effects: Blocks external network access by default
    compatibility: Dev-mode bypass for local static serving
  - name: State_Sync_Writer
    type: YAML/Atomic
    inputs: state.yml, progress.yml, lifecycle.yml, task_snapshot.yml
    outputs: Synchronized state files, rollback on partial failure
    side_effects: Overwrites stale state during block transitions
    compatibility: Requires versioned schema to prevent legacy drift
  - name: Archivist_EDIT_Parser
    type: Prompt/JSON
    inputs: AGENTLAB_EDIT block (LLM output)
    outputs: Validated patch payload, memory write-back
    side_effects: Fails fast on malformed schema
    compatibility: Strict JSON/YAML validation; legacy fallback optional
  - name: Token_Budget_Gate
    type: Pre-call Check
    inputs: current_token_usage, stop_threshold_tokens
    outputs: Allow/Deny dispatch, budget_exceeded flag
    side_effects: Halts execution before LLM call
    compatibility: Must integrate with brain_governor.py retry logic
  - name: CLI_Guard_Recover
    type: CLI/JSON
    inputs: --status, --recover flags
    outputs: Structured state report, recovery actions
    side_effects: Resets block states, updates task_snapshot.yml
    compatibility: Backward-compatible with existing CLI router
```