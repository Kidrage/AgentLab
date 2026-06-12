# External Agent Ledger

## Overview

The External Agent Ledger tracks every handoff and result submission for external agents (Cline/Codex, ECC Skill Pack). It is a YAML file written to the task run directory as `external_agent_ledger.yml`.

## Key Design Principles

- **AgentLab only creates handoff artifacts.** AgentLab does not execute Cline/Codex/ECC automatically.
- **AgentLab does not access subscription tokens.** No OAuth tokens, API keys, or subscription credentials are read or used.
- **External costs are tracked as unknown unless explicitly reported.** The default for subscription-based external agents is `unknown`, never `0`.
- **External results require evidence.** Commands run, build/test claims, and changed files must be accompanied by evidence or marked `external_unverified`.
- **Submitting an external result does not automatically pass the artifact gate.** A human or supervisor must separately approve.

## Ledger Data Model

### Full Ledger

```yaml
task_id: "task_001"
handoffs:
  - handoff_id: "handoff_task_001_cline_codex_20260612_120000_abc12345"
    agent_id: "cline_codex"
    status: "proposed"
    billing_mode: "subscription_quota"
    token_visibility: "unknown"
    api_cost_visible: false
    created_at: "2026-06-12T12:00:00+00:00"
    submitted_at: null
    evidence_status: "missing"
    artifact_gate_status: "pending"
    skill_usage_events: []
```

### Ledger Entry Fields

| Field | Description | Values |
|-------|-------------|--------|
| `handoff_id` | Unique identifier for the handoff | String |
| `agent_id` | External agent identifier | `cline_codex`, `ecc_pack` |
| `status` | Current lifecycle status | `proposed`, `submitted` (NOT `accepted`) |
| `billing_mode` | Billing mode from agent config | `subscription_quota`, `external_harness` |
| `token_visibility` | Token cost visibility | Always `unknown` |
| `api_cost_visible` | Whether API cost is visible | Always `false` |
| `created_at` | Handoff creation timestamp | ISO 8601 |
| `submitted_at` | Result submission timestamp | ISO 8601 or null |
| `evidence_status` | Evidence completeness | `missing`, `partial`, `complete` |
| `artifact_gate_status` | Gate state (manual) | `pending` (never auto-passed) |
| `skill_usage_events` | Recorded skill usage | List of event dicts |

## Lifecycle States

### 1. Handoff Created → `proposed`

When a handoff is created via CLI:
- `status` is set to `proposed`
- `evidence_status` is `missing`
- `artifact_gate_status` is `pending`
- `created_at` is recorded
- `submitted_at` is null

### 2. Result Submitted → `submitted`

When a result is submitted:
- `status` changes to `submitted` (NOT `accepted`)
- `evidence_status` is updated based on evidence check
- `artifact_gate_status` remains `pending` — never auto-passed
- `submitted_at` is recorded

### 3. Gate Approval (Manual)

The artifact gate must be approved separately:
- `artifact_gate_status` does NOT change during result submission
- A human or supervisor must explicitly approve the gate
- Gate approval is outside the scope of automatic submission

## CLI Commands

```bash
# View ledger for a task
python -m agent_runtime.external_agents_cli ledger --task-id task_001

# Create handoff (writes ledger entry automatically)
python -m agent_runtime.external_agents_cli create-handoff \
  --task-id task_001 \
  --agent-id cline_codex \
  --title "Feature X" \
  --summary "Implement feature X"

# Submit result (updates ledger automatically)
python -m agent_runtime.external_agents_cli submit-result \
  --task-id task_001 \
  --handoff-id handoff_xxx \
  --result-file path/to/result.yml
```

## Cost Tracking Rules

- `api_cost_usd`: Default `null` (not `0`)
- `subscription_quota_used`: Default `unknown`
- `pricing_status`: Default `external_unknown`
- External cost `0` is only valid if `free: true` is explicitly set
- Subscription/external_harness costs are never auto-calculated

## Evidence Tracking

- `evidence_status` reflects whether evidence was provided in the result
- `complete`: commands/artifacts present
- `partial`: changed files present but no command evidence
- `missing`: no evidence or status is `failed`/`rejected`
- `evidence_status` is separate from `artifact_gate_status`
- Missing command evidence triggers warnings or hard errors depending on context

## Security Rules

- No API keys or credentials stored in ledger
- Ledger is never auto-uploaded to external services
- External token/cost data remains `unknown`
- Artifact gate is never auto-passed on result submission