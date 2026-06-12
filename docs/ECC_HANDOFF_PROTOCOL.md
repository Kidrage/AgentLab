# ECC Handoff Protocol

## Purpose
This document defines the specific protocol for handoffs involving ECC (Everything Claude Code) skill packs. The protocol ensures proper documentation, validation, and tracking of ECC agent interactions.

## Protocol Requirements

### 1. ECC Agent Configuration
- Only agents with type=external_agent_pack can be used
- Integration mode must be handoff_only
- Token visibility must always be "unknown"
- Risk level must be high
- Requires explicit user trigger and skill approval

### 2. Handoff Creation Process
1. **Skill Selection**: User must explicitly select one or more skills from the ECC pack
2. **Skill Approval**: Requires manual approval for each selected skill
3. **Artifact Structure**:
   - `external_handoff.yml` - Machine-readable YAML format
   - `external_handoff.md` - Human-readable documentation with skill details

### 3. Handoff Data Model
```yaml
handoff_id: "handoff_20260612_235959"
task_id: "task_0035"
project: "AgentLab"
target:
  agent_id: "ecc_pack"
  agent_type: "external_agent_pack"
  integration_mode: "handoff_only"
  enabled: false
  status: "proposed"
objective:
  title: "Implement feature X"
  summary: "Description of the task to be performed by the ECC agent"
constraints: []
required_outputs: []
budget:
  billing_mode: "external_harness"
  api_cost_visible: false
  external_token_visibility: "unknown"
suggested_external_skills:
  - "ecc.planner"
  - "ecc.code-reviewer"
evidence_requirements: []
```

## Key Constraints

### 1. Skill Usage
- Must explicitly list suggested skills in handoff
- Skill approval required before execution
- Skill usage must be recorded in skill usage ledger

### 2. Security Requirements
- No API keys or credentials stored in artifacts
- No automatic execution of external agents
- All handoffs require explicit user trigger and skill approval

### 3. Artifact Management
- Handoff artifacts must be written to task run directories
- No direct repository modifications during handoff creation
- All handoffs must be recorded in the external agent ledger and skill usage ledger

## Integration with Skill System

### 1. Skill Planning
- Handoff must explicitly list suggested skills
- Skills must be validated against skill registry
- Skill usage must be recorded in skill usage ledger

### 2. Skill Execution
- Successful result submission can trigger skill incubation
- Quality scores must be recorded for used skills
- Skill usage history affects incubation decisions

### 3. Evidence Requirements
- Changed files must have corresponding command execution or artifact evidence
- Build/test claims require verification through execution evidence
- Missing evidence results in warning/failure status