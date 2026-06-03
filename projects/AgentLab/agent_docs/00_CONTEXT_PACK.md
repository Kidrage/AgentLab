# AgentLab Context Pack

AgentLab is a personal, local-first multi-agent development workflow.

Core operating split:

- DeepSeek API handles management reasoning, planning, review, and Codex prompt drafting.
- Codex Plus handles real code edits, local file changes, commands, and validation.
- AgentLab only runs when the user explicitly asks to use AgentLab.
- Every AgentLab task should leave local reports and project memory updates.

Current implementation stage:

- CLI-first workflow.
- Static UI skeletons are allowed when they do not require dependency installs.
- Web UI should be able to grow into a local service-backed dashboard later.

Important boundaries:

- Configuration lives under `config/`.
- Role prompts live under `agent_templates/`.
- Runtime code lives under `agent_runtime/`.
- Project memory and task reports live under `projects/<ProjectName>/`.
- Browser/static UI surfaces live under `web_ui/`.
