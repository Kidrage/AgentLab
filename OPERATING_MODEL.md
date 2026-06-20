# AgentLab Operating Model

## Hybrid Agent-Executor Operating Model

Earlier AgentLab assumed that most runtime roles would be handled by direct model API providers. This is no longer the preferred default.

AgentLab should support a hybrid operating model where each role can be backed by either:

1. a direct model API provider,
2. a local or remote agent harness,
3. a CLI / IDE coding agent,
4. a human-approved manual executor,
5. a mock / dry-run executor for tests and safety.

The key design shift is:

```text
Model Provider ≠ Executor
Agent Harness ≠ Project Owner
AgentLab = Project OS / Truth Source / Governance Layer
```

AgentLab may delegate reasoning, coding, review, research, or artifact production to specialized agents such as Hermes, Claude Code, Codex, Cline, OpenClaw, or a direct model API. However, AgentLab must always retain control of:

* mission contracts,
* workflow plans,
* project brain,
* task packets,
* phase acceptance,
* evidence ledger,
* cost/resource ledger,
* approval gates,
* recovery and replanning,
* asset registration,
* final delivery state.

### Preferred high-capability local configuration

A high-capability local-first configuration may look like:

```yaml
operating_mode: hybrid_agent_executor

roles:
  project_governor:
    owner: agentlab
    responsibilities:
      - mission_contract
      - workflow_plan
      - project_brain
      - phase_acceptance
      - recovery
      - evidence_review
      - cost_governance

  brain_executor:
    type: agent_harness
    provider: hermes
    model_backend:
      - gpt-5.5
      - deepseek
      - other_user_configured_model
    responsibilities:
      - high_level_reasoning
      - route_planning
      - task_decomposition
      - strategy_review
      - replanning_suggestions
    governance:
      bypass_agentlab_state: false
      requires_task_packet: true
      writes_result_report: true

  code_executor:
    type: cli_coding_agent
    provider: claude_code
    responsibilities:
      - repo_inspection
      - code_patch
      - test_execution
      - bug_fixing
      - implementation_report
    governance:
      bypass_agentlab_state: false
      requires_scoped_task_packet: true
      requires_diff_summary: true
      requires_test_evidence: true

  fallback_model_provider:
    type: direct_api
    provider: qwen_or_deepseek_or_openai
    responsibilities:
      - low_cost_summarization
      - deterministic_classification
      - small_review_tasks
      - fallback_reasoning
```

### Why agent executors may outperform direct API execution

Direct model API execution is simple and cheap to integrate, but it lacks a full tool-use loop unless AgentLab implements that loop itself. Specialized agents often include repo navigation, tool calling, shell interaction, patch generation, context handling, and iterative repair behavior.

Therefore, for complex coding and long-running project work, AgentLab should prefer agent executors when:

* the task requires repository-scale inspection,
* code changes span multiple files,
* tests need to be run repeatedly,
* the executor must inspect logs or diffs,
* the task benefits from IDE/CLI-native context,
* the user has already configured a strong local agent harness.

Direct API providers remain useful for:

* cheap classification,
* summarization,
* mission contract drafting,
* artifact normalization,
* lightweight review,
* fallback execution,
* deterministic offline tests.

### Required safety boundary

No agent executor may directly mutate project state without AgentLab recording:

```text
task_packet
→ executor_assignment
→ result_report
→ changed_files
→ diff_summary
→ evidence_artifacts
→ test_results
→ phase_acceptance
→ project_brain_update
```

AgentLab must treat every external or local agent as an executor, not as the source of truth.

If Hermes or Claude Code makes a plan, AgentLab records it as a proposal.

If Claude Code changes code, AgentLab records it as a patch result.

If an agent claims success, AgentLab verifies evidence before accepting.

If evidence is missing, AgentLab must return retry / blocked / human_review rather than silently closing the phase.

### Recommended default policy

Use this priority order for high-value local project work:

```text
1. AgentLab compiles mission and workflow.
2. Hermes-backed brain executor proposes route and decomposition.
3. AgentLab converts proposal into governed task packets.
4. Claude Code / Codex / Cline executes scoped coding packets.
5. AgentLab ingests reports, diffs, tests, and artifacts.
6. AgentLab performs phase acceptance.
7. AgentLab updates project brain and generates the next phase.
```

The goal is not to make AgentLab a weaker replacement for strong agents. The goal is to make AgentLab the operating system that coordinates them.

## Trigger Rule

AgentLab only runs when the user explicitly asks to use AgentLab.

If the user gives a normal coding request without saying to use AgentLab, the local coding agent handles it independently in the current session.

## Logging Rule

Each AgentLab project maintains:

```text
agent_docs/07_DEVELOPMENT_LOG.md
agent_docs/08_CODEX_DIALOGUE_LOG.md
agent_docs/09_COST_LEDGER.yml
```

The development log is organized by module. The dialogue log records the user-visible task conversation and coding agent actions. Hidden model reasoning is not available and must not be fabricated.

## Billing Rule

Token usage is recorded from API telemetry when available. Local coding agent or local harness usage is not exposed to AgentLab as a local billing API, so their execution is recorded as a manual usage event with exact cost marked `unavailable`.

## Brain Governance Rule

The project governor layer governs traversal and token pressure:

- Any full-directory or full-repository traversal must call `request-traversal`.
- The governor records decisions in `runs/task_xxxx/brain_decisions.yml`.
- If the decision is ambiguous, AgentLab writes `USER_DECISION_REQUIRED.md` and the driving agent asks the user for a yes/no answer in the main conversation.
- If token usage approaches the warning threshold, continuing is allowed with a warning.
- If token usage crosses the stop threshold, the governor asks the user.
- If an agent executor appears stuck in a repeated loop or drifts from the task goal, the governor stops and replans.

Commands:

```bash
./agentlab.sh brain-status --project ExampleProject --task-id task_0001
./agentlab.sh request-traversal RepoScout --project ExampleProject --task-id task_0001 --scope full_repo --full-repo --reason "Need initial repo map" --estimated-files 300 --estimated-tokens 9000
```

## Dual-End Collaboration and Sync Protocol

AgentLab operates across a dual-end execution link layout to enable remote running / deployment while maintaining synchronized agent capabilities:

1.  **Architecture**:
    *   **Local Mac (<USER>)**: Primary development environment and source of truth.
    *   **Relay Hub (TrueNAS at `<RELAY_IP>:<PORT>`)**: Shared repository and exchange relay station.
    *   **Cloud Runtime (Server at `<CLOUD_IP>`)**: Run/deployment server. Connected to `<RELAY_IP>` and directly accessible from Local Mac via SSH (`admin@<CLOUD_IP>`).
2.  **Sync Workflow**:
    *   **Local Mac -> Relay Hub**: Local pushes workspace changes (skills, configs, memory snapshots) to TrueNAS (`<RELAY_IP>`) using `./agentlab.sh truenas-sync --execute` or manual rsync.
    *   **Relay Hub -> Cloud Runtime**: Remote agents on `<CLOUD_IP>` pull workspace/skills/MCP updates from `<RELAY_IP>` using `rsync` over SSH.
    *   **Cloud Runtime -> Relay Hub -> Local Mac**: Task execution logs and agent memory produced on `<CLOUD_IP>` sync back to TrueNAS (`<RELAY_IP>`), then pull to local Mac, maintaining synchronized memory and skills.

