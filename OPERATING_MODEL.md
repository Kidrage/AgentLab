# AgentLab Operating Model

This AgentLab instance uses an external-driver, internal-agent workflow:

- AgentLab owns task routing, planning, perception, execution, audit, memory,
  provider accounting, and local artifacts.
- External IDE AI owns task dispatch, final acceptance, and gap-filling only.
- DeepSeek official API remains available for high-quality brain/review work
  when configured.
- DashScope is the runtime provider for all Qwen profiles. OpenRouter is not a
  default or assumed provider.

## Trigger Rule

AgentLab only runs when the user explicitly asks to use AgentLab.

If the user gives a normal coding request without saying to use AgentLab, Codex
handles it independently in the current session.

## DeepSeek Responsibilities

DeepSeek must be used for AgentLab brain work, including simulations, small
tasks, and large engineering tasks. This remains true unless the user explicitly
changes the AgentLab configuration.

DeepSeek responsibilities:

- Supervisor planning.
- Repository analysis summaries.
- Architecture and interface discussion.
- Error analysis.
- Code review notes.
- Task decomposition.
- Generating Codex implementation prompts.
- Archival summaries.

DeepSeek must not be treated as the source-of-truth executor for real source
edits. If Codex quota is exhausted and the user chooses the API fallback,
DeepSeek remains the brain and Qwen becomes the temporary Coder model.

## External IDE AI Responsibilities

Codex Plus/Cline/Claude/etc. handle:

- Translating the user's request into `user_request.md`.
- Running AgentLab CLI commands.
- Reading task status and local artifacts.
- Reporting conclusions, risks, and missing evidence to the user.
- Manually rescuing a blocked stage only when the user explicitly authorizes it.

When external IDE AI performs any manual rescue or file edits, the task artifact
must say `backend: external_ide_manual` or `backend: codex_plus_manual`. It must
not be recorded as a model API result.

## Fallback Rule

If DeepSeek is unavailable, out of quota, rate limited, or missing credentials
during a brain stage, AgentLab must stop and ask the user. Codex Plus must not
silently perform Supervisor, RepoScout, Researcher, InterfaceMapper,
Tester/Auditor, Archivist, or CodexPromptGenerator work as a replacement brain.

If Qwen Coder/DashScope is unavailable during Coder execution, AgentLab asks the
user whether to pause/retry, switch to another configured API model, or authorize
external IDE manual rescue:

```text
AgentLab brain + Qwen Coder API, or AgentLab brain + external IDE manual rescue
```

Qwen coding is the default self-drive API path when `DASHSCOPE_API_KEY` is
configured. The first safe output is a patch proposal and implementation report
unless a later checkpoint/approval mechanism allows direct application.

## New Task Protocol

When the user describes a new task to Codex:

1. Codex writes the request to `runs/task_xxxx/user_request.md`.
2. Codex runs `agentlab.sh prepare --write-plan`.
3. DeepSeek agents produce planning/review/prompt reports. This is required,
   even for simulations and small tasks.
4. Codex Plus performs real source edits and commands.
5. Tester/Auditor and Archivist reports are written back into the run folder.

## Logging Rule

Each AgentLab project maintains:

```text
agent_docs/07_DEVELOPMENT_LOG.md
agent_docs/08_CODEX_DIALOGUE_LOG.md
agent_docs/09_COST_LEDGER.yml
```

The development log is organized by module. The dialogue log records the
user-visible task conversation and Codex Coder actions. Hidden model reasoning is
not available and must not be fabricated.

## Billing Rule

DeepSeek token usage is recorded from API telemetry when available. Codex Plus
membership usage is not exposed to AgentLab as a local billing API, so Codex
execution is recorded as a manual usage event with exact cost marked
`unavailable`.

## Brain Governance Rule

The Supervisor/brain layer governs traversal and token pressure:

- Any full-directory or full-repository traversal must call `request-traversal`.
- The brain records decisions in `runs/task_xxxx/brain_decisions.yml`.
- If the decision is ambiguous, AgentLab writes `USER_DECISION_REQUIRED.md` and
  Codex asks the user for a yes/no answer in the main conversation.
- If token usage approaches the warning threshold, continuing is allowed with a
  warning.
- If token usage crosses the stop threshold, the brain asks the user.
- If an agent appears stuck in a repeated loop or drifts from the task goal, the
  brain stops and replans.

Commands:

```bash
./agentlab.sh brain-status --project ExampleProject --task-id task_0001
./agentlab.sh request-traversal RepoScout --project ExampleProject --task-id task_0001 --scope full_repo --full-repo --reason "Need initial repo map" --estimated-files 300 --estimated-tokens 9000
```

## Dual-End Collaboration and Sync Protocol

AgentLab operates across a dual-end execution link layout to enable remote running / deployment while maintaining synchronized agent capabilities:

1.  **Architecture**:
    *   **Local Mac (saintpeter)**: Primary development environment and source of truth.
    *   **Relay Hub (TrueNAS at `10.147.17.61:2222`)**: Shared repository and exchange relay station at `/mnt/hdd2/AgentLab_WorkSpace/`.
    *   **Cloud Runtime (Server at `10.147.17.250`)**: Run/deployment server. Connected to `10.147.17.61` and directly accessible from Local Mac via SSH (`admin@10.147.17.250`).
2.  **Sync Workflow**:
    *   **Local Mac -> Relay Hub**: Local pushes workspace changes (skills, configs, memory snapshots) to TrueNAS (`10.147.17.61`) using `./agentlab.sh truenas-sync --execute` or manual rsync.
    *   **Relay Hub -> Cloud Runtime (250)**: Remote agents on `10.147.17.250` pull workspace/skills/MCP updates from `10.147.17.61` using `rsync` over SSH.
    *   **Cloud Runtime (250) -> Relay Hub -> Local Mac**: Task execution logs and agent memory produced on `10.147.17.250` sync back to TrueNAS (`10.147.17.61`), then pull to local Mac, maintaining synchronized memory and skills.

