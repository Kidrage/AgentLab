# Repository Directory Constitution

AgentLab's repository root is a product surface, not a scratchpad.

External IDEs, coding agents, and local helpers must not place unclassified runtime artifacts in the repository root. Root pollution makes future agents reread stale handoffs, duplicate reports, and local-only files as if they were project truth.

## Allowed Root Areas

The root should contain source, tests, docs, examples, config, scripts, and acceptance evidence only:

- `agent_runtime/`
- `config/`
- `docs/`
- `tests/`
- `scripts/`
- `examples/`
- `acceptance_runs/`
- `skills/`
- `projects/` for templates or ignored local project state
- `memory/` for templates or ignored local memory state
- `.github/`
- top-level project files such as `README.md`, `agentlab.sh`, and `agentlab_app.py`

## Runtime Inbox

External tools should write scratch material under `.agentlab/`:

- `.agentlab/inbox/`
- `.agentlab/tmp/`
- `.agentlab/external_handoffs/`
- `.agentlab/external_reports/`
- `.agentlab/scratch/`
- `.agentlab/rejected_artifacts/`

`.agentlab/` is local-only and ignored by git.

Managed CLI entrypoint directories (`.agy/`, `.claude/`, `.codex/`, `.gemini/`,
`.hermes/`, `.openclaw/`, and `.qwen/`) and `.agentlab_runtime/` are also
local-only. They contain wrappers, symlinks, caches, heartbeats, or authentication
state; they are never project facts or deliverables and must remain Git-ignored.

## Repository Memory Exception

`PROJECT_HANDOFF.md` is the one allowed root-level repository-memory file and the
only writable authority. Generic `HandOff.md` / `HANDOFF.md`,
`.agentlab/HandOff.md`, and `agent_docs/HandOff.md` are legacy read-only discovery
aliases and must not be regenerated. The optional
`memory/repositories/<repository_id>/HandOff.md` copy is a cross-endpoint or
read-only-repository fallback, not a second authority. The required inventory
enumerates repository paths and metadata safely; it must not recursively read file
contents, binaries, secrets, dependency caches, or linked directory trees. Refresh
canonical `PROJECT_HANDOFF.md` after every material project change and before final
reporting.

## Project State

User-project material belongs under `projects/<project_id>/`, but project runtime state is also local-only by default. Public commits should keep only examples, templates, tests, docs, and acceptance fixtures.

## Guard

Run:

```bash
./agentlab.sh repo-hygiene-check
```

or:

```bash
python -m agent_runtime.project_ops.cli repo-hygiene-check
```
