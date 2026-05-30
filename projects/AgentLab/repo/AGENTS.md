# Agent Instructions

This project tracks the AgentLab workflow itself.

Before planning or editing:

- Read `projects/AgentLab/project_config.yml`.
- Read `projects/AgentLab/agent_docs/00_CONTEXT_PACK.md`.
- Read `projects/AgentLab/agent_docs/01_REPO_MAP.md`.
- Write reports under `projects/AgentLab/runs/task_xxxx/`.

Implementation rules:

- Make minimal, scoped changes.
- Keep UI, runtime, configuration, project memory, and integration layers separated.
- Never claim validation passed unless commands were actually run.
- Do not install dependencies without explicit user approval.
- Do not use DeepSeek for actual source edits.
- DeepSeek must perform AgentLab brain planning/review for simulations, small tasks, and large tasks unless the user changes `config/execution_policy.yml`.
- If Codex quota is exhausted for Coder work, ask the user whether to pause or explicitly switch to DeepSeek brain + Qwen Coder API fallback.
- Record Codex-visible implementation actions in the project dialogue log.
