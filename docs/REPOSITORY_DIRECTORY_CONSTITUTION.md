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
