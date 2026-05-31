# AgentLab Provider Failover + Resume + Progress UI Guard Spec

> Version: 1.0  
> Date: 2026-05-31  
> Target repository: `Kidrage/AgentLab`  
> Purpose: Implement a reliable protection layer so AgentLab can survive provider quota exhaustion, provider outage, local process interruption, and half-finished tasks without losing task state or forcing duplicate research.  
> Priority: **P0 / must implement before any long-running managed task execution**

---

## 0. Implementation instruction for AgentLab/Codex

This document is an implementation specification. Follow it directly.

Do **not** redesign the whole AgentLab architecture. Implement the smallest safe runtime extension that satisfies the acceptance tests below.

The goal is to add:

1. **Provider quota/failover protection**: if the current model/API hits quota, rate limit, missing balance, or temporary provider outage, AgentLab must either switch to a compatible provider or pause safely.
2. **Lossless pause/resume**: if the user recharges API credits or changes provider later, the current task must resume from the last safe checkpoint without repeating finished agent stages.
3. **CLI progress interface**: AgentLab must expose a clear command-line status/progress view for active tasks.
4. **Web UI progress extension**: the existing Web UI should read the same status files as the CLI and display task progress, provider health, incidents, and resume actions.
5. **No unsafe silent fallback**: fallback may be automatic only when allowed by policy and role capability. Otherwise it must pause, checkpoint, and ask the user.

---

## 1. Current repository diagnosis

The current AgentLab repository already has a reasonable local-first foundation:

- `agentlab.sh` is the one-command CLI shell entrypoint and dispatches into `agent_runtime/run_task.py`.
- `agent_runtime/run_task.py` already provides commands such as `init-task`, `prepare`, `status`, `models`, `policy-status`, `harness-status`, `request-coder-quota`, and `run-agent`.
- `projects/<ProjectName>/runs/<task_id>/` is already the task audit folder.
- `workflow_plan.yml`, `state.yml`, `brain_decisions.yml`, `cost_ledger.yml`, report markdown files, and `USER_DECISION_REQUIRED.md` are already used as task state/audit files.
- `web_ui/server.py` already reads the filesystem and returns project/task status to the frontend.
- `web_ui/index.html` already exists as the local dashboard.
- The current operating model is split-brain: DeepSeek for brain/planning/review, Codex Plus for execution, Qwen as fallback in some Coder cases.

This means the correct implementation direction is:

> Keep CLI + filesystem as the source of truth. Extend the runtime state files. Let both CLI and Web UI read the same state. Never let Web UI become a second state system.

---

## 2. Fundamental logic issues that must be fixed

These are not fatal design flaws, but they will become production blockers if not corrected.

### 2.1 Hard-coded brand-as-role logic

Current logic treats `DeepSeek` as the required brain and `Codex Plus` as the required executor. This is too rigid.

Correct model:

```text
Role capability > model brand
```

AgentLab should define roles such as:

- `brain_planner`
- `repo_reader`
- `researcher`
- `interface_mapper`
- `coder_executor`
- `tester_auditor`
- `archivist`

Each role may have one or more providers/models that satisfy it.

DeepSeek can remain the default primary brain provider, but it must not be the only possible brain provider. If DeepSeek quota is exhausted and a policy-approved brain fallback exists, AgentLab should switch or pause based on policy.

### 2.2 Quota fallback is currently stage-specific, not system-level

Current Coder quota logic exists, but quota protection must apply to **every API-backed stage**, including Supervisor, RepoScout, Researcher, InterfaceMapper, TesterAuditor, Verifier, and Archivist.

Provider failure handling should be centralized in a new provider guard, not scattered across individual agent commands.

### 2.3 Manual external Coder cannot be treated as seamlessly resumable unless there is a handshake

Codex Plus is not a normal API provider from AgentLab's perspective. AgentLab cannot read exact Codex quota or force a Codex session to resume a half-written edit unless AgentLab records:

- Coder handoff prompt
- approved file scope
- pre-edit checkpoint
- post-edit diff
- implementation report
- commands run
- completion marker

Therefore external Coder execution must follow a strict handoff/return contract.

### 2.4 Existing status UI should not become the executor

The Web UI should display status and call CLI actions. It must not bypass:

- `workflow_plan.yml`
- `state.yml`
- validation gates
- provider guard
- checkpoint manager
- backup manager

All state-changing Web UI endpoints must call the same runtime functions used by CLI commands.

### 2.5 Keyword-only route classification is fragile

The current route selection is mostly keyword/length-based. Keep it for now, but add risk override signals:

- files may be deleted
- database/schema/config/security/auth/payment changes
- project-wide refactor
- package manager changes
- CI/build/deployment changes
- external credentials/API changes
- cross-project or backup-related changes

Any risk override should escalate protection level even if the task text is short.

---

## 3. New runtime modules to add

Add the following modules under `agent_runtime/`.

```text
agent_runtime/
├── atomic_io.py                # atomic YAML/JSON/text writes + fsync
├── provider_guard.py           # provider health, quota classification, fallback selection
├── provider_registry.py        # load provider pool, role capabilities, fallback chains
├── task_checkpoint.py          # checkpoint, rollback preview, restore metadata
├── progress_tracker.py         # progress.yml state updates and rendering data
├── progress_renderer.py        # CLI table/watch rendering
├── resume_manager.py           # paused task scan and resume plan generation
├── incident_manager.py         # provider incidents and blocked states
└── task_orchestrator.py        # optional sequential run-next/run-task wrapper
```

Do not remove existing modules. Wire these into existing `run_task.py`, `llm_provider.py`, and `web_ui/server.py`.

---

## 4. Filesystem layout additions

For each task:

```text
projects/<ProjectName>/runs/<task_id>/
├── state.yml
├── workflow_plan.yml
├── progress.yml                         # NEW: source-of-truth progress summary
├── provider_health.yml                  # NEW: per-task provider health snapshot
├── provider_incidents.yml               # NEW: quota/rate-limit/outage incidents
├── resume_plan.yml                      # NEW: written when paused/resumable
├── llm_calls/                           # NEW: lossless API call ledger
│   └── <call_id>/
│       ├── request.yml
│       ├── messages.json
│       ├── settings.yml
│       ├── response.json                # only after success
│       ├── error.yml                    # only after failure
│       └── status.yml
├── checkpoints/                         # NEW: task/agent/coder checkpoints
│   └── <checkpoint_id>/
│       ├── manifest.yml
│       ├── state.yml
│       ├── progress.yml
│       ├── workflow_plan.yml
│       ├── reports_snapshot/
│       └── git_diff.patch               # if source repo is bound
├── USER_DECISION_REQUIRED.md
└── MODEL_SWITCH_NOTICE.md               # NEW: only when fallback/switch happened
```

For each project:

```text
projects/<ProjectName>/
├── project_config.yml
├── agent_docs/
├── research/                            # from previous Research Vault design
├── runs/
└── .agentlab/
    ├── provider_pool_cache.yml
    ├── active_task_lock.yml
    ├── backup_queue.yml
    └── last_known_good.yml
```

---

## 5. Provider pool configuration

Add a new config file:

```text
config/provider_pool.yml
```

Suggested schema:

```yaml
version: 1

provider_policy:
  default_failover_mode: pause_then_ask
  allow_automatic_fallback_for_low_risk: true
  allow_automatic_fallback_for_high_risk: false
  write_model_switch_notice: true
  require_checkpoint_before_switch: true
  require_same_or_higher_capability_class: true
  max_fallback_attempts_per_agent: 2
  max_total_provider_switches_per_task: 4
  rate_limit_retry_seconds: [2, 5, 15]
  provider_circuit_breaker_minutes: 30

roles:
  brain_planner:
    capability_class: brain
    min_quality: strong
    allowed_providers:
      - deepseek_pro
      - qwen_plus
      - qwen_max
      - openai_reasoning
    default_chain:
      - deepseek_pro
      - qwen_max
      - qwen_plus
    automatic_fallback: false

  repo_reader:
    capability_class: perception
    min_quality: medium
    allowed_providers:
      - qwen_plus
      - qwen_flash
      - deepseek_flash
      - deepseek_pro
    default_chain:
      - qwen_plus
      - deepseek_flash
      - qwen_flash
    automatic_fallback: true

  researcher:
    capability_class: research
    min_quality: medium
    allowed_providers:
      - qwen_plus
      - qwen_flash
      - deepseek_flash
      - deepseek_pro
    default_chain:
      - qwen_plus
      - deepseek_flash
      - qwen_flash
    automatic_fallback: true

  coder_executor:
    capability_class: execution
    min_quality: strong
    allowed_providers:
      - codex_plus_manual
      - qwen_coder_api
      - deepseek_pro_patch
    default_chain:
      - codex_plus_manual
      - qwen_coder_api
    automatic_fallback: false
    fallback_output_mode: patch_proposal_only

  tester_auditor:
    capability_class: audit
    min_quality: medium
    allowed_providers:
      - qwen_plus
      - qwen_max
      - deepseek_pro
      - deepseek_flash
    default_chain:
      - qwen_plus
      - deepseek_pro
    automatic_fallback: false

  archivist:
    capability_class: archive
    min_quality: basic
    allowed_providers:
      - qwen_flash
      - deepseek_flash
      - qwen_plus
    default_chain:
      - qwen_flash
      - deepseek_flash
    automatic_fallback: true

providers:
  deepseek_pro:
    provider_name: deepseek
    provider_type: openai_compatible
    env_api_key: DEEPSEEK_API_KEY
    env_base_url: DEEPSEEK_BASE_URL
    model_env: DEEPSEEK_PRO_MODEL
    default_model: deepseek-v4-pro
    health_check: reactive
    quota_error_patterns:
      - quota
      - balance
      - insufficient
      - credit
      - payment
    rate_limit_error_patterns:
      - rate limit
      - too many requests
    temporary_error_patterns:
      - timeout
      - connection
      - temporarily unavailable
      - service unavailable
    circuit_breaker: true

  deepseek_flash:
    provider_name: deepseek
    provider_type: openai_compatible
    env_api_key: DEEPSEEK_API_KEY
    env_base_url: DEEPSEEK_BASE_URL
    model_env: DEEPSEEK_FLASH_MODEL
    default_model: deepseek-v4-flash
    health_check: reactive
    circuit_breaker: true

  qwen_plus:
    provider_name: qwen
    provider_type: openai_compatible
    env_api_key: QWEN_API_KEY
    env_base_url: QWEN_BASE_URL
    model_env: QWEN_PLUS_MODEL
    default_model: qwen-plus
    health_check: reactive
    circuit_breaker: true

  qwen_max:
    provider_name: qwen
    provider_type: openai_compatible
    env_api_key: QWEN_API_KEY
    env_base_url: QWEN_BASE_URL
    model_env: QWEN_MAX_MODEL
    default_model: qwen-max
    health_check: reactive
    circuit_breaker: true

  qwen_coder_api:
    provider_name: qwen
    provider_type: openai_compatible
    env_api_key: QWEN_API_KEY
    env_base_url: QWEN_BASE_URL
    model_env: QWEN_CODER_MODEL
    default_model: qwen-coder-plus
    health_check: reactive
    circuit_breaker: true
    output_mode: patch_proposal_only

  codex_plus_manual:
    provider_name: codex_plus_manual
    provider_type: external_manual
    health_check: manual
    quota_visibility: unavailable
    output_mode: implementation_report_required
```

Notes:

- Keep model names configurable. Do not hard-code exact public model names into runtime logic.
- Provider pool config must never store API keys directly.
- Environment variables remain private in `.env`, which must stay gitignored.

---

## 6. Provider error classification

Implement `provider_guard.classify_provider_error(exc)`.

Return one of:

```text
quota_exceeded
rate_limited
auth_error
missing_api_key
network_error
timeout
provider_unavailable
context_length_exceeded
invalid_request
content_filter
unknown_provider_error
```

Rules:

- HTTP 401/403 → `auth_error`
- HTTP 402 → `quota_exceeded`
- HTTP 429 → `rate_limited`, unless text contains balance/credit/quota, then `quota_exceeded`
- HTTP 500/502/503/504 → `provider_unavailable`
- timeout exceptions → `timeout`
- connection exceptions → `network_error`
- text contains `quota`, `balance`, `credit`, `insufficient`, `payment` → `quota_exceeded`
- text contains `context length`, `maximum context`, `too many tokens` → `context_length_exceeded`

Important:

- `context_length_exceeded` must not be solved by blindly switching provider. It usually needs summarization, chunking, or route replanning.
- `auth_error` must not silently fallback unless the fallback provider is already configured and policy allows it.
- `quota_exceeded` may fallback only if a compatible provider exists.

---

## 7. LLM call lifecycle: lossless by default

Every API-backed call must follow this lifecycle.

### 7.1 Before call

Create a `call_id`:

```text
<task_id>__<agent_name>__<timestamp_utc>__<short_hash>
```

Write before the network request:

```text
llm_calls/<call_id>/request.yml
llm_calls/<call_id>/messages.json
llm_calls/<call_id>/settings.yml
llm_calls/<call_id>/status.yml
```

`status.yml` initially:

```yaml
status: started
project: <ProjectName>
task_id: <task_id>
agent: <AgentName>
role: <role_name>
provider_key: <provider_key>
model: <model_name>
started_at: <UTC ISO>
attempt: 1
```

Also update `progress.yml`:

```yaml
current_agent: <AgentName>
current_stage: llm_call_started
last_call_id: <call_id>
```

### 7.2 On success

Write response atomically:

```text
llm_calls/<call_id>/response.json
```

Then mark:

```yaml
status: completed
completed_at: <UTC ISO>
input_tokens: <n|null>
output_tokens: <n|null>
total_tokens: <n|null>
```

Only after the agent report file is successfully written and validated should AgentLab update:

```yaml
state.status: running or completed
state.reports.<AgentName>: true
progress.agents.<AgentName>.status: completed
```

### 7.3 On failure

Write:

```text
llm_calls/<call_id>/error.yml
provider_incidents.yml
```

Do not delete the failed request. The failed request is important for resume/fallback.

---

## 8. Provider fallback decision algorithm

Implement in `provider_guard.select_next_provider()`.

Inputs:

- project
- task_id
- agent_name
- role
- current_provider_key
- error_class
- task risk level
- provider pool config
- provider incident history
- user policy override if present

Algorithm:

1. If error is `context_length_exceeded`, return action `replan_required`.
2. If error is `auth_error` or `missing_api_key`, return fallback only if another configured provider has a valid key and policy permits; otherwise pause.
3. If error is `rate_limited`, retry with backoff first. If retry exhausted, fallback if policy permits; otherwise pause.
4. If error is `quota_exceeded`, mark current provider circuit-open for this task. Then:
   - If role allows automatic fallback and task risk is low/medium, select next compatible provider.
   - If role does not allow automatic fallback, write `USER_DECISION_REQUIRED.md` and pause.
5. If error is `provider_unavailable`, fallback if configured; otherwise pause.
6. Never fallback to a provider whose capability class is lower than required.
7. Never fallback Coder direct-edit mode to API direct-edit mode. API Coder fallback must produce patch proposals only unless the user explicitly enables direct patch application.
8. Always create checkpoint before provider switch.
9. Always write `MODEL_SWITCH_NOTICE.md` before continuing with a different provider.

Action output schema:

```yaml
action: switch_provider | pause_for_user | retry_later | replan_required | fail_terminal
reason: quota_exceeded
from_provider: deepseek_pro
to_provider: qwen_max
requires_user_approval: true
checkpoint_id: ckpt_...
message: "DeepSeek quota exceeded during Supervisor. Compatible fallback qwen_max is available, but this is a brain stage and requires approval."
```

---

## 9. User decision file schema

When fallback is not automatically allowed, write `USER_DECISION_REQUIRED.md` like this:

```markdown
# User Decision Required

## Status
Task paused safely. No completed work was lost.

## Reason
Provider quota exceeded during `<AgentName>`.

## Current Stage
- Project: `<ProjectName>`
- Task: `<task_id>`
- Agent: `<AgentName>`
- Role: `<role_name>`
- Failed provider: `<provider_key>`
- Error class: `quota_exceeded`
- Last safe checkpoint: `<checkpoint_id>`
- Last LLM call: `<call_id>`

## Available Options

### Option A — Pause and resume after recharge
Recommended when you want to keep the same model/provider.

Command after recharge:

```bash
./agentlab.sh resume --project <ProjectName> --task-id <task_id>
```

### Option B — Switch to fallback provider
Available fallback provider: `<fallback_provider>`.

Command:

```bash
./agentlab.sh resume --project <ProjectName> --task-id <task_id> --provider <fallback_provider>
```

### Option C — Stop this task
The task remains archived with all reports and checkpoints.

```bash
./agentlab.sh task-clear <task_id> --project <ProjectName> --reason "stopped after provider quota incident"
```

## Safety Note
AgentLab will not rerun completed agents. It will resume from the current blocked agent using the stored prompt package and checkpoint.
```

Also write machine-readable `resume_plan.yml`.

---

## 10. Resume plan schema

`resume_plan.yml`:

```yaml
version: 1
project: <ProjectName>
task_id: <task_id>
status: paused_resumable
paused_at: <UTC ISO>
paused_reason: quota_exceeded
current_agent: Supervisor
current_role: brain_planner
failed_provider: deepseek_pro
failed_call_id: <call_id>
last_safe_checkpoint: <checkpoint_id>
completed_agents:
  - RepoScout
pending_agents:
  - Supervisor
  - Coder
  - TesterAuditor
  - Archivist
resume_mode: same_provider_or_approved_fallback
allowed_resume_providers:
  - deepseek_pro
  - qwen_max
  - qwen_plus
must_reuse_prompt_package: true
must_not_repeat_completed_agents: true
must_validate_reports_before_continue: true
```

Resume command behavior:

```bash
./agentlab.sh resume --project <ProjectName> --task-id <task_id>
```

Should:

1. Load `resume_plan.yml`.
2. Verify last checkpoint exists.
3. Verify completed reports exist and are not placeholders.
4. Verify pending current agent has stored prompt package.
5. If same provider is configured and healthy, retry the current agent from stored messages.
6. If user provided `--provider`, validate it against allowed providers.
7. Continue from current agent, not from task start.
8. Update `progress.yml` and `state.yml`.

---

## 11. Progress tracking

Add `progress.yml` as the simple, canonical progress file.

Schema:

```yaml
version: 1
project: <ProjectName>
task_id: <task_id>
status: new | planned | running | paused | blocked | completed | failed | archived
risk_level: R0 | R1 | R2 | R3
budget_mode: frugal | balanced | max_quality
route:
  - Supervisor
  - RepoScout
  - Coder
  - TesterAuditor
  - Archivist
current_agent: Supervisor
current_stage: planning
percent_complete: 20
last_event: "Supervisor started"
last_event_at: <UTC ISO>
last_checkpoint: ckpt_...
last_call_id: call_...
provider_status:
  current_provider: deepseek_pro
  failed_provider: null
  fallback_available: true
  paused_for_provider: false
agents:
  Supervisor:
    order: 1
    status: completed | active | waiting | skipped | blocked | failed
    provider_key: deepseek_pro
    model: deepseek-v4-pro
    started_at: <UTC ISO|null>
    completed_at: <UTC ISO|null>
    input_tokens: 0
    output_tokens: 0
    total_tokens: 0
    report_path: supervisor_plan.md
  RepoScout:
    order: 2
    status: waiting
    provider_key: qwen_plus
  Coder:
    order: 3
    status: waiting
    provider_key: codex_plus_manual
incidents:
  open_count: 0
  latest: null
backup:
  p0_synced: false
  last_backup_at: null
```

Percent calculation:

```text
completed_weight / total_weight
```

Default weights:

```yaml
Supervisor: 15
RepoScout: 15
Researcher: 15
InterfaceMapper: 15
Coder: 25
TesterAuditor: 20
Verifier: 10
Archivist: 10
```

If an agent is not in route, ignore it. If Coder is manual and waiting for user/external execution, show it as `manual_waiting`.

---

## 12. CLI progress interface

Add these commands to `run_task.py` and expose through `agentlab.sh`.

### 12.1 `progress`

```bash
./agentlab.sh progress --project <ProjectName> --task-id <task_id>
```

Display:

```text
AgentLab Progress
Project: AgentLab
Task: task_0021_provider-failover
Status: paused_resumable
Progress: 42%
Current: Supervisor / quota_exceeded / waiting_user_decision
Last checkpoint: ckpt_20260531_...

Route:
  ✓ Supervisor        deepseek_pro      completed      1,240 tokens
  ✓ RepoScout         qwen_plus         completed      3,812 tokens
  ! Researcher        deepseek_pro      paused         quota_exceeded
  · Coder             codex_manual      waiting
  · TesterAuditor     qwen_plus         waiting
  · Archivist         qwen_flash        waiting

Provider incidents:
  - deepseek_pro quota_exceeded during Researcher at 2026-05-31T...

Next safe commands:
  ./agentlab.sh resume --project AgentLab --task-id task_0021
  ./agentlab.sh resume --project AgentLab --task-id task_0021 --provider qwen_plus
```

### 12.2 `watch`

```bash
./agentlab.sh watch --project <ProjectName> --task-id <task_id> --interval 2
```

Use `rich.live.Live` if available. If not, clear/reprint every interval.

### 12.3 `providers`

```bash
./agentlab.sh providers
./agentlab.sh providers --project <ProjectName> --task-id <task_id>
```

Display provider keys, whether API key is configured, circuit breaker status, and allowed roles.

Never print API keys.

### 12.4 `provider-test`

```bash
./agentlab.sh provider-test --provider deepseek_pro
./agentlab.sh provider-test --provider qwen_plus --dry-run
```

Behavior:

- If dry-run: check config and env only.
- If execute: make a tiny harmless request like `Reply with OK` and record result.

### 12.5 `pause`

```bash
./agentlab.sh pause --project <ProjectName> --task-id <task_id> --reason "manual pause"
```

Creates checkpoint and marks task paused.

### 12.6 `resume`

```bash
./agentlab.sh resume --project <ProjectName> --task-id <task_id>
./agentlab.sh resume --project <ProjectName> --task-id <task_id> --provider qwen_plus
```

Resumes current blocked/pending agent only.

### 12.7 `run-next`

```bash
./agentlab.sh run-next --project <ProjectName> --task-id <task_id> --execute
```

Runs the next pending agent in `progress.yml` / `workflow_plan.yml` route.

### 12.8 `run-task`

```bash
./agentlab.sh run-task --project <ProjectName> --task-id <task_id> --execute
```

Sequentially runs until:

- task completed
- Coder manual handoff required
- user decision required
- provider quota pause
- validation failure
- max loop reached

This command must be conservative. It must stop at manual Coder by default.

---

## 13. Web UI progress design

The existing `web_ui/server.py` should be extended, not replaced.

### 13.1 Backend endpoint additions

Add or extend endpoints:

```text
GET  /api/status?project=<ProjectName>&task_id=<task_id>
GET  /api/progress?project=<ProjectName>&task_id=<task_id>
GET  /api/providers?project=<ProjectName>&task_id=<task_id>
POST /api/task/pause
POST /api/task/resume
POST /api/task/run-next
POST /api/provider/test
```

All POST endpoints must call runtime functions or CLI-equivalent code paths. They must not directly mutate state except through the same atomic helpers.

### 13.2 Frontend additions in `web_ui/index.html`

Add a task progress panel:

```text
[ Task Progress ]
Progress bar: 42%
Current agent: Researcher
Current stage: quota_exceeded / waiting user decision
Last checkpoint: ckpt_...

Agent route timeline:
✓ Supervisor
✓ RepoScout
! Researcher paused
· Coder waiting
· TesterAuditor waiting
· Archivist waiting

Provider health:
DeepSeek Pro: quota exceeded / circuit open
Qwen Plus: configured / available
Codex Manual: manual / quota unknown

Actions:
[Resume Same Provider]
[Resume with Fallback]
[Pause]
[Run Next]
[Open USER_DECISION_REQUIRED]
```

Polling strategy:

- Poll `/api/progress` every 2 seconds while a task is running.
- Poll every 10 seconds when paused/completed.
- No WebSocket required for now.

### 13.3 UI source-of-truth rule

The UI must not keep its own progress state. It must render `progress.yml` and status endpoint responses.

---

## 14. Checkpoint requirements

Create a checkpoint before:

1. Provider switch.
2. Coder stage starts.
3. Applying patch proposal.
4. Running destructive or broad commands.
5. Resuming after provider quota incident.
6. Marking task completed.

Checkpoint manifest:

```yaml
version: 1
checkpoint_id: ckpt_20260531_153012_<hash>
project: <ProjectName>
task_id: <task_id>
created_at: <UTC ISO>
reason: before_provider_switch
current_agent: Researcher
state_files:
  - state.yml
  - progress.yml
  - workflow_plan.yml
  - cost_ledger.yml
  - brain_decisions.yml
reports:
  - supervisor_plan.md
  - reposcout_report.md
git:
  source_repo_path: <path|null>
  head_commit: <hash|null>
  dirty: true
  diff_patch: git_diff.patch
```

Acceptance:

- If a checkpoint cannot be created, provider switch or resume must not proceed.

---

## 15. Atomic write requirements

Implement `atomic_io.py`:

```python
def atomic_write_text(path: Path, text: str) -> None: ...
def atomic_write_yaml(path: Path, data: dict) -> None: ...
def atomic_write_json(path: Path, data: Any) -> None: ...
def safe_read_yaml(path: Path, default: Any = None) -> Any: ...
def safe_read_json(path: Path, default: Any = None) -> Any: ...
```

Atomic write strategy:

1. Write to `.<filename>.tmp.<pid>` in same directory.
2. Flush file.
3. `os.fsync()` file descriptor.
4. `os.replace(tmp, target)`.
5. `fsync()` parent directory where supported.

Use this for:

- `state.yml`
- `progress.yml`
- `workflow_plan.yml`
- `cost_ledger.yml`
- `brain_decisions.yml`
- `provider_incidents.yml`
- `resume_plan.yml`
- `provider_health.yml`
- checkpoint manifests
- research vault index
- backup queue

---

## 16. Coder fallback rules

Coder is special.

### 16.1 Codex Plus manual Coder

When Codex Plus executes Coder manually, AgentLab must write a handoff package:

```text
coder_handoff/
└── <handoff_id>/
    ├── CoderPrompt.md
    ├── approved_scope.yml
    ├── pre_edit_checkpoint.yml
    ├── expected_report_schema.yml
    └── return_instructions.md
```

Codex must return:

```text
implementation_report.md
commands_run.yml
diff_summary.md
```

AgentLab then runs TesterAuditor.

### 16.2 API Coder fallback

When Codex quota is unavailable and user chooses API fallback:

- API Coder must produce a patch proposal first.
- Do not apply patch automatically unless `--apply-approved-patch` is passed or policy allows it.
- Save patch under:

```text
patches/<patch_id>.patch
patches/<patch_id>_rationale.md
```

Then user or an approved patch applicator applies it.

---

## 17. Provider switching safety matrix

| Stage | Automatic fallback allowed? | Requires user approval? | Output mode |
|---|---:|---:|---|
| Supervisor | No by default | Yes | report |
| RepoScout | Yes if low/medium risk | No for low risk, yes for high risk | report |
| Researcher | Yes if low/medium risk | No for low risk, yes for high risk | report |
| InterfaceMapper | No by default | Yes | report |
| Coder manual → API | No | Yes | patch proposal only |
| TesterAuditor | No by default | Yes | report |
| Archivist | Yes | No unless project memory conflict | report |

---

## 18. Integration points

### 18.1 Modify `llm_provider.py`

Wrap provider calls with:

```python
ProviderGuard.before_call(...)
ProviderGuard.record_started_call(...)
try:
    response = actual_provider_call(...)
    ProviderGuard.record_success(...)
except Exception as exc:
    decision = ProviderGuard.handle_failure(...)
    if decision.action == "switch_provider":
        return retry_with_provider(decision.to_provider)
    if decision.action == "pause_for_user":
        return blocked_user_decision_result(...)
    if decision.action == "replan_required":
        return replan_required_result(...)
    raise
```

### 18.2 Modify `run_task.py`

Add commands:

```text
progress
watch
providers
provider-test
pause
resume
run-next
run-task
checkpoint
rollback-preview
```

Replace direct `path.write_text` or `ledger_path.write_text` for state/audit files with atomic helpers.

### 18.3 Modify `state_store.py`

Use atomic write. Add fields:

```yaml
status: running | paused | blocked | completed
current_agent: <AgentName>
current_call_id: <call_id|null>
last_checkpoint: <checkpoint_id|null>
resume_available: true|false
provider_blocked: true|false
```

### 18.4 Modify `web_ui/server.py`

Read and expose:

- `progress.yml`
- `provider_incidents.yml`
- `resume_plan.yml`
- `provider_health.yml`
- `checkpoints/*/manifest.yml`

Add POST handlers that call safe runtime functions.

### 18.5 Modify `web_ui/index.html`

Add visible task timeline and provider incident panels.

---

## 19. Minimal implementation order

Implement in this exact order.

### Phase 1 — P0 provider pause/resume foundation

1. `atomic_io.py`
2. `progress_tracker.py`
3. `incident_manager.py`
4. `provider_guard.py` with classification and pause behavior
5. `llm_provider.py` integration
6. CLI: `progress`, `providers`, `pause`, `resume`

Acceptance: a simulated quota error pauses the task and writes `USER_DECISION_REQUIRED.md`, `provider_incidents.yml`, `resume_plan.yml`, and `progress.yml`.

### Phase 2 — safe fallback switching

1. `provider_registry.py`
2. `config/provider_pool.yml`
3. fallback chain validation
4. `MODEL_SWITCH_NOTICE.md`
5. CLI: `provider-test`, `resume --provider`

Acceptance: a failed DeepSeek call can resume with Qwen after explicit user approval, without rerunning completed agents.

### Phase 3 — checkpoint manager

1. `task_checkpoint.py`
2. checkpoint before provider switch
3. checkpoint before Coder
4. rollback preview

Acceptance: before fallback switch, checkpoint exists and rollback preview shows exactly what would be restored.

### Phase 4 — progress UI

1. Extend CLI `watch`
2. Extend `web_ui/server.py`
3. Extend `web_ui/index.html`

Acceptance: Web UI and CLI show the same current task status.

### Phase 5 — orchestrated run-next/run-task

1. `task_orchestrator.py`
2. `run-next`
3. `run-task`
4. stop at manual Coder or user decision

Acceptance: one command can progress through non-manual agents until a safe stop condition.

---

## 20. Acceptance tests

Add tests or manual test scripts under:

```text
scripts/test_provider_guard.py
scripts/test_resume_flow.py
scripts/test_progress_cli.py
```

### Test A: quota pause

Simulate provider error:

```bash
AGENTLAB_TEST_FORCE_PROVIDER_ERROR=quota_exceeded \
./agentlab.sh run-agent Supervisor --project AgentLab --task-id task_test_quota --execute
```

Expected:

- `state.yml` status becomes `paused` or `blocked_user_decision`
- `progress.yml` exists
- `provider_incidents.yml` exists
- `resume_plan.yml` exists
- `USER_DECISION_REQUIRED.md` exists
- completed previous reports are not modified

### Test B: resume same provider

After clearing forced error:

```bash
./agentlab.sh resume --project AgentLab --task-id task_test_quota
```

Expected:

- resumes current agent only
- does not rerun completed agents
- `progress.yml` updates

### Test C: resume fallback provider

```bash
./agentlab.sh resume --project AgentLab --task-id task_test_quota --provider qwen_plus
```

Expected:

- writes `MODEL_SWITCH_NOTICE.md`
- creates checkpoint before switch
- uses stored prompt package
- appends cost/provider ledger

### Test D: CLI progress

```bash
./agentlab.sh progress --project AgentLab --task-id task_test_quota
```

Expected readable table with:

- task status
- current agent
- route
- provider status
- next safe commands

### Test E: Web UI consistency

Start UI:

```bash
python3 agentlab_app.py
```

Expected:

- selected task shows same progress as CLI
- provider incident is visible
- resume buttons correspond to available options

### Test F: no silent unsafe fallback

For Supervisor high-risk task with quota error:

Expected:

- no automatic fallback
- writes user decision file
- task remains resumable

### Test G: low-risk Researcher automatic fallback

For low-risk research task with Researcher quota error and configured Qwen fallback:

Expected:

- automatic fallback allowed if policy says so
- writes `MODEL_SWITCH_NOTICE.md`
- continues after checkpoint

---

## 21. Final behavior standard

When API quota is exhausted mid-task, AgentLab must behave like this:

```text
1. Save everything already known.
2. Record exactly which provider/model failed.
3. Create checkpoint.
4. Decide whether fallback is allowed.
5. If safe, switch provider with notice.
6. If not safe, pause and ask user.
7. After recharge or approval, resume from the blocked agent using stored prompt package.
8. Never rerun completed agents unless user explicitly requests rerun.
9. Never silently let a weaker or unauthorized model take over a high-risk stage.
```

When the user asks “where is the task now?”, AgentLab must answer through either CLI or UI:

```bash
./agentlab.sh progress --project <ProjectName> --task-id <task_id>
./agentlab.sh watch --project <ProjectName> --task-id <task_id>
```

The Web UI must show the same thing by reading the same `progress.yml`.

---

## 22. Definition of done

This task is complete only when:

- Provider quota failures are classified and persisted.
- A failed provider call leaves a resumable task, not a corrupted task.
- User can recharge and run `resume` without losing progress.
- User can switch provider through `resume --provider` when policy allows.
- CLI shows clear progress.
- Web UI shows the same progress.
- Checkpoints are created before provider switch and Coder execution.
- No API key is printed or written to reports.
- No completed agent is rerun during resume unless explicitly requested.
- Existing commands continue to work.
