# ECC Handoff Protocol

## Purpose

This document defines the specific protocol for handoffs involving ECC (Everything Claude Code) skill packs. ECC is treated as an **external_agent_pack** type — AgentLab creates handoff artifacts but does **NOT** auto-run ECC hooks, commands, or MCP servers.

## Key Principles

- **AgentLab only creates handoff artifacts.** AgentLab does not execute Cline/Codex/ECC automatically.
- **AgentLab does not access subscription tokens.** ECC is an external harness; token visibility is unknown.
- **External costs are tracked as unknown unless explicitly reported.** Default is unknown, never 0.
- **External results require evidence.** Skills used must be recorded; build/test claims require evidence.
- **Submitting an external result does not automatically pass the artifact gate.**

## Protocol Requirements

### 1. ECC Agent Configuration

- Agent type must be `external_agent_pack`
- Integration mode must be `handoff_only`
- Token visibility must always be `unknown`
- Risk level must be `high`
- Requires explicit user trigger and skill approval
- Default: `enabled: false`

### 2. Handoff Creation Process

1. **Skill Selection**: User must explicitly select one or more skills from the ECC pack
2. **Skill Approval**: Requires manual approval for each selected skill
3. **Artifact Structure**:
   - `external_handoff.yml` — Machine-readable YAML format
   - `external_handoff.md` — Human-readable documentation with skill details

### 3. Handoff Data Model

```yaml
handoff_id: "handoff_task_001_ecc_pack_20260612_120000_abc12345"
task_id: "task_001"
project: "AgentLab"
target:
  agent_id: "ecc_pack"
  agent_type: "external_agent_pack"
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
  billing_mode: "external_harness"
  api_cost_visible: false
  external_token_visibility: "unknown"
  expected_agentlab_api_cost_usd: null
evidence_requirements:
  require_changed_files: true
  require_test_summary: true
  require_execution_log_or_external_unverified_marker: true
  require_no_secret_leak: true
  require_residual_risks: true
skill_context:
  suggested_external_skills:
    - "ecc.planner"
    - "ecc.code-reviewer"
```

### 4. CLI Commands

```bash
# List ECC agent
python -m agent_runtime.external_agents_cli list

# Create ECC handoff
python -m agent_runtime.external_agents_cli create-handoff \
  --task-id task_001 \
  --agent-id ecc_pack \
  --title "Security review" \
  --summary "Review code for vulnerabilities"

# Submit ECC result
python -m agent_runtime.external_agents_cli submit-result \
  --task-id task_001 \
  --handoff-id handoff_xxx \
  --result-file path/to/result.yml
```

## Key Constraints

### 1. Skill Usage

- Must explicitly list suggested skills in handoff `skill_context`
- Skill approval required before execution
- Skill usage must be recorded in the external agent ledger

### 2. Security Requirements

- No API keys or credentials stored in artifacts
- No automatic execution of ECC hooks or MCP servers
- All handoffs require explicit user trigger and skill approval
- AgentLab does not auto-run ECC commands

### 3. Artifact Management

- Handoff artifacts written to task run directories
- No direct repository modifications during handoff creation
- All handoffs recorded in external_agent_ledger.yml

### 4. Evidence Requirements

- Changed files must have corresponding command execution or artifact evidence
- Build/test claims require verification through execution evidence
- Missing evidence results in warning/failure status
- `external_unverified: true` suppresses hard errors but does not constitute evidence pass

## Integration with Task Management

- All handoffs recorded in task events
- Ledger updates occur for each handoff and result submission
- Skill usage tracked in the skill usage ledger
- ECC integration is strictly handoff-only; no automatic MCP server connections