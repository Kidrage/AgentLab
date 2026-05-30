# AgentLab Operating Model

This AgentLab instance uses a split-brain workflow:

- DeepSeek API is the low-cost management and reasoning layer.
- Codex Plus is the real engineering execution layer.

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

## Codex Plus Responsibilities

Codex Plus handles:

- Writing code.
- Editing files.
- Running project commands.
- Reading diffs and command output.
- Applying fixes.
- Producing final implementation reports.

Codex Plus dialogue and implementation actions must be summarized into the
project dialogue log when AgentLab is active.

## Fallback Rule

If DeepSeek is unavailable, out of quota, rate limited, or missing credentials
during a brain stage, AgentLab must stop and ask the user. Codex Plus must not
silently perform Supervisor, RepoScout, Researcher, InterfaceMapper,
Tester/Auditor, Archivist, or CodexPromptGenerator work as a replacement brain.

If Codex Plus quota is exhausted during Coder execution, AgentLab asks the user
whether to pause until Codex quota refreshes or switch to a pure API fallback:

```text
DeepSeek brain + Qwen Coder API
```

Qwen coding is never automatic. The first safe output is a patch proposal and
implementation report unless a later checkpoint/approval mechanism allows direct
application.

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
