# AgentLab Codex Full-Driver Operation Chain Spec

> Version: v1.0  
> Purpose: Allow Codex to temporarily execute the full AgentLab operating chain while preserving every AgentLab handoff artifact locally, so the project can later continue through AgentLab's own API-based agents without losing context.  
> Target reader: Codex / AgentLab / future runtime implementer  
> Priority: reliability, local traceability, resumability, privacy boundary, backup-first workflow

---

## 0. Executive Summary

AgentLab currently uses a split-brain workflow: API-based brain agents plan/review/archive, while Codex performs real code edits and command execution. This spec introduces a second execution mode:

```text
Codex Full-Driver Mode
```

In this mode, when the user has Codex quota available, Codex may temporarily perform all AgentLab roles **as an external driver**, but it must write the same artifacts that the normal AgentLab pipeline would have produced. The goal is not to replace AgentLab. The goal is to let Codex consume Codex quota while AgentLab still preserves a complete local task record.

The core requirement is:

```text
No AgentLab task may depend on chat memory alone.
Every decision, plan, research result, code change, validation result, and handoff state must be written to the local AgentLab project folder.
```

This allows three safe transitions:

1. **Codex → Codex:** continue the task in a later Codex session.
2. **Codex → AgentLab API agents:** stop using Codex and resume with DeepSeek/Qwen/OpenAI API agents.
3. **Codex → human/manual:** inspect all reports and continue manually.

---

## 1. Problem Statement

The user wants to use Codex quota when available, especially when Codex is already included in a subscription or shared coding plan, instead of consuming separate API credits. However, raw Codex sessions have a major weakness for long projects:

```text
The actual project-development process may remain trapped inside one Codex conversation/session.
```

That creates four risks:

1. If Codex quota runs out, the task may be hard to continue with API agents.
2. If the Codex session is lost, important decisions may be lost.
3. If the user later uses another model, that model may need to rediscover the whole project state.
4. If the account is shared or organizational, the user still needs a private local record of what happened in the project workspace.

AgentLab must therefore treat Codex as an **execution engine** or **external driver**, not as the source of truth.

The source of truth remains:

```text
projects/<ProjectName>/runs/<task_id>/
projects/<ProjectName>/agent_docs/
projects/<ProjectName>/research/
Git history
Backup ledger
```

---

## 2. Definitions

### 2.1 Normal AgentLab API Mode

AgentLab executes role agents through configured providers:

```text
Supervisor        → API brain model
RepoScout         → API brain model
Researcher        → API/research model
InterfaceMapper   → API brain model
CodexPromptGen    → API brain model
Coder             → Codex / Qwen Coder / external editor
TesterAuditor     → API brain model + local shell checks
Archivist         → API brain model
```

### 2.2 Codex Coder Mode

Codex only performs the Coder phase:

```text
API agents plan/review/archive.
Codex edits files and runs commands.
```

This is the existing split-brain model.

### 2.3 Codex Full-Driver Mode

Codex performs every role sequentially, but must write the same artifacts as separate agents:

```text
Codex acting as Supervisor
Codex acting as RepoScout
Codex acting as Researcher
Codex acting as InterfaceMapper
Codex acting as CodexPromptGenerator
Codex acting as Coder
Codex acting as TesterAuditor
Codex acting as Archivist
```

Important: this is **role emulation with artifact separation**, not free-form chat.

### 2.4 Handoff Packet

A machine-readable package that tells AgentLab or another model exactly where the task stopped and what to do next.

Required file:

```text
projects/<Project>/runs/<task_id>/handoff_packet.yml
```

---

## 3. Core Principle

Codex Full-Driver Mode is allowed only if the following rule is obeyed:

```text
Codex may execute all roles, but it must never collapse all roles into one undocumented chat response.
```

Each role must produce its own file. Each file must be sufficient for another model to continue without reading the original Codex conversation.

---

## 4. Required Directory Layout

For every task, create or maintain:

```text
projects/<ProjectName>/runs/<task_id>/
├── user_request.md
├── workflow_plan.yml
├── state.yml
├── progress.yml
├── codex_driver_manifest.yml
├── handoff_packet.yml
│
├── 00_preflight_report.md
├── 01_supervisor_plan.md
├── 02_reposcout_report.md
├── 03_research_notes.md
├── 04_interface_map.md
├── 05_codex_prompt.md
├── 06_implementation_report.md
├── 07_validation_report.md
├── 08_audit_report.md
├── 09_archive_update.md
│
├── brain_decisions.yml
├── cost_ledger.yml
├── provider_incidents.yml
├── USER_DECISION_REQUIRED.md
│
├── diffs/
│   ├── pre_coder.diff
│   ├── post_coder.diff
│   └── final.diff
│
├── checkpoints/
│   ├── checkpoint_000_preflight/
│   ├── checkpoint_001_before_coder/
│   ├── checkpoint_002_after_coder/
│   └── checkpoint_003_final/
│
├── command_logs/
│   ├── commands_run.md
│   └── command_outputs/
│
└── sync/
    ├── self_check_report.yml
    ├── github_sync_report.yml
    └── truenas_sync_report.yml
```

For project-level persistent memory:

```text
projects/<ProjectName>/agent_docs/
├── 00_PROJECT_OVERVIEW.md
├── 01_ARCHITECTURE.md
├── 02_DECISIONS.md
├── 03_RISK_REGISTER.md
├── 04_RESEARCH_INDEX.md
├── 07_DEVELOPMENT_LOG.md
├── 08_CODEX_DIALOGUE_LOG.md
├── 09_COST_LEDGER.yml
└── 10_SYNC_LEDGER.yml
```

For reusable research:

```text
projects/<ProjectName>/research/
├── index.yml
├── topic_cards/
├── reports/
├── source_cache/
└── update_proposals/
```

---

## 5. Execution Mode Configuration

Add this config file:

```text
config/execution_modes.yml
```

Recommended content:

```yaml
execution_modes:
  api_native:
    description: "AgentLab agents run through configured API providers."
    artifact_required: true
    allow_codex_full_driver: false

  codex_coder_only:
    description: "API agents plan/review; Codex only edits code and runs commands."
    artifact_required: true
    allow_codex_full_driver: false

  codex_full_driver:
    description: "Codex emulates all AgentLab roles while writing all standard artifacts."
    artifact_required: true
    allow_codex_full_driver: true
    requires_user_confirmation: true
    requires_local_artifacts: true
    max_audit_reentry_rounds: 3
    allowed_roles:
      - Supervisor
      - RepoScout
      - Researcher
      - InterfaceMapper
      - CodexPromptGenerator
      - Coder
      - TesterAuditor
      - Archivist
    forbidden:
      - undocumented_role_merging
      - editing_without_preflight
      - skipping_validation
      - skipping_handoff_packet
      - pushing_without_self_check
```

Add a per-task setting in `workflow_plan.yml`:

```yaml
execution:
  mode: codex_full_driver
  driver: codex
  driver_scope: full_chain
  artifact_contract: strict
  resume_supported: true
```

---

## 6. CLI Commands to Add

Add commands to `agentlab.sh` / `agent_runtime/run_task.py`:

```bash
./agentlab.sh codex-start \
  --project <ProjectName> \
  --task-id <task_id> \
  --request-file <path> \
  --mode full-driver
```

```bash
./agentlab.sh codex-status \
  --project <ProjectName> \
  --task-id <task_id>
```

```bash
./agentlab.sh codex-handoff \
  --project <ProjectName> \
  --task-id <task_id>
```

```bash
./agentlab.sh codex-resume \
  --project <ProjectName> \
  --task-id <task_id> \
  --from handoff_packet.yml
```

```bash
./agentlab.sh codex-verify-artifacts \
  --project <ProjectName> \
  --task-id <task_id>
```

```bash
./agentlab.sh continue-with-api \
  --project <ProjectName> \
  --task-id <task_id> \
  --from handoff_packet.yml
```

The first implementation may be simple: these commands only create/validate files and print the next required step. They do not need to call Codex directly.

---

## 7. Full Operation Chain

### Phase 0 — User Intent Capture

Codex must create:

```text
user_request.md
```

Template:

```markdown
# User Request

## Original Request
<copy the user's actual request or a faithful short summary>

## Explicit Constraints
- <only constraints stated by the user>

## Forbidden Assumptions
- Do not invent requirements.
- Do not silently expand scope.
- Do not modify unrelated files.

## Requested Execution Mode
Codex Full-Driver Mode

## Continuation Requirement
All reports, decisions, diffs, and handoff state must be saved locally so AgentLab API agents can resume later.
```

---

### Phase 1 — Preflight Guard

Codex must inspect the workspace before any change.

Create:

```text
00_preflight_report.md
```

Required sections:

```markdown
# Preflight Report

## Repository
- Root path:
- Current branch:
- Current commit:
- Git clean status:

## Execution Mode
- Mode: codex_full_driver
- Driver: Codex
- Reason:

## Safety Checks
- .env staged: yes/no
- credentials detected: yes/no
- large files detected: yes/no
- uncommitted user changes: yes/no
- current task folder exists: yes/no

## Checkpoint
- checkpoint id:
- checkpoint path:

## Allowed Scope
- Files allowed to inspect:
- Files allowed to edit:
- Files forbidden to edit:

## Blockers
- none / list blockers
```

Rules:

1. If the Git tree is dirty before Codex starts, Codex must record the dirty files.
2. If dirty files appear to be user work unrelated to the task, stop and ask the user.
3. If secrets are staged, stop immediately.
4. Before code edits, save a checkpoint.

---

### Phase 2 — Workflow Planning

Create or update:

```text
workflow_plan.yml
state.yml
progress.yml
codex_driver_manifest.yml
```

Minimum `workflow_plan.yml`:

```yaml
task_id: task_XXXX
project: <ProjectName>
execution:
  mode: codex_full_driver
  driver: codex
  artifact_contract: strict
route:
  agents:
    - Supervisor
    - RepoScout
    - Researcher
    - InterfaceMapper
    - CodexPromptGenerator
    - Coder
    - TesterAuditor
    - Archivist
scope:
  allowed_edit_paths: []
  forbidden_paths:
    - .env
    - secrets/
    - .git/
    - node_modules/
    - .venv/
validation_gates:
  preflight_required: true
  implementation_report_required: true
  validation_report_required: true
  audit_report_required: true
  handoff_packet_required: true
  self_check_required_before_push: true
resume:
  supported: true
  handoff_file: handoff_packet.yml
```

Minimum `state.yml`:

```yaml
task_id: task_XXXX
project: <ProjectName>
status: running
execution_mode: codex_full_driver
current_phase: planning
current_agent: Supervisor
completed_agents: []
next_agent: Supervisor
last_checkpoint: checkpoint_000_preflight
resume_available: true
blocked: false
```

Minimum `progress.yml`:

```yaml
percent: 5
current_stage: preflight
current_agent: Supervisor
stages:
  preflight: completed
  supervisor: pending
  reposcout: pending
  researcher: pending
  interface_mapper: pending
  coder: pending
  tester_auditor: pending
  archivist: pending
  sync: pending
```

Minimum `codex_driver_manifest.yml`:

```yaml
driver: codex
mode: full_driver
started_at: <iso timestamp>
codex_session_id: unknown
codex_plan_or_account: unknown
cost_visibility: unavailable
local_artifact_contract: strict
all_role_outputs_required: true
resume_target:
  - codex
  - api_native
  - human_manual
```

---

### Phase 3 — Supervisor Role

Codex now acts as Supervisor.

Create:

```text
01_supervisor_plan.md
```

Template:

```markdown
# Supervisor Plan

## Task Summary

## Scope Decision
- In scope:
- Out of scope:

## Route
- Supervisor
- RepoScout
- Researcher: yes/no + reason
- InterfaceMapper: yes/no + reason
- CodexPromptGenerator
- Coder
- TesterAuditor
- Archivist

## Allowed Edits
- <exact paths or path patterns>

## Forbidden Edits
- <exact paths or path patterns>

## Risk Level
- Low / Medium / High

## Acceptance Criteria
- [ ] criterion 1
- [ ] criterion 2

## Stop Conditions
- stop if tests fail in a destructive way
- stop if secrets appear in staged files
- stop if required files are missing
- stop if scope must expand beyond allowed edits

## Next Agent
RepoScout
```

Rules:

1. Supervisor must define allowed edit paths before Coder runs.
2. If allowed edit paths cannot be determined, stop and ask user.
3. Supervisor must not perform code edits.

---

### Phase 4 — RepoScout Role

Codex now acts as RepoScout.

Create:

```text
02_reposcout_report.md
```

Template:

```markdown
# RepoScout Report

## Repository Map

## Relevant Files
| File | Why relevant | Read status |
|---|---|---|

## Existing Runtime Entry Points

## Existing Config Files

## Existing Agent Templates

## Known Constraints from Repo

## Minimal Context for Coder

## Files Not Inspected

## Next Agent
Researcher / InterfaceMapper / CodexPromptGenerator
```

Rules:

1. Prefer minimal inspection over full-repo traversal.
2. If full-repo traversal is needed, write a decision entry in `brain_decisions.yml`.
3. RepoScout must not edit files.

---

### Phase 5 — Researcher Role

Run this phase only if the task requires current external information, docs, pricing, APIs, regulations, or competitor behavior.

Create:

```text
03_research_notes.md
```

Also update:

```text
projects/<ProjectName>/research/index.yml
projects/<ProjectName>/research/topic_cards/<topic_id>.md
```

Template:

```markdown
# Research Notes

## Research Question

## Existing Project Research Checked
- topic cards checked:
- reusable reports:
- freshness status:

## New Findings
| Finding | Source | Date checked | Confidence |
|---|---|---|---|

## Impact on This Task

## What Should Not Be Re-researched Next Time

## Freshness / Expiry
- expires_after:
- reason:

## Next Agent
InterfaceMapper / CodexPromptGenerator
```

Rules:

1. Search existing Research Vault first.
2. Do not repeat prior research unless stale or contradicted.
3. Cite sources in the research note.
4. Separate stable facts from current facts.

---

### Phase 6 — InterfaceMapper Role

Run this phase when the task touches CLI commands, APIs, config schema, file schemas, providers, backup interfaces, or task state.

Create:

```text
04_interface_map.md
```

Template:

```markdown
# Interface Map

## Interfaces Affected

## Existing Contracts
| Interface | Current behavior | File |
|---|---|---|

## Proposed Contract Changes
| Interface | New behavior | Compatibility risk |
|---|---|---|

## File Schema Changes

## CLI Command Changes

## Backward Compatibility

## Migration Notes

## Next Agent
CodexPromptGenerator
```

Rules:

1. If changing schema, document old and new schema.
2. If adding CLI commands, document exact arguments.
3. InterfaceMapper must not implement code.

---

### Phase 7 — CodexPromptGenerator Role

Even though Codex is already driving the task, it must still write a Coder handoff prompt. This creates role separation and makes later replay possible.

Create:

```text
05_codex_prompt.md
```

Template:

```markdown
# Codex Coder Prompt

## Objective

## Read These Files First
- 01_supervisor_plan.md
- 02_reposcout_report.md
- 04_interface_map.md

## Edit Only These Files
- <file list>

## Do Not Edit
- <file list>

## Required Implementation Steps
1.
2.
3.

## Required Reports After Editing
- 06_implementation_report.md
- diffs/post_coder.diff
- command_logs/commands_run.md

## Validation Commands

## Stop Conditions

## Expected Final Behavior
```

Rules:

1. The Coder prompt must be specific enough for another coding model to execute later.
2. No hidden assumptions from chat may be required.

---

### Phase 8 — Coder Role

Codex now edits files and runs commands.

Before editing:

```bash
git diff > projects/<Project>/runs/<task_id>/diffs/pre_coder.diff
```

Create checkpoint:

```text
checkpoints/checkpoint_001_before_coder/
```

After editing, create:

```text
06_implementation_report.md
command_logs/commands_run.md
diffs/post_coder.diff
```

Template:

```markdown
# Implementation Report

## Backend
Codex Full-Driver Mode

## Files Changed
| File | Change summary | Reason |
|---|---|---|

## Commands Run
| Command | Result | Notes |
|---|---|---|

## Behavior Implemented

## Compatibility Notes

## Known Risks

## Files Not Touched

## Next Agent
TesterAuditor
```

Rules:

1. Coder may only edit paths approved by Supervisor.
2. Coder must not silently rewrite large unrelated sections.
3. Coder must write implementation report immediately after editing.
4. Coder must record commands, including failed commands.
5. If Codex quota runs out mid-edit, write `handoff_packet.yml` before stopping if possible.

---

### Phase 9 — TesterAuditor Role

Codex now switches role and audits its own work. It must behave as if it is reviewing another agent's changes.

Create:

```text
07_validation_report.md
08_audit_report.md
```

Validation report template:

```markdown
# Validation Report

## Commands Run
| Command | Result | Output location |
|---|---|---|

## Static Checks
- YAML parse:
- Python compile:
- Shell syntax:
- Link/path checks:

## Functional Checks

## Failed Checks

## Risk Assessment

## Recommendation
READY_FOR_ARCHIVIST / RECOMMEND_CODER_REENTRY / BLOCKED_USER_DECISION
```

Audit report template:

```markdown
# Audit Report

## Diff Summary

## Scope Compliance
- Edited only approved files: yes/no
- Sensitive files touched: yes/no
- Large unrelated rewrite: yes/no

## Security / Secret Scan

## State Consistency
- state.yml valid: yes/no
- progress.yml valid: yes/no
- handoff_packet.yml valid: yes/no

## Findings
| Severity | Finding | Required action |
|---|---|---|

## Final Decision
READY_FOR_ARCHIVIST / RECOMMEND_CODER_REENTRY / BLOCKED_USER_DECISION
```

Rules:

1. If audit finds issues, return to Coder phase.
2. Maximum Coder re-entry: 3 rounds.
3. Each re-entry must append to `06_implementation_report.md`, not erase it.
4. Never mark ready if validation was not actually run.

---

### Phase 10 — Archivist Role

Create:

```text
09_archive_update.md
```

Update as needed:

```text
agent_docs/07_DEVELOPMENT_LOG.md
agent_docs/08_CODEX_DIALOGUE_LOG.md
agent_docs/09_COST_LEDGER.yml
agent_docs/10_SYNC_LEDGER.yml
research/index.yml
```

Template:

```markdown
# Archive Update

## Task Completed
- task_id:
- title:
- execution_mode: codex_full_driver

## What Changed

## Why It Changed

## Important Decisions to Remember

## Research Added / Updated

## Follow-up Tasks

## Resume Notes

## Backup Status
- GitHub:
- TrueNAS:
- Local checkpoint:
```

Rules:

1. Archivist must preserve long-term project memory.
2. Archivist must not invent hidden reasoning.
3. Archivist should summarize user-visible decisions and artifacts.

---

### Phase 11 — Handoff Packet

Create or update:

```text
handoff_packet.yml
```

Required schema:

```yaml
task_id: task_XXXX
project: <ProjectName>
execution_mode: codex_full_driver
status: completed # running | paused | blocked | completed
last_completed_agent: Archivist
next_agent: null
resume_available: true

artifacts:
  user_request: user_request.md
  workflow_plan: workflow_plan.yml
  supervisor_plan: 01_supervisor_plan.md
  reposcout_report: 02_reposcout_report.md
  research_notes: 03_research_notes.md
  interface_map: 04_interface_map.md
  codex_prompt: 05_codex_prompt.md
  implementation_report: 06_implementation_report.md
  validation_report: 07_validation_report.md
  audit_report: 08_audit_report.md
  archive_update: 09_archive_update.md

code_state:
  branch: <branch>
  base_commit: <sha>
  final_commit: <sha or null>
  dirty: true/false
  changed_files: []

validation:
  status: passed # passed | failed | partial | not_run
  commands_run: []
  known_risks: []

resume_instructions:
  for_codex: "Read handoff_packet.yml, then continue from next_agent."
  for_api_agents: "Run ./agentlab.sh continue-with-api --project <ProjectName> --task-id task_XXXX --from handoff_packet.yml"
  for_human: "Read 09_archive_update.md and 08_audit_report.md first."

backup:
  github_pushed: true/false
  truenas_synced: true/false
  local_checkpoint: checkpoint_003_final
```

If Codex stops early, `status` must be `paused` or `blocked`, and `next_agent` must be set.

---

### Phase 12 — Self-Check and Sync

Before GitHub push or TrueNAS sync, run self-check.

Create:

```text
sync/self_check_report.yml
```

Minimum checks:

```yaml
checks:
  git_status_recorded: pass/fail
  no_env_staged: pass/fail
  no_credentials_detected: pass/fail
  yaml_files_parse: pass/fail
  python_files_compile: pass/fail/not_applicable
  shell_files_syntax: pass/fail/not_applicable
  required_artifacts_exist: pass/fail
  handoff_packet_valid: pass/fail
  validation_report_exists: pass/fail
  audit_report_exists: pass/fail
  backup_manifest_updated: pass/fail
result: pass/fail
```

Only if `result: pass`, proceed to commit/push.

Recommended commit message:

```text
agentlab: codex full-driver task_<id> <short summary>
```

After GitHub push:

```text
sync/github_sync_report.yml
```

After TrueNAS sync:

```text
sync/truenas_sync_report.yml
```

---

## 8. Resume Rules

### 8.1 Resume with Codex

Codex must start by reading:

```text
handoff_packet.yml
state.yml
progress.yml
09_archive_update.md
08_audit_report.md
```

Then continue from `next_agent`.

### 8.2 Resume with AgentLab API Agents

AgentLab must use:

```bash
./agentlab.sh continue-with-api --project <ProjectName> --task-id <task_id> --from handoff_packet.yml
```

Behavior:

1. Read `handoff_packet.yml`.
2. Validate all required artifacts.
3. Identify `next_agent`.
4. Load prior role reports as context.
5. Continue using configured API providers.
6. Never ask the API model to rediscover already documented work unless artifacts are missing or stale.

### 8.3 Resume After Codex Quota Exhaustion

If Codex quota runs out, Codex must write:

```text
provider_incidents.yml
handoff_packet.yml
state.yml
progress.yml
```

Example `provider_incidents.yml` entry:

```yaml
- timestamp: <iso timestamp>
  provider: codex
  incident_type: quota_exhausted
  phase: Coder
  status: paused
  safe_to_resume: true
  resume_from: handoff_packet.yml
  notes: "Codex stopped after editing files but before validation. Run validation before continuing."
```

---

## 9. Cost and Privacy Accounting

### 9.1 Cost Ledger

Codex plan usage is usually not exposed as exact per-task billing telemetry. Therefore record:

```yaml
- provider: codex
  execution_mode: codex_full_driver
  exact_cost: unavailable
  billing_source: external_subscription_or_shared_plan
  local_artifacts_saved: true
```

For API mode, record exact API usage when available.

### 9.2 Shared or Company Account Warning

Local AgentLab artifacts preserve the user's own project record, but they do **not** guarantee that the external Codex provider, organization administrator, workspace owner, or compliance tooling cannot see usage metadata or content according to the account's policy.

Therefore:

1. Do not process confidential company code through a personal AgentLab project unless authorized.
2. Do not process personal proprietary code through a company/shared Codex account unless policy allows it.
3. Do not rely on local saving as a privacy guarantee.
4. Never put API keys, private keys, client secrets, or credentials into Codex prompts or AgentLab reports.
5. Keep `.env`, `secrets/`, and credentials excluded from GitHub and backup reports.

### 9.3 Safe Use Position

The safe claim is:

```text
AgentLab can preserve a complete local project-development record independent of Codex sessions.
```

The unsafe claim is:

```text
Using a shared/company Codex account means the development process is invisible to others.
```

AgentLab must never promise the unsafe claim.

---

## 10. Role Separation Rules for Same-Model Execution

When Codex performs multiple roles, it must follow these separation rules:

1. Each role must write a separate artifact.
2. Later roles may cite earlier artifacts but must not silently rewrite them.
3. If a prior artifact is wrong, create an amendment section:

```markdown
## Amendment
- Previous statement:
- Correction:
- Reason:
- Affected downstream files:
```

4. Coder cannot override Supervisor scope without writing `USER_DECISION_REQUIRED.md`.
5. TesterAuditor must review the diff as if created by another agent.
6. Archivist must summarize what happened, not invent reasoning.

---

## 11. Required Agent Templates

Add templates:

```text
agent_templates/codex_full_driver/
├── 00_PRE_FLIGHT.md
├── 01_SUPERVISOR.md
├── 02_REPOSCOUT.md
├── 03_RESEARCHER.md
├── 04_INTERFACE_MAPPER.md
├── 05_CODEX_PROMPT_GENERATOR.md
├── 06_CODER.md
├── 07_TESTER_AUDITOR.md
├── 08_ARCHIVIST.md
└── 09_HANDOFF.md
```

Each template must contain:

```text
Role
Inputs
Outputs
Forbidden actions
Required artifact path
Completion criteria
```

---

## 12. Minimal Implementation Plan

### Phase A — Documentation and Templates

1. Add this spec as:

```text
docs/AGENTLAB_CODEX_FULL_DRIVER_OPERATION_CHAIN_SPEC.md
```

2. Add templates under:

```text
agent_templates/codex_full_driver/
```

3. Update `DRIVER_PROTOCOL.md` to define two Codex modes:

```text
codex_coder_only
codex_full_driver
```

### Phase B — Local Artifact Validator

Add:

```text
agent_runtime/codex_artifact_validator.py
```

Responsibilities:

1. Check required files exist.
2. Check YAML parses.
3. Check handoff packet schema.
4. Check report sequence.
5. Check whether task can resume.

Add command:

```bash
./agentlab.sh codex-verify-artifacts --project <ProjectName> --task-id <task_id>
```

### Phase C — Handoff Builder

Add:

```text
agent_runtime/handoff_builder.py
```

Responsibilities:

1. Read state/progress/reports.
2. Build `handoff_packet.yml`.
3. Mark `next_agent`.
4. Mark continuation mode options.

Add command:

```bash
./agentlab.sh codex-handoff --project <ProjectName> --task-id <task_id>
```

### Phase D — API Continuation

Add:

```text
agent_runtime/api_continuation.py
```

Responsibilities:

1. Read `handoff_packet.yml`.
2. Reconstruct context package.
3. Run next API agent.
4. Append reports without destroying Codex artifacts.

Add command:

```bash
./agentlab.sh continue-with-api --project <ProjectName> --task-id <task_id> --from handoff_packet.yml
```

---

## 13. Acceptance Criteria

This feature is complete when:

1. A user can start a task in Codex Full-Driver Mode.
2. Codex can write all AgentLab role artifacts locally.
3. Codex can stop mid-task and leave a valid `handoff_packet.yml`.
4. AgentLab can validate artifacts without calling an API.
5. AgentLab can resume the task with API agents using only local artifacts.
6. Self-check blocks GitHub push if required reports or handoff files are missing.
7. Final archive includes development log, cost ledger, and sync ledger updates.
8. No step relies on Codex conversation memory as the only source of truth.

---

## 14. One-Shot Prompt for Codex

Use this prompt when asking Codex to operate in Full-Driver Mode:

```text
You are operating AgentLab in Codex Full-Driver Mode.

You may temporarily perform all AgentLab roles because Codex quota is available, but AgentLab's local files remain the source of truth.

Do not collapse roles into one chat response. Execute the role chain exactly:

Preflight → Supervisor → RepoScout → Researcher if needed → InterfaceMapper if needed → CodexPromptGenerator → Coder → TesterAuditor → Archivist → Handoff → Self-check → GitHub/backup sync.

For each role, write the required artifact into:
projects/<ProjectName>/runs/<task_id>/

Required files:
- user_request.md
- workflow_plan.yml
- state.yml
- progress.yml
- codex_driver_manifest.yml
- 00_preflight_report.md
- 01_supervisor_plan.md
- 02_reposcout_report.md
- 03_research_notes.md if research is needed
- 04_interface_map.md if interfaces are affected
- 05_codex_prompt.md
- 06_implementation_report.md
- 07_validation_report.md
- 08_audit_report.md
- 09_archive_update.md
- handoff_packet.yml
- sync/self_check_report.yml

Rules:
1. Do not edit files before preflight and Supervisor scope approval.
2. Do not edit outside allowed paths.
3. Record all commands and diffs.
4. If quota runs out or uncertainty appears, stop only after writing handoff_packet.yml, state.yml, and progress.yml.
5. Make the task resumable by AgentLab API agents without reading this Codex chat.
6. Do not stage or commit secrets.
7. Push to GitHub only after self-check passes.

Begin by reading user_request.md or creating it from the user's request. Then create the preflight report.
```

---

## 15. Final Design Judgment

Codex Full-Driver Mode is useful only if it strengthens AgentLab's local project governance.

Bad version:

```text
Codex just chats and edits, while AgentLab becomes decorative.
```

Good version:

```text
Codex consumes Codex quota, but AgentLab keeps the task chain, artifacts, decisions, diffs, validation, backup, and resume state.
```

Therefore the correct positioning is:

```text
Codex = temporary execution engine
AgentLab = permanent project memory, governance, checkpoint, backup, and resume system