# AgentLab Terminal Chat + Rule Self-Check + GitHub Auto-Sync Implementation Spec

Version: v1.0  
Date: 2026-05-31  
Target repository: `Kidrage/AgentLab`  
Purpose: Make AgentLab usable directly from Terminal without depending on an external IDE chat window; add a rule-based local self-check gate; automatically commit and push safe local changes to GitHub after successful modification.

---

## 0. Executive Summary

AgentLab is currently designed as a local-first, semi-managed agentic development workflow. It already has the right foundation: project memory, task folders, workflow plans, state files, cost ledgers, brain decisions, a CLI entrypoint, and a static Web UI. However, the user still has to drive it mostly through external IDE/chat tools. This creates three operational weaknesses:

1. **No native chat loop**: the user cannot talk to AgentLab directly in Terminal as the primary control surface.
2. **No mandatory post-edit rule check**: local changes can exist without a deterministic safety/audit gate.
3. **No automatic GitHub backup after safe edits**: if the local machine fails, recent AgentLab changes may be lost unless the user manually commits and pushes.

This task implements a new layer:

> **AgentLab Terminal Control Layer**

It contains:

- Terminal chat command: `./agentlab.sh chat`
- Terminal task command shortcuts: `/new`, `/task`, `/status`, `/plan`, `/run-next`, `/pause`, `/resume`, `/check`, `/push`, `/sync`, `/exit`
- Rule-based self-check engine: `agent_runtime/rule_self_check.py`
- Safe GitHub sync manager: `agent_runtime/github_sync.py`
- Policy config: `config/self_check_policy.yml`, `config/auto_sync_policy.yml`
- New per-task artifacts: `self_check_report.yml`, `sync_report.yml`, `chat_transcript.md`
- Project-level sync ledger update: `projects/<Project>/agent_docs/10_SYNC_LEDGER.yml`

The system must **never push blindly**. The required order is:

```text
local modification
  -> rule self-check
  -> secret scan
  -> state/config validation
  -> optional test/syntax checks
  -> generate self_check_report.yml
  -> commit only if checks pass
  -> push only if GitHub sync policy allows it
  -> write sync_report.yml and project sync ledger
```

---

## 1. Current Repo Facts and Design Constraints

The current README defines AgentLab as a local-first workflow with local task state, local project memory, agent routing, token budgets, separated implementation/validation/audit/archive evidence, and explicit long-running project memory files.

The current repo structure already includes:

```text
AgentLab/
├── agent_runtime/
├── agent_templates/
├── config/
├── projects/
├── web_ui/
├── scripts/
├── agentlab.sh
├── DRIVER_PROTOCOL.md
└── OPERATING_MODEL.md
```

The current CLI contract already includes commands such as:

```bash
./agentlab.sh init-task
./agentlab.sh prepare
./agentlab.sh status
./agentlab.sh run-agent
./agentlab.sh brain-status
./agentlab.sh models
./agentlab.sh policy-status
./agentlab.sh log-event
```

The current CLI roadmap explicitly says CLI comes first, and a future UI should sit on top of the same files and Python APIs. Therefore, the new Terminal chat must be implemented as a CLI command that calls existing runtime modules, not as a separate parallel system.

Important constraint:

- Do not bypass `workflow_plan.yml`.
- Do not bypass `state.yml`.
- Do not bypass validation gates.
- Do not bypass cost/decision ledgers.
- Do not make the Web UI the source of truth.
- Do not make external IDE chat the only source of truth.

Terminal chat should become the **primary local control surface**, while Web UI remains a read-only or lightly interactive dashboard.

---

## 2. Diagnosis: Root Logic Issues to Fix

There is no fatal architectural mistake requiring a full rewrite. The current system direction is correct. But the following logic issues must be corrected before AgentLab becomes reliable as a daily workflow.

### 2.1 External-IDE dependency is too high

Current design allows external AIs to drive AgentLab as a thin relay. That is useful, but it should not be the only practical interaction mode.

**Problem:**

The user currently has to open another AI/IDE chat to say what they want. AgentLab itself does not provide a conversational command loop.

**Fix:**

Add `agentlab chat`, a Terminal REPL that can:

- start a task from natural language;
- attach follow-up instructions to the active task;
- show current task progress;
- execute the next safe step;
- pause/resume;
- run self-check;
- commit/push after checks;
- write all chat turns into `chat_transcript.md`.

### 2.2 Hard brand dependency should be reduced

The existing operating model strongly assumes DeepSeek for brain and Codex Plus for implementation. This is a valid early design, but it becomes brittle when API quota, network availability, or provider quality changes.

**Fix in this task:**

Do not fully rewrite model failover here. However, the Terminal chat should be provider-aware and must display current provider status from the existing/future provider guard:

```bash
/providers
/models
```

It must not silently switch models without policy approval. If provider switching exists from the previous Provider Failover spec, Terminal chat should call it rather than duplicating it.

### 2.3 No mandatory rule-based check before GitHub sync

Automatic GitHub upload is desirable, but it is dangerous without a deterministic safety gate.

**Fix:**

Add rule-based self-check and make GitHub sync depend on it.

### 2.4 Existing Web UI should not be replaced

The Web UI already reads local project/task files. Do not move the source of truth into a new frontend.

**Fix:**

Terminal chat writes the same files. Web UI can later display `chat_transcript.md`, `self_check_report.yml`, and `sync_report.yml`.

---

## 3. New File Layout

Add these files:

```text
agent_runtime/
├── terminal_chat.py             # Terminal REPL / chat control surface
├── chat_router.py               # Rule-based intent parser for chat input
├── rule_self_check.py           # Deterministic local self-check engine
├── github_sync.py               # Safe Git commit/push manager
├── git_utils.py                 # Git status/diff helpers
└── report_renderers.py          # Rich table/text rendering helpers, optional

config/
├── self_check_policy.yml        # Rules for local self-check
└── auto_sync_policy.yml         # Rules for commit/push behavior

projects/<Project>/runs/<task_id>/
├── chat_transcript.md
├── self_check_report.yml
├── sync_report.yml
└── sync_errors.md               # only if sync fails

projects/<Project>/agent_docs/
└── 10_SYNC_LEDGER.yml           # already exists in Web UI helper; update it consistently
```

Modify these files:

```text
agent_runtime/run_task.py        # register new Typer commands if using same app
agentlab.sh                      # ensure it forwards args to run_task.py / Typer app
web_ui/server.py                 # optional: read/display new reports later
README.md                        # document new chat/check/sync commands
CLI_ROADMAP.md                   # update CLI-first roadmap
OPERATING_MODEL.md               # clarify Terminal chat vs external IDE driver
```

Do not remove existing commands.

---

## 4. Terminal Chat: Functional Requirements

### 4.1 Command

Add:

```bash
./agentlab.sh chat --project <ProjectName>
```

Optional args:

```bash
./agentlab.sh chat --project <ProjectName> --task-id <task_id>
./agentlab.sh chat --project <ProjectName> --new-task
./agentlab.sh chat --project <ProjectName> --execute
./agentlab.sh chat --project <ProjectName> --no-auto-sync
```

Behavior:

- If no task exists, chat starts in project-level mode.
- If `--task-id` is provided, chat attaches to that task.
- If `--new-task` is provided, the first natural-language message creates a new task.
- If `--execute` is absent, dangerous actions should remain dry-run or ask confirmation.
- If `--no-auto-sync` is set, suppress auto-push for this session, but still write self-check reports.

### 4.2 Chat prompt format

Use Rich if available. A simple text loop is enough.

Example:

```text
AgentLab[AgentLab/no-task]> 帮我给AgentLab加一个自查机制
```

When attached to a task:

```text
AgentLab[AgentLab/task_0021_terminal-chat-self-check]> /status
AgentLab[AgentLab/task_0021_terminal-chat-self-check]> /run-next
```

### 4.3 Slash commands

Implement at least:

```text
/help                  show available commands
/new <text>             create task from text, auto-slug task id, prepare plan
/task <task_id>         attach current chat session to existing task
/status                show status summary
/progress              show stage, route, completed/missing reports, current agent
/plan                  show workflow_plan.yml summary
/run <AgentName>        run specific agent; dry-run unless --execute session flag is set
/run-next              run next pending agent according to workflow_plan.yml and state.yml
/check                 run rule-based self-check
/push                  run self-check then commit/push if allowed
/sync                  alias for /push
/pause                 mark task paused
/resume                resume paused/blocked task if possible
/providers             show provider health/status if provider guard exists
/models                show configured providers/models
/open                  print run_dir path
/exit                  close chat
```

### 4.4 Natural language behavior

If user enters free text without a slash command:

#### Case A: no active task

Treat the message as a new task request.

Actions:

1. Generate next task id, e.g. `task_0024_<slug>`.
2. Call existing task creation logic.
3. Write `user_request.md`.
4. Write first `chat_transcript.md` entry.
5. Call `prepare --write-plan`.
6. Show route summary.
7. Ask whether to execute next step.

#### Case B: active task exists and task is not complete

Treat the message as a follow-up instruction.

Actions:

1. Append to `chat_transcript.md`.
2. Append to `runs/<task_id>/followup_instructions.md`.
3. Mark state last_event = `User follow-up added.`
4. If workflow plan already exists, mark `needs_replan: true` unless message is clearly a small clarification.
5. Ask whether to re-run Supervisor/prepare.

#### Case C: active task complete

Ask whether to:

- create a new task;
- reopen task;
- archive note only.

No silent modification of completed task.

### 4.5 Transcript format

Write every chat turn to:

```text
projects/<Project>/runs/<task_id>/chat_transcript.md
```

Format:

```markdown
# Chat Transcript

## 2026-05-31T12:30:00Z — user

<message>

## 2026-05-31T12:30:02Z — agentlab

<summary of action taken>

Artifacts updated:
- user_request.md
- workflow_plan.yml
- state.yml
```

Never store API keys or raw `.env` values in transcript.

---

## 5. Chat Intent Router

Add:

```text
agent_runtime/chat_router.py
```

The first version should be rule-based, not LLM-based.

### 5.1 Intent enum

```python
class ChatIntent(str, Enum):
    NEW_TASK = "new_task"
    ATTACH_TASK = "attach_task"
    STATUS = "status"
    PROGRESS = "progress"
    PLAN = "plan"
    RUN_AGENT = "run_agent"
    RUN_NEXT = "run_next"
    CHECK = "check"
    SYNC = "sync"
    PAUSE = "pause"
    RESUME = "resume"
    PROVIDERS = "providers"
    MODELS = "models"
    OPEN_PATH = "open_path"
    HELP = "help"
    EXIT = "exit"
    FOLLOWUP = "followup"
    UNKNOWN = "unknown"
```

### 5.2 Parser rules

- Slash commands always win.
- `task_\d+` after `/task` attaches to a task.
- `/run <AgentName>` parses agent name.
- Non-slash text becomes `NEW_TASK` if no active task.
- Non-slash text becomes `FOLLOWUP` if active task exists.

No LLM call should be needed to parse chat intent.

---

## 6. Rule-Based Self-Check Engine

Add:

```text
agent_runtime/rule_self_check.py
config/self_check_policy.yml
```

The rule self-check must be deterministic. Do not use an LLM for pass/fail.

### 6.1 Command

Add:

```bash
./agentlab.sh check --project <ProjectName> --task-id <task_id>
```

Options:

```bash
./agentlab.sh check --project <ProjectName> --task-id <task_id> --strict
./agentlab.sh check --project <ProjectName> --task-id <task_id> --json
```

### 6.2 Output

Write:

```text
projects/<Project>/runs/<task_id>/self_check_report.yml
```

Schema:

```yaml
version: 1
project: AgentLab
task_id: task_0024_terminal-chat-self-check
status: pass | warn | fail
created_at: "2026-05-31T12:30:00Z"
summary:
  total_checks: 12
  passed: 10
  warnings: 2
  failed: 0
checks:
  - id: git_worktree_detected
    status: pass
    severity: info
    message: "Git worktree detected."
  - id: secrets_scan
    status: pass
    severity: critical
    message: "No obvious secrets detected in staged diff."
artifacts:
  changed_files:
    - agent_runtime/terminal_chat.py
  reports_written:
    - self_check_report.yml
blocking_reasons: []
```

### 6.3 Required checks

Implement these checks in order:

#### 6.3.1 Git repository check

- `git rev-parse --is-inside-work-tree`
- Fail if not inside a git repo and sync is requested.
- Warn if no remote named `origin` exists.

#### 6.3.2 Changed file check

Use `git status --porcelain`.

Fail if:

- no changed files and command was called as `/push`? Actually this should be `warn`, not `fail`.
- changed path escapes AgentLab root.
- changed path includes blocked file patterns.

Blocked patterns:

```text
.env
.env.*
*.key
*.pem
*.p12
*.pfx
*secret*
*token*
__pycache__/
.venv/
node_modules/
.DS_Store
```

Allow docs containing the word token, such as `TOKEN_BUDGET.md`, only if not matching secret-like content.

#### 6.3.3 Secret scan

Scan staged and unstaged changed text files. Do not scan binary files larger than configured limit.

Detect common secrets:

```text
sk-[A-Za-z0-9_-]{20,}
AKIA[0-9A-Z]{16}
ghp_[A-Za-z0-9_]{20,}
github_pat_[A-Za-z0-9_]{20,}
AIza[0-9A-Za-z\-_]{35}
-----BEGIN PRIVATE KEY-----
api[_-]?key\s*[:=]\s*["'][^"']{12,}["']
token\s*[:=]\s*["'][^"']{12,}["']
password\s*[:=]\s*["'][^"']{8,}["']
```

If secret pattern is detected:

- status = fail;
- do not print full secret;
- print file path and redacted line number only;
- block commit and push.

#### 6.3.4 YAML validation

Parse all changed `.yml` and `.yaml` files with PyYAML.

Fail if any changed YAML file cannot parse.

#### 6.3.5 Python syntax validation

For changed `.py` files:

```bash
python -m py_compile <file>
```

Fail on syntax error.

Optional broader check:

```bash
python -m compileall agent_runtime
```

#### 6.3.6 Shell syntax validation

For changed `.sh` files:

```bash
bash -n <file>
```

Fail on syntax error.

#### 6.3.7 Git diff whitespace check

Run:

```bash
git diff --check
```

Warn or fail depending on policy.

Default: warn.

#### 6.3.8 Report completeness check

For a task that has modified code, ensure at least one of these exists and is non-placeholder:

```text
implementation_report.md
validation_report.md
audit_report.md
```

For small local CLI/system changes, `implementation_report.md` may be enough.

Use existing placeholder detection logic if available.

#### 6.3.9 State consistency check

Parse:

```text
state.yml
workflow_plan.yml
brain_decisions.yml
cost_ledger.yml
```

Check:

- task_id matches folder name;
- current_agent is in workflow route if set;
- completed reports correspond to existing files;
- status is one of allowed values.

Do not over-block on old tasks; produce warning for legacy inconsistencies.

#### 6.3.10 Size check

Block accidental upload of large files.

Default thresholds:

```yaml
max_single_file_mb: 25
max_total_diff_mb: 50
```

Fail if exceeded, unless file is explicitly allowlisted.

#### 6.3.11 Test command hook

If `config/self_check_policy.yml` defines test commands, run them.

Example:

```yaml
test_commands:
  - name: unit_tests
    command: "python -m pytest"
    required: false
  - name: compile_runtime
    command: "python -m compileall agent_runtime"
    required: true
```

If command missing tool, warn unless required.

#### 6.3.12 Auto-sync eligibility

Self-check report should include:

```yaml
auto_sync_eligible: true | false
```

True only if:

- status is pass or acceptable warn;
- no critical/secret checks failed;
- git repo and origin remote exist;
- auto sync policy allows this project;
- changed files are not blocked.

---

## 7. Self-Check Policy File

Create:

```text
config/self_check_policy.yml
```

Initial content:

```yaml
version: 1
mode: standard

status_policy:
  allow_push_on: [pass]
  block_push_on: [fail]
  warn_requires_confirmation: true

path_policy:
  blocked_patterns:
    - ".env"
    - ".env.*"
    - "*.key"
    - "*.pem"
    - "*.p12"
    - "*.pfx"
    - "__pycache__/**"
    - ".venv/**"
    - "node_modules/**"
    - ".DS_Store"
  allowed_large_file_patterns: []

size_policy:
  max_single_file_mb: 25
  max_total_diff_mb: 50

secret_scan:
  enabled: true
  max_file_mb: 5
  redaction: true

syntax_checks:
  python_py_compile: true
  shell_bash_n: true
  yaml_parse: true
  git_diff_check: true

report_completeness:
  enabled: true
  require_implementation_report_for_code_changes: true
  require_validation_report_for_source_changes: false

test_commands:
  - name: compile_runtime
    command: "python -m compileall agent_runtime"
    required: true
```

---

## 8. GitHub Auto-Sync Manager

Add:

```text
agent_runtime/github_sync.py
agent_runtime/git_utils.py
config/auto_sync_policy.yml
```

### 8.1 Commands

Add:

```bash
./agentlab.sh sync --project <ProjectName> --task-id <task_id>
./agentlab.sh sync --project <ProjectName> --task-id <task_id> --dry-run
./agentlab.sh sync --project <ProjectName> --task-id <task_id> --confirm
./agentlab.sh sync-status --project <ProjectName>
```

Aliases in Terminal chat:

```text
/push
/sync
```

### 8.2 Sync behavior

Default behavior:

1. Run self-check first.
2. If self-check fails, do not commit or push.
3. If self-check warns, require confirmation unless `auto_sync_policy.yml` allows warn push.
4. Stage allowed files only.
5. Commit with generated message.
6. Push to configured remote and branch.
7. Write `sync_report.yml`.
8. Append project-level `10_SYNC_LEDGER.yml`.

### 8.3 Generated commit message

Format:

```text
AgentLab: <task_id> <short_slug>

Project: <ProjectName>
Task: <task_id>
Self-check: pass
Changed files: <N>

Generated by AgentLab GitHub Sync Manager.
```

For example:

```text
AgentLab: task_0024 terminal-chat-self-check

Project: AgentLab
Task: task_0024_terminal-chat-self-check
Self-check: pass
Changed files: 8

Generated by AgentLab GitHub Sync Manager.
```

### 8.4 Sync report schema

Write:

```text
projects/<Project>/runs/<task_id>/sync_report.yml
```

Schema:

```yaml
version: 1
project: AgentLab
task_id: task_0024_terminal-chat-self-check
created_at: "2026-05-31T12:30:00Z"
status: pushed | committed_only | skipped | failed
remote: origin
branch: main
commit_sha: "abc123..."
pushed: true
self_check_report: self_check_report.yml
changed_files:
  - agent_runtime/terminal_chat.py
  - agent_runtime/rule_self_check.py
blocking_reasons: []
warnings: []
```

### 8.5 Project sync ledger

Append to:

```text
projects/<Project>/agent_docs/10_SYNC_LEDGER.yml
```

Schema:

```yaml
version: 1
project: AgentLab
entries:
  - timestamp: "2026-05-31T12:30:00Z"
    task_id: task_0024_terminal-chat-self-check
    status: pushed
    remote: origin
    branch: main
    commit_sha: "abc123..."
    self_check_status: pass
    changed_files_count: 8
```

### 8.6 Auto-sync policy

Create:

```text
config/auto_sync_policy.yml
```

Initial content:

```yaml
version: 1

defaults:
  enabled: true
  mode: guarded_auto_push
  remote: origin
  branch: main
  require_self_check: true
  push_on_self_check_status: [pass]
  require_confirmation_for_warn: true
  allow_force_push: false
  allow_push_with_untracked_blocked_files: false
  commit_message_prefix: "AgentLab"

safety:
  never_push_if_secret_detected: true
  never_push_if_yaml_invalid: true
  never_push_if_python_syntax_invalid: true
  never_push_if_shell_syntax_invalid: true
  never_push_if_state_corrupt: true
  never_push_if_large_file_blocked: true

staging:
  mode: all_allowed_changes
  exclude_patterns:
    - ".env"
    - ".env.*"
    - "*.key"
    - "*.pem"
    - "*.p12"
    - "*.pfx"
    - "__pycache__/**"
    - ".venv/**"
    - "node_modules/**"
    - ".DS_Store"

on_success:
  write_sync_report: true
  update_project_sync_ledger: true
  update_state_last_event: true

on_failure:
  write_sync_errors: true
  do_not_commit: true
  do_not_push: true
```

---

## 9. Integration With Existing CLI

The current `run_task.py` appears to own the Typer CLI app. Add commands either directly there or through imported functions from new modules.

Recommended style:

```python
from terminal_chat import chat_main
from rule_self_check import run_self_check
from github_sync import run_sync

@app.command("chat")
def chat(...):
    chat_main(...)

@app.command("check")
def check(...):
    run_self_check(...)

@app.command("sync")
def sync(...):
    run_sync(...)
```

Keep `run_task.py` as command registration, but keep heavy logic inside dedicated modules.

Do not put a huge REPL implementation directly inside `run_task.py`.

---

## 10. How Terminal Chat Should Call Existing Runtime

Terminal chat must reuse existing functions where possible.

Use existing or equivalent functions:

```python
runtime_context(project)
ensure_project_memory_files(project_root)
load_or_build_plan(...)
load_state(...)
save_state(...)
mark_planned(...)
run_agent_model(...)
append_cost_ledgers(...)
```

Do not duplicate project path logic.

Do not implement a second task folder format.

Do not create a database.

---

## 11. Safe Execution Rules

### 11.1 Default dry-run

Terminal chat should default to safe mode.

If the chat session was not started with `--execute`, commands that call external model APIs or modify git remote should require confirmation.

Safe by default:

```text
/status
/progress
/plan
/models
/providers
/open
/check
```

Needs confirmation or `--execute`:

```text
/run
/run-next
/resume if it calls API
```

Needs confirmation unless auto-sync policy allows:

```text
/push
/sync
```

### 11.2 No silent GitHub push on failing check

Never push if `self_check_report.yml` status is `fail`.

### 11.3 No force push

Never run:

```bash
git push --force
git push --force-with-lease
```

unless a future policy explicitly allows it and user confirms interactively.

For this task, force push must be hard-disabled.

### 11.4 No secrets in logs

Do not print env vars, API keys, provider headers, or raw token values.

---

## 12. Minimal Implementation Plan

Implement in this order.

### Phase 1 — Terminal Chat Shell

Files:

```text
agent_runtime/terminal_chat.py
agent_runtime/chat_router.py
```

Add command:

```bash
./agentlab.sh chat --project AgentLab
```

Acceptance criteria:

- User can enter `/help`.
- User can enter natural language and create a new task.
- `chat_transcript.md` is written.
- `/status` works.
- `/task <task_id>` attaches to existing task.
- `/exit` exits cleanly.

### Phase 2 — Self-Check Engine

Files:

```text
agent_runtime/rule_self_check.py
config/self_check_policy.yml
```

Add command:

```bash
./agentlab.sh check --project AgentLab --task-id <task_id>
```

Acceptance criteria:

- Parses policy.
- Detects changed files.
- Runs YAML/Python/Shell syntax checks.
- Runs secret scan.
- Writes `self_check_report.yml`.
- Returns nonzero exit code on fail.

### Phase 3 — GitHub Sync Manager

Files:

```text
agent_runtime/github_sync.py
agent_runtime/git_utils.py
config/auto_sync_policy.yml
```

Add command:

```bash
./agentlab.sh sync --project AgentLab --task-id <task_id>
```

Acceptance criteria:

- Runs self-check first.
- Refuses sync on failure.
- Stages allowed files.
- Commits if changes exist.
- Pushes to origin/main or configured branch.
- Writes `sync_report.yml`.
- Updates `10_SYNC_LEDGER.yml`.

### Phase 4 — Chat Integration

Update Terminal chat slash commands:

```text
/check
/push
/sync
```

Acceptance criteria:

- `/check` displays compact report.
- `/push` runs check then sync.
- If push fails, writes `sync_errors.md` and explains reason.

### Phase 5 — Documentation

Update:

```text
README.md
CLI_ROADMAP.md
OPERATING_MODEL.md
```

Document:

- Terminal chat usage.
- Self-check behavior.
- GitHub sync behavior.
- Safety rules.

---

## 13. Example User Flow

### 13.1 Start chat

```bash
./agentlab.sh chat --project AgentLab
```

Terminal:

```text
AgentLab[AgentLab/no-task]> 给AgentLab加一个自查机制，每次修改后自动上传github
```

Expected:

```text
Created task: task_0024_self-check-github-sync
Prepared workflow plan.
Route: Supervisor -> RepoScout -> InterfaceMapper -> Coder -> TesterAuditor -> Archivist
Next: /run-next
```

### 13.2 Run next agent

```text
AgentLab[AgentLab/task_0024_self-check-github-sync]> /run-next
```

Expected:

```text
Next agent: Supervisor
Mode: dry-run. Use --execute session or confirm to call provider.
```

### 13.3 After modifications

```text
AgentLab[AgentLab/task_0024_self-check-github-sync]> /check
```

Expected:

```text
Self-check: PASS
Changed files: 7
Warnings: 0
Auto-sync eligible: yes
```

### 13.4 Push

```text
AgentLab[AgentLab/task_0024_self-check-github-sync]> /push
```

Expected:

```text
Running self-check...
Self-check PASS.
Committing changes...
Pushing to origin/main...
Pushed commit: abc1234
Sync report written: sync_report.yml
```

---

## 14. Testing Requirements

Add tests if a test framework already exists. If not, provide manual smoke tests in `validation_report.md`.

### 14.1 Self-check smoke tests

1. Create a harmless changed `.md` file.
2. Run `./agentlab.sh check`.
3. Expect pass.

2. Create a temporary file containing fake secret:

```text
sk-test_abcdefghijklmnopqrstuvwxyz123456
```

Run check.

Expect fail and redacted output.

3. Create invalid YAML.

Expect fail.

4. Create invalid Python syntax.

Expect fail.

### 14.2 GitHub sync dry-run tests

Run:

```bash
./agentlab.sh sync --project AgentLab --task-id <task_id> --dry-run
```

Expect:

- no commit;
- no push;
- report says dry-run.

### 14.3 Terminal chat smoke tests

Run:

```bash
./agentlab.sh chat --project AgentLab
```

Test:

```text
/help
/status
/new hello world task
/check
/exit
```

Expect transcript written.

---

## 15. Non-Goals

Do not implement these in this task:

- Full graphical chat UI.
- Cloud runner.
- Remote daemon.
- Multi-user auth.
- Full provider failover.
- Database backend.
- Force push or branch rewrite.
- Automatic PR creation.

This task is strictly:

```text
Terminal chat + deterministic self-check + guarded GitHub auto-sync
```

---

## 16. Implementation Prompt for Codex / AgentLab

Use this exact prompt for the implementation agent:

```text
You are modifying the AgentLab repository. Implement Terminal Chat + Rule-Based Self-Check + Guarded GitHub Auto-Sync according to AGENTLAB_TERMINAL_CHAT_SELF_CHECK_GITHUB_SYNC_SPEC.md.

Hard constraints:
1. Do not remove existing CLI commands.
2. Do not bypass workflow_plan.yml, state.yml, cost_ledger.yml, or brain_decisions.yml.
3. Implement new logic in separate modules, not as a huge block inside run_task.py.
4. Add ./agentlab.sh chat, ./agentlab.sh check, ./agentlab.sh sync, and ./agentlab.sh sync-status.
5. Terminal chat must be usable without external IDE chat.
6. Self-check must be deterministic and rule-based, not LLM-based.
7. GitHub sync must run self-check first.
8. Never push if secrets, invalid YAML, invalid Python syntax, invalid shell syntax, corrupt state, or blocked large files are detected.
9. Never force push.
10. Never print API keys or secrets.
11. Write self_check_report.yml and sync_report.yml into the current task folder.
12. Update projects/<Project>/agent_docs/10_SYNC_LEDGER.yml after successful sync.
13. Keep dry-run safe behavior where applicable.
14. Update README.md and CLI_ROADMAP.md with the new commands.
15. Provide validation_report.md with commands executed and results.

Implementation order:
1. Add config/self_check_policy.yml and config/auto_sync_policy.yml.
2. Add agent_runtime/chat_router.py.
3. Add agent_runtime/terminal_chat.py.
4. Add agent_runtime/rule_self_check.py.
5. Add agent_runtime/git_utils.py.
6. Add agent_runtime/github_sync.py.
7. Register commands in agent_runtime/run_task.py.
8. Run syntax checks and manual smoke tests.
9. Run self-check.
10. If self-check passes, commit and push using the guarded sync manager.
```

---

## 17. Definition of Done

This task is complete only when:

- `./agentlab.sh chat --project AgentLab` starts a usable Terminal chat.
- User can create or attach to tasks from Terminal chat.
- Chat transcript is written into task folder.
- `./agentlab.sh check` writes `self_check_report.yml`.
- `./agentlab.sh sync --dry-run` works.
- `./agentlab.sh sync` refuses to push on failing self-check.
- `./agentlab.sh sync` commits and pushes after passing self-check.
- `10_SYNC_LEDGER.yml` is updated after successful sync.
- README and CLI roadmap document the new behavior.
- No secrets are printed or committed.
- Existing commands still work.
```
