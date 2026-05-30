# AgentLab

AgentLab is a local-first, semi-managed development workflow for personal agentic
software work.

The goal is to make model-assisted development cheaper, more transparent, and
more controllable than one long chat:

- Store task state and project memory locally.
- Route only the agents needed for the task.
- Publish token budgets before work starts.
- Keep implementation, validation, audit, and archival evidence separate.
- Preserve long-running project direction through explicit memory files.

## Operating Model

This AgentLab uses a split-brain workflow:

```text
DeepSeek API = low-cost management and reasoning
Codex Plus   = real code generation, file edits, and command execution
```

DeepSeek is required for planning, task decomposition, architecture notes, code
review, error analysis, and Codex prompt generation whenever AgentLab is active,
including simulations and small tasks. Codex Plus performs actual source edits
and project commands. See `OPERATING_MODEL.md`.

## Where To Write Prompts

Project-level context:

```text
projects/<ProjectName>/agent_docs/00_CONTEXT_PACK.md
```

Task-level request:

```text
projects/<ProjectName>/runs/task_xxxx/user_request.md
```

## Where To Edit Agents

Agent behavior is controlled in two layers:

```text
config/*.yml              policy, routing, budget, model, memory, permissions
agent_templates/*.md      role prompts and report formats
```

Start with `config/agent_registry.yml` when changing what an agent may do.

## Prepare A Workflow Plan

```bash
cd /Users/saintpeter/AgentLab/agent_runtime
.venv/bin/python run_task.py prepare --project ExampleProject --task-id task_0001
```

To generate an Aider Coder backend plan without running Aider:

```bash
.venv/bin/python run_task.py prepare --project ExampleProject --task-id task_0001 --execution-backend aider
```

To write a visible plan into the active run folder:

```bash
.venv/bin/python run_task.py prepare --project ExampleProject --task-id task_0001 --write-plan
```

Phase 2A/2B behavior is still conservative: no model calls, source edits,
dependency installs, or validation commands are run automatically by `prepare`.

## One-Command CLI

From the AgentLab root:

```bash
./agentlab.sh status --project ExampleProject --task-id task_0001
./agentlab.sh models
./agentlab.sh run-agent Supervisor --project ExampleProject --task-id task_0001
```

`run-agent` is dry-run by default. It calls the configured model API only when
you pass `--execute`. For real AgentLab runs, brain-stage agents must be run
with DeepSeek before Codex Coder execution.

Codex implementation stages should be handled by the current Codex session. If
AgentLab cannot call DeepSeek for a brain stage, it blocks and asks the user
instead of letting Codex silently simulate the brain layer.

Policy checks:

```bash
./agentlab.sh policy-status --project ExampleProject
./agentlab.sh request-coder-quota --project ExampleProject --task-id task_0001 --reason "Codex quota may be insufficient for the next implementation pass"
```

If Codex quota is exhausted, the configured choices are:

```text
pause_until_codex_refresh
switch_to_deepseek_brain_qwen_coder_api
```

Optional provider example:

```bash
./agentlab.sh models
./agentlab.sh run-agent RepoScout --project ExampleProject --task-id task_0001 --provider qwen --model qwen-plus --execute
```

Brain governance commands:

```bash
./agentlab.sh brain-status --project ExampleProject --task-id task_0001
./agentlab.sh request-traversal RepoScout --project ExampleProject --task-id task_0001 --scope full_repo --full-repo --reason "Need initial repo map"
```

## How External AIs Drive AgentLab

Any external AI (Codex Plus, Claude, IDE assistants) can drive AgentLab as a thin relay.
Read `DRIVER_PROTOCOL.md` for the full 7-step protocol.

The key rule: **external AIs do NOT think — AgentLab's brain (DeepSeek) does.**
External AIs only transcribe user requests, execute the Coder phase, and relay decisions.

## Local Status UI

AgentLab now has a dependency-free static status board:

```text
web_ui/index.html
```

It shows the current UI data contract for agent state, route, provider,
ownership, edit rights, token budget, and recent events. The page can be opened
directly in a browser and can later be wired to a local CLI-generated snapshot
or service endpoint.

## Version Control

This repo is version-controlled on GitHub:

```text
https://github.com/Kidrage/AgentLab
```

After any meaningful change, commit and push:

```bash
git add -A
git commit -m "描述此次修改"
git push origin main
```

Use `git status` before committing to ensure no sensitive files (`.env`, credentials) are staged.

-------

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-05-30 | Initial release: 8-agent multi-agent workflow, split-brain architecture (DeepSeek + Codex Plus), task routing, token budget governance, brain governor, local status UI, driver protocol for external AI |
