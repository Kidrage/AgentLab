# External Agent Handoff Protocol

## Overview

AgentLab supports external agent handoffs for agents like Cline/Codex and ECC Skill Pack. The protocol is strictly **handoff_only** — AgentLab creates artifacts that a human user can give to an external agent, but AgentLab does **NOT** automatically execute, invoke, or manage external agents.

## Key Design Principles

- **AgentLab only creates handoff artifacts.** AgentLab does not execute Cline/Codex/ECC automatically.
- **AgentLab does not access subscription tokens.** No OAuth tokens, API keys, or subscription credentials are read or used.
- **External costs are tracked as unknown unless explicitly reported.** The default for subscription-based external agents is `unknown`, never `0`.
- **External results require evidence.** Commands run, build/test claims, and changed files must be accompanied by evidence or marked `external_unverified`.
- **Submitting an external result does not automatically pass the artifact gate.** A human or supervisor must separately approve.

## Handoff Creation Process

### 1. Prerequisites

- External agent must be registered in `config/external_agents.yml`
- Default agents are disabled (`enabled: false`)
- Integration mode must be `handoff_only`
- User must explicitly trigger the handoff creation via CLI

### 2. Handoff Artifacts

The handoff process generates two artifacts in the task run directory:

- `external_handoff.yml` — Machine-readable YAML format
- `external_handoff.md` — Human-readable Markdown that can be copied to Cline/Codex/ECC

### 3. Handoff Data Model

```yaml
handoff_id: "handoff_task_001_cline_codex_20260612_120000_abc12345"
task_id: "task_001"
project: "AgentLab"
created_at: "2026-06-12T12:00:00+00:00"
target:
  agent_id: "cline_codex"
  display_name: "Cline with Codex Subscription"
  type: "ide_agent"
  integration_mode: "handoff_only"
  enabled: false
  status: "proposed"
objective:
  title: "Implement feature X"
  summary: "Description of the task"
constraints:
  - "Do not auto-run external tools from AgentLab."
  - "Do not full clone remote repositories unless explicitly approved."
  - "Do not install dependencies without approval."
  - "Do not copy third-party source code."
  - "Do not expose secrets, API keys, OAuth tokens, or subscription credentials."
  - "Return changed files, commands run, evidence artifacts, and residual risks."
required_outputs:
  - implementation_summary
  - changed_files
  - tests_run
  - evidence_artifacts
  - residual_risks
  - cost_notes
budget:
  billing_mode: "subscription_quota"
  api_cost_visible: false
  external_token_visibility: "unknown"
  expected_agentlab_api_cost_usd: null
evidence_requirements:
  require_changed_files: true
  require_test_summary: true
  require_execution_log_or_external_unverified_marker: true
  require_no_secret_leak: true
  require_residual_risks: true
```

### 4. Markdown Format

The `external_handoff.md` is formatted so a human can copy it to an external agent context window. It includes all constraints, required outputs, evidence requirements, and submission instructions.

## CLI Commands

```bash
# List configured external agents
python -m agent_runtime.external_agents_cli list

# Create a handoff
python -m agent_runtime.external_agents_cli create-handoff \
  --task-id task_001 \
  --agent-id cline_codex \
  --title "Implement feature X" \
  --summary "Add new feature with tests"

# View ledger for a task
python -m agent_runtime.external_agents_cli ledger --task-id task_001

# Submit a result
python -m agent_runtime.external_agents_cli submit-result \
  --task-id task_001 \
  --handoff-id handoff_xxx \
  --result-file path/to/result.yml
```

## Key Constraints

### 1. Agent Configuration

- Only `integration_mode: handoff_only` is supported
- Disabled agents produce `status: proposed` handoffs
- `token_visibility` must always be `unknown`
- `api_cost_visible` must be `false` for subscription/external_harness modes

### 2. No Automatic Execution

- Handoff creation writes files only — no subprocess calls
- CLI commands do not invoke external agents
- AgentLab never reads OAuth tokens or subscription credentials

### 3. Evidence Requirements

- Changed files require command evidence, artifacts, or `external_unverified` flag
- Build/test claims in summary require corresponding evidence
- Missing evidence produces warnings; hard violations raise errors

### 4. Artifact Gate

- Submitting a result sets ledger status to `submitted`, not `accepted`
- `artifact_gate_status` remains `pending` until explicit approval
- `evidence_status` and `artifact_gate_status` are separate fields

## Security Rules

- No API keys or credentials stored in artifacts
- No automatic execution of external agents
- All handoffs require explicit user trigger
- External costs default to unknown/null, never 0